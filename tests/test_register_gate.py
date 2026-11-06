# -*- coding: utf-8 -*-
"""v1.8.6 自助注册门控回归。

覆盖三件事：
  A. 默认（不设 SA_ALLOW_REGISTER）：/api/register -> 403，登录页不暴露注册入口，启动日志声明已关闭；
  B. SA_ALLOW_REGISTER=1 且已有管理员：注册 -> 200 但 pending=True（viewer + disabled），不种会话、
     不能登录、读不到任何统计；管理员启用后才能登录；
  C. SA_ALLOW_REGISTER=1 且空库：首个注册者仍是 admin 并直接登录（引导路径不回退），同时启动stderr告警。

不碰生产数据：每个实例用独立 data-dir + 随机端口。
"""
import http.cookiejar
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_CAND = [os.path.join(_HERE, '..', 'app.py'),                  # 入库后：tests/ 的上一级即仓库根
         os.path.join(_HERE, 'site_analytics', 'app.py')]      # 老位置：工作区根
APP = os.environ.get('SA_APP_PATH') or next((p for p in _CAND if os.path.isfile(p)), _CAND[0])
PY = sys.executable
results = []


def check(name, cond, detail=''):
    results.append((name, bool(cond)))
    print(('PASS ' if cond else 'FAIL ') + name + (('  | ' + str(detail)) if detail and not cond else ''))


def free_port():
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


def wait_port(port, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(('127.0.0.1', port), 0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


class Client(object):
    def __init__(self, base):
        self.base = base
        self.cj = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cj))
        self.op.addheaders = [('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) GateProbe')]

    def _do(self, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data,
                                     method='POST' if body is not None else 'GET')
        if body is not None:
            req.add_header('Content-Type', 'application/json')
        try:
            r = self.op.open(req, timeout=10)
            raw = r.read()
            code, headers = r.status, dict(r.headers)
        except urllib.error.HTTPError as e:
            raw = e.read()
            code, headers = e.code, dict(e.headers)
        try:
            return code, (json.loads(raw.decode('utf-8')) if raw else None), headers, raw.decode('utf-8', 'replace')
        except Exception:
            return code, '<<NOT_JSON>>', headers, raw.decode('utf-8', 'replace')

    def post(self, path, body):
        return self._do(path, body)

    def get(self, path):
        return self._do(path)

    def sid_names(self):
        return [c.name for c in self.cj]


def boot(datadir, reg_on, pre_admin=None):
    """起一个实例，返回 (proc, base, stderr_path)。reg_on=False 时显式清除该环境变量。"""
    env = dict(os.environ)
    if reg_on:
        env['SA_ALLOW_REGISTER'] = '1'
    else:
        env.pop('SA_ALLOW_REGISTER', None)
    if pre_admin:
        p = subprocess.run([PY, APP, '--create-admin', pre_admin[0], pre_admin[1], '--data-dir', datadir],
                           capture_output=True, text=True, timeout=90, env=env)
        assert p.returncode == 0, 'create-admin 失败: %s%s' % (p.stdout, p.stderr)
    port = free_port()
    errpath = os.path.join(datadir, '_stderr.log')
    errf = open(errpath, 'w', encoding='utf-8')
    proc = subprocess.Popen([PY, APP, '--host', '127.0.0.1', '--port', str(port), '--data-dir', datadir],
                            stdout=subprocess.DEVNULL, stderr=errf, env=env)
    proc._errf = errf
    assert wait_port(port), '服务未启动'
    return proc, 'http://127.0.0.1:%d' % port, errpath


def stop(proc):
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except Exception:
        proc.kill()
    try:
        proc._errf.close()
    except Exception:
        pass


WORK = tempfile.mkdtemp(prefix='sa_reggate_')
sys.stdout.reconfigure(encoding='utf-8')

# ---------------- A. 默认关闭 ----------------
print('--- A. 默认（SA_ALLOW_REGISTER 未设）---')
dA = os.path.join(WORK, 'a')
os.makedirs(dA, exist_ok=True)
proc, base, errpath = boot(dA, reg_on=False)
try:
    c = Client(base)
    code, j, hd, raw = c.post('/api/register', {'username': 'sneaky', 'password': 'sneaky123'})
    check('A1 注册 -> 403', code == 403, '%s %s' % (code, raw[:120]))
    check('A2 响应为 JSON 且 status=False', isinstance(j, dict) and j.get('status') is False, raw[:160])
    check('A3 错误文案提示已关闭', isinstance(j, dict) and '已关闭' in (j.get('error') or ''), raw[:160])
    check('A4 不种会话 cookie', 'sid' not in c.sid_names(), c.sid_names())
    code, j, _, _ = c.get('/api/me')
    check('A5 注册失败后 /api/me -> 401', code == 401, code)
    code, _, _, html = c.get('/login')
    check('A6 登录页 200', code == 200, code)
    check('A7 登录页下发 reg=false', 'var SA_CONF={"reg":false};' in html, html[:0])
    check('A8 登录页不残留 reg=true', 'var SA_CONF={"reg":true};' not in html)
    check('A9 登录页含注册入口隐藏逻辑', 'applyRegAvailability' in html)
    con = sqlite3.connect(os.path.join(dA, 'events.db'))
    n = con.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    con.close()
    check('A10 库内未落任何用户', n == 0, n)
finally:
    stop(proc)
log = open(errpath, encoding='utf-8').read()
check('A11 启动日志声明注册已关闭', '自助注册：已关闭' in log, log[-400:])

# ---------------- B. 开启 + 已有管理员 -> 待审 ----------------
print('--- B. SA_ALLOW_REGISTER=1 且已有管理员 ---')
dB = os.path.join(WORK, 'b')
os.makedirs(dB, exist_ok=True)
BUSER, BPWD = 'boss', 'boss123456'
proc, base, errpath = boot(dB, reg_on=True, pre_admin=(BUSER, BPWD))
try:
    cur = Client(base)
    code, _, _, html = cur.get('/login')
    check('B1 登录页下发 reg=true', 'var SA_CONF={"reg":true};' in html, code)

    reg = Client(base)
    code, j, _, raw = reg.post('/api/register', {'username': 'alice', 'password': 'alice123456'})
    check('B2 注册 -> 200', code == 200, '%s %s' % (code, raw[:160]))
    check('B3 响应 pending=True', isinstance(j, dict) and j.get('pending') is True, raw[:160])
    check('B4 角色=viewer', isinstance(j, dict) and j.get('user', {}).get('role') == 'viewer', raw[:160])
    check('B5 不种会话 cookie', 'sid' not in reg.sid_names(), reg.sid_names())
    code, _, _, _ = reg.get('/api/me')
    check('B6 待审账号 /api/me -> 401', code == 401, code)
    for api in ('/api/stats?site=example.com', '/api/visitors?site=example.com',
                '/api/admin/blocked', '/api/admin/settings'):
        code, _, _, _ = reg.get(api)
        check('B7 待审账号读 %s -> 401' % api.split('?')[0], code == 401, code)
    code, _, _, _ = reg.post('/api/login', {'username': 'alice', 'password': 'alice123456'})
    check('B8 待审账号登录 -> 401', code == 401, code)

    adm = Client(base)
    code, j, _, _ = adm.post('/api/login', {'username': BUSER, 'password': BPWD})
    check('B9 管理员登录 -> 200', code == 200, '%s %s' % (code, j))
    code, j, _, _ = adm.get('/api/admin/users')
    rows = (j or {}).get('data') or []
    alice = next((r for r in rows if r.get('username') == 'alice'), None)
    check('B10 用户列表里 alice 为 disabled', bool(alice) and alice.get('status') == 'disabled', rows)
    check('B11 alice 角色 viewer', bool(alice) and alice.get('role') == 'viewer', rows)

    code, j, _, _ = adm.post('/api/admin/user', {'username': 'alice', 'action': 'status', 'status': 'active'})
    check('B12 管理员启用 alice -> 200', code == 200, '%s %s' % (code, j))
    code, j, _, _ = reg.post('/api/login', {'username': 'alice', 'password': 'alice123456'})
    check('B13 启用后可登录', code == 200, '%s %s' % (code, j))
    check('B14 登录后角色 viewer', code == 200 and j.get('user', {}).get('role') == 'viewer', j)
    code, j, _, _ = adm.post('/api/site', {'site': 'gate.example', 'label': 'gate'})
    check('B15 管理员加站点 -> 200', code == 200, '%s %s' % (code, j))
    code, _, _, _ = reg.get('/api/stats?site=gate.example')
    check('B16 启用后 viewer 可读统计 -> 200', code == 200, code)
finally:
    stop(proc)

# ---------------- C. 开启 + 空库 -> 首个注册者=admin（引导路径） ----------------
print('--- C. SA_ALLOW_REGISTER=1 且空库 ---')
dC = os.path.join(WORK, 'c')
os.makedirs(dC, exist_ok=True)
proc, base, errpath = boot(dC, reg_on=True)
try:
    c = Client(base)
    code, j, _, raw = c.post('/api/register', {'username': 'firstadmin', 'password': 'first123456'})
    check('C1 空库首个注册 -> 200', code == 200, '%s %s' % (code, raw[:160]))
    check('C2 不是待审（pending 缺省）', isinstance(j, dict) and not j.get('pending'), raw[:160])
    check('C3 角色=admin', isinstance(j, dict) and j.get('user', {}).get('role') == 'admin', raw[:160])
    check('C4 直接种会话 cookie', 'sid' in c.sid_names(), c.sid_names())
    code, j, _, _ = c.get('/api/me')
    check('C5 首登 /api/me -> 200 admin', code == 200 and (j.get('user') or {}).get('role') == 'admin', j)
finally:
    stop(proc)
log = open(errpath, encoding='utf-8').read()
check('C6 启动 stderr 告警“首个注册者将成为管理员”', '首个注册者将直接成为管理员' in log, log[-400:])

npass = sum(1 for _, ok in results if ok)
print('\n===== %d/%d PASS =====' % (npass, len(results)))
sys.exit(0 if npass == len(results) else 1)
