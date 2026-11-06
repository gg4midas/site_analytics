# -*- coding: utf-8 -*-
"""P1 应用层安全加固 + 统计缓存 TTL/手动刷新 回归测试（仅 Python stdlib）

A 安全响应头：200/gzip/304/204/302/404/HEAD 均含 4 个头；Content-Length 与 body 一致；gzip 可解压；ETag/304 命中
B Cookie 条件化 Secure：X-Forwarded-Proto / SA_SECURE_COOKIE 强制 / 纯 HTTP 直连 / logout 同判断
C CSRF 同源校验：跨站 Origin 管理类 POST 403；/api/event exempt + ACAO *；SA_CSRF_STRICT 严格模式
D 统计缓存 TTL=90 + fresh=1 绕过缓存并刷新同 key + fresh 限流降级 + 未登录 401

每个服务实例使用临时端口 + 临时 --data-dir；脚本内部自带 SA_ALLOW_REGISTER=1。
"""
import gzip
import http.client
import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_CAND = [os.path.join(_HERE, '..', 'app.py'),                  # 入库后：tests/ 的上一级即仓库根
         os.path.join(_HERE, 'site_analytics', 'app.py')]      # 老位置：工作区根
APP = os.environ.get('SA_APP_PATH') or next((p for p in _CAND if os.path.isfile(p)), _CAND[0])
APP_DIR = os.path.dirname(APP)
PY = sys.executable
sys.dont_write_bytecode = True   # test_logic() 用 importlib 加载 app.py，不落 __pycache__ 到仓库
DEPLOY_KEY = 'p1key'

EXPECT_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'strict-origin-when-cross-origin',
    'X-Frame-Options': 'SAMEORIGIN',
}
CSP_MUST = ("default-src 'self'", "script-src 'self'", "style-src 'self'",
            "object-src 'none'", "base-uri 'self'", "form-action 'self'", "frame-ancestors 'self'")
CSP_FORBID = ('upgrade-insecure-requests', 'block-all-mixed-content', "default-src 'none'")

results = []


def check(name, ok, extra=''):
    results.append((name, bool(ok)))
    print('%-58s %s  %s' % (name, 'PASS' if ok else 'FAIL', extra))


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_port(port, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(('127.0.0.1', port), 0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def spawn(port, datadir, env_extra=None):
    env = dict(os.environ)
    env['SA_ALLOW_REGISTER'] = '1'
    for k in ('SA_SECURE_COOKIE', 'SA_CSRF_STRICT', 'SA_TRUSTED_PROXIES',
              'SA_DEPLOY_KEY', 'SA_REQUIRE_KEY'):
        env.pop(k, None)
    if env_extra:
        env.update(env_extra)
    cmd = [PY, APP, '--host', '127.0.0.1', '--port', str(port), '--data-dir', datadir]
    return subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                            stderr=subprocess.STDOUT, env=env)


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except Exception:
        proc.kill()


class Client(object):
    """http.client 封装：手动维护 sid cookie。

    返回 (status, flat_headers, all_headers, body_bytes, set_cookies)
    """

    def __init__(self, port):
        self.port = port
        self.cookie = ''

    def req(self, method, path, body=None, headers=None, with_cookie=True):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        h = {'User-Agent': 'Mozilla/5.0 P1HardeningTest'}
        if headers:
            h.update(headers)
        if with_cookie and self.cookie:
            h['Cookie'] = self.cookie
        conn.request(method, path, body=body, headers=h)
        r = conn.getresponse()
        data = r.read()
        allh = {}
        for k, v in r.getheaders():
            allh.setdefault(k, []).append(v)
        flat = {k: vals[-1] for k, vals in allh.items()}
        out = (r.status, flat, allh, data, allh.get('Set-Cookie', []))
        conn.close()
        return out

    def capture_sid(self, set_cookies):
        for sc in set_cookies:
            part = sc.split(';')[0].strip()
            if part.startswith('sid=') and len(part) > 4:
                self.cookie = part
                return True
        return False


def sec_ok(h):
    """4 个安全头齐备且 CSP 合规（保留两个 unsafe-inline、无禁止项）。"""
    for k, v in EXPECT_HEADERS.items():
        if h.get(k) != v:
            return False
    csp = h.get('Content-Security-Policy', '')
    for tok in CSP_MUST:
        if tok not in csp:
            return False
    for tok in CSP_FORBID:
        if tok in csp:
            return False
    if csp.count("'unsafe-inline'") != 2:
        return False
    return True


def jbody(data):
    try:
        return json.loads(data.decode('utf-8'))
    except Exception:
        return None


def stats_pv(data):
    j = jbody(data)
    if not isinstance(j, dict):
        return None
    d = j.get('data')
    if not isinstance(d, dict):
        return None
    return d.get('total_pv')


def ev_body(n):
    return json.dumps({'site': 'demo.com', 'visitor': 'v_%d' % n,
                       'session': 's_%d' % n, 'type': 'pageview',
                       'key': DEPLOY_KEY}).encode('utf-8')


def post_json(cli, path, obj, extra_headers=None, with_cookie=True):
    h = {'Content-Type': 'application/json'}
    if extra_headers:
        h.update(extra_headers)
    return cli.req('POST', path, body=json.dumps(obj).encode('utf-8'),
                   headers=h, with_cookie=with_cookie)


def send_event(cli, n):
    return cli.req('POST', '/api/event', body=ev_body(n),
                   headers={'Content-Type': 'application/json'})


# ---------------------------------------------------------------- L. 逻辑层
def test_logic():
    print('=== L. 逻辑层（importlib 加载 app.py，不启动服务）===')
    spec = importlib.util.spec_from_file_location('sa_p1_logic', APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    check('L1 STATS_CACHE_TTL == 90', mod.STATS_CACHE_TTL == 90,
          '实际=%s' % mod.STATS_CACHE_TTL)
    check('L2 _SECURITY_HEADERS 恰好 4 项', len(mod._SECURITY_HEADERS) == 4,
          '实际=%d' % len(mod._SECURITY_HEADERS))
    csp = dict(mod._SECURITY_HEADERS).get('Content-Security-Policy', '')
    check('L3 CSP 保留 2 个 unsafe-inline', csp.count("'unsafe-inline'") == 2)
    check('L4 CSP 无禁止项', all(t not in csp for t in CSP_FORBID))
    check('L5 环境变量名常量正确',
          mod.SECURE_COOKIE_ENV == 'SA_SECURE_COOKIE' and mod.CSRF_STRICT_ENV == 'SA_CSRF_STRICT')

    # get_stats: 默认命中缓存 / bypass_cache 重算 / 刷新同 key / key 不含 fresh
    mod._stats_cache.clear()

    class Probe(object):
        get_stats = mod.StatEngine.get_stats

        def __init__(self):
            self.n = 0

        def _compute_stats(self, site, days, range_str):
            self.n += 1
            return {'total_pv': self.n}

    p = Probe()
    r1 = p.get_stats('s.com', 30); n1 = p.n
    r2 = p.get_stats('s.com', 30); n2 = p.n
    r3 = p.get_stats('s.com', 30, bypass_cache=True); n3 = p.n
    r4 = p.get_stats('s.com', 30); n4 = p.n
    check('L6 默认命中缓存(_compute_stats 仅 1 次)',
          r1['total_pv'] == 1 and r2['total_pv'] == 1 and n1 == 1 and n2 == 1)
    check('L7 bypass_cache=True 重算', r3['total_pv'] == 2 and n3 == 2)
    check('L8 fresh 刷新同 key（后续默认调用不回退）',
          r4['total_pv'] == 2 and n4 == 2)
    keys = list(mod._stats_cache.keys())
    check('L9 缓存 key 仍 (site,days,range_str) 不含 fresh',
          keys == [('s.com', 30, None)], 'keys=%s' % (keys,))

    # _fresh_rate_ok: 10 秒窗口最多 3 次，第 4 次 False
    mod._FRESH_RATE.clear()

    class FakeReq(object):
        client_address = ('127.0.0.1', 12345)
        headers = {}

        def client_ip(self):
            return '127.0.0.1'

    outs = [mod.Handler._fresh_rate_ok(FakeReq()) for _ in range(4)]
    check('L10 fresh 限流前 3 True 第 4 False', outs == [True, True, True, False], str(outs))
    print()


# ---------------------------------------------------------------- S1（默认）
def test_s1(port):
    print('=== S1（默认 + SA_DEPLOY_KEY）：A 响应头 / B Secure / C CSRF / D fresh ===')
    c0 = Client(port)    # 无 cookie
    cli = Client(port)   # 注册后带 cookie

    # ---- A. 响应头矩阵 ----
    st, flat, allh, data, sc = c0.req('GET', '/login')
    check('A1 /login 200', st == 200, 'code=%s' % st)
    check('A1 四安全头齐备(200 HTML)', sec_ok(flat))
    cl = flat.get('Content-Length')
    check('A1 Content-Length 与 body 一致',
          cl is not None and int(cl) == len(data), 'cl=%s len=%d' % (cl, len(data)))
    check('A1 Cache-Control: no-store', flat.get('Cache-Control') == 'no-store')

    raw = open(os.path.join(APP_DIR, 'tracker.js'), 'rb').read()
    st, flat, allh, data, sc = c0.req('GET', '/tracker.js',
                                      headers={'Accept-Encoding': 'gzip'})
    check('A2 /tracker.js gzip 200',
          st == 200 and flat.get('Content-Encoding') == 'gzip',
          'code=%s ce=%s' % (st, flat.get('Content-Encoding')))
    check('A2 四安全头齐备(200 gzip)', sec_ok(flat))
    cl = flat.get('Content-Length')
    check('A2 Content-Length 与压缩后 body 一致',
          cl is not None and int(cl) == len(data), 'cl=%s len=%d' % (cl, len(data)))
    try:
        dec = gzip.decompress(data)
        gz_ok = (dec == raw)
    except Exception:
        dec, gz_ok = b'', False
    check('A2 gzip 可解压且内容与原文件一致', gz_ok,
          '解压=%d 原文件=%d' % (len(dec), len(raw)))

    st, flat, allh, data, sc = c0.req('GET', '/tracker.js')
    etag = flat.get('ETag', '')
    check('A3 首次 GET /tracker.js 200 且带 ETag', st == 200 and bool(etag), 'etag=%s' % etag)
    check('A3 四安全头齐备(200 静态)', sec_ok(flat))
    st, flat, allh, data, sc = c0.req('GET', '/tracker.js',
                                      headers={'If-None-Match': etag})
    check('A4 If-None-Match 命中 304', st == 304, 'code=%s' % st)
    check('A4 四安全头齐备(304)', sec_ok(flat))
    check('A4 304 Content-Length 0 且 body 空',
          flat.get('Content-Length') == '0' and len(data) == 0)

    st, flat, allh, data, sc = c0.req('OPTIONS', '/api/event')
    check('A5 OPTIONS /api/event 204', st == 204, 'code=%s' % st)
    check('A5 四安全头齐备(204)', sec_ok(flat))
    check('A5 ACAO 仍 *', flat.get('Access-Control-Allow-Origin') == '*')
    check('A5 204 无 body', len(data) == 0)

    st, flat, allh, data, sc = c0.req('GET', '/')
    check('A6 未登录 GET / → 302',
          st == 302 and flat.get('Location') == '/login',
          'code=%s loc=%s' % (st, flat.get('Location')))
    check('A6 四安全头齐备(302)', sec_ok(flat))
    check('A6 302 Content-Length 0 且 body 空',
          flat.get('Content-Length') == '0' and len(data) == 0)

    st, flat, allh, data, sc = c0.req('GET', '/p1-no-such-route')
    check('A7 未知路径 404', st == 404, 'code=%s' % st)
    check('A7 四安全头齐备(404 send_error)', sec_ok(flat))
    cl = flat.get('Content-Length')
    check('A7 404 Content-Length 与 body 一致',
          cl is not None and int(cl) == len(data), 'cl=%s len=%d' % (cl, len(data)))

    st, flat, allh, data, sc = c0.req('HEAD', '/login')
    check('A8 HEAD /login 200', st == 200, 'code=%s' % st)
    check('A8 四安全头齐备(HEAD)', sec_ok(flat))
    check('A8 HEAD 无 body', len(data) == 0)

    st, flat, allh, data, sc = c0.req('GET', '/api/me')
    check('A9 未登录 /api/me 401', st == 401, 'code=%s' % st)
    check('A9 四安全头齐备(401 JSON)', sec_ok(flat))
    check('A9 _send_json 加 Cache-Control: no-store',
          flat.get('Cache-Control') == 'no-store')

    # ---- B. Cookie 条件化 Secure ----
    U, P = 'p1admin', 'secret66'
    st, flat, allh, data, sc = post_json(cli, '/api/register', {'username': U, 'password': P})
    check('B1 纯 HTTP 直连注册 200', st == 200, 'code=%s' % st)
    check('B1 Set-Cookie 名仍为 sid', any(x.startswith('sid=') for x in sc), str(sc))
    check('B1 纯 HTTP 直连 Set-Cookie 不含 ; Secure',
          all('; Secure' not in x for x in sc), str(sc))
    check('B1 捕获 sid cookie', cli.capture_sid(sc))

    st, flat, allh, data, sc = post_json(cli, '/api/login', {'username': U, 'password': P},
                                         extra_headers={'X-Forwarded-Proto': 'https'})
    check('B2 可信 loopback + XFP https 登录 200', st == 200, 'code=%s' % st)
    check('B2 Set-Cookie 含 ; Secure', any('; Secure' in x for x in sc), str(sc))

    st, flat, allh, data, sc = post_json(cli, '/api/logout', {},
                                         extra_headers={'X-Forwarded-Proto': 'https'},
                                         with_cookie=False)
    check('B3 logout 同一判断，Set-Cookie 含 ; Secure',
          st == 200 and any('; Secure' in x for x in sc), str(sc))

    # ---- C. CSRF 同源校验 ----
    st, flat, allh, data, sc = post_json(c0, '/api/admin/block', {},
                                         extra_headers={'Origin': 'https://evil.example'})
    check('C1 跨站 Origin 管理类 POST → 403', st == 403, 'code=%s' % st)
    check('C1 四安全头齐备(403)', sec_ok(flat))
    j = jbody(data) or {}
    check('C1 403 文案含来源/跨站校验',
          ('来源' in str(j.get('error', '')) or '跨站' in str(j.get('error', ''))), str(j))

    st, flat, allh, data, sc = c0.req('POST', '/api/event', body=ev_body(1),
                                      headers={'Content-Type': 'application/json',
                                               'Origin': 'https://evil.example'})
    check('C2 /api/event 带任意 Origin → 200', st == 200,
          'code=%s body=%s' % (st, data[:120]))
    check('C2 ACAO 仍 *', flat.get('Access-Control-Allow-Origin') == '*')
    check('C2 四安全头齐备(200 event)', sec_ok(flat))

    st, flat, allh, data, sc = post_json(cli, '/api/admin/settings', {})
    check('C3 默认模式缺 Origin 写操作放行(业务 200)', st == 200, 'code=%s' % st)

    # ---- D. fresh 绕过缓存 + 刷新同 key + 未登录 401 ----
    st, flat, allh, data, sc = cli.req('GET', '/api/stats?site=demo.com')
    check('D1 /api/stats 200（已登录）', st == 200, 'code=%s' % st)
    check('D1 统计 JSON 带 Cache-Control: no-store',
          flat.get('Cache-Control') == 'no-store')
    check('D1 四安全头齐备(200 stats)', sec_ok(flat))
    pv_a = stats_pv(data)
    check('D1 total_pv 可读', isinstance(pv_a, int), 'pv=%s' % pv_a)

    send_event(c0, 201)
    send_event(c0, 202)
    st, flat, allh, data, sc = cli.req('GET', '/api/stats?site=demo.com')
    pv_cached = stats_pv(data)
    check('D2 无 fresh 命中缓存（pv 不变）', pv_cached == pv_a,
          'cached=%s a=%s' % (pv_cached, pv_a))

    send_event(c0, 203)
    st, flat, allh, data, sc = cli.req('GET', '/api/stats?site=demo.com&fresh=1')
    pv_fresh = stats_pv(data)
    check('D3 fresh=1 绕过缓存返回新数据',
          isinstance(pv_fresh, int) and isinstance(pv_cached, int) and pv_fresh > pv_cached,
          'fresh=%s cached=%s' % (pv_fresh, pv_cached))

    st, flat, allh, data, sc = cli.req('GET', '/api/stats?site=demo.com')
    pv_after = stats_pv(data)
    check('D4 fresh 刷新同 key（后续默认调用不回退）', pv_after == pv_fresh,
          'after=%s fresh=%s' % (pv_after, pv_fresh))

    st, flat, allh, data, sc = c0.req('GET', '/api/stats?site=demo.com&fresh=1')
    check('D5 未登录 /api/stats?fresh=1 → 401', st == 401, 'code=%s' % st)
    check('D5 四安全头齐备(401)', sec_ok(flat))
    print()


# ---------------------------------------------------------------- S2 / S3
def test_secure_cookie_force(port, expect_secure, with_xfp, label):
    print('=== %s ===' % label)
    c = Client(port)
    hdr = {'X-Forwarded-Proto': 'https'} if with_xfp else None
    st, flat, allh, data, sc = post_json(c, '/api/register',
                                         {'username': 'p1u', 'password': 'secret66'},
                                         extra_headers=hdr)
    check('%s 注册 200' % label, st == 200, 'code=%s' % st)
    has = any('; Secure' in x for x in sc)
    check('%s Set-Cookie Secure==%s' % (label, expect_secure),
          has == expect_secure, str(sc))
    print()


# ---------------------------------------------------------------- S4
def test_strict(port):
    print('=== S4（SA_CSRF_STRICT=1）===')
    c = Client(port)
    st, flat, allh, data, sc = post_json(c, '/api/admin/block', {})
    check('C4 strict 缺 Origin 写操作 → 403', st == 403, 'code=%s' % st)
    j = jbody(data) or {}
    check('C4 403 文案为「缺少来源校验头」',
          '缺少来源校验头' in str(j.get('error', '')), str(j))
    check('C4 四安全头齐备(403 strict)', sec_ok(flat))

    st, flat, allh, data, sc = post_json(c, '/api/admin/block', {},
                                         extra_headers={'Origin': 'http://127.0.0.1'})
    check('C5 strict 同源 Origin 放行（非 403，未登录为 401）', st == 401, 'code=%s' % st)
    print()


# ---------------------------------------------------------------- S5
def test_fresh_rate(port):
    print('=== S5（干净窗口：fresh 限流降级走缓存）===')
    c = Client(port)
    st, flat, allh, data, sc = post_json(c, '/api/register',
                                         {'username': 'p1u', 'password': 'secret66'})
    check('D6 S5 注册 200', st == 200, 'code=%s' % st)
    c.capture_sid(sc)

    send_event(c, 1)
    st, flat, allh, data, sc = c.req('GET', '/api/stats?site=demo.com')
    pv0 = stats_pv(data)
    check('D7 S5 /api/stats 200 且 pv 可读',
          st == 200 and isinstance(pv0, int), 'pv0=%s' % pv0)

    oks = []
    for _ in range(3):
        st, flat, allh, data, sc = c.req('GET', '/api/stats?site=demo.com&fresh=1')
        oks.append(st == 200)
    check('D8 前 3 次 fresh=1 均 200（窗口内未被限流）', all(oks), str(oks))

    send_event(c, 2)   # DB 的 pv 变为 pv0+1
    st, flat, allh, data, sc = c.req('GET', '/api/stats?site=demo.com&fresh=1')
    pv4 = stats_pv(data)
    check('D9 第 4 次 fresh 被限流降级走缓存（返回缓存 pv0）',
          st == 200 and pv4 == pv0, 'pv4=%s pv0=%s' % (pv4, pv0))

    # 不同 days → 新缓存 key → 新算一次，证明 DB 确有 pv0+1，D9 拿到的确实是缓存旧值
    st, flat, allh, data, sc = c.req('GET', '/api/stats?site=demo.com&days=7')
    pv_new = stats_pv(data)
    check('D10 DB 确有新数据（pv0+1），证实 D9 是缓存而非新算',
          pv_new == pv0 + 1, 'pv_new=%s 期望=%s' % (pv_new, pv0 + 1))

    st, flat, allh, data, sc = c.req('GET', '/api/stats?site=demo.com&fresh=1')
    check('D11 限流后仍 200（降级走缓存，不报 429）', st == 200, 'code=%s' % st)
    print()


# ---------------------------------------------------------------- main
def main():
    procs = []

    def launch(env_extra=None):
        p = free_port()
        d = tempfile.mkdtemp(prefix='sa_p1_')
        proc = spawn(p, d, env_extra)
        procs.append(proc)
        assert wait_port(p), '服务未启动'
        return p

    try:
        test_logic()
        p1 = launch({'SA_DEPLOY_KEY': DEPLOY_KEY})
        test_s1(p1)
        p2 = launch({'SA_SECURE_COOKIE': '1'})
        test_secure_cookie_force(p2, True, False, 'S2 SA_SECURE_COOKIE=1 强制 Secure')
        p3 = launch({'SA_SECURE_COOKIE': '0'})
        test_secure_cookie_force(p3, False, True, 'S3 SA_SECURE_COOKIE=0 强制不 Secure（带 XFP https）')
        p4 = launch({'SA_CSRF_STRICT': '1'})
        test_strict(p4)
        p5 = launch({'SA_DEPLOY_KEY': DEPLOY_KEY})
        test_fresh_rate(p5)
    finally:
        for proc in procs:
            stop(proc)

    print()
    fails = [n for n, ok in results if not ok]
    print('checks=%d failures=%d' % (len(results), len(fails)))
    for n in fails:
        print('  FAIL:', n)
    print('RESULT:', 'ALL_PASS' if not fails else 'HAS_FAIL')
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
