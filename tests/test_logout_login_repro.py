# -*- coding: utf-8 -*-
"""v1.5.0 登出后无法登录问题复现：register -> me -> logout -> login 全链路"""
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
    datadir = tempfile.mkdtemp(prefix='sa_repro_')
    # v1.8.6：自助注册默认关闭，本测试显式开启（空库首个注册者仍=admin 并可直接登录）
    env = dict(os.environ, SA_ALLOW_REGISTER='1')
    proc = subprocess.Popen([PY, APP, '--host', '127.0.0.1', '--port', str(port),
                             '--data-dir', datadir],
                            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, env=env)
    base = 'http://127.0.0.1:%d' % port
    try:
        assert wait_port(port), '服务未启动'
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        op.addheaders = [('User-Agent', 'Mozilla/5.0 Repro')]

        def post(path, body):
            req = urllib.request.Request(base + path, method='POST',
                                         data=json.dumps(body).encode(),
                                         headers={'Content-Type': 'application/json'})
            try:
                r = op.open(req, timeout=10)
                return r.status, json.loads(r.read().decode() or '{}')
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read().decode() or '{}')

        def get(path):
            try:
                r = op.open(base + path, timeout=10)
                return r.status, json.loads(r.read().decode() or '{}')
            except urllib.error.HTTPError as e:
                return e.code, json.loads(e.read().decode() or '{}')

        results = []
        USER, PWD = 'reproadmin', 'secret66'

        # 1. 注册
        c, j = post('/api/register', {'username': USER, 'password': PWD})
        results.append(('register', c, j, c == 200))
        sids1 = [ck.value[:8] for ck in cj if ck.name == 'sid']

        # 2. me（注册后应已登录）
        c, j = get('/api/me')
        results.append(('me_after_register', c, j, c == 200 and j.get('user', {}).get('username') == USER))

        # 3. 登出
        c, j = post('/api/logout', {})
        results.append(('logout', c, j, c == 200))

        # 4. 登出后 me 应 401
        c, j = get('/api/me')
        results.append(('me_after_logout', c, j, c == 401))

        # 5. 错误密码登录 -> 401 用户名或密码错误
        c, j = post('/api/login', {'username': USER, 'password': 'wrong99'})
        results.append(('login_wrong_pwd', c, j, c == 401 and '密码' in j.get('error', '')))

        # 6. 正确密码登录 -> 200 且种下新 cookie
        c, j = post('/api/login', {'username': USER, 'password': PWD})
        sids2 = [ck.value[:8] for ck in cj if ck.name == 'sid']
        results.append(('login_correct_pwd', c, j, c == 200))

        # 7. 登录后 me 应 200
        c, j = get('/api/me')
        results.append(('me_after_login', c, j, c == 200 and j.get('user', {}).get('username') == USER))

        # 8. 再登出再登录（第二轮）
        post('/api/logout', {})
        c, j = post('/api/login', {'username': USER, 'password': PWD})
        results.append(('second_cycle_login', c, j, c == 200))
        c, j = get('/api/me')
        results.append(('second_cycle_me', c, j, c == 200))

        # 9. 修改密码后用新密码登录
        c, j = post('/api/user/password', {'old': PWD, 'new': 'newpass88'})
        results.append(('change_password', c, j, c == 200))
        post('/api/logout', {})
        c, j = post('/api/login', {'username': USER, 'password': 'newpass88'})
        results.append(('login_after_change', c, j, c == 200))

        print('cookie sid 注册后=%s 现在=%s' % (sids1, sids2))
        allpass = True
        for name, code, j, ok in results:
            print('%-22s HTTP %s  %-5s  %s' % (name, code, 'PASS' if ok else 'FAIL', j))
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
