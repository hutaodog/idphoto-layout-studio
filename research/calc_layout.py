# -*- coding: utf-8 -*-
"""Integer layout engine + exact verification. Mirrors what the app must implement."""
from math import floor

MM_PER_INCH = 25.4


def mm_to_px(mm, dpi):
    return int(round(mm / MM_PER_INCH * dpi))


def px_to_mm(px, dpi):
    return px / dpi * MM_PER_INCH


def grid(paper_px, photo_px, gap_px, margin_px):
    """Max cols/rows of photo on paper. paper/photo/gap/margin all in px, same axis."""
    usable = paper_px - 2 * margin_px
    if usable < photo_px:
        return 0
    return (usable + gap_px) // (photo_px + gap_px)


def layout(paper_w, paper_h, photo_w, photo_h, gap=0, margin=0, allow_rotate=True):
    """Return (count, cols, rows, rotated, block_w, block_h)."""
    best = (0, 0, 0, False, 0, 0)
    for rot in ([False, True] if allow_rotate else [False]):
        pw, ph = (photo_h, photo_w) if rot else (photo_w, photo_h)
        c = grid(paper_w, pw, gap, margin)
        r = grid(paper_h, ph, gap, margin)
        n = c * r
        if n > best[0]:
            bw = c * pw + (c - 1) * gap if c else 0
            bh = r * ph + (r - 1) * gap if r else 0
            best = (n, c, r, rot, bw, bh)
    return best


# ---- ground truth: paper sizes @300dpi, integers ----
PAPERS = {
    "3R/5in 89x127": (1051, 1500),
    "4R/6in 102x152": (1205, 1795),
    "5R/7in 127x178": (1500, 2102),
    "A4 210x297": (2480, 3508),
    "A3 297x420": (3508, 4961),
}

# name: (w_mm, h_mm, w_px, h_px, dpi)
PHOTOS = {
    "1inch 25x35": (25, 35, 295, 413, 300),
    "small1cun 22x32": (22, 32, 260, 378, 300),
    "big1cun 33x48": (33, 48, 390, 567, 300),
    "2inch 35x53": (35, 53, 413, 626, 300),
    "small2cun 33x48": (33, 48, 390, 567, 300),
    "big2cun 35x49": (35, 49, 413, 579, 300),
    "passport 33x48": (33, 48, 390, 567, 300),
    "USvisa 51x51": (51, 51, 602, 602, 300),
    "JPvisa 45x45": (45, 45, 531, 531, 300),
    "KRvisa 35x45": (35, 45, 413, 531, 300),
    "IDcard 26x32@350": (26, 32, 358, 441, 350),
    "CET 12x16": (12, 16, 144, 192, 300),
}

# ---- verification 1: do the published px equal mm@dpi rounded? ----
print("=== V1: px vs mm@dpi consistency (tolerance 1px) ===")
bad = 0
for n, (wm, hm, wp, hp, dpi) in PHOTOS.items():
    ew, eh = mm_to_px(wm, dpi), mm_to_px(hm, dpi)
    okw, okh = abs(ew - wp) <= 1, abs(eh - hp) <= 1
    if not (okw and okh):
        bad += 1
        print(f"  MISMATCH {n}: mm->px {ew}x{eh} but catalogue says {wp}x{hp} @{dpi}dpi "
              f"(reverse: {wp}px = {px_to_mm(wp,dpi):.2f}mm)")
print(f"  {len(PHOTOS)-bad}/{len(PHOTOS)} consistent")

print("\n=== V2: paper mm->px @300 ===")
for n, (wp, hp) in PAPERS.items():
    print(f"  {n:16s} {wp}x{hp}")

# ---- verification 2: layout matrix at 3 conventions ----
CONVENTIONS = [("gap0 margin0", 0, 0), ("gap2mm margin3mm", mm_to_px(2, 300), mm_to_px(3, 300)),
               ("gap3mm margin5mm", mm_to_px(3, 300), mm_to_px(5, 300))]

for label, gap, margin in CONVENTIONS:
    print(f"\n=== V3: LAYOUT (gap={gap}px, margin={margin}px) ===")
    print("photo".ljust(20) + "".join(k.split()[0].rjust(14) for k in PAPERS))
    for pn, (wm, hm, wp, hp, dpi) in PHOTOS.items():
        row = pn.ljust(20)
        for paper, (PW, PH) in PAPERS.items():
            n, c, r, rot, bw, bh = layout(PW, PH, wp, hp, gap, margin)
            row += f"{n}({c}x{r}{'R' if rot else ''})".rjust(14)
        print(row)

# ---- verification 3: the specific combos the brief asks about ----
print("\n=== V4: KEY COMBOS (gap2mm margin3mm) ===")
G, M = mm_to_px(2, 300), mm_to_px(3, 300)
asks = [("1inch", "1inch 25x35"), ("2inch", "2inch 35x53"), ("small2cun", "small2cun 33x48"),
        ("passport", "passport 33x48"), ("USvisa", "USvisa 51x51")]
for label, key in asks:
    wm, hm, wp, hp, dpi = PHOTOS[key]
    out = []
    for paper, (PW, PH) in PAPERS.items():
        n, c, r, rot, bw, bh = layout(PW, PH, wp, hp, G, M)
        out.append(f"{paper.split()[0]}={n}({c}x{r}{'R' if rot else ''})")
    print(f"  {label:10s} " + "  ".join(out))

# ---- verification 4: centering produces integral offsets ----
print("\n=== V5: centering offsets (1inch on 6in, gap2mm margin3mm) ===")
PW, PH = PAPERS["4R/6in 102x152"]
wp, hp = 295, 413
n, c, r, rot, bw, bh = layout(PW, PH, wp, hp, G, M)
print(f"  cols={c} rows={r} count={n} block={bw}x{bh}")
print(f"  x0=(PW-bw)//2={(PW-bw)//2}  y0=(PH-bh)//2={(PH-bh)//2}")
print(f"  slack_x=PW-bw-min_gap_edges -> {(PW-bw)}px total, leftover per side "
      f"{((PW-bw)-(c-1)*G)/2:.1f}px = {px_to_mm(((PW-bw)-(c-1)*G)/2,300):.2f}mm")

# ---- verification 5: file size model ----
print("\n=== V6: file size model ===")
for n, (wp, hp) in [("295x413", (295, 413)), ("358x441", (358, 441)), ("413x531", (413, 531)),
                    ("600x600", (600, 600)), ("1205x1795", (1205, 1795)), ("1051x1500", (1051, 1500))]:
    px_n = wp * hp
    print(f"  {n:10s} {px_n/1e3:7.1f} kpx  raw RGB {px_n*3/1024:8.0f} KB  "
          f"jpg q95~{px_n*0.55/1024:7.0f}KB  q85~{px_n*0.35/1024:7.0f}KB  q70~{px_n*0.22/1024:7.0f}KB")
