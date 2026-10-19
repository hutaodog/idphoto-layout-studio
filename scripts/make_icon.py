# -*- coding: utf-8 -*-
"""生成程序图标与启动画面。

用法：python scripts/make_icon.py
输出：app/resources/icon.ico、app/resources/icon.png、app/resources/splash.png

图标优先用 **app/resources/icon_source.png**（项目作者提供的图标源图，
已缩到 1024² 放进仓库）；找不到源图才退回下面那段"程序化画一个"的老逻辑。
这样一个源图就同时决定了：窗口左上角图标、任务栏图标、exe 图标、安装包图标。
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "app", "resources")
os.makedirs(OUT, exist_ok=True)

SOURCE = os.path.join(OUT, "icon_source.png")
SQUARE = 1024                        # 源图统一缩到这个边长（256 的 ico 够用了）

BLUE = (98, 139, 206)
DARK = (43, 47, 54)
WHITE = (255, 255, 255)


def _content_bbox(im: Image.Image):
    """内容的包围盒：透明像素和接近纯白的像素都算留白。

    用户给的源图四周有 ~9% 空白，不裁掉的话 16×16 / 32×32 的图标里主体只剩一小块，
    任务栏和标题栏上糊成一团。裁到内容边缘再留 2% 呼吸位，图标会大一圈也更清楚。
    """
    from PIL import ImageChops

    rgb = im.convert("RGB")
    white = Image.new("RGB", im.size, (255, 255, 255))
    # 和纯白的差异 > 8 才算"有内容"
    diff = ImageChops.difference(rgb, white).convert("L").point(lambda v: 255 if v > 8 else 0)
    alpha = im.split()[3].point(lambda v: 255 if v > 8 else 0)
    return ImageChops.multiply(diff, alpha).getbbox()


def from_source(size: int) -> Image.Image:
    """把用户给的图标源图做成 size×size 的 RGBA（裁掉四周留白 + 居中放到正方画布）。"""
    im = Image.open(SOURCE).convert("RGBA")
    box = _content_bbox(im)
    if box:
        pad = int(max(im.size) * 0.02)
        box = (max(0, box[0] - pad), max(0, box[1] - pad),
               min(im.width, box[2] + pad), min(im.height, box[3] + pad))
        # 只有留白真的明显（>3%）才裁，免得把本来就贴边的图裁坏
        if (box[2] - box[0]) < im.width * 0.97 or (box[3] - box[1]) < im.height * 0.97:
            im = im.crop(box)
    side = max(im.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(im, ((side - im.width) // 2, (side - im.height) // 2), im)
    if side != size:
        canvas = canvas.resize((size, size), Image.LANCZOS)
    return canvas


def rounded(size: int) -> Image.Image:
    """程序化兜底图标（没有源图时用）。"""
    s = size * 4                                  # 4 倍超采样后缩小，边缘更干净
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(s * 0.22)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=BLUE)
    # 白色证件照相框
    m = int(s * 0.16)
    d.rounded_rectangle([m, m, s - m, s - m], radius=int(s * 0.06), fill=WHITE)
    # 人像剪影：头 + 肩
    cx = s // 2
    head_r = int(s * 0.115)
    head_cy = int(s * 0.40)
    d.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r], fill=BLUE)
    sh_top = head_cy + int(head_r * 1.25)
    d.rounded_rectangle([cx - int(s * 0.185), sh_top, cx + int(s * 0.185), s - m - int(s * 0.04)],
                        radius=int(s * 0.10), fill=BLUE)
    return img.resize((size, size), Image.LANCZOS)


def base_icon(size: int = 256) -> Image.Image:
    if os.path.exists(SOURCE):
        return from_source(size)
    return rounded(size)


def main() -> None:
    sizes = [16, 20, 24, 32, 40, 48, 64, 128, 256]
    base = base_icon(256)
    ico = os.path.join(OUT, "icon.ico")
    # 每个尺寸单独渲染一遍，缩小时再走一次 LANCZOS（一次性从 2048 缩到 16 会糊）
    frames = [base_icon(s) for s in sizes]
    frames[-1].save(ico, format="ICO",
                    sizes=[(s, s) for s in sizes],
                    append_images=frames[:-1])
    print("源图  :", SOURCE if os.path.exists(SOURCE) else "（没有，用程序化兜底图）")
    print("icon ->", ico, os.path.getsize(ico), "bytes")

    png = os.path.join(OUT, "icon.png")
    base_icon(256).save(png)
    print("png  ->", png)

    # 启动画面（onefile 版解压时要十几秒，必须给用户一个反馈）
    w, h = 520, 280
    sp = Image.new("RGB", (w, h), DARK)
    d = ImageDraw.Draw(sp)
    d.rounded_rectangle([24, 24, w - 24, h - 24], radius=14, fill=(38, 42, 50))
    logo = base_icon(110)
    sp.paste(logo, (44, (h - 110) // 2), logo)

    def font(size: int):
        for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "simsun.ttc"):
            p = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts", name)
            if os.path.exists(p):
                try:
                    return ImageFont.truetype(p, size)
                except OSError:
                    continue
        return ImageFont.load_default()

    d.text((178, 92), "证件照排版助手", font=font(30), fill=(240, 243, 248))
    d.text((180, 138), "正在启动，首次运行需要解压约 10 秒…", font=font(16), fill=(150, 160, 175))
    d.text((180, 166), "一寸 · 二寸 · 护照签证 · 5/6/7寸相纸排版", font=font(14), fill=(110, 120, 135))
    splash = os.path.join(OUT, "splash.png")
    sp.save(splash)
    print("splash ->", splash)


if __name__ == "__main__":
    main()
