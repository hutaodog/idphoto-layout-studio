# -*- coding: utf-8 -*-
"""把上游 HivisionIDPhotos 内核做成可内嵌的 vendor 副本，并打上必需的最小补丁。

用法：  python app/vendor/build_vendor.py

为什么要 vendor 而不是 pip 依赖：上游已停更（master 末次提交只改了 README，106 个 issue
无人处理），我们必须自己维护这几处补丁。每一处补丁都做字面量断言，上游改动导致补丁失配时
会立刻报错，绝不静默跳过。

补丁清单：
  PATCH-1  plugin/beauty/whitening.py   gradio 只在 __main__ 演示块里用，改成可选导入
  PATCH-2  plugin/beauty/__init__.py    改惰性导入，避免 import 时拉起 grind_skin
           （grind_skin.py 在【模块级】构建 Gradio 界面，是 import hivision 失败的真凶）
  PATCH-3  新增 hivision/_io_compat.py  + 替换包内 2 处 cv2.imread
           （cv2.imread 在中文路径下静默返回 None，实测确认）
  PATCH-4  creator/human_matting.py     hollow_out_fix 可用环境变量 IDPHOTO_HOLLOW_FIX=0 关闭
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)
ROOT = os.path.dirname(APP_DIR)

DEFAULT_UPSTREAM = os.path.join(ROOT, "_research", "hivision")
DEFAULT_DEST = os.path.join(HERE, "hivision")

MODEL_NAME = "hivision_modnet.onnx"
MODEL_SHA256 = "7E0CB9A2A841B426DD0DAF1A788EC398DAB059BC039041D62B15636C0783BC56"
MODEL_BYTES = 25888609

IO_COMPAT = '''# -*- coding: utf-8 -*-
"""PATCH-3: cv2.imread / cv2.imwrite 在 Windows 上无法处理中文路径
（实测：同一文件放 ASCII 路径能读，放中文路径返回 None）。np.fromfile + cv2.imdecode 可以。
本模块供内核内部读取 LUT / 模板等资源文件使用。
"""
import os

import cv2
import numpy as np


def imread(path, flags=cv2.IMREAD_COLOR):
    """路径安全的 cv2.imread：读不到时返回 None，行为与原函数一致。"""
    try:
        buf = np.fromfile(path, dtype=np.uint8)
    except OSError:
        return None
    if buf.size == 0:
        return None
    return cv2.imdecode(buf, flags)


def imwrite(path, img, params=None):
    """路径安全的 cv2.imwrite，返回是否写成功。"""
    ext = os.path.splitext(path)[1] or ".png"
    ok, buf = cv2.imencode(ext, img, params or [])
    if not ok:
        return False
    buf.tofile(path)
    return True
'''

HOLLOW_HELPER = '''
def _maybe_hollow_out_fix(src):
    """PATCH-4: 允许用环境变量关闭抠图内部空洞修补（默认保持上游行为）。"""
    if os.getenv("IDPHOTO_HOLLOW_FIX", "1") == "0":
        return src
    return hollow_out_fix(src)

'''

PATCHES = [
    # ---- PATCH-1 ----
    ("plugin/beauty/whitening.py", 1,
     "import gradio as gr\n",
     "try:\n"
     "    import gradio as gr\n"
     "except ImportError:  # PATCH-1: gradio is only used by the __main__ demo block\n"
     "    gr = None\n"),
    # ---- PATCH-2 ----
    ("plugin/beauty/__init__.py", 1,
     "from .beauty_tools import BeautyTools\n",
     "def __getattr__(name):  # PATCH-2: lazy import, beauty_tools pulls in grind_skin\n"
     "    if name == \"BeautyTools\":\n"
     "        from .beauty_tools import BeautyTools\n"
     "        return BeautyTools\n"
     "    raise AttributeError(name)\n"),
    # ---- PATCH-3：中文路径安全读写 ----
    ("plugin/beauty/whitening.py", 1,
     "default_lut = cv2.imread(os.path.join(base_dir, \"lut/lut_origin.png\"))",
     "default_lut = imread(os.path.join(base_dir, \"lut/lut_origin.png\"))"),
    ("plugin/beauty/whitening.py", 1,
     "import numpy as np\n",
     "import numpy as np\n\nfrom hivision._io_compat import imread  # PATCH-3\n"),
    ("plugin/template/template_calculator.py", 1,
     "template_image = cv2.imread(template_image_path, cv2.IMREAD_UNCHANGED)",
     "template_image = imread(template_image_path, cv2.IMREAD_UNCHANGED)"),
    ("plugin/template/template_calculator.py", 1,
     "import cv2\n",
     "import cv2\n\nfrom hivision._io_compat import imread  # PATCH-3\n"),
    # ---- PATCH-4：hollow_out_fix 可关 ----
    ("creator/human_matting.py", 2,
     "ctx.processing_image = hollow_out_fix(matting_image)",
     "ctx.processing_image = _maybe_hollow_out_fix(matting_image)"),
    ("creator/human_matting.py", 1,
     "def hollow_out_fix(src: np.ndarray) -> np.ndarray:",
     HOLLOW_HELPER.lstrip("\n") + "def hollow_out_fix(src: np.ndarray) -> np.ndarray:"),
]


def _apply(dest: str, rel: str, occurrences: int, old: str, new: str) -> None:
    path = os.path.join(dest, rel)
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    n = text.count(old)
    assert n == occurrences, (
        "补丁失配：%s 里期望 %d 处 %r，实际 %d 处。上游可能已改动，请人工核对。"
        % (rel, occurrences, old[:60], n)
    )
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))


def build(upstream: str, dest: str) -> None:
    pkg = os.path.join(upstream, "hivision")
    if not os.path.isdir(pkg):
        sys.exit("找不到上游包：%s" % pkg)

    if os.path.isdir(dest):
        shutil.rmtree(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    shutil.copytree(pkg, dest)
    print("vendor -> %s" % dest)

    with open(os.path.join(dest, "_io_compat.py"), "w", encoding="utf-8") as f:
        f.write(IO_COMPAT)
    print("  新增 hivision/_io_compat.py")

    for rel, occ, old, new in PATCHES:
        _apply(dest, rel, occ, old, new)
        print("  打补丁 %s" % rel)

    # 权重
    wdir = os.path.join(dest, "creator", "weights")
    os.makedirs(wdir, exist_ok=True)
    model_dst = os.path.join(wdir, MODEL_NAME)
    if not os.path.exists(model_dst):
        candidates = [
            os.path.join(upstream, "hivision", "creator", "weights", MODEL_NAME),
            os.path.join(APP_DIR, "models", MODEL_NAME),
            os.path.join(ROOT, "_probe", "vendor", "hivision", "creator", "weights", MODEL_NAME),
        ]
        for c in candidates:
            if os.path.exists(c):
                shutil.copyfile(c, model_dst)
                print("  权重 <- %s" % c)
                break
    if not os.path.exists(model_dst):
        print("  !! 权重缺失：请先运行 scripts\\download_weights.ps1")
    else:
        size = os.path.getsize(model_dst)
        print("  权重 %s (%d 字节)" % (MODEL_NAME, size))
        if size != MODEL_BYTES:
            print("  !! 权重字节数与记录不符：期望 %d 实际 %d" % (MODEL_BYTES, size))

    # 许可证与来源声明
    for name in ("LICENSE", "NOTICE"):
        src = os.path.join(upstream, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(HERE, name))
            print("  复制 %s" % name)

    # 验证：不装 gradio 也要能 import
    sys.path.insert(0, os.path.dirname(dest))
    try:
        import gradio  # noqa: F401
        print("  注意：本解释器里装了 gradio，补丁验证不充分")
    except ImportError:
        print("  本解释器未装 gradio —— 正好用来验证补丁有效")
    from hivision import IDCreator  # noqa: F401
    from hivision.creator.layout_calculator import generate_layout_array  # noqa: F401
    import hivision.plugin.beauty.handler  # noqa: F401
    assert "hivision.plugin.beauty.grind_skin" not in sys.modules, \
        "PATCH-2 失效：grind_skin 仍被提前导入"
    print("  验证通过：无 gradio 也能 import hivision，且未拉起 grind_skin")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--upstream", default=DEFAULT_UPSTREAM,
                    help="上游 HivisionIDPhotos 源码目录（默认 %(default)s）")
    ap.add_argument("--dest", default=DEFAULT_DEST)
    args = ap.parse_args()
    if not os.path.isdir(args.upstream):
        ap.error(
            "上游源码目录不存在：%s\n"
            "  先 clone 一份，再用 --upstream 指过来（默认值指向的 _research\\hivision 是调研期的\n"
            "  过程产物，已经清理掉了；日常构建不需要上游，app/vendor/hivision 已是打好的副本）：\n"
            "    git clone --depth 1 https://github.com/Zeyi-Lin/HivisionIDPhotos.git .tmp\\upstream\n"
            "    python app\\vendor\\build_vendor.py --upstream .tmp\\upstream" % args.upstream)
    build(args.upstream, args.dest)


if __name__ == "__main__":
    main()
