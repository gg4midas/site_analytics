# -*- coding: utf-8 -*-
"""v1.5.0 登录鉴权行为验证（隔离 data-dir + 随机端口，不碰生产数据）"""
import json, os, shutil, socket, sqlite3, subprocess, sys, tempfile, time, urllib.request, urllib.error, http.cookiejar

_HERE = os.path.dirname(os.path.abspath(__file__))
_CAND = [os.path.join(_HERE, '..', 'app.py'),                  # 入库后：tests/ 的上一级即仓库根
         os.path.join(_HERE, 'site_analytics', 'app.py')]      # 老位置：工作区根
APP  = os.environ.get('SA_APP_PATH') or next((p for p in _CAND if os.path.isfile(p)), _CAND[0])
PY   = sys.executable
WORK = tempfile.mkdtemp(prefix='sa_v150_')
results = []

def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + (("  | " + str(detail)) if detail and not cond else ""))

def free_port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k): return None

def client():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(NoRedirect, urllib.request.HTTPCookieProcessor(cj)), cj

def req(op, url, data=None, method=None, headers=None):
    r = urllib.request.Request(url, data=(json.dumps(data).encode() if data is not None else None), method=method)
    if data is not None: r.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items(): r.add_header(k, v)
    try:
        resp = op.open(r, timeout=10)
        body = resp.read()
        try: j = json.loads(body.decode("utf-8"))
        except Exception: j = None
        return resp.status, j, dict(resp.headers)
    except urllib.error.HTTPError as e:
        body = e.read()
        try: j = json.loads(body.decode("utf-8"))
        except Exception: j = None
        return e.code, j, dict(e.headers)

def wait_up(url, tries=50):
    for _ in range(tries):
        try:
            op = urllib.request.build_opener(NoRedirect)
            st, _, _ = req(op, url + "/login")
            if st == 200: return True
        except Exception: pass
        time.sleep(0.2)
    return False

shutil.rmtree(WORK, ignore_errors=True)
os.makedirs(WORK, exist_ok=True)
sys.stdout.reconfigure(encoding="utf-8")

# ---------- 阶段 0：--create-admin 无头建号 ----------
D1 = os.path.join(WORK, "db1")
p = subprocess.run([PY, APP, "--create-admin", "boss", "boss123456", "--data-dir", D1],
                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
check("create-admin 退出码 0", p.returncode == 0, p.stdout + p.stderr)
check("create-admin 打印确认", "boss" in (p.stdout or ""), p.stdout + p.stderr)
p2 = subprocess.run([PY, APP, "--create-admin", "boss", "x222222", "--data-dir", D1],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
check("create-admin 重复用户名失败(退出码非0)", p2.returncode != 0, p2.stdout + p2.stderr)

# ---------- 阶段 1：主流程（admin + viewer + 公开端点） ----------
PORT = free_port(); BASE = "http://127.0.0.1:%d" % PORT
# v1.8.6：自助注册默认关闭，本阶段显式开启以验证「待审 -> 管理员启用 -> 可登录」链路
ENV_REG_ON = dict(os.environ, SA_ALLOW_REGISTER="1")
proc = subprocess.Popen([PY, APP, "--port", str(PORT), "--data-dir", D1, "--host", "127.0.0.1"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV_REG_ON)
try:
    check("服务启动 /login 200", wait_up(BASE))
    anon, _ = client()
    st, _, hd = req(anon, BASE + "/")
    check("未登录 GET / -> 302 /login", st == 302 and "/login" in (hd.get("Location") or hd.get("location") or ""), "%s %s" % (st, hd))
    st, _, _ = req(anon, BASE + "/api/stats?site=example.com")
    check("未登录查询 API -> 401", st == 401, st)
    st, j, _ = req(anon, BASE + "/api/me")
    check("未登录 /api/me -> 401", st == 401, st)
    st, j, hd = req(anon, BASE + "/api/event?site=unregistered.example&visitor=vt1")
    check("未注册站点公开上报被业务拒绝 403（非鉴权拦截）", st == 403, st)
    st, _, _ = req(anon, BASE + "/tracker.js")
    check("公开 /tracker.js -> 200", st == 200, st)
    st, _, _ = req(anon, BASE + "/login")
    check("/login 页面 200", st == 200, st)

    # ---- v1.8.6：注册不再「注册即读」——建成 viewer + 待审，管理员启用后才能登录 ----
    reg, regcj = client()
    st, j, _ = req(reg, BASE + "/api/register", data={"username": "alice", "password": "alice123456"})
    check("注册第二用户 -> 200 且 pending=True", st == 200 and j and j.get("pending") is True, "%s %s" % (st, j))
    check("待审用户角色=viewer", bool(j) and j.get("user", {}).get("role") == "viewer", str(j))
    check("待审注册不种会话 cookie", not any(ck.name == "sid" for ck in regcj), [ck.name for ck in regcj])
    st, j, _ = req(reg, BASE + "/api/me")
    check("待审账号 /api/me -> 401", st == 401, st)
    st, j, _ = req(reg, BASE + "/api/stats?site=example.com")
    check("待审账号查询 API -> 401（注册即读已堵死）", st == 401, st)
    st, j, _ = req(reg, BASE + "/api/login", data={"username": "alice", "password": "alice123456"})
    check("待审账号登录 -> 401", st == 401, st)

    adm, admcj = client()
    st, j, _ = req(adm, BASE + "/api/login", data={"username": "boss", "password": "wrong-password"})
    check("admin 错密码 -> 401", st == 401, st)
    st, j, hd = req(adm, BASE + "/api/login", data={"username": "boss", "password": "boss123456"})
    cookie_set = any("sid=" in str(v) for k, v in hd.items() if k.lower() == "set-cookie")
    check("admin 登录 -> 200 + 种 sid cookie", st == 200 and cookie_set, "%s %s" % (st, hd))
    st, j, _ = req(adm, BASE + "/api/me")
    check("admin /api/me role=admin", st == 200 and j and j.get("user", {}).get("role") == "admin", str(j))

    # 管理员在「用户管理」里启用待审账号
    st, j, _ = req(adm, BASE + "/api/admin/user",
                   data={"username": "alice", "action": "status", "status": "active"})
    check("管理员启用待审账号 -> 200", st == 200, "%s %s" % (st, j))
    st, j, _ = req(reg, BASE + "/api/login", data={"username": "alice", "password": "alice123456"})
    check("启用后可登录且角色=viewer", st == 200 and j and j.get("user", {}).get("role") == "viewer",
          "%s %s" % (st, j))

    st, j, _ = req(reg, BASE + "/api/sites")
    check("viewer 可读站点列表(空) API", st == 200 and j and j.get("sites") == [], str(j))
    st, j, _ = req(reg, BASE + "/api/admin/settings")
    check("viewer 可读设置 GET", st == 200, st)
    st, j, _ = req(reg, BASE + "/api/admin/settings", data={"retention_days": 400})
    check("viewer 写设置 -> 403", st == 403, st)
    st, j, _ = req(reg, BASE + "/api/admin/users")
    check("viewer 看用户列表 -> 403", st == 403, st)
    st, j, _ = req(reg, BASE + "/api/site", data={"site": "evil.example"})
    check("viewer 加站点 -> 403", st == 403, st)

    st, j, _ = req(adm, BASE + "/api/site", data={"site": "example.com", "label": "test"})
    check("admin 加站点 -> 200", st == 200, str(j))
    con = sqlite3.connect(os.path.join(D1, "events.db"))
    skey = con.execute("SELECT site_key FROM sites WHERE site='example.com'").fetchone()[0]
    con.close()
    check("加站自动生成 site_key", bool(skey), skey)
    anon2, _ = client()
    UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    st, j, _ = req(anon2, BASE + "/api/event?site=example.com&visitor=vt123456&key=" + skey, headers=UA)
    check("known 站点带 key 公开上报 -> 200", st == 200, st)
    st, j, _ = req(adm, BASE + "/api/stats?site=example.com")
    check("admin 查询 API -> 200", st == 200, st)
    st, j, _ = req(reg, BASE + "/api/stats?site=example.com")
    check("viewer 查询 API -> 200", st == 200, st)
    st, j, _ = req(adm, BASE + "/api/admin/settings", data={"retention_days": 400})
    check("admin 写设置 -> 200", st == 200, str(j))
    st, j, _ = req(adm, BASE + "/api/admin/users")
    check("admin 用户列表含 2 用户", st == 200 and j and len(j.get("data", [])) == 2, str(j))
    # 最后管理员保护：尝试把自己降级
    st, j, _ = req(adm, BASE + "/api/admin/user", data={"username": "boss", "action": "role", "role": "viewer"})
    check("降级最后管理员被拒", st == 400, "%s %s" % (st, j))
    # viewer 改自己密码
    st, j, _ = req(reg, BASE + "/api/user/password", data={"old": "alice123456", "new": "alice654321"})
    check("viewer 本人改密 -> 200", st == 200, str(j))
    v2, _ = client()
    st, j, _ = req(v2, BASE + "/api/login", data={"username": "alice", "password": "alice654321"})
    check("新密码可登录", st == 200, st)
    # 登出
    st, j, hd = req(adm, BASE + "/api/logout", data={})
    st2, j2, _ = req(adm, BASE + "/api/me")
    check("logout 后 /api/me -> 401", st == 200 and st2 == 401, "%s->%s" % (st, st2))
finally:
    proc.terminate()
    try: proc.wait(timeout=10)
    except Exception: proc.kill()

# ---------- 阶段 2：空库注册 → 首个用户 = admin；限流 429 ----------
D2 = os.path.join(WORK, "db2")
PORT2 = free_port(); BASE2 = "http://127.0.0.1:%d" % PORT2
proc2 = subprocess.Popen([PY, APP, "--port", str(PORT2), "--data-dir", D2, "--host", "127.0.0.1"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV_REG_ON)
try:
    check("服务2启动", wait_up(BASE2))
    c, _ = client()
    st, j, _ = req(c, BASE2 + "/api/register", data={"username": "first", "password": "first123456"})
    st2, j2, _ = req(c, BASE2 + "/api/me")
    check("空库首个注册用户=admin", st == 200 and j2 and j2.get("user", {}).get("role") == "admin", str(j2))
    c2, _ = client()
    codes = []
    for i in range(12):
        st, j, _ = req(c2, BASE2 + "/api/login", data={"username": "nobody", "password": "badbadbad"})
        codes.append(st)
    check("限流：窗口内 10 次放行后 429（注册占 1 次配额）", codes[-1] == 429 and codes.count(429) >= 2 and codes.count(401) >= 8, codes)
finally:
    proc2.terminate()
    try: proc2.wait(timeout=10)
    except Exception: proc2.kill()

# ---------- 阶段 3：表结构 ----------
con = sqlite3.connect(os.path.join(D1, "events.db"))
tabs = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
ucols = {r[1] for r in con.execute("PRAGMA table_info(users)").fetchall()}
scols = {r[1] for r in con.execute("PRAGMA table_info(sessions)").fetchall()}
nusers = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
con.close()
check("users 表存在且含角色/盐列", "users" in tabs and {"username","pwd_hash","salt","role","status"} <= ucols, ucols)
check("sessions 表存在且含过期列", "sessions" in tabs and {"sid","uid","expires"} <= scols, scols)
check("users 落库 2 条", nusers == 2, nusers)

npass = sum(1 for _, ok, _ in results if ok)
print("\n===== %d/%d PASS =====" % (npass, len(results)))
sys.exit(0 if npass == len(results) else 1)
