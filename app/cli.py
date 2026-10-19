# -*- coding: utf-8 -*-
"""命令行入口：一条命令产出可打印的证件照与排版照。

示例：
    python app/cli.py --input 照片.jpg --spec cn_yicun --bg blue --paper 6inch --out 输出目录
    python app/cli.py --list-specs
    python app/cli.py --list-papers
    python app/cli.py --plan --spec cn_yicun --paper 7inch
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.core.exporter import printed_mm, save_image          # noqa: E402
from app.core.layout import (DEFAULT_GAP_MM, DEFAULT_MARGIN_MM,  # noqa: E402
                             plan_layout, render_layout, smallest_paper_for)
from app.core.pipeline import (ManualTransform, PipelineError,  # noqa: E402
                               Processor, load_photo)
from app.core.specs import SpecLibrary                          # noqa: E402


def safe_stem(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    return re.sub(r'[\\/:*?"<>|]', "_", stem) or "photo"


def cmd_list_specs(lib: SpecLibrary, args) -> int:
    for cat in lib.categories():
        print("\n【%s】" % cat)
        for s in lib.by_category(cat):
            flag = "" if s.confidence in ("A", "B") else "  [%s 级]" % s.confidence
            print("  %-24s %s%s" % (s.id, s.display(), flag))
            if args.verbose and s.note:
                print("      %s" % s.note)
    print("\n共 %d 条规格。" % len(lib.photos))
    return 0


def cmd_list_papers(lib: SpecLibrary, args) -> int:
    for p in lib.papers:
        print("  %-8s %-12s %.0f×%.0fmm  %d×%dpx@%ddpi"
              % (p.id, p.name_zh, p.mm[0], p.mm[1], p.px[0], p.px[1], p.dpi))
    print("\n可用底色：", "、".join("%s(%s)" % (c.name_zh, c.hex_code) for c in lib.colors))
    return 0


def cmd_plan(lib: SpecLibrary, args) -> int:
    spec = lib.photo(args.spec)
    papers = [lib.paper(args.paper)] if args.paper else lib.papers
    for paper in papers:
        plan = plan_layout(paper.px_at(300), spec.px_size, dpi=300,
                           gap_mm=args.gap, margin_mm=args.margin, paper_id=paper.id)
        print("  %-14s %s" % (paper.name_zh, plan.summary()))
    if args.count:
        best = smallest_paper_for(args.count, spec.px_size, lib.papers,
                                  gap_mm=args.gap, margin_mm=args.margin)
        if best:
            print("\n  要排 %d 张，最小可用相纸：%s（可排 %d 张）"
                  % (args.count, best.paper_id, best.count))
        else:
            print("\n  没有任何相纸能一次排下 %d 张" % args.count)
    return 0


def cmd_run(lib: SpecLibrary, args) -> int:
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)

    spec = lib.photo(args.spec)
    if args.dpi:
        spec = type(spec)(**{**spec.__dict__, "dpi": args.dpi,
                             "px": spec.px_at(args.dpi)})
    paper = lib.paper(args.paper)

    t0 = time.time()
    img = load_photo(args.input)
    print("读入：%s  %dx%d" % (args.input, img.shape[1], img.shape[0]))

    proc = Processor(lib=lib)
    res = proc.process(img, spec, bg=args.bg, hollow_fix=not args.no_hollow_fix,
                       face_alignment=args.face_alignment)
    print("内核：%.3fs  人脸框=%s" % (time.time() - t0, res.face_rect))

    if args.adjust:
        t = ManualTransform.from_dict({
            k: float(v) for k, v in
            (kv.split("=") for kv in args.adjust.split(",") if "=" in kv)
        })
        res.standard_bgr = proc.recrop(res, t)
        print("已应用手动微调：%s" % t.as_dict())

    stem = safe_stem(args.input)
    tag = "%s_%s_%s" % (stem, spec.id, args.bg)

    single = os.path.join(out_dir, "%s.jpg" % tag)
    rep = save_image(res.standard_bgr, single, dpi=spec.dpi,
                     target_kb=args.kb, max_kb=spec.kb_limits[1],
                     min_kb=spec.kb_limits[0])
    mm = printed_mm(single)
    print("\n证件照  %s" % single)
    print("  %d×%dpx  %.1fKB  dpi回读=%s  质量=%s"
          % (spec.px[0], spec.px[1], rep.kb, rep.dpi_readback, rep.quality))
    if mm:
        print("  按该 dpi 打印尺寸：%.2f×%.2fmm（标称 %.0f×%.0fmm）"
              % (mm[0], mm[1], spec.mm[0], spec.mm[1]))
    for m in rep.messages:
        print("  注意：%s" % m)
    if not rep.ok():
        print("  ！导出未满足约束（dpi 或大小）")

    if args.no_layout:
        return 0

    plan = plan_layout(paper.px_at(300), spec.px_size, dpi=300,
                       gap_mm=args.gap, margin_mm=args.margin, paper_id=paper.id)
    if plan.is_empty:
        print("\n！%s 上排不下 %s" % (paper.name_zh, spec.name_zh))
        return 2
    canvas = render_layout(res.standard_bgr, plan, crop_line=args.crop_line)
    layout_path = os.path.join(out_dir, "%s_%s排版.jpg" % (tag, paper.id))
    rep2 = save_image(canvas, layout_path, dpi=300, max_kb=args.layout_max_kb)
    mm2 = printed_mm(layout_path)
    print("\n排版照  %s" % layout_path)
    print("  %s" % plan.summary())
    print("  %.1fKB  按该 dpi 打印尺寸：%.0f×%.0fmm（标称 %.0f×%.0fmm）"
          % (rep2.kb, mm2[0], mm2[1], paper.mm[0], paper.mm[1]))
    print("\n总耗时 %.2fs" % (time.time() - t0))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="证件照自动裁剪排版（命令行版）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", "-i", help="输入照片路径")
    ap.add_argument("--spec", "-s", default="cn_yicun", help="证件照规格 id（默认 cn_yicun）")
    ap.add_argument("--bg", "-b", default="white", help="底色 id（默认 white）")
    ap.add_argument("--paper", "-p", default="6inch", help="相纸 id（默认 6inch）")
    ap.add_argument("--out", "-o", default="output", help="输出目录")
    ap.add_argument("--dpi", type=int, default=0, help="覆盖导出 dpi（默认用规格自带值）")
    ap.add_argument("--kb", type=float, default=0, help="目标文件大小上限 KB")
    ap.add_argument("--gap", type=float, default=DEFAULT_GAP_MM, help="照片间距 mm（默认 2）")
    ap.add_argument("--margin", type=float, default=DEFAULT_MARGIN_MM, help="纸张留边 mm（默认 3）")
    ap.add_argument("--crop-line", default="cross", choices=["none", "cross", "box"],
                    help="裁剪线样式（默认 cross 贯穿式）")
    ap.add_argument("--layout-max-kb", type=float, default=0, help="排版照大小上限 KB")
    ap.add_argument("--adjust", default="", help="手动微调，如 zoom=1.2,offset_y=0.05,rotate=3")
    ap.add_argument("--no-layout", action="store_true", help="只出证件照，不出版照")
    ap.add_argument("--no-hollow-fix", action="store_true", help="关闭抠图内部空洞修补")
    ap.add_argument("--face-alignment", action="store_true", help="开启人脸矫正")
    ap.add_argument("--list-specs", action="store_true", help="列出全部规格")
    ap.add_argument("--list-papers", action="store_true", help="列出相纸与底色")
    ap.add_argument("--plan", action="store_true", help="只算排版张数，不出图")
    ap.add_argument("--count", type=int, default=0, help="配合 --plan：反算最小相纸")
    ap.add_argument("--verbose", "-v", action="store_true")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    lib = SpecLibrary.load()
    lib.require()

    if args.list_specs:
        return cmd_list_specs(lib, args)
    if args.list_papers:
        return cmd_list_papers(lib, args)
    if args.plan:
        return cmd_plan(lib, args)
    if not args.input:
        build_parser().print_help()
        return 1
    try:
        return cmd_run(lib, args)
    except PipelineError as e:
        print("\n处理失败：%s" % e, file=sys.stderr)
        return 3
    except KeyError as e:
        print("\n规格/底色不存在：%s" % e, file=sys.stderr)
        return 4


if __name__ == "__main__":
    sys.exit(main())
