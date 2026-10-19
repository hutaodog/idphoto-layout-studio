# -*- coding: utf-8 -*-
"""让测试能直接 import app.*（项目根加入 sys.path）。"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# 测试用的示例照片：一张**合成头像**（不是真人照片），由 scripts\make_demo_face.py 画出来。
# 要求只有一条：能被 MTCNN 检出**恰好 1 张人脸**，否则整套测试会挂在"Expected 1 face"上。
# 想换成自己的照片也可以，改这个路径即可（别把真人照片放进公开仓库）。
DEMO_IMAGE = os.path.join(ROOT, "tests", "assets", "demo_face.jpg")
OUT_DIR = os.path.join(ROOT, "_tmp", "test_out")
