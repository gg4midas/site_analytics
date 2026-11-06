# -*- coding: utf-8 -*-
"""壳冒烟回归：?v=VERSION 注入、静态资源可访问、缓存头与 304 协商"""
import json, os, re, socket, subprocess, sys, tempfile, time, urllib.request, http.cookiejar

_HERE = os.path.dirname(os.path.abspath(__file__))
_CAND = [os.path.join(_HERE, '..', 'app.py'),                  # 入库后：tests/ 的上一级即仓库根
         os.path.join(_HERE, 'site_analytics', 'app.py')]      # 老位置：工作区根
APP = os.environ.get('SA_APP_PATH') or next((p for p in _CAND if os.path.isfile(p)), _CAND[0])
PY = sys.executable
# 版本从 app.py 动态读取，避免每次 bump 版本号都要同步改测试断言
with open(APP, encoding='utf-8') as _f:
    _m = re.search(r'^VERSION\s*=\s*"([^"]+)"', _f.read(), re.M)
assert _m, '读不到 app.py 的 VERSION'
VER = _m.group(1)

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
    datadir = tempfile.mkdtemp(prefix='sa_v160_')
    # v1.8.6：自助注册默认关闭；本冒烟用「空库首个注册=admin」做引导登录，故显式开启
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
        op.addheaders = [('User-Agent', 'Mozilla/5.0 V160Smoke')]

        def req(path, method='GET', body=None, headers=None):
            h = dict(headers or {})
            data = json.dumps(body).encode() if body is not None else None
            if data is not None:
                h['Content-Type'] = 'application/json'
            r = urllib.request.Request(base + path, data=data, headers=h, method=method)
            try:
                resp = op.open(r, timeout=10)
                return resp.status, dict(resp.headers), resp.read()
            except urllib.error.HTTPError as e:
                return e.code, dict(e.headers), e.read()

        def check(name, ok, detail=''):
            results.append((name, ok, detail))

        # 登录
        c, h, _ = req('/api/register', 'POST', {'username': 'v160smoke', 'password': 'secret66'})
        check('register', c == 200)

        # 1. 壳：?v=<VERSION> 注入
        c, h, body = req('/')
        html = body.decode('utf-8')
        check('index_200', c == 200)
        for ref in ['static/style.css?v=%s' % VER, 'static/i18n.js?v=%s' % VER,
                    'static/app.js?v=%s' % VER, 'static/echarts.min.js?v=%s' % VER]:
            check('ref[%s]' % ref.split('/')[-1], ref in html)
        check('no_inline_style', '<style>' not in html)
        check('no_inline_script', '<script>' not in html)
        check('has_userArea', 'userArea' in html)
        etag = h.get('ETag', '')
        check('etag_has_version', etag.startswith('"%s-' % VER), etag)
        check('index_no_store', 'max-age=0' in h.get('Cache-Control', ''), h.get('Cache-Control', ''))

        # 2. 静态资源
        for p, ctype in [('/static/style.css', 'text/css'),
                         ('/static/i18n.js', 'application/javascript'),
                         ('/static/app.js', 'application/javascript'),
                         ('/static/echarts.min.js', 'application/javascript')]:
            c, h, b = req(p)
            check('static[%s]' % p.split('/')[-1], c == 200 and ctype in h.get('Content-Type', ''),
                  '%s %s %dB' % (c, h.get('Content-Type', ''), len(b)))
            check('cache86400[%s]' % p.split('/')[-1], 'max-age=86400' in h.get('Cache-Control', ''),
                  h.get('Cache-Control', ''))

        # 3. 304 协商
        c, h, b = req('/static/app.js')
        et = h.get('ETag', '')
        c2, h2, b2 = req('/static/app.js', headers={'If-None-Match': et})
        check('etag_304', c2 == 304 and len(b2) == 0, '%s etag=%s' % (c2, et))
        # 4. 壳 304（版本化 ETag 协商）
        c3, h3, _ = req('/', headers={'If-None-Match': h.get('ETag', '')}) if False else (0, {}, b'')
        ci, hi, bi = req('/')
        et_idx = hi.get('ETag', '')
        ci2, hi2, bi2 = req('/', headers={'If-None-Match': et_idx})
        check('index_304', ci2 == 304, '%s' % ci2)

        allpass = True
        for name, ok, detail in results:
            print('%-36s %-5s %s' % (name, 'PASS' if ok else 'FAIL', detail))
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
