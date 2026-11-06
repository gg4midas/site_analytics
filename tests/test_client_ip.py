# -*- coding: utf-8 -*-
"""client_ip() 可信代理回归（v1.8.4）

背景：旧实现无条件信任 X-Forwarded-For 且取 split(',')[0]（最左 = 客户端自己塞的那一段），
配合 nginx 的 $proxy_add_x_forwarded_for（追加）→ 客户端可任意伪造访客 IP，
导致 ①地域/ISP 统计被污染 ②机房自动屏蔽判定被操纵 ③登录爆破限流被完全绕过。

本测试覆盖两部分：
  A. 纯逻辑矩阵：可信代理门控 + 取 XFF 最右一跳 + X-Real-IP 回退 + CIDR + 环境变量解析
  B. 端到端：模拟 nginx 追加 XFF 后，登录限流必须仍然生效（漏洞已闭合）
"""
import importlib.util, json, os, socket, subprocess, sys, tempfile, time, urllib.request, urllib.error

_HERE = os.path.dirname(os.path.abspath(__file__))
_CAND = [os.path.join(_HERE, '..', 'app.py'),                  # 入库后：tests/ 的上一级即仓库根
         os.path.join(_HERE, 'site_analytics', 'app.py')]      # 老位置：工作区根
APP = os.environ.get('SA_APP_PATH') or next((p for p in _CAND if os.path.isfile(p)), _CAND[0])
PY = sys.executable
sys.dont_write_bytecode = True   # importlib 加载 app.py 时不在仓库内生成 __pycache__

def load_app():
    spec = importlib.util.spec_from_file_location('sa_client_ip', APP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

class FakeReq(object):
    """最小化的请求对象：client_ip() 只用到 client_address / headers / _warn_untrusted_proxy"""
    def __init__(self, peer, headers=None):
        self.client_address = (peer, 54321)
        self.headers = headers or {}
    def _warn_untrusted_proxy(self, peer):
        pass

def free_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p

def wait_port(port, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection(('127.0.0.1', port), 0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False

results = []
def check(name, ok, extra=''):
    results.append((name, bool(ok)))
    print('%-42s %s  %s' % (name, 'PASS' if ok else 'FAIL', extra))

# ---------------------------------------------------------------- A. 逻辑矩阵
mod = load_app()
H = mod.Handler
# 向后兼容：对着**未修复**的旧版 app.py 跑本测试时不应崩溃，而应逐条判 FAIL
LOOPBACK = getattr(mod, '_LOOPBACK_IPS', ('127.0.0.1', '::1'))
TP_ENV = getattr(mod, 'TRUSTED_PROXY_ENV', 'SA_TRUSTED_PROXIES')
HAS_GATE = hasattr(mod, '_load_trusted_proxies')

def set_trusted(exact, nets=(), configured=True):
    H.trusted_proxies = (set(exact), list(nets), configured)

def resolve(peer, xff=None, xri=None):
    headers = {}
    if xff is not None:
        headers['X-Forwarded-For'] = xff
    if xri is not None:
        headers['X-Real-IP'] = xri
    return H.client_ip(FakeReq(peer, headers))

print('=== A. client_ip() 逻辑矩阵 ===')
set_trusted(LOOPBACK)
check('A1 代理追加XFF -> 取最右(真实IP)',
      resolve('127.0.0.1', '8.8.8.8, 203.0.113.5') == '203.0.113.5',
      resolve('127.0.0.1', '8.8.8.8, 203.0.113.5'))
check('A2 代理覆盖XFF(单段) -> 用该值',
      resolve('127.0.0.1', '203.0.113.5') == '203.0.113.5')
check('A3 对端不可信 -> 忽略XFF',
      resolve('203.0.113.9', '8.8.8.8') == '203.0.113.9',
      resolve('203.0.113.9', '8.8.8.8'))
check('A4 对端不可信 -> 忽略X-Real-IP',
      resolve('203.0.113.9', None, '1.2.3.4') == '203.0.113.9')
check('A5 无XFF -> X-Real-IP 回退',
      resolve('127.0.0.1', None, '1.2.3.4') == '1.2.3.4')
check('A6 XFF含空段 -> 跳过空段取最右',
      resolve('127.0.0.1', '8.8.8.8, , 203.0.113.5') == '203.0.113.5')
check('A7 XFF全空白 -> 回退对端',
      resolve('127.0.0.1', '   ') == '127.0.0.1')
set_trusted([], (), True)
check('A8 显式不信任任何代理 -> 完全用对端',
      resolve('127.0.0.1', '8.8.8.8, 1.1.1.1') == '127.0.0.1')
import ipaddress
set_trusted([], [ipaddress.ip_network('10.0.0.0/8')], True)
check('A9 CIDR 可信代理生效',
      resolve('10.1.2.3', '8.8.8.8, 203.0.113.5') == '203.0.113.5')
check('A10 CIDR 外对端仍不可信',
      resolve('11.1.2.3', '8.8.8.8') == '11.1.2.3')

print()
print('=== A2. %s 环境变量解析 ===' % TP_ENV)
old = os.environ.pop(TP_ENV, None)
try:
    if not HAS_GATE:
        check('A11 存在 _load_trusted_proxies()（可信代理门控）', False, '当前 app.py 没有该门控函数')
        check('A12 设为空 -> 不信任任何代理', False, '无门控，无法实现')
        check('A13 CIDR+精确IP 混合解析', False, '无门控，无法实现')
    else:
        e, n, c = mod._load_trusted_proxies()
        check('A11 未设置 -> 默认 loopback 且未显式配置',
              e == set(LOOPBACK) and n == [] and c is False, '%s %s %s' % (sorted(e), n, c))
        os.environ[TP_ENV] = ''
        e, n, c = mod._load_trusted_proxies()
        check('A12 设为空 -> 不信任任何代理',
              e == set() and n == [] and c is True, '%s %s %s' % (sorted(e), n, c))
        os.environ[TP_ENV] = '10.0.0.0/8, 192.168.1.1'
        e, n, c = mod._load_trusted_proxies()
        check('A13 CIDR+精确IP 混合解析',
              e == {'192.168.1.1'} and len(n) == 1 and str(n[0]) == '10.0.0.0/8',
              '%s %s' % (sorted(e), [str(x) for x in n]))
finally:
    os.environ.pop(TP_ENV, None)
    if old is not None:
        os.environ[TP_ENV] = old

# ---------------------------------------------------------------- B. 端到端
def login_burst(port, xff_fmt, n=15):
    """连续 n 次失败登录，返回状态码列表"""
    base = 'http://127.0.0.1:%d' % port
    out = []
    for i in range(n):
        headers = {'Content-Type': 'application/json'}
        if xff_fmt:
            headers['X-Forwarded-For'] = xff_fmt(i)
        req = urllib.request.Request(base + '/api/login', method='POST',
                                     data=json.dumps({'username': 'demo', 'password': 'wrongpass'}).encode(),
                                     headers=headers)
        try:
            r = urllib.request.urlopen(req, timeout=10)
            out.append(r.status)
        except urllib.error.HTTPError as e:
            out.append(e.code)
        except Exception as e:
            out.append(0)
    return out

def spawn(port, datadir, env_extra=None):
    env = dict(os.environ)
    env.pop(TP_ENV, None)
    if env_extra:
        env.update(env_extra)
    return subprocess.Popen([PY, APP, '--host', '127.0.0.1', '--port', str(port),
                             '--data-dir', datadir],
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)

print()
print('=== B. 端到端：登录爆破限流必须仍然生效 ===')

# B1 模拟 nginx $proxy_add_x_forwarded_for：客户端伪造值在前，真实对端 IP 在后
port = free_port(); datadir = tempfile.mkdtemp(prefix='sa_cip_b1_')
proc = spawn(port, datadir)
try:
    assert wait_port(port), '服务未启动'
    codes = login_burst(port, lambda i: '198.51.100.%d, 203.0.113.5' % (i + 1))
    got429 = [c for c in codes if c == 429]
    check('B1 伪造XFF前缀+代理追加 -> 限流仍触发',
          len(got429) >= 1 and codes[:10] == [401] * 10,
          'codes=' + ','.join(str(c) for c in codes))
    check('B1b 伪造XFF前缀不再能绕过限流',
          codes[10] == 429, '第11次=' + str(codes[10]))
finally:
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()

# B2 显式不信任任何代理（应用直接对外暴露场景）：转发头必须被忽略
port = free_port(); datadir = tempfile.mkdtemp(prefix='sa_cip_b2_')
proc = spawn(port, datadir, env_extra={TP_ENV: ''})
try:
    assert wait_port(port), '服务未启动'
    codes = login_burst(port, lambda i: '198.51.100.%d' % (i + 1))
    check('B2 不信任任何代理 -> 转发头被忽略、限流按对端IP计',
          codes[10] == 429, '第11次=' + str(codes[10]) if len(codes) > 10 else str(codes))
finally:
    proc.terminate()
    try: proc.wait(timeout=5)
    except Exception: proc.kill()

print()
allpass = True
for name, ok in results:
    allpass = allpass and ok
print('checks=%d failures=%d' % (len(results), sum(1 for _, ok in results if not ok)))
print('RESULT:', 'ALL_PASS' if allpass else 'HAS_FAIL')
sys.exit(0 if allpass else 1)
