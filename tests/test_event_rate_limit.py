# -*- coding: utf-8 -*-
"""v1.8.x /api/event 限流 + site_key 修复的长期入库回归（spec-event-rl #38，12 条验收断言）。

设计要点：
  * 每个场景用 tempfile.mkdtemp() + --data-dir 启动独立子进程做真实 HTTP；
    限流常量在 app.py import 期读取，测不同环境变量值必须重启子进程。
  * 客户端一律伪装浏览器 UA —— Python-urllib / curl 等会命中 _BOT_UA_RE 造成 400 假失败。
  * 用 SA_DEPLOY_KEY 全局兜底令牌并随事件带 key=，使任意站点均可落库（不依赖 site_known 状态）；
    「令牌错 403」改用从未上报过的新站点，避免 site_known 宽松放行掩盖断言。
  * 断言 10（_EVENT_RATE_MAX 清空）是白盒：该常量硬编码 10000、无环境变量可覆盖，
    走 HTTP 造 10001 个 IP 不现实，故用 importlib 在当前进程加载 app.py 后改小上限直接调
    Handler._event_rate_ok()。其余 11 条全部走真实 HTTP 子进程。
  * 所有运行期产物落在系统临时目录，不写仓库工作树。
"""
import http.client as _http_client
import importlib.util
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

_HERE = os.path.dirname(os.path.abspath(__file__))
_CAND = [os.path.join(_HERE, '..', 'app.py'),                  # 入库后：tests/ 的上一级即仓库根
         os.path.join(_HERE, 'site_analytics', 'app.py')]      # 老位置：工作区根
APP = os.environ.get('SA_APP_PATH') or next((p for p in _CAND if os.path.isfile(p)), _CAND[0])
PY = sys.executable
sys.dont_write_bytecode = True   # importlib 加载 app.py 时不在仓库内生成 __pycache__
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

# _BOT_UA_RE 命中 python-urllib / curl / headless 等；必须是干净的浏览器 UA
BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
DEPLOY_KEY = 'rl_deploy_key'
RATE_ERR = {'status': False, 'error': '上报过于频繁，请稍后再试'}

results = []


def check(name, ok, extra=''):
    results.append((name, bool(ok)))
    print('%-62s %s  %s' % (name, 'PASS' if ok else 'FAIL', extra))


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
            time.sleep(0.1)
    return False


def req(port, method, path, body=None, headers=None):
    conn = _http_client.HTTPConnection('127.0.0.1', port, timeout=15)
    h = {'User-Agent': BROWSER_UA}
    if headers:
        h.update(headers)
    conn.request(method, path, body=body, headers=h)
    r = conn.getresponse()
    data = r.read()
    flat = {k.lower(): v for k, v in r.getheaders()}
    code = r.status
    conn.close()
    return code, flat, data


def jbody(data):
    try:
        return json.loads(data.decode('utf-8'))
    except Exception:
        return None


def event_query(site='rl.test', **kw):
    p = {'site': site, 'visitor': 'v1', 'session': 's1', 'type': 'pageview',
         'path': '/', 'key': DEPLOY_KEY}
    p.update(kw)
    return '/api/event?' + urllib.parse.urlencode(p)


def event_obj(site='rl.test', **kw):
    d = {'site': site, 'visitor': 'v1', 'session': 's1', 'type': 'pageview',
         'path': '/', 'key': DEPLOY_KEY}
    d.update(kw)
    return d


def post_json(port, path, obj, extra_headers=None):
    hdrs = {'Content-Type': 'application/json'}
    if extra_headers:
        hdrs.update(extra_headers)
    return req(port, 'POST', path, json.dumps(obj).encode('utf-8'), hdrs)


def sid_from(h):
    m = re.search(r'sid=([^;]+)', h.get('set-cookie', '') or '')
    return m.group(1) if m else ''


class Box(object):
    """一个隔离实例：独立临时数据目录 + 随机端口 + 可注入环境变量。"""

    def __init__(self, env_extra=None, register=False):
        self.dir = tempfile.mkdtemp(prefix='sa_evrl_')
        self.port = free_port()
        env = dict(os.environ)
        for k in ('SA_TRUSTED_PROXIES', 'SA_EVENT_RATE_LIMIT', 'SA_EVENT_RATE_WINDOW',
                  'SA_SECURE_COOKIE', 'SA_CSRF_STRICT', 'SA_REQUIRE_KEY',
                  'SA_DEPLOY_KEY', 'SA_ALLOW_REGISTER'):
            env.pop(k, None)
        env['SA_DEPLOY_KEY'] = DEPLOY_KEY
        if register:
            env['SA_ALLOW_REGISTER'] = '1'
        if env_extra:
            env.update(env_extra)
        self.proc = subprocess.Popen(
            [PY, APP, '--host', '127.0.0.1', '--port', str(self.port), '--data-dir', self.dir],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
        self.ok = wait_port(self.port)

    def stop(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=8)
        except Exception:
            self.proc.kill()
        shutil.rmtree(self.dir, ignore_errors=True)

    def _db(self):
        return sqlite3.connect(os.path.join(self.dir, 'events.db'))

    def counts(self):
        con = self._db()
        e = con.execute('SELECT COUNT(*) FROM events').fetchone()[0]
        b = con.execute('SELECT COUNT(*) FROM blocked_visitors').fetchone()[0]
        con.close()
        return e, b

    def site_key(self, site):
        con = self._db()
        row = con.execute('SELECT site_key FROM sites WHERE site=?', (site,)).fetchone()
        con.close()
        return (row[0] or '') if row else None

    def sites_rows(self, site):
        con = self._db()
        n = con.execute('SELECT COUNT(*) FROM sites WHERE site=?', (site,)).fetchone()[0]
        con.close()
        return n


def run(fn, env_extra=None, register=False):
    b = Box(env_extra, register)
    try:
        if not b.ok:
            check('启动失败 env=%r' % (env_extra,), False)
            return
        try:
            fn(b)
        except Exception as e:
            check('场景异常 %s env=%r' % (getattr(fn, '__name__', 'fn'), env_extra), False, repr(e))
    finally:
        b.stop()


# ---------------------------------------------------------------- 1 / 2
def t_basic(b):
    """1. 正常 GET + 3 种 POST 均 200 / ACAO:* / events+1；2. 返回码语义不被限流串改。"""
    e0, _ = b.counts()
    cases = [
        ('GET(query)', 'GET', event_query(site='basic.test'), None, None),
        ('POST JSON', 'POST', '/api/event',
         json.dumps(event_obj(site='basic.test', visitor='v2')).encode('utf-8'),
         {'Content-Type': 'application/json'}),
        ('POST form', 'POST', '/api/event',
         urllib.parse.urlencode(event_obj(site='basic.test', visitor='v3')).encode('utf-8'),
         {'Content-Type': 'application/x-www-form-urlencoded'}),
        ('POST text-plain', 'POST', '/api/event',
         json.dumps(event_obj(site='basic.test', visitor='v4')).encode('utf-8'),
         {'Content-Type': 'text/plain'}),
    ]
    for i, (label, method, path, body, hdrs) in enumerate(cases):
        c, h, d = req(b.port, method, path, body=body, headers=hdrs)
        e_now, _ = b.counts()
        good = (c == 200 and (jbody(d) or {}).get('status') is True
                and h.get('access-control-allow-origin') == '*'
                and e_now == e0 + i + 1)
        check('01 %s 200 + ACAO:* + events+1' % label, good,
              'code=%s acao=%s ev=%d' % (c, h.get('access-control-allow-origin'), e_now))
    c, h, d = req(b.port, 'GET', event_query(site='badkey.test', key='wrong-key'))
    check('02 令牌错仍 403 + ACAO:*',
          c == 403 and h.get('access-control-allow-origin') == '*', 'code=%s' % c)
    c, h, d = req(b.port, 'GET', event_query(site='basic.test', type='not_a_type'))
    check('02b add_event False 仍 400 + ACAO:*',
          c == 400 and h.get('access-control-allow-origin') == '*', 'code=%s' % c)


# ---------------------------------------------------------------- 3 / 4
def t_limit2(b):
    """3. LIMIT=2 第 3 次 429 + 指定 JSON + ACAO:*；4. 429 落库前拦截。"""
    e0, bv0 = b.counts()
    codes, bodies, acaos = [], [], []
    for i in range(3):
        c, h, d = req(b.port, 'GET', event_query(site='rl.test', visitor='v%d' % i))
        codes.append(c)
        bodies.append(jbody(d) or {})
        acaos.append(h.get('access-control-allow-origin'))
    check('03 LIMIT=2 前2次200 第3次429', codes == [200, 200, 429], 'codes=%s' % codes)
    check('03b 429 JSON 指定文案 + ACAO:*',
          bodies[2] == RATE_ERR and acaos[2] == '*', 'body=%s acao=%s' % (bodies[2], acaos[2]))
    e1, bv1 = b.counts()
    check('04 429 期间 events 与 blocked_visitors 不增长',
          e1 == e0 + 2 and bv1 == bv0,
          'events %d->%d blocked %d->%d' % (e0, e1, bv0, bv1))


# ---------------------------------------------------------------- 5
def t_get_to_post(b):
    c1, _, _ = req(b.port, 'GET', event_query(site='rl.test', visitor='g1'))
    c2, _, _ = req(b.port, 'GET', event_query(site='rl.test', visitor='g2'))
    c3, _, _ = post_json(b.port, '/api/event', event_obj(site='rl.test', visitor='g3'))
    check('05 GET 打满后 POST 也 429（两处插桩共享字典）',
          (c1, c2, c3) == (200, 200, 429), 'codes=%s' % ((c1, c2, c3),))


def t_post_to_get(b):
    c1, _, _ = post_json(b.port, '/api/event', event_obj(site='rl.test', visitor='p1'))
    c2, _, _ = post_json(b.port, '/api/event', event_obj(site='rl.test', visitor='p2'))
    c3, _, _ = req(b.port, 'GET', event_query(site='rl.test', visitor='p3'))
    check('05b POST 打满后 GET 也 429（两处插桩共享字典）',
          (c1, c2, c3) == (200, 200, 429), 'codes=%s' % ((c1, c2, c3),))


# ---------------------------------------------------------------- 6
def t_fallback(b, label):
    """修正后语义：0 / 负值 / 非法值 / 空串一律回退默认 600，不是钳制为 1。"""
    codes = []
    for i in range(5):
        c, _, _ = req(b.port, 'GET', event_query(site='fb.test', visitor='v%d' % i))
        codes.append(c)
    check('06 回退默认 %s 启动不崩、连发5次全200' % label,
          codes == [200] * 5, 'codes=%s' % codes)


# ---------------------------------------------------------------- 7
def t_window(b):
    codes = []
    for i in range(3):
        c, _, _ = req(b.port, 'GET', event_query(site='win.test', visitor='w%d' % i))
        codes.append(c)
    time.sleep(1.3)
    c4, _, _ = req(b.port, 'GET', event_query(site='win.test', visitor='w4'))
    codes.append(c4)
    check('07 WINDOW=1 打满后 sleep1.3s 恢复 200',
          codes == [200, 200, 429, 200], 'codes=%s' % codes)


# ---------------------------------------------------------------- 8
def t_concurrent(b):
    """20 线程齐发同一 IP，_EVENT_RATE_LOCK 保证恰好 LIMIT 个通过且无少计。"""
    n, limit = 20, 5
    e0, _ = b.counts()
    barrier = threading.Barrier(n)
    out = [0] * n

    def worker(i):
        barrier.wait()
        try:
            c, _, _ = req(b.port, 'GET', event_query(site='cc.test', visitor='c%d' % i))
            out[i] = c
        except Exception:
            out[i] = 0

    ts = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    n200, n429 = out.count(200), out.count(429)
    e1, _ = b.counts()
    check('08 并发锁 20线程恰好5个200/15个429、events+5',
          n200 == limit and n429 == n - limit and e1 == e0 + limit,
          '200=%d 429=%d events %d->%d out=%s' % (n200, n429, e0, e1, out))


# ---------------------------------------------------------------- 9
def t_xff_default(b):
    """生产默认（不设 SA_TRUSTED_PROXIES，信任 loopback）：XFF 取最右一跳。"""

    def ev(xff, visitor):
        c, _, _ = req(b.port, 'GET', event_query(site='xff.test', visitor=visitor),
                       headers={'X-Forwarded-For': xff})
        return c

    codes = [ev('1.1.1.1, 198.51.100.1', 'x1'),
             ev('2.2.2.2, 198.51.100.1', 'x2'),
             ev('3.3.3.3, 198.51.100.1', 'x3'),   # 最左伪造、最右相同 -> 仍 429
             ev('9.9.9.9, 198.51.100.2', 'x4'),   # 不同最右 -> 独立配额
             ev('8.8.8.8, 198.51.100.2', 'x5')]
    check('09 默认可信代理 XFF 最右一跳：伪造最左无效、不同最右独立配额',
          codes == [200, 200, 429, 200, 200], 'codes=%s' % codes)


def t_xff_untrusted(b):
    """SA_TRUSTED_PROXIES=192.0.2.1：TCP 对端 127.0.0.1 不可信，忽略 XFF 按对端计数。"""

    def ev(xff, visitor):
        c, _, _ = req(b.port, 'GET', event_query(site='xff2.test', visitor=visitor),
                       headers={'X-Forwarded-For': xff})
        return c

    codes = [ev('198.51.100.1', 'u1'), ev('198.51.100.1', 'u2'),
             ev('198.51.100.2', 'u3')]
    check('09b 不可信对端忽略 XFF，按 TCP 对端计数',
          codes == [200, 200, 429], 'codes=%s' % codes)


# ---------------------------------------------------------------- 10（白盒）
def t_max_clear():
    """_EVENT_RATE_MAX 硬编码 10000 且无环境变量可覆盖，改小上限做白盒断言。"""
    spec = importlib.util.spec_from_file_location('sa_evrl_logic', APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod._EVENT_RATE.clear()
    mod._EVENT_RATE_MAX = 3

    class FakeReq(object):
        def __init__(self, ip):
            self._ip = ip

        def client_ip(self):
            return self._ip

    sizes = []
    for i in range(7):
        mod.Handler._event_rate_ok(FakeReq('10.0.0.%d' % i))
        sizes.append(len(mod._EVENT_RATE))
    fell = any(sizes[i] > sizes[i + 1] for i in range(len(sizes) - 1))
    check('10 _EVENT_RATE_MAX 超上限回落而非无界增长',
          fell and sizes[-1] <= 3 and max(sizes) <= 4, 'sizes=%s' % sizes)


# ---------------------------------------------------------------- 11
def t_isolation(b):
    """三个限流器（_EVENT_RATE / _AUTH_RATE / _FRESH_RATE）互不挤占。"""
    c, h, _ = post_json(b.port, '/api/register',
                        {'username': 'rladmin', 'password': 'rladmin123'})
    sid = sid_from(h)
    check('11 注册 admin 成功（空库首个用户）', c == 200 and bool(sid),
          'code=%s sid=%s' % (c, bool(sid)))
    codes = []
    for i in range(3):
        cc, _, _ = req(b.port, 'GET', event_query(site='iso.test', visitor='i%d' % i))
        codes.append(cc)
    check('11b 事件限流已打满', codes == [200, 200, 429], 'codes=%s' % codes)
    logins = []
    for i in range(3):
        cc, _, _ = post_json(b.port, '/api/login',
                            {'username': 'rladmin', 'password': 'wrong%d' % i})
        logins.append(cc)
    check('11c 打满 _EVENT_RATE 后登录限流仍独立（3次均401）',
          logins == [401] * 3, 'codes=%s' % logins)
    cc, _, _ = req(b.port, 'GET', '/api/stats?site=iso.test&fresh=1',
                    headers={'Cookie': 'sid=' + sid})
    check('11d 打满 _EVENT_RATE 后 fresh=1 仍放行（200）', cc == 200, 'code=%s' % cc)


# ---------------------------------------------------------------- 12
def t_site_key(b):
    """site_key 两个修复：list_sites 键名一致；rowcount==0 补行后新令牌生效。"""
    c, h, _ = post_json(b.port, '/api/register',
                        {'username': 'rladmin', 'password': 'rladmin123'})
    sid = sid_from(h)
    auth = {'Cookie': 'sid=' + sid}
    post_json(b.port, '/api/site', {'site': 'key.test', 'label': 'k'}, auth)
    c, _, d = req(b.port, 'GET', '/api/site', headers=auth)
    sites = (jbody(d) or {}).get('sites') or []
    row = next((s for s in sites if s.get('site') == 'key.test'), None)
    dbk = b.site_key('key.test')
    good = (c == 200 and bool(row) and bool(row.get('site_key'))
            and row['site_key'] == dbk and bool(dbk))
    check('12 GET /api/site 的 site_key 非空且与 sqlite 一致', good,
          'code=%s api=%r db=%r' % (c, row.get('site_key') if row else None, dbk))

    c, _, _ = req(b.port, 'GET', event_query(site='orphan.test', visitor='o1'))
    rows0 = b.sites_rows('orphan.test')
    check('12b 孤儿站点仅 events 有数据、sites 无行',
          c == 200 and rows0 == 0, 'code=%s rows=%d' % (c, rows0))

    c, _, d = post_json(b.port, '/api/site/key', {'site': 'orphan.test'}, auth)
    new_key = (jbody(d) or {}).get('site_key')
    dbk2 = b.site_key('orphan.test')
    rows1 = b.sites_rows('orphan.test')
    check('12c rowcount==0 补行，get_site_key 返回新令牌',
          c == 200 and bool(new_key) and new_key == dbk2 and rows1 == 1,
          'code=%s new=%r db=%r rows=%d' % (c, new_key, dbk2, rows1))

    c0, _, _ = req(b.port, 'GET', event_query(site='orphan.test', visitor='o2', key=''))
    c1, _, _ = req(b.port, 'GET', event_query(site='orphan.test', visitor='o3', id=new_key))
    check('12d _deploy_ok 不带 id 403 / 带正确 id 200',
          c0 == 403 and c1 == 200, 'codes=%s' % ((c0, c1),))


FALLBACKS = [
    ({'SA_EVENT_RATE_LIMIT': '0'}, 'LIMIT=0'),
    ({'SA_EVENT_RATE_LIMIT': '-1'}, 'LIMIT=-1'),
    ({'SA_EVENT_RATE_LIMIT': 'abc'}, 'LIMIT=abc'),
    ({'SA_EVENT_RATE_LIMIT': ''}, 'LIMIT=空串'),
    ({'SA_EVENT_RATE_WINDOW': '-1'}, 'WINDOW=-1'),
]


def main():
    run(t_basic)
    run(t_limit2, {'SA_EVENT_RATE_LIMIT': '2'})
    run(t_get_to_post, {'SA_EVENT_RATE_LIMIT': '2'})
    run(t_post_to_get, {'SA_EVENT_RATE_LIMIT': '2'})
    for env, label in FALLBACKS:
        run(lambda b, l=label: t_fallback(b, l), env)
    run(t_window, {'SA_EVENT_RATE_LIMIT': '2', 'SA_EVENT_RATE_WINDOW': '1'})
    run(t_concurrent, {'SA_EVENT_RATE_LIMIT': '5'})
    run(t_xff_default, {'SA_EVENT_RATE_LIMIT': '2'})
    run(t_xff_untrusted, {'SA_EVENT_RATE_LIMIT': '2', 'SA_TRUSTED_PROXIES': '192.0.2.1'})
    t_max_clear()   # 白盒，不启动子进程
    run(t_isolation, {'SA_EVENT_RATE_LIMIT': '2'}, register=True)
    run(t_site_key, register=True)

    print()
    fails = [n for n, ok in results if not ok]
    print('checks=%d failures=%d' % (len(results), len(fails)))
    for n in fails:
        print('  FAIL:', n)
    print('RESULT:', 'ALL_PASS' if not fails else 'HAS_FAIL')
    return 0 if not fails else 1


if __name__ == '__main__':
    sys.exit(main())
