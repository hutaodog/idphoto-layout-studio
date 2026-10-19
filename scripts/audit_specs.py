# -*- coding: utf-8 -*-
"""规格库体检：自洽性 / 相纸标准值 / 同尺寸重复项 / 张数。

用法：& .\.venv\Scripts\python.exe scripts\audit_specs.py
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.layout import plan_for_spec                      # noqa: E402
from app.core.specs import SpecLibrary, mm_to_px               # noqa: E402

# 相纸标准值（mm）：3R/4R/5R 与 A 系。ISO 216 + 照片冲印行业惯例。
PAPER_STD = {
    "5inch": (89.0, 127.0, "3R 5寸"),
    "6inch": (102.0, 152.0, "4R 6寸"),
    "7inch": (127.0, 178.0, "5R 7寸"),
    "A4": (210.0, 297.0, "ISO A4"),
    "A3": (297.0, 420.0, "ISO A3"),
}


def main() -> int:
    lib = SpecLibrary.load()
    problems = []

    print("=" * 78)
    print("一、相纸尺寸（mm / px / 300dpi 回算）")
    print("=" * 78)
    for p in lib.papers:
        std = PAPER_STD.get(p.id)
        mm_ok = std and abs(p.mm[0] - std[0]) < 0.6 and abs(p.mm[1] - std[1]) < 0.6
        px_ok = all(abs(mm_to_px(p.mm[i], p.dpi) - p.px[i]) <= 1 for i in (0, 1))
        back = tuple(round(p.px[i] / p.dpi * 25.4, 1) for i in (0, 1))
        print("  %-8s %-10s %6.1f×%-6.1f mm  px=%-11s  @%ddpi 回算 %s×%s mm  %s%s"
              % (p.id, p.name_zh, p.mm[0], p.mm[1], "%d×%d" % p.px, p.dpi,
                 back[0], back[1],
                 "标准值一致" if mm_ok else "!! 与标准值 %s 不符" % (std,),
                 "" if px_ok else "  !! px 与 mm@dpi 不自洽"))
        if not mm_ok:
            problems.append("相纸 %s 与标准值不符" % p.id)
        if not px_ok:
            problems.append("相纸 %s 的 px 与 mm@dpi 不自洽" % p.id)

    print()
    print("=" * 78)
    print("二、照片规格自洽性（px == round(mm/25.4*dpi)，容差 0）")
    print("=" * 78)
    bad = 0
    for s in lib.photos:
        for axis in (0, 1):
            want = mm_to_px(s.mm[axis], s.dpi)
            if abs(want - s.px[axis]) > 1:
                bad += 1
                print("  !! %s(%s) 第%d轴 mm=%s dpi=%d → 应为 %d，实为 %d"
                      % (s.name_zh, s.id, axis, s.mm[axis], s.dpi, want, s.px[axis]))
    print("  %d 条规格，%d 处不自洽" % (len(lib.photos), bad))
    if bad:
        problems.append("有 %d 处 px/mm/dpi 不自洽" % bad)

    print()
    print("=" * 78)
    print("三、同尺寸重复项")
    print("=" * 78)
    print("  「中国常用」按用户要求做了去重（一个尺寸只留一条通用规格）：")
    groups = collections.defaultdict(list)
    for s in lib.photos:
        groups[(s.category, round(s.mm[0], 2), round(s.mm[1], 2))].append(s)
    hard = {k: v for k, v in groups.items()
            if len(v) > 1 and k[0] == "中国常用" and v[0].name_zh != "五寸生活照"}
    if hard:
        for (cat, w, h), items in sorted(hard.items()):
            print("  !! [%s] %g×%gmm 仍有 %d 条：" % (cat, w, h, len(items)))
            for s in items:
                print("        %-28s id=%-18s dpi=%-4d %s" % (
                    s.name_zh, s.id, s.dpi, s.confidence))
        problems.append("「中国常用」里还有同尺寸重复项")
    else:
        print("     ✓ 中国常用：没有同尺寸重复")
    print()
    print("  其它分类里「同尺寸多条」是**故意的**——它们是一条报名系统 / 一个国家一条，")
    print("  底色、文件大小、头部比例都可能不同，合并会丢信息：")
    for (cat, w, h), items in sorted(groups.items()):
        if len(items) > 1 and cat != "中国常用":
            print("     [%s] %g×%gmm ×%d：%s" % (
                cat, w, h, len(items), "、".join(s.name_zh for s in items)))

    print()
    print("=" * 78)
    print("四、每条规格在 5 种相纸上的张数（0 = 排不下）")
    print("=" * 78)
    print("  %-26s %-8s %6s %6s %6s %6s %6s" % ("规格", "mm", "5寸", "6寸", "7寸", "A4", "A3"))
    zero = []
    for s in lib.photos:
        counts = []
        for pid in ("5inch", "6inch", "7inch", "A4", "A3"):
            counts.append(plan_for_spec(lib.paper(pid), s).count)
        if counts[0] == 0 and counts[1] == 0:
            zero.append(s)
        print("  %-26s %-8s %6d %6d %6d %6d %6d" % (
            s.name_zh[:26], "%g×%g" % s.mm, counts[0], counts[1], counts[2],
            counts[3], counts[4]))
    if zero:
        print()
        print("  !! 连 6 寸都排不下的规格：%s" % [s.name_zh for s in zero])
        problems.append("有规格连 6 寸都排不下")

    print()
    print("=" * 78)
    print("五、可信度分布（C/D 级的条目需要人工再确认）")
    print("=" * 78)
    by_conf = collections.Counter(s.confidence for s in lib.photos)
    print("  " + "  ".join("%s=%d" % (k, by_conf[k]) for k in sorted(by_conf)))
    for s in lib.photos:
        if s.confidence in ("C", "D"):
            print("  %s级  %-28s %g×%gmm  %s" % (s.confidence, s.name_zh,
                                                 s.mm[0], s.mm[1], s.source[:44]))

    print()
    print("=" * 78)
    print("结论：%s" % ("发现问题 %d 类" % len(problems) if problems else "没有硬伤"))
    for p in problems:
        print("  - " + p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
