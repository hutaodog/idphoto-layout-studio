# -*- coding: utf-8 -*-
"""生成一张"合成人像"：既能被 MTCNN 检出 1 张人脸，又不含任何真人的形象。

用途：替换 tests/assets 里那张真人示例照 + README 截图里的示例人脸。
画法：PIL 4 倍超采样 + 打光渐变 + 皮肤颗粒 + 轻微柔化，做成"扁平插画风格的头像"。
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tests", "assets", "demo_face.jpg")

SS = 4
W, H = 900, 1200

SKIN = (222, 180, 152)
SKIN_DARK = (196, 150, 124)
HAIR = (52, 44, 40)
LIP = (168, 104, 100)


def build() -> Image.Image:
    w, h = W * SS, H * SS
    cx = w // 2
    img = Image.new("RGB", (w, h), (208, 216, 228))
    d = ImageDraw.Draw(img, "RGBA")

    # ---- 背景：上亮下暗 + 一团柔光 ----
    for y in range(h):
        k = y / h
        d.line([(0, y), (w, y)], fill=(int(216 - 30 * k), int(222 - 26 * k),
                                      int(234 - 22 * k)))
    d.ellipse([-w * 0.30, -h * 0.45, w * 1.10, h * 0.60], fill=(228, 234, 244))

    # ---- 肩 / 西装 ----
    d.ellipse([cx - int(w * 0.52), int(h * 0.87), cx + int(w * 0.52), int(h * 1.60)],
              fill=(56, 60, 72))
    d.polygon([(cx - int(w * 0.14), int(h * 0.895)), (cx, int(h * 1.03)),
               (cx + int(w * 0.14), int(h * 0.895))], fill=(242, 244, 248))
    d.line([(cx - int(w * 0.14), int(h * 0.895)), (cx, int(h * 1.03))],
           fill=(206, 210, 218), width=max(1, int(w * 0.003)))
    d.line([(cx + int(w * 0.14), int(h * 0.895)), (cx, int(h * 1.03))],
           fill=(206, 210, 218), width=max(1, int(w * 0.003)))

    # ---- 脖子 + 脖子上的阴影 ----
    d.rounded_rectangle([cx - int(w * 0.080), int(h * 0.52),
                         cx + int(w * 0.080), int(h * 0.92)],
                        radius=int(w * 0.045), fill=SKIN_DARK)
    d.ellipse([cx - int(w * 0.095), int(h * 0.50), cx + int(w * 0.095), int(h * 0.64)],
              fill=(178, 134, 110))

    hx = cx
    hy = int(h * 0.405)
    hw, hh = int(w * 0.158), int(h * 0.163)
    # ---- 头发（先画一个大椭圆，再用脸盖住下半部分 → 自然发际线）----
    d.ellipse([hx - hw - int(w * 0.014), hy - hh - int(hh * 0.26),
               hx + hw + int(w * 0.014), hy + hh + int(hh * 0.10)], fill=HAIR)
    # ---- 耳朵 ----
    for sx in (-1, 1):
        d.ellipse([hx + sx * hw - int(w * 0.020), hy - int(hh * 0.24),
                   hx + sx * hw + int(w * 0.020), hy + int(hh * 0.20)], fill=SKIN_DARK)
    # ---- 脸 ----
    d.ellipse([hx - hw, hy - hh, hx + hw, hy + hh], fill=SKIN)
    # ---- 鬓角（只在两侧，别压到眼睛）----
    for sx in (-1, 1):
        d.ellipse([hx + sx * int(hw * 1.00) - int(hw * 0.13), hy - int(hh * 0.62),
                   hx + sx * int(hw * 1.00) + int(hw * 0.13), hy - int(hh * 0.02)],
                  fill=HAIR)

    # ---- 打光：左上偏亮 ----
    light = Image.new("L", (w, h), 0)
    ld = ImageDraw.Draw(light)
    ld.ellipse([hx - hw, hy - hh, hx + hw, hy + hh], fill=80)
    light = light.filter(ImageFilter.GaussianBlur(int(w * 0.055)))
    img = Image.composite(Image.blend(img, Image.new("RGB", (w, h), (255, 238, 224)),
                                      0.30), img, light)
    d = ImageDraw.Draw(img, "RGBA")

    # ---- 眉毛（在发际线以下、眼睛以上）----
    for sx in (-1, 1):
        bx = hx + sx * int(hw * 0.40)
        by = hy - int(hh * 0.42)
        d.arc([bx - int(hw * 0.26), by - int(hh * 0.06),
               bx + int(hw * 0.26), by + int(hh * 0.16)],
              start=200 if sx > 0 else 340, end=340 if sx > 0 else 200,
              fill=(58, 48, 44), width=max(3, int(w * 0.007)))

    # ---- 眼睛 ----
    for sx in (-1, 1):
        ex = hx + sx * int(hw * 0.40)
        ey = hy - int(hh * 0.18)
        ew, eh = int(hw * 0.205), int(hh * 0.062)
        d.ellipse([ex - ew, ey - eh, ex + ew, ey + eh], fill=(252, 251, 249))
        ir = int(eh * 0.86)
        d.ellipse([ex - ir, ey - ir, ex + ir, ey + ir], fill=(86, 104, 120))
        pr = int(ir * 0.50)
        d.ellipse([ex - pr, ey - pr, ex + pr, ey + pr], fill=(26, 24, 26))
        d.ellipse([ex - int(ir * 0.55), ey - int(ir * 0.62),
                   ex - int(ir * 0.05), ey - int(ir * 0.10)], fill=(255, 255, 255))
        # 上眼睑
        d.arc([ex - ew, ey - int(eh * 1.6), ex + ew, ey + eh],
              start=190, end=350, fill=(132, 104, 90), width=max(2, int(w * 0.0035)))

    # ---- 鼻子：鼻梁一条淡高光 + 鼻尖一点阴影 + 两个鼻孔 ----
    d.ellipse([hx - int(hw * 0.055), hy - int(hh * 0.10),
               hx + int(hw * 0.055), hy + int(hh * 0.16)], fill=(210, 166, 140))
    d.arc([hx - int(hw * 0.15), hy + int(hh * 0.06),
           hx + int(hw * 0.15), hy + int(hh * 0.22)], start=20, end=160,
          fill=(176, 136, 116), width=max(2, int(w * 0.004)))
    for sx in (-1, 1):
        d.ellipse([hx + sx * int(hw * 0.075) - int(hw * 0.022), hy + int(hh * 0.165),
                   hx + sx * int(hw * 0.075) + int(hw * 0.022), hy + int(hh * 0.195)],
                  fill=(150, 112, 96))

    # ---- 嘴（上唇一条弧 + 下唇小半圆）----
    my = hy + int(hh * 0.50)
    mw = int(hw * 0.26)
    d.ellipse([hx - mw, my - int(hh * 0.02), hx + mw, my + int(hh * 0.075)], fill=LIP)
    d.arc([hx - mw, my - int(hh * 0.05), hx + mw, my + int(hh * 0.04)],
          start=10, end=170, fill=(138, 78, 76), width=max(2, int(w * 0.004)))

    # ---- 下巴阴影 ----
    d.arc([hx - int(hw * 0.30), my + int(hh * 0.12),
           hx + int(hw * 0.30), my + int(hh * 0.40)], start=25, end=155,
          fill=(198, 158, 136), width=max(2, int(w * 0.0035)))

    # ---- 柔化 + 颗粒 ----
    img = img.filter(ImageFilter.GaussianBlur(w / 2600.0))
    arr = np.asarray(img).astype(np.int16)
    rnd = np.random.default_rng(7)
    arr = np.clip(arr + rnd.normal(0, 3.0, arr.shape).astype(np.int16), 0, 255)
    return Image.fromarray(arr.astype(np.uint8)).resize((W, H), Image.LANCZOS)


def main() -> int:
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    im = build()
    im.save(OUT, quality=92)
    print("saved", OUT, os.path.getsize(OUT), "bytes", im.size)

    sys.path.insert(0, ROOT)
    from app.core.pipeline import Processor, load_photo
    from app.core.specs import SpecLibrary

    lib = SpecLibrary.load()
    res = Processor(lib=lib).process(load_photo(OUT), lib.photo("cn_yicun"), bg="blue")
    print("管线 OK：尺寸", res.size, "人脸框", getattr(res, "face_rect", None))
    out = os.path.join(ROOT, "_tmp", "crops", "demo_face_result.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    import cv2
    ok, buf = cv2.imencode(".png", res.standard_bgr)
    buf.tofile(out)
    print("结果图:", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
