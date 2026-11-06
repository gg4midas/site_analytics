# -*- coding: utf-8 -*-
"""v1.5.1 登录/注册契约回归：200 必须返回 JSON body + 登录页确认密码字段"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request, http.cookiejar

_HERE = os.path.dirname(os.path.abspath(__file__))
_CAND = [os.path.join(_HERE, '..', 'app.py'),                  # 入库后：tests/ 的上一级即仓库根
         os.path.join(_HERE, 'site_analytics', 'app.py')]      # 老位置：工作区根
APP = os.environ.get('SA_APP_PATH') or next((p for p in _CAND if os.path.isfile(p)), _CAND[0])
PY = sys.executable

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

def main():
    port = free_port()
    datadir = tempfile.mkdtemp(prefix='sa_v151_')
    # v1.8.6：自助注册默认关闭，本测试显式开启（否则 /api/register 直接 403）
    env = dict(os.environ, SA_ALLOW_REGISTER='1')
    proc = subprocess.Popen([PY, APP, '--host', '127.0.0.1', '--port', str(port),
                             '--data-dir', datadir],
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    base = 'http://127.0.0.1:%d' % port
    results = []
    try:
        assert wait_port(port), '服务未启动'
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        op.addheaders = [('User-Agent', 'Mozilla/5.0 Repro')]

        def post_raw(path, body):
            req = urllib.request.Request(base + path, method='POST',
                                         data=json.dumps(body).encode(),
                                         headers={'Content-Type': 'application/json'})
            try:
                r = op.open(req, timeout=10)
                return r.status, r.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()

        def post(path, body):
            c, t = post_raw(path, body)
            try:
                return c, json.loads(t) if t else None
            except Exception:
                return c, '<<NOT_JSON>>'

        def get(path):
            try:
                r = op.open(base + path, timeout=10)
                return r.status, r.read().decode()
            except urllib.error.HTTPError as e:
                return e.code, e.read().decode()

        def get_json(path):
            c, t = get(path)
            try:
                return c, (json.loads(t) if t else None)
            except Exception:
                return c, '<<NOT_JSON>>'

        def check(name, ok):
            results.append((name, ok))

        USER, PWD = 'contract1', 'secret66'

        # 0. 编译检查（cfile 指向临时目录，避免 __pycache__ 落在仓库内）
        import py_compile
        try:
            with tempfile.TemporaryDirectory(prefix='sa_v151_pyc_') as _td:
                py_compile.compile(APP, cfile=os.path.join(_td, 'app.pyc'), doraise=True)
            check('py_compile', True)
        except Exception as e:
            check('py_compile: %s' % e, False)

        # 1. 登录页 HTML：确认密码字段 + 校验 + 容错解析
        c, html = get('/login')
        check('login_page_200', c == 200)
        for token, desc in [('id="p2"', '确认密码输入框'), ('id="lbl-p2"', '确认密码标签'),
                            ('两次输入的密码不一致', '一致性校验文案'),
                            ('密码至少 6 位', '长度校验文案'),
                            ('JSON.parse(', '解析容错')]:
            check('html_has[%s]' % desc, token in html)

        # 2. 注册：200 + 可解析 JSON status/user
        c, j = post('/api/register', {'username': USER, 'password': PWD})
        check('register_200', c == 200)
        check('register_json_body', isinstance(j, dict) and j.get('status') is True
              and j.get('user', {}).get('username') == USER)
        check('register_sets_cookie', any(ck.name == 'sid' for ck in cj))

        # 3. 注册后 me
        c, j = get_json('/api/me')
        check('me_after_register', c == 200 and j.get('user', {}).get('username') == USER)

        # 4. logout：200 + JSON body + 清 cookie
        c, j = post('/api/logout', {})
        check('logout_200', c == 200)
        check('logout_json_body', isinstance(j, dict) and j.get('status') is True)
        c, j = get('/api/me')
        check('me_after_logout_401', c == 401)

        # 5. 错误密码：401 + JSON error（契约回归）
        c, j = post('/api/login', {'username': USER, 'password': 'wrong99'})
        check('login_wrong_401_json', c == 401 and isinstance(j, dict) and '密码' in j.get('error', ''))

        # 6. 正确登录：200 + JSON body + 新 cookie
        c, j = post('/api/login', {'username': USER, 'password': PWD})
        check('login_200', c == 200)
        check('login_json_body', isinstance(j, dict) and j.get('status') is True
              and j.get('user', {}).get('username') == USER)
        check('login_sets_cookie', any(ck.name == 'sid' for ck in cj))
        c, j = get_json('/api/me')
        check('me_after_login', c == 200)

        # 7. 二轮 logout -> login
        post('/api/logout', {})
        c, j = post('/api/login', {'username': USER, 'password': PWD})
        check('second_cycle', c == 200 and isinstance(j, dict) and j.get('status') is True)

        # 8. 原全链路回归（改密码等）
        c, j = post('/api/user/password', {'old': PWD, 'new': 'newpass88'})
        check('change_password', c == 200)
        post('/api/logout', {})
        c, j = post('/api/login', {'username': USER, 'password': 'newpass88'})
        check('login_after_change', c == 200 and isinstance(j, dict) and j.get('status') is True)

        allpass = True
        for name, ok in results:
            print('%-34s %s' % (name, 'PASS' if ok else 'FAIL'))
            allpass = allpass and ok
        print('RESULT:', 'ALL_PASS' if allpass else 'HAS_FAIL')
        return 0 if allpass else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()

if __name__ == '__main__':
    sys.exit(main())
