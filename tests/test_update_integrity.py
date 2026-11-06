# -*- coding: utf-8 -*-
"""sa-console.sh 供应链完整性校验的独立自检（Python stdlib，只读真实脚本）。

做法：把 sa-console.sh 复制到系统临时目录，用 sed 截掉末尾 case dispatch 后 source，
逐个调用真实函数验证。所有临时产物写入 tempfile.mkdtemp()，结束即清理。
不修改任何仓库文件；不执行 sync_final_v180.py；不生成 sha256sums.txt。

覆盖：
  1) check_tar_entries    正常 / 绝对路径 / .. 穿越 / symlink / hardlink / FIFO / 反斜杠转义
  2) validate_manifest    合法 / CRLF / 非法 hex / 绝对路径 / .. 路径 / 空 / 反斜杠
  3) verify_tree          正常 / CRLF 清单 / 错误 hex / 文件被篡改
  4) sa256                sha256sum / shasum / openssl / 三工具全缺
  5) checksum_url_for     gitee / github / codeload / 目录型镜像
  6) do_install_release   无清单默认告警继续 / SA_REQUIRE_CHECKSUM=1 拒绝且未停服
  7) 清单外文件白名单     static/evil.js 被拦 / static/world.json 被豁免（旧 tag 兼容）
  8) tests/ 白名单        仅放行顶层 .py；tests/legit.js / tests/sub/evil.py / tests/../../evil 均被拒
"""
import os
import re
import sys
import io
import tarfile
import hashlib
import tempfile
import shutil
import subprocess

WS = os.path.dirname(os.path.abspath(__file__))
# 兼容两种位置：脚本在 <repo>/tests/ 时 sa-console.sh 在上一级；在工作区根时在 site_analytics/ 下
_SA_CAND = [os.path.join(WS, "..", "sa-console.sh"),
            os.path.join(WS, "site_analytics", "sa-console.sh")]
SA = os.environ.get("SA_CONSOLE_PATH") or next((p for p in _SA_CAND if os.path.isfile(p)), _SA_CAND[0])


def bash_path(p):
    """Windows 路径 -> Git Bash 可见路径 (C:\\x -> /c/x)。"""
    p = p.replace("\\", "/")
    m = re.match(r"^([A-Za-z]):(.*)$", p)
    if m:
        return "/" + m.group(1).lower() + m.group(2)
    return p


BASH = shutil.which("bash") or "bash"
RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, bool(ok)))
    print(("  PASS  " if ok else "  FAIL  ") + name + (("  | " + detail) if detail else ""))


def ti(name, typ=tarfile.REGTYPE, mode=0o644, linkname=""):
    t = tarfile.TarInfo(name)
    t.type = typ
    t.size = 0
    t.mode = mode
    t.linkname = linkname
    t.mtime = 0
    t.uid = 0
    t.gid = 0
    t.uname = ""
    t.gname = ""
    return t


def write_tar(path, entries):
    with tarfile.open(path, "w:gz") as tf:
        for info, data in entries:
            if data is None:
                tf.addfile(info)
            else:
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))


def put(path, data, binary=True):
    with open(path, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8", "newline": ""})) as f:
        f.write(data)


def main():
    if not os.path.isfile(SA):
        print("找不到 sa-console.sh:", SA)
        return 2

    T_WIN = tempfile.mkdtemp(prefix="sa_integrity_")
    T = bash_path(T_WIN)
    SA_B = bash_path(SA)
    d = lambda *p: os.path.join(T_WIN, *p)

    for sub in ("install", "bin", "case", "sums", "src/static", "src_tamper/static",
                "shim_sha", "shim_shasum", "shim_openssl", "shim_none"):
        os.makedirs(d(sub), exist_ok=True)

    put(d("install", "app.py"), b"")
    put(d("bin", "curl"), b"#!/bin/sh\nexit 0\n")

    real_sha = subprocess.run([BASH, "-c", "command -v sha256sum"],
                              capture_output=True, text=True).stdout.strip() or "/usr/bin/sha256sum"
    put(d("shim_sha", "sha256sum"),
        ("#!/bin/sh\nout=$(%s \"$1\" 2>/dev/null)\nprintf '%%s  %%s\\n' \"${out%%%% *}\" \"$1\"\n" % real_sha).encode())
    put(d("shim_shasum", "shasum"),
        ("#!/bin/sh\nout=$(%s \"$3\" 2>/dev/null)\nprintf '%%s  %%s\\n' \"${out%%%% *}\" \"$3\"\n" % real_sha).encode())
    put(d("shim_openssl", "openssl"),
        ("#!/bin/sh\nout=$(%s \"$4\" 2>/dev/null)\nprintf '%%s *%%s\\n' \"${out%%%% *}\" \"$4\"\n" % real_sha).encode())

    # ---- 6 类 tarball ----
    APP = b"app\n"
    HTML = b"<html></html>\n"
    JS = b"js\n"
    normal = [
        (ti("pkg/", tarfile.DIRTYPE, mode=0o755), None),
        (ti("pkg/app.py"), APP),
        (ti("pkg/static/", tarfile.DIRTYPE, mode=0o755), None),
        (ti("pkg/static/app.js"), JS),
    ]
    write_tar(d("case", "normal.tar.gz"), normal)
    write_tar(d("case", "abs.tar.gz"),
              [(ti("pkg/app.py"), APP), (ti("/tmp/evil.py"), b"evil\n")])
    write_tar(d("case", "dotdot.tar.gz"),
              [(ti("pkg/app.py"), APP), (ti("pkg/../../evil.py"), b"evil\n")])
    write_tar(d("case", "symlink.tar.gz"),
              [(ti("pkg/app.py"), APP),
               (ti("pkg/link", tarfile.SYMTYPE, linkname="app.py"), None)])
    write_tar(d("case", "hardlink.tar.gz"),
              [(ti("pkg/app.py"), APP),
               (ti("pkg/hard", tarfile.LNKTYPE, linkname="pkg/app.py"), None)])
    write_tar(d("case", "fifo.tar.gz"),
              [(ti("pkg/app.py"), APP),
               (ti("pkg/pipe", tarfile.FIFOTYPE), None)])
    # 附加用例：条目名含反斜杠（GNU tar -tzf 会转义成两个反斜杠后输出）
    write_tar(d("case", "backslash.tar.gz"),
              [(ti("pkg/app.py"), APP),
               (ti("pkg/evil" + chr(92) + "name"), b"evil\n")])

    # ---- 清单测试文件 ----
    H = hashlib.sha256(b"x").hexdigest()          # 合法 64 位 hex
    BADHEX = "deadbeef"                          # 长度 != 64
    ZERO = "0" * 64
    legal_lines = [H + "  app.py", H + "  index.html", H + "  static/app.js"]
    put(d("sums", "m_legal.txt"), ("\n".join(legal_lines) + "\n").encode())
    put(d("sums", "m_crlf.txt"), ("\r\n".join(legal_lines) + "\r\n").encode())
    put(d("sums", "m_badhex.txt"), ("\n".join(legal_lines + [BADHEX + "  app.py"]) + "\n").encode())
    put(d("sums", "m_abspath.txt"), ("\n".join(legal_lines + [H + "  /etc/passwd"]) + "\n").encode())
    put(d("sums", "m_dotdot.txt"), ("\n".join(legal_lines + [H + "  ../evil"]) + "\n").encode())
    put(d("sums", "m_empty.txt"), b"# only a comment\n\n")
    put(d("sums", "m_backslash.txt"),
        ("\n".join(legal_lines + [H + "  static" + chr(92) + "evil.js"]) + "\n").encode())
    put(d("sums", "m_comment.txt"),
        ("\n".join(["# 这是注释行", ""] + legal_lines) + "\n").encode())
    put(d("sums", "m_dotdot2.txt"),
        ("\n".join(legal_lines + [H + "  static/../../evil"]) + "\n").encode())
    put(d("sums", "m_allbad.txt"), (BADHEX + "  app.py\n").encode())

    # ---- verify_tree 用的 src 树 ----
    put(d("src", "app.py"), APP)
    put(d("src", "index.html"), HTML)
    put(d("src", "static", "app.js"), JS)
    put(d("src_tamper", "app.py"), APP)
    put(d("src_tamper", "index.html"), HTML)
    put(d("src_tamper", "static", "app.js"), b"EVIL\n")
    tree_lines = [
        hashlib.sha256(APP).hexdigest() + "  app.py",
        hashlib.sha256(HTML).hexdigest() + "  index.html",
        hashlib.sha256(JS).hexdigest() + "  static/app.js",
    ]
    put(d("sums", "tree_ok.txt"), ("\n".join(tree_lines) + "\n").encode())
    put(d("sums", "tree_crlf.txt"), ("\r\n".join(tree_lines) + "\r\n").encode())
    put(d("sums", "tree_bad.txt"),
        ("\n".join([ZERO + "  app.py"] + tree_lines[1:]) + "\n").encode())

    # ---- 带清单的完整运行时 tarball（18 项）+ 清单外文件 ----
    RUNTIME = [
        "app.py", "index.html", "tracker.js", "tracker-loader.html",
        "sa-console.sh", "site_analytics.service", "nginx_bypass_auth.conf",
        "update_geoip.sh", "make_mirror.sh", "start.sh", "restart.sh", "LICENSE",
        "static/app.js", "static/echarts.min.js", "static/i18n.js",
        "static/iso3166.json", "static/style.css", "static/world_map.json",
    ]
    contents = {r: ("content of " + r + "\n").encode() for r in RUNTIME}
    full_manifest = ["%s  %s" % (hashlib.sha256(contents[r]).hexdigest(), r) for r in RUNTIME]
    put(d("sums", "full_manifest.txt"), ("\n".join(full_manifest) + "\n").encode())

    def full_entries(extra_name, extra_data):
        ent = [(ti("pkg/", tarfile.DIRTYPE, mode=0o755), None)]
        for r in RUNTIME:
            ent.append((ti("pkg/" + r), contents[r]))
        ent.append((ti("pkg/" + extra_name), extra_data))
        return ent

    write_tar(d("case", "full.tar.gz"), full_entries("static/evil.js", b"evil\n"))
    write_tar(d("case", "full_world.tar.gz"), full_entries("static/world.json", b"{}\n"))

    PROLOGUE = r'''export LC_ALL=C
T="__T__"
unset SA_UPDATE_MIRROR SA_REQUIRE_CHECKSUM
export SA_HOME="$T/install"
export PATH="$T/bin:$PATH"
for s in "$T/bin/curl" "$T/shim_sha/sha256sum" "$T/shim_shasum/shasum" "$T/shim_openssl/openssl"; do
  chmod +x "$s" 2>/dev/null || true
done
sed '/^case /,$d' "__SA__" > "$T/sa.sh"
. "$T/sa.sh"
cd "$T" || exit 1
set +e
'''.replace("__T__", T).replace("__SA__", SA_B)

    def run_bash(body, extra_env=None):
        env = dict(os.environ)
        if extra_env:
            env.update(extra_env)
        return subprocess.run([BASH, "-c", PROLOGUE + "\n" + body],
                              capture_output=True, text=True, env=env, cwd=T_WIN)

    def rc_map(out, prefix):
        m = {}
        for ln in out.splitlines():
            p = ln.split()
            if len(p) >= 3 and p[0] == prefix:
                m[p[1]] = p[2]
        return m

    # ============ 1) check_tar_entries ============
    print("\n[1] check_tar_entries：正常包 PASS，6 类危险包全部 REJECT")
    body = r'''for f in normal abs dotdot symlink hardlink fifo backslash; do
  check_tar_entries "$T/case/$f.tar.gz" >/dev/null 2>&1
  printf 'CASE %s %s\n' "$f" "$?"
done
'''
    r = run_bash(body)
    m = rc_map(r.stdout, "CASE")
    if r.stderr.strip():
        print("    bash stderr:", r.stderr.strip()[:200])
    record("normal 返回 0", m.get("normal") == "0", "rc=" + str(m.get("normal")))
    for f in ("abs", "dotdot", "symlink", "hardlink", "fifo", "backslash"):
        record(f + " 被拒绝", m.get(f) not in (None, "0"), "rc=" + str(m.get(f)))

    # ============ 2) validate_manifest（勘误版，10 个用例）============
    print("\n[2] validate_manifest：正常 LF/CRLF/注释 → 0；7 类非法 → 1（逐用例报告实际 rc）")
    body = r'''for f in m_legal m_crlf m_comment m_badhex m_abspath m_dotdot m_dotdot2 m_backslash m_empty m_allbad; do
  validate_manifest "$T/sums/$f.txt" >/dev/null 2>&1
  printf 'MANIFEST %s %s\n' "$f" "$?"
done
out=$( validate_manifest "$T/sums/m_allbad.txt" 2>&1 ); printf 'ALLBAD_MSG %s\n' "$(printf '%s' "$out" | tr '\n' '|')"
'''
    r = run_bash(body)
    m = rc_map(r.stdout, "MANIFEST")
    if r.stderr.strip():
        print("    bash stderr:", r.stderr.strip()[:200])
    for f in ("m_legal", "m_crlf", "m_comment", "m_badhex", "m_abspath",
              "m_dotdot", "m_dotdot2", "m_backslash", "m_empty", "m_allbad"):
        print("    用例 %-12s rc=%s" % (f, m.get(f)))
    record("正常 LF 清单 → 0", m.get("m_legal") == "0", "rc=" + str(m.get("m_legal")))
    record("CRLF 清单 → 0", m.get("m_crlf") == "0", "rc=" + str(m.get("m_crlf")))
    record("含 # 注释行 → 0", m.get("m_comment") == "0", "rc=" + str(m.get("m_comment")))
    for f, label in (("m_badhex", "非法 hex 长度 → 1"), ("m_abspath", "绝对路径 /etc/passwd → 1"),
                     ("m_dotdot", "../evil → 1"), ("m_dotdot2", "static/../../evil → 1"),
                     ("m_backslash", "static\\evil.js → 1"), ("m_empty", "空清单 → 1"),
                     ("m_allbad", "全非法行 → 1")):
        record(label, m.get(f) not in (None, "0"), "rc=" + str(m.get(f)))
    allbad_msg = next((l for l in r.stdout.splitlines() if l.startswith("ALLBAD_MSG ")), "")
    record("全非法行不误报「清单为空」（n++ 前移生效）", "清单为空" not in allbad_msg,
           allbad_msg[:120])

    # ============ 3) verify_tree ============
    print("\n[3] verify_tree：正常/CRLF PASS，错误 hex 与篡改字节 FAIL")
    body = r'''verify_tree "$T/src" "$T/sums/tree_ok.txt" >/dev/null 2>&1
printf 'TREE ok %s\n' "$?"
verify_tree "$T/src" "$T/sums/tree_crlf.txt" >/dev/null 2>&1
printf 'TREE crlf %s\n' "$?"
verify_tree "$T/src" "$T/sums/tree_bad.txt" >/dev/null 2>&1
printf 'TREE bad %s\n' "$?"
verify_tree "$T/src_tamper" "$T/sums/tree_ok.txt" >/dev/null 2>&1
printf 'TREE tamper %s\n' "$?"
'''
    r = run_bash(body)
    m = rc_map(r.stdout, "TREE")
    if r.stderr.strip():
        print("    bash stderr:", r.stderr.strip()[:200])
    record("正常逐文件校验 PASS", m.get("ok") == "0", "rc=" + str(m.get("ok")))
    record("CRLF 清单逐文件校验 PASS", m.get("crlf") == "0", "rc=" + str(m.get("crlf")))
    record("错误 hex 被拒绝", m.get("bad") not in (None, "0"), "rc=" + str(m.get("bad")))
    record("文件字节被篡改后拒绝", m.get("tamper") not in (None, "0"), "rc=" + str(m.get("tamper")))

    # ============ 4) sa256 三工具回退 ============
    print("\n[4] sa256：sha256sum / shasum / openssl 三分支 + 全缺失")
    expect = hashlib.sha256(APP).hexdigest()
    body = r'''for b in shim_sha shim_shasum shim_openssl; do
  out=$( ( PATH="$T/$b"; sa256 "$T/src/app.py" ) 2>&1 ); rc=$?
  printf 'SA256 %s rc=%s h=%s\n' "$b" "$rc" "$out"
done
out=$( ( PATH="$T/shim_none"; sa256 "$T/src/app.py" ) 2>&1 ); rc=$?
printf 'SA256 shim_none rc=%s msg=%s\n' "$rc" "$out"
'''
    r = run_bash(body)
    if r.stderr.strip():
        print("    bash stderr:", r.stderr.strip()[:200])
    lines = {}
    for ln in r.stdout.splitlines():
        p = ln.split(None, 3)
        if len(p) >= 3 and p[0] == "SA256":
            lines[p[1]] = ln
    for b in ("shim_sha", "shim_shasum", "shim_openssl"):
        ln = lines.get(b, "")
        ok = ("rc=0" in ln) and (expect in ln)
        record("sa256 回退 " + b + " 产出正确 sha256", ok, ln.strip()[:110])
    ln = lines.get("shim_none", "")
    ok = ("rc=1" in ln) and ("找不到 sha256 工具" in ln)
    record("sa256 三工具全缺时报错返回 1", ok, ln.strip()[:110])

    # ============ 5) checksum_url_for ============
    print("\n[5] checksum_url_for：gitee / github / codeload / 目录型镜像")
    body = r'''printf 'URL gitee %s\n' "$(checksum_url_for v1.2.3 'https://gitee.com/u/r/repository/archive/v1.2.3.tar.gz')"
printf 'URL github %s\n' "$(checksum_url_for v1.2.3 'https://github.com/gg4midas/site_analytics/archive/refs/tags/v1.2.3.tar.gz')"
printf 'URL codeload %s\n' "$(checksum_url_for v1.2.3 'https://codeload.github.com/gg4midas/site_analytics/tar.gz/refs/tags/v1.2.3')"
printf 'URL mirror_begin\n'
checksum_url_for v1.2.3 'https://mirror.example.com/sa/v1.2.3.tar.gz'
printf 'URL mirror_end\n'
'''
    r = run_bash(body)
    out = r.stdout
    if r.stderr.strip():
        print("    bash stderr:", r.stderr.strip()[:200])
    record("gitee 分支 URL", "URL gitee https://gitee.com/u/r/raw/v1.2.3/sha256sums.txt" in out,
           next((l for l in out.splitlines() if l.startswith("URL gitee")), ""))
    record("github 分支 URL",
           "URL github https://raw.githubusercontent.com/gg4midas/site_analytics/v1.2.3/sha256sums.txt" in out,
           next((l for l in out.splitlines() if l.startswith("URL github")), ""))
    record("codeload 归入 github 分支",
           "URL codeload https://raw.githubusercontent.com/gg4midas/site_analytics/v1.2.3/sha256sums.txt" in out,
           next((l for l in out.splitlines() if l.startswith("URL codeload")), ""))
    try:
        block = out.split("URL mirror_begin\n", 1)[1].split("URL mirror_end", 1)[0].strip().splitlines()
    except IndexError:
        block = []
    record("目录型镜像输出两种命名（tag + latest）",
           block == ["https://mirror.example.com/sa/v1.2.3.sha256sums.txt",
                     "https://mirror.example.com/sa/sha256sums.txt"],
           str(block))

    # ============ 6) 无清单时 do_install_release 行为 ============
    print("\n[6] do_install_release：无清单默认告警继续；SA_REQUIRE_CHECKSUM=1 拒绝且未停服")
    body = r'''do_stop()      { : > "$T/stop.flag"; }
do_start()     { :; }
app_version()  { echo "v1.8.6"; }
download_tarball() {
  case "$1" in
    *sha256sums.txt*) return 1;;
    *) cp "$T/case/normal.tar.gz" "$2"; return 0;;
  esac
}
rm -f "$T/stop.flag"
out=$( do_install_release v1.2.3 "default-test" 2>&1 ); rc=$?
printf 'NOSUM_DEFAULT rc=%s stop=%s\n' "$rc" "$([ -f "$T/stop.flag" ] && echo yes || echo no)"
printf 'NOSUM_DEFAULT_OUT %s\n' "$(printf '%s' "$out" | tr '\n' '|')"

export SA_REQUIRE_CHECKSUM=1
rm -f "$T/stop.flag"
out=$( do_install_release v1.2.4 "require-test" 2>&1 ); rc=$?
printf 'NOSUM_REQUIRE rc=%s stop=%s\n' "$rc" "$([ -f "$T/stop.flag" ] && echo yes || echo no)"
printf 'NOSUM_REQUIRE_OUT %s\n' "$(printf '%s' "$out" | tr '\n' '|')"
unset SA_REQUIRE_CHECKSUM
'''
    r = run_bash(body)
    if r.stderr.strip():
        print("    bash stderr:", r.stderr.strip()[:200])
    default_line = next((l for l in r.stdout.splitlines() if l.startswith("NOSUM_DEFAULT ")), "")
    require_line = next((l for l in r.stdout.splitlines() if l.startswith("NOSUM_REQUIRE ")), "")
    default_out = next((l for l in r.stdout.splitlines() if l.startswith("NOSUM_DEFAULT_OUT ")), "")
    require_out = next((l for l in r.stdout.splitlines() if l.startswith("NOSUM_REQUIRE_OUT ")), "")
    ok_def = ("rc=0" in default_line) and ("[警告]" in default_out) and ("未提供有效 sha256sums.txt" in default_out)
    record("无清单默认告警且继续到安装（rc=0）", ok_def,
           default_line + " | " + default_out[:150])
    ok_req = ("rc=1" in require_line) and ("stop=no" in require_line) \
             and ("SA_REQUIRE_CHECKSUM=1" in require_out) and ("未解压、未停服" in require_out)
    record("SA_REQUIRE_CHECKSUM=1 拒绝且未停服", ok_req,
           require_line + " | " + require_out[:150])
    record("拒绝分支确未解压（提示含未解压/未停服）", "未解压、未停服" in require_out)

    # ============ 7) 清单外文件白名单 ============
    print("\n[7] 清单外文件白名单：static/evil.js 被拦；static/world.json 被豁免（旧 tag）")
    body = r'''do_stop()      { : > "$T/stop.flag"; }
do_start()     { :; }
app_version()  { echo "v1.8.6"; }
download_tarball() {
  case "$1" in
    *sha256sums.txt*) cp "$T/sums/full_manifest.txt" "$2"; return 0;;
    *) cp "$T/case/full.tar.gz" "$2"; return 0;;
  esac
}
rm -f "$T/stop.flag"
out=$( do_install_release v1.2.3 "evil-test" 2>&1 ); rc=$?
printf 'EVIL rc=%s stop=%s\n' "$rc" "$([ -f "$T/stop.flag" ] && echo yes || echo no)"
printf 'EVIL_OUT %s\n' "$(printf '%s' "$out" | tr '\n' '|')"

download_tarball() {
  case "$1" in
    *sha256sums.txt*) cp "$T/sums/full_manifest.txt" "$2"; return 0;;
    *) cp "$T/case/full_world.tar.gz" "$2"; return 0;;
  esac
}
rm -f "$T/stop.flag"
out=$( do_install_release v1.2.4 "world-test" 2>&1 ); rc=$?
printf 'WORLD rc=%s stop=%s\n' "$rc" "$([ -f "$T/stop.flag" ] && echo yes || echo no)"
printf 'WORLD_OUT %s\n' "$(printf '%s' "$out" | tr '\n' '|')"
'''
    r = run_bash(body)
    if r.stderr.strip():
        print("    bash stderr:", r.stderr.strip()[:200])
    evil_line = next((l for l in r.stdout.splitlines() if l.startswith("EVIL ")), "")
    evil_out = next((l for l in r.stdout.splitlines() if l.startswith("EVIL_OUT ")), "")
    world_line = next((l for l in r.stdout.splitlines() if l.startswith("WORLD ")), "")
    world_out = next((l for l in r.stdout.splitlines() if l.startswith("WORLD_OUT ")), "")
    ok_evil = ("rc=1" in evil_line) and ("stop=no" in evil_line) \
              and ("归档含清单外文件" in evil_out) and ("static/evil.js" in evil_out)
    record("static/evil.js 被拦（rc=1，未停服）", ok_evil,
           evil_line + " | " + evil_out[:170])
    ok_world = ("rc=0" in world_line) and ("归档含清单外文件" not in world_out)
    record("static/world.json 豁免，旧 tag 可继续安装（rc=0）", ok_world,
           world_line + " | " + world_out[:170])

    # ============ 8) tests/ 白名单（收紧后仅放行顶层 .py）============
    print("\n[8] tests/ 白名单：仅放行顶层 .py；非 .py / 子目录 / .. 穿越仍被拒")
    write_tar(d("case", "full_tests.tar.gz"), full_entries("tests/legit.py", b"legit\n"))
    write_tar(d("case", "full_tests_js.tar.gz"), full_entries("tests/legit.js", b"evil\n"))
    write_tar(d("case", "full_tests_sub.tar.gz"), full_entries("tests/sub/evil.py", b"evil\n"))
    write_tar(d("case", "full_tests_dotdot.tar.gz"), full_entries("tests/../../evil", b"evil\n"))
    body = r'''do_stop()      { : > "$T/stop.flag"; }
do_start()     { :; }
app_version()  { echo "v1.8.6"; }
download_tarball() {
  case "$1" in
    *sha256sums.txt*) cp "$T/sums/full_manifest.txt" "$2"; return 0;;
    *) cp "$T/case/full_tests.tar.gz" "$2"; return 0;;
  esac
}
rm -f "$T/stop.flag"
out=$( do_install_release v1.2.5 "tests-legit" 2>&1 ); rc=$?
printf 'TESTS_LEGIT rc=%s stop=%s\n' "$rc" "$([ -f "$T/stop.flag" ] && echo yes || echo no)"
printf 'TESTS_LEGIT_OUT %s\n' "$(printf '%s' "$out" | tr '\n' '|')"

download_tarball() {
  case "$1" in
    *sha256sums.txt*) cp "$T/sums/full_manifest.txt" "$2"; return 0;;
    *) cp "$T/case/full_tests_js.tar.gz" "$2"; return 0;;
  esac
}
rm -f "$T/stop.flag"
out=$( do_install_release v1.2.6 "tests-js" 2>&1 ); rc=$?
printf 'TESTS_JS rc=%s stop=%s\n' "$rc" "$([ -f "$T/stop.flag" ] && echo yes || echo no)"
printf 'TESTS_JS_OUT %s\n' "$(printf '%s' "$out" | tr '\n' '|')"

download_tarball() {
  case "$1" in
    *sha256sums.txt*) cp "$T/sums/full_manifest.txt" "$2"; return 0;;
    *) cp "$T/case/full_tests_sub.tar.gz" "$2"; return 0;;
  esac
}
rm -f "$T/stop.flag"
out=$( do_install_release v1.2.7 "tests-sub" 2>&1 ); rc=$?
printf 'TESTS_SUB rc=%s stop=%s\n' "$rc" "$([ -f "$T/stop.flag" ] && echo yes || echo no)"
printf 'TESTS_SUB_OUT %s\n' "$(printf '%s' "$out" | tr '\n' '|')"

download_tarball() {
  case "$1" in
    *sha256sums.txt*) cp "$T/sums/full_manifest.txt" "$2"; return 0;;
    *) cp "$T/case/full_tests_dotdot.tar.gz" "$2"; return 0;;
  esac
}
rm -f "$T/stop.flag"
out=$( do_install_release v1.2.8 "tests-dotdot" 2>&1 ); rc=$?
printf 'TESTS_DOTDOT rc=%s stop=%s\n' "$rc" "$([ -f "$T/stop.flag" ] && echo yes || echo no)"
printf 'TESTS_DOTDOT_OUT %s\n' "$(printf '%s' "$out" | tr '\n' '|')"
'''
    r = run_bash(body)
    if r.stderr.strip():
        print("    bash stderr:", r.stderr.strip()[:200])
    def tline(tag):
        return next((l for l in r.stdout.splitlines() if l.startswith(tag + " ")), "")
    def tout(tag):
        return next((l for l in r.stdout.splitlines() if l.startswith(tag + "_OUT ")), "")
    legit_line, legit_out = tline("TESTS_LEGIT"), tout("TESTS_LEGIT")
    js_line, js_out = tline("TESTS_JS"), tout("TESTS_JS")
    sub_line, sub_out = tline("TESTS_SUB"), tout("TESTS_SUB")
    dotdot_line, dotdot_out = tline("TESTS_DOTDOT"), tout("TESTS_DOTDOT")
    ok_legit = ("rc=0" in legit_line) and ("归档含清单外文件" not in legit_out)
    record("tests/legit.py 白名单放行，可继续安装（rc=0）", ok_legit,
           legit_line + " | " + legit_out[:170])
    ok_js = ("rc=1" in js_line) and ("stop=no" in js_line) \
            and ("归档含清单外文件" in js_out) and ("tests/legit.js" in js_out)
    record("tests/legit.js 非 .py 被拒（收紧后不再靠 .. 兜底）", ok_js,
           js_line + " | " + js_out[:170])
    ok_sub = ("rc=1" in sub_line) and ("stop=no" in sub_line) \
             and ("归档含清单外文件" in sub_out) and ("tests/sub/evil.py" in sub_out)
    record("tests/sub/evil.py 子目录路径被拒（收紧后不再靠 .. 兜底）", ok_sub,
           sub_line + " | " + sub_out[:170])
    ok_dotdot = ("rc=1" in dotdot_line) and ("stop=no" in dotdot_line) \
                and ("归档含危险条目" in dotdot_out)
    record("tests/../../evil 仍被拒（tar 条目 .. 检查兜底，rc=1 未停服）", ok_dotdot,
           dotdot_line + " | " + dotdot_out[:170])

    # ---- 汇总 ----
    passed = sum(1 for _, ok in RESULTS if ok)
    total = len(RESULTS)
    print("\n==== 汇总：%d/%d 通过 ====" % (passed, total))
    print("临时目录:", T_WIN, "（将清理）")
    shutil.rmtree(T_WIN, ignore_errors=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
