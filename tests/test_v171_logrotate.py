# -*- coding: utf-8 -*-
"""v1.7.1 日志轮转专项验证：把轮转阈值调小，连续写日志，断言 .1 产生且新 log 从零累计。"""
import os, sys, tempfile, shutil
_HERE = os.path.dirname(os.path.abspath(__file__))
_CAND = [os.path.join(_HERE, '..', 'app.py'),                  # 入库后：tests/ 的上一级即仓库根
         os.path.join(_HERE, 'site_analytics', 'app.py')]      # 老位置：工作区根
APP = os.environ.get('SA_APP_PATH') or next((p for p in _CAND if os.path.isfile(p)), _CAND[0])
sys.path.insert(0, os.path.dirname(APP))
sys.dont_write_bytecode = True   # exec_module 加载 app.py，不落 __pycache__ 到仓库
import importlib.util
spec = importlib.util.spec_from_file_location('sa_app', APP)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

tmp = tempfile.mkdtemp(prefix='sa_rot_')
try:
    eng = m.StatEngine(data_dir=tmp, geo_db='', asn_db='')
    eng.LOG_ROTATE_SIZE = 200  # 调小阈值便于测试
    for i in range(30):
        eng._log('rotate-test line %d %s' % (i, 'x' * 20))
    rotated = os.path.exists(os.path.join(tmp, 'debug.log.1'))
    cur = os.path.getsize(os.path.join(tmp, 'debug.log'))
    print('rotated file exists:', rotated, '| current debug.log size:', cur, '(<300:', cur < 300, ')')
    print('RESULT:', 'PASS' if (rotated and cur < 300) else 'FAIL')
finally:
    shutil.rmtree(tmp, ignore_errors=True)
