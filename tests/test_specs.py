# -*- coding: utf-8 -*-
"""规格库测试：数量、id 唯一、mm→px 数学自洽、底色引用合法。

自洽性这条是整个规格库的地基：调研里两个主流开源实现的尺寸表都出现过
「px 与 mm@dpi 对不上」的问题（Hivision 把社保卡 441×358 标成 300dpi，
实际那是 350dpi 的 26×32mm；LiYing 的身份证行如果不看 per-row dpi 会算错 15%）。
"""
import pytest

from app.core.specs import SpecLibrary, mm_to_px

MIN_SPEC_COUNT = 40
# 曾经是 50。v1.5.5 按用户要求做了去重（「一寸/二寸/三寸…一个尺寸只留一条」），
# 把 13 条同尺寸重复项合并成了别名，所以下限跟着降到 40。
# 别再把它调回 50 —— 那是"数量"而不是"质量"的指标，重复项恰恰是用户抱怨的东西。


@pytest.fixture(scope="module")
def lib():
    library = SpecLibrary.load()
    library.require()
    return library


def test_spec_count_at_least_50(lib):
    assert len(lib.photos) >= MIN_SPEC_COUNT, (
        "规格数量不足：%d < %d" % (len(lib.photos), MIN_SPEC_COUNT))


def test_spec_ids_unique(lib):
    ids = [s.id for s in lib.photos]
    assert len(ids) == len(set(ids))


def test_every_spec_is_self_consistent(lib):
    """每条规格都必须满足 px == round(mm/25.4*dpi)，容差 0（round 已含 ±0.5px）。"""
    bad = []
    for s in lib.photos:
        for axis in (0, 1):
            want = mm_to_px(s.mm[axis], s.dpi)
            got = s.px[axis]
            if abs(want - got) > 1:
                bad.append("%s(%s) 第%d轴 mm=%s dpi=%d -> 应为 %d 实为 %d"
                           % (s.name_zh, s.id, axis, s.mm[axis], s.dpi, want, got))
    assert bad == [], "尺寸不自洽的规格：\n" + "\n".join(bad)


def test_no_duplicate_physical_size_in_one_category(lib):
    """「中国常用」里，一个物理尺寸只许有一条通用规格。

    用户对着截图里的「小一寸 / 一寸 / 一寸（350dpi 打印）/ 大一寸 / 二寸」说：
    "把什么一寸、二寸、三寸的，就留一个正常用的那个"。所以：
    * 不同 dpi 的同尺寸变体（一寸（350dpi 打印））合并 —— dpi 在「输出设置」里选；
    * 同尺寸的别的证件名（驾照/社保卡/护照/小二寸…）合并成 aliases，仍然搜得到。

    只查「中国常用」这一个分类：「考试报名」是**一个报名系统一条**（人事考试网/NTCE/研招…），
    「签证护照」是**一个国家一条**（申根/韩国/加拿大…），它们尺寸相同但要求不同
    （底色、文件大小、头部比例），合并反而会丢信息。
    """
    groups = {}
    for s in lib.photos:
        if s.category != "中国常用" or s.name_zh == "五寸生活照":
            continue          # 五寸生活照是"相纸尺寸"不是证件照，不参与去重
        key = (round(s.mm[0], 2), round(s.mm[1], 2))
        groups.setdefault(key, []).append(s.name_zh)
    dup = {k: v for k, v in groups.items() if len(v) > 1}
    assert not dup, "「中国常用」里有重复尺寸的规格：\n" + "\n".join(
        "%sx%smm -> %s" % (k[0], k[1], " | ".join(v)) for k, v in dup.items())


def test_no_dpi_variant_specs(lib):
    """不许再有「XX（350dpi 打印）」「XX（600dpi 高清）」这种"只差 dpi"的规格。

    它们和本体是同一个物理尺寸，混在列表里正是用户抱怨的那类重复项；
    想要别的分辨率就在「输出设置 · 输出分辨率」里选（像素会跟着缩放，打印尺寸不变）。
    """
    bad = [s.name_zh for s in lib.photos
           if "dpi" in s.name_zh.lower() or "dpi" in "".join(s.aliases).lower()
           or "高清" in s.name_zh]
    assert not bad, "还有只差 dpi 的重复规格：%s" % bad


def test_merged_names_are_still_searchable(lib):
    """被合并掉的名字必须还能搜到（靠 aliases），否则用户会以为功能没了。"""
    cases = {
        "社保卡": "身份证",
        "居住证": "身份证",
        "驾照": "小一寸",
        "电子驾照": "小一寸",
        "小二寸": "大一寸",
        "护照": "大一寸",
        "大二寸": "二寸",
        "简历照": "一寸",
        "35x49": "简历照（宽版）",
    }
    for kw, want in cases.items():
        hits = [s.name_zh for s in lib.search(kw)]
        assert want in hits, "搜「%s」找不到「%s」，实际：%s" % (kw, want, hits)


def test_dpi_is_per_spec_not_global_300(lib):
    """必须存在非 300dpi 的规格，否则说明 dpi 被写成了全局常量。"""
    dpis = {s.dpi for s in lib.photos}
    assert 350 in dpis, "缺少 350dpi 规格（身份证/社保卡是 350dpi）"
    assert len(dpis) >= 3, "dpi 取值过少，疑似被当成全局常量：%s" % sorted(dpis)


def test_idcard_is_350dpi_and_26x32mm(lib):
    """身份证这条最容易错：358×441px 只有按 350dpi 才是 26×32mm，按 300dpi 会大 15%。"""
    s = lib.photo("cn_idcard")
    assert s.dpi == 350
    assert s.px == (358, 441)
    w_mm, h_mm = s.print_mm_at(s.dpi)
    assert abs(w_mm - 26.0) < 0.05 and abs(h_mm - 32.0) < 0.05


def test_all_bg_ids_exist(lib):
    color_ids = {c.id for c in lib.colors}
    for s in lib.photos:
        assert s.bg, "%s 没有可用底色" % s.id
        for b in s.bg:
            assert b in color_ids, "%s 引用了不存在的底色 %s" % (s.id, b)


def test_every_spec_has_source_and_confidence(lib):
    for s in lib.photos:
        assert s.source.strip(), "%s 缺少 source" % s.id
        assert s.confidence in ("A", "B", "C", "D"), "%s confidence 非法" % s.id


def test_categories_and_lookup(lib):
    cats = lib.categories()
    assert len(cats) >= 3
    assert all(lib.by_category(c) for c in cats)
    assert lib.photo("cn_yicun").px == (295, 413)
    assert any(s.id == "visa_us" for s in lib.search("美签"))
    assert lib.color("white").bgr == (255, 255, 255)
    assert lib.color("blue").hex.upper() == "628BCE"


def test_papers_are_consistent(lib):
    assert len(lib.papers) >= 5
    for p in lib.papers:
        assert p.px == p.px_at(p.dpi)
    six = lib.paper("6inch")
    assert six.px == (1205, 1795)
    seven = lib.paper("7inch")
    assert seven.px == (1500, 2102)


def test_unknown_spec_raises(lib):
    with pytest.raises(KeyError):
        lib.photo("no_such_spec")
