# -*- coding: utf-8 -*-
"""界面测试（离屏运行，不需要真实显示器）。

覆盖：窗口构建、规格/相纸/底色联动、导入→自动处理、手动微调、排版预览、导出。
需要抠图权重，缺失时整组跳过。
"""
import ast
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt                                     # noqa: E402
from PySide6.QtWidgets import QVBoxLayout, QWidget                 # noqa: E402
from PySide6.QtWidgets import QApplication                        # noqa: E402

from app.core.pipeline import Processor                            # noqa: E402
from app.core.specs import SpecLibrary                             # noqa: E402
from app.ui.main_window import MainWindow                          # noqa: E402

from conftest import DEMO_IMAGE, OUT_DIR, ROOT                # noqa: E402

pytestmark = pytest.mark.skipif(
    not Processor.weights_ready(),
    reason="抠图权重缺失，先运行 scripts\\download_weights.ps1",
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    # 离屏平台常常拿不到系统字体数据库（实测字体数 0），中文会渲染成方框。
    # 这里手动挂一个系统中文字体，让截图和文本测量在测试里也真实可信。
    from PySide6.QtGui import QFontDatabase
    if not QFontDatabase.families():
        for path in (r"C:\Windows\Fonts\msyh.ttc", r"C:\Windows\Fonts\msyh.ttf",
                     r"C:\Windows\Fonts\simhei.ttf", r"C:\Windows\Fonts\simsun.ttc"):
            if os.path.exists(path):
                fid = QFontDatabase.addApplicationFont(path)
                if fid >= 0 and QFontDatabase.families():
                    break
    yield app


@pytest.fixture(scope="module")
def win(qapp):
    os.makedirs(OUT_DIR, exist_ok=True)
    w = MainWindow(SpecLibrary.load())
    yield w
    w.close()


def pump(app, seconds=30.0, until=None):
    """转动事件循环，直到 until() 为真或超时。"""
    t0 = time.time()
    while time.time() - t0 < seconds:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return until() if until else True


def test_window_builds(win):
    assert win.windowTitle()
    assert win.lst_specs.count() >= 40
    assert win.cmb_paper.count() == 5
    assert len(win._color_buttons) >= 6


def test_spec_selection_updates_info_and_layout(win):
    win.ed_search.setText("二寸")
    assert win.lst_specs.count() >= 1
    # 去重后「小二寸」等名字并进了别名，搜「二寸」的第一条可能是「大一寸」——
    # 这里挑出名字就是「二寸」的那条来选（搜得到名字也算功能没丢）
    names = [win.lst_specs.item(i).text() for i in range(win.lst_specs.count())]
    row = next(i for i, t in enumerate(names) if t.startswith("二寸"))
    win.lst_specs.setCurrentRow(row)
    spec = win.current_spec()
    assert spec.name_zh == "二寸", spec.name_zh
    win.ed_search.setText("")
    info = win.lbl_spec_info.text()
    assert "px" in info and "dpi" in info


def test_import_process_and_preview(win, qapp):
    before = win.lst_specs.count()
    win.ed_search.setText("一寸")
    win.lst_specs.setCurrentRow(0)
    assert win.lst_specs.count() >= 1

    win.add_photos([DEMO_IMAGE])
    assert len(win.items) == 1
    ok = pump(qapp, 60, lambda: win.result is not None)
    assert ok, "处理没有返回结果：%s" % (win.items[0].error or "超时")
    assert win.result.size == win.current_spec().px_size
    assert win.canvas.has_image
    assert before >= 40


def test_manual_adjust_changes_pixels(win, qapp):
    base = win.result.standard_bgr.copy()
    win.rb_manual.setChecked(True)
    win.sl_zoom.setValue(40)
    assert win.manual_mode
    assert not (win.result.standard_bgr == base).all(), "缩放滑块没有改变画面"
    win.sl_offset_y.setValue(25)
    win.sl_rotate.setValue(30)
    assert win.result.standard_bgr.shape == base.shape
    # 画布拖动 = 平移（只验证不抛异常且参数被更新）
    old = win.sl_offset_x.value()
    win.on_canvas_panned(-0.05, 0.0)
    assert win.sl_offset_x.value() != old


def test_reset_returns_to_auto(win, qapp):
    win.on_canvas_reset()
    ok = pump(qapp, 60, lambda: win.result is not None and not win.manual_mode)
    assert ok
    assert not win.manual_mode
    assert win.sl_zoom.value() == 0
    # 复位时滑块屏蔽了信号，配对数字框也必须跟着回到默认值（否则界面自相矛盾）
    assert win.sl_zoom.value_box.value() == 0
    assert win.sl_head.value_box.value() == 55
    assert win.sl_center.value_box.value() == 42


def test_background_switch_recomposes_without_model(win, qapp):
    win.on_bg_changed("blue")
    blue = win.result.standard_bgr.copy()
    t0 = time.time()
    win.on_bg_changed("red")
    dt = time.time() - t0
    red = win.result.standard_bgr
    assert not (blue == red).all()
    assert dt < 2.0, "换底色不该重跑模型，耗时 %.2fs" % dt


def select_spec(win, spec_id):
    """在列表里按 id 精确选中一个规格（搜索会命中多个同名近似项）。"""
    win.ed_search.setText("")
    if win.cmb_category.currentText() != "全部":
        win.cmb_category.setCurrentText("全部")
    for row in range(win.lst_specs.count()):
        if win.lst_specs.item(row).data(Qt.UserRole) == spec_id:
            win.lst_specs.setCurrentRow(row)
            assert win.current_spec().id == spec_id
            return
    raise AssertionError("列表里找不到规格 %s" % spec_id)


def test_layout_preview_and_crop_line_switch(win, qapp):
    select_spec(win, "cn_yicun")
    win.rb_layout.setChecked(True)
    win.cmb_paper.setCurrentIndex(1)          # 6寸
    win.cmb_crop_line.setCurrentIndex(0)      # 贯穿式
    assert win.preview_layout_mode
    assert win.canvas.has_image
    info = win.lbl_layout_info.text()
    assert "12 张" in info, info              # 6寸排一寸照 = 12 张
    win.cmb_crop_line.setCurrentIndex(2)      # 不画线
    assert win.canvas.has_image
    win.rb_photo.setChecked(True)


def test_gap_and_margin_recompute(win):
    win.sp_gap.setValue(1.0)
    win.sp_margin.setValue(1.0)
    tight = win.lbl_layout_info.text()
    win.sp_gap.setValue(6.0)
    win.sp_margin.setValue(10.0)
    loose = win.lbl_layout_info.text()
    assert tight != loose


def ensure_photo(win, qapp):
    """保证窗口里有一张已处理完成的照片，让测试可以单独运行而不依赖执行顺序。"""
    if win.result is None:
        win.add_photos([DEMO_IMAGE])
    ok = pump(qapp, 60, lambda: win.result is not None)
    assert ok, "处理没有返回结果：%s" % (win.items[0].error if win.items else "无照片")
    return win.result


def silence_popups(monkeypatch):
    """把圆角弹窗换成空实现，避免测试卡在模态对话框上。"""
    import app.ui.main_window as mw
    monkeypatch.setattr(mw, "show_message", lambda *a, **k: None, raising=True)


def test_export_current_writes_files(win, qapp, monkeypatch):
    import shutil
    silence_popups(monkeypatch)
    ensure_photo(win, qapp)
    # 等后台处理跟上界面选择；等不到就用界面当前规格重新算一次
    if not pump(qapp, 10, lambda: win.result is not None
                and win.result.spec.id == win.current_spec().id):
        win.reprocess_current()
        assert pump(qapp, 60, lambda: win.result is not None
                    and win.result.spec.id == win.current_spec().id), "规格切换后没有重算"
    win._out_dir = os.path.join(OUT_DIR, "gui_export")
    if os.path.isdir(win._out_dir):
        shutil.rmtree(win._out_dir)          # 清干净，避免读到上一次运行的残留文件
    win._update_out_label()
    win.sp_gap.setValue(2.0)
    win.sp_margin.setValue(3.0)
    win.cb_single.setChecked(True)
    win.cb_layout.setChecked(True)
    spec = win.current_spec()
    win.on_export_current()
    files = os.listdir(win._out_dir)
    assert any(f.endswith(".jpg") and "排版" not in f for f in files), files
    assert any("排版" in f for f in files), files
    from app.core.exporter import printed_mm, read_dpi
    single = [f for f in files if f.endswith(".jpg") and "排版" not in f][0]
    assert ("_%s_" % spec.id) in single, "导出的文件名没带当前规格：%s" % single
    p = os.path.join(win._out_dir, single)
    assert read_dpi(p) == (spec.dpi, spec.dpi)
    w_mm, h_mm = printed_mm(p)
    assert abs(w_mm - spec.mm[0]) < 0.2 and abs(h_mm - spec.mm[1]) < 0.2, (w_mm, h_mm)


def test_batch_export(win, qapp, monkeypatch):
    silence_popups(monkeypatch)
    win.add_photos([DEMO_IMAGE])          # 重复路径会被去重，所以换个副本名
    import shutil
    second = os.path.join(OUT_DIR, "第二张测试照片.jpg")
    shutil.copyfile(DEMO_IMAGE, second)
    win.add_photos([second])
    assert len(win.items) >= 2
    win._out_dir = os.path.join(OUT_DIR, "gui_batch")
    win._update_out_label()
    win.on_export_all()
    ok = pump(qapp, 180, lambda: win._batch is not None and not win._batch.isRunning())
    assert ok, "批量导出超时"
    files = os.listdir(win._out_dir)
    assert sum(1 for f in files if f.endswith(".jpg")) >= 4, files


def test_canvas_renders_real_pixels(win, qapp):
    """真渲染一次，确认 PySide6 在含中文的安装路径下能正常绘制。"""
    win.rb_photo.setChecked(True)
    win.refresh_preview()
    qapp.processEvents()
    pm = win.canvas.grab()
    assert not pm.isNull()
    assert pm.width() > 50 and pm.height() > 50
    shot = os.path.join(OUT_DIR, "ui_screenshot.png")
    win.grab().save(shot)
    assert os.path.exists(shot) and os.path.getsize(shot) > 5000


def test_chinese_font_is_usable(qapp):
    """界面文字必须有能显示中文的字体可用，否则用户看到的是方框。"""
    from PySide6.QtGui import QFontMetrics
    from app.main import apply_chinese_font
    name = apply_chinese_font(qapp)
    assert name, "没有找到任何中文字体"
    fm = QFontMetrics(qapp.font())
    assert fm.horizontalAdvance("证件照排版") > 20
    # 用足够宽的画布测：方框与真汉字宽度接近，但至少确认能测量且不为 0
    assert fm.horizontalAdvance("一寸") > 0


# --------------------------------------------------------------------------
# 以下 4 项对应用户实测反馈的 4 个问题，防止回归
# --------------------------------------------------------------------------

def test_close_splash_is_safe_without_frozen_runtime():
    """问题 1：启动画面必须被主动关掉。

    冻结版里 pyi_splash 存在，这里验证「从源码运行（没有该模块）」时也不报错。
    """
    from app.main import close_splash
    close_splash()          # 不应抛异常


def test_splash_close_is_called_on_startup(monkeypatch):
    """确认 main() 的启动路径里确实调用了 close_splash。

    漏掉这一步就是用户看到的「启动窗口一直搁在那儿不消失」。
    """
    import PySide6.QtWidgets as QW
    import app.main as m
    import app.ui.main_window as mw

    called = {"splash": 0, "shown": 0}

    class FakeStatus:
        def showMessage(self, *a, **k):
            pass

    class FakeWindow:
        def __init__(self, lib):
            self.status = FakeStatus()

        def show(self):
            called["shown"] += 1

    class FakeApp:
        def __init__(self, *a, **k):
            pass

        def setApplicationName(self, *a):
            pass

        def setApplicationVersion(self, *a):
            pass

        def exec(self):
            return 0

    monkeypatch.setattr(QW, "QApplication", FakeApp)
    monkeypatch.setattr(mw, "MainWindow", FakeWindow)
    monkeypatch.setattr(m, "setup_streams", lambda: None)
    monkeypatch.setattr(m, "apply_chinese_font", lambda app: "")
    monkeypatch.setattr(m, "close_splash",
                        lambda: called.__setitem__("splash", called["splash"] + 1))

    rc = m.main()
    assert rc == 0
    assert called["shown"] == 1, "窗口没有被显示"
    assert called["splash"] >= 1, "启动流程里没有关闭启动画面"


def test_bg_change_is_immediate_in_manual_mode(win, qapp):
    """问题 2：手动微调模式下换底色必须立即生效。

    曾经的 bug：先 recrop 后写 result.bg，导致 recrop 用的是旧底色，
    必须切换一次规格（触发重跑模型）背景才变。
    """
    import numpy as np
    ensure_photo(win, qapp)
    win.rb_manual.setChecked(True)
    assert win.manual_mode

    win.on_bg_changed("white")
    white = win.result.standard_bgr.copy()
    win.on_bg_changed("blue")
    blue = win.result.standard_bgr

    assert not np.array_equal(white, blue), "手动微调模式下换底色没有立即生效"
    # 四角应接近所选底色（Hivision 蓝 #628BCE -> BGR 206,139,98）
    corner = blue[3, 3].astype(int)
    assert abs(corner[0] - 206) < 45 and abs(corner[1] - 139) < 45, corner
    # 白色底换回白色也应该马上生效
    win.on_bg_changed("white")
    back = win.result.standard_bgr
    assert np.array_equal(back, white), "换回白色没有还原"


def test_wheel_never_changes_values(win, qapp):
    """问题 3（v1.1.1 加强）：滚轮划过数字框/下拉框，**任何时候**都不能改数值。

    历史：v1.0.0 是一划就改；v1.1.0 改成"先点一下聚焦，滚轮才生效"；但用户第二次
    截图反馈——点过之后再滚页面（鼠标停在参数框上）照样会改，所以现在彻底不响应
    滚轮：改数值只能键盘输入，或者用数字框右侧的上下箭头。
    """
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from app.ui.widgets import NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox

    def wheel(widget, delta=120):
        ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, delta),
                         Qt.NoButton, Qt.NoModifier, Qt.ScrollUpdate, False)
        widget.wheelEvent(ev)

    for box in (NoWheelSpinBox(), NoWheelDoubleSpinBox()):
        box.setRange(-100, 100)
        box.setValue(7)
        box.clearFocus()
        qapp.processEvents()
        wheel(box)
        assert box.value() == 7, "%s 在未聚焦时被滚轮改了值" % type(box).__name__

        # 离屏环境下必须先 show() 才能拿到焦点
        box.show()
        box.setFocus()
        qapp.processEvents()
        wheel(box)
        assert box.value() == 7, \
            "%s 聚焦后被滚轮改了值——用户要求鼠标在上面滚动绝不改数值" % type(box).__name__
        box.close()

    cmb = NoWheelComboBox()
    cmb.addItems(["a", "b", "c"])
    cmb.setCurrentIndex(1)
    wheel(cmb)
    assert cmb.currentIndex() == 1, "下拉框被滚轮改了选中项"

    # 界面里的实际控件也必须是防误触类型
    from app.ui.widgets import NoWheelSlider
    assert isinstance(win.sl_zoom, NoWheelSlider)
    assert isinstance(win.sp_gap, NoWheelDoubleSpinBox)
    assert isinstance(win.cmb_paper, type(win.cmb_crop_line))


def test_color_swatches_render_their_actual_color(win, qapp):
    """色块必须真的显示出对应颜色。

    曾经的 bug：规格库里的 hex 不带 #，直接塞进 CSS 是非法值，
    Qt 静默回退成全局样式的白色 —— 表现为"色块一片空白"。
    """
    from app.ui.widgets import ColorSwatch
    holder = QWidget()
    v = QVBoxLayout(holder)
    pairs = []
    for c in win.lib.colors:
        b = ColorSwatch(c.hex, c.name_zh)
        v.addWidget(b)
        pairs.append((c, b))
    holder.resize(320, 60 * len(pairs))
    holder.show()
    qapp.processEvents()
    img = holder.grab().toImage()
    bad = []
    for c, b in pairs:
        assert b.css_color == "#" + c.hex.upper(), (b.css_color, c.hex)
        g = b.geometry()
        px = img.pixelColor(g.x() + g.width() // 2, g.y() + 8)
        if (abs(px.red() - c.rgb[0]) > 12 or abs(px.green() - c.rgb[1]) > 12
                or abs(px.blue() - c.rgb[2]) > 12):
            bad.append("%s 期望 %s 实得 #%02X%02X%02X"
                       % (c.name_zh, c.hex_code, px.red(), px.green(), px.blue()))
    holder.close()
    assert bad == [], "色块颜色不对：\n" + "\n".join(bad)


def test_drag_pans_the_view_not_the_photo(win, qapp):
    """拖动 = 平移**视图**，不能再改照片参数。

    用户连着提了两轮：
      v1.5.2「为什么滚轮直接调整图片缩放？」→ 滚轮改成只放大视图；
      v1.5.3「怎么还是拖拽里面的图片呢？不应该是拖拽预览图左右那个查看」→ 拖动也改成平移视图。
    这里守住三件事：普通拖动**不发** panned（参数不动）、视图平移量真的变了、
    Ctrl+拖动才发 panned（保留挪照片那条老路）。
    """
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    canvas = win.canvas
    win.resize(1200, 800)
    win.show()
    qapp.processEvents()
    # 塞一张纯色图进去（不跑模型），再放大 3 档，这样才有"四处看看"的余地
    import numpy as np
    canvas.set_image(np.full((400, 300, 3), 120, np.uint8), "测试")
    canvas.resize(360, 360)
    canvas.zoom_view(6)
    qapp.processEvents()
    assert canvas.view_zoom() > 1.0, "测试前提：视图得先放大"

    seen = []
    canvas.panned.connect(lambda dx, dy: seen.append((dx, dy)))

    def drag(modifier=Qt.NoModifier):
        start = QPointF(canvas.width() / 2, canvas.height() / 2)
        canvas.mousePressEvent(QMouseEvent(
            QMouseEvent.MouseButtonPress, start, canvas.mapToGlobal(start.toPoint()),
            Qt.LeftButton, Qt.LeftButton, modifier))
        mid = QPointF(start.x() - 40, start.y() - 25)
        canvas.mouseMoveEvent(QMouseEvent(
            QMouseEvent.MouseMove, mid, canvas.mapToGlobal(mid.toPoint()),
            Qt.NoButton, Qt.LeftButton, modifier))
        canvas.mouseReleaseEvent(QMouseEvent(
            QMouseEvent.MouseButtonRelease, mid, canvas.mapToGlobal(mid.toPoint()),
            Qt.LeftButton, Qt.NoButton, modifier))

    before = QPointF(canvas.view_pan())
    drag()
    assert seen == [], "普通拖动居然发了 panned（会去改照片参数）：%s" % (seen,)
    assert canvas.view_pan() != before, "普通拖动没有平移视图"

    seen.clear()
    before2 = QPointF(canvas.view_pan())
    drag(Qt.ControlModifier)
    assert seen, "Ctrl+拖动应该发 panned（挪照片构图那条老路）"
    assert canvas.view_pan() == before2, "Ctrl+拖动不该平移视图"


def test_left_column_order_matches_user_marks(win, qapp):
    """左列卡片顺序 = 用户在截图里手写的编号（证件照规格 1 / 背景底色 2 / 构图微调 3）。

    原来「照片列表」在最上面，用户给这三张标了 1/2/3 —— 也就是它们要排最前，
    照片列表往后挪。
    """
    from app.ui.section_card import SectionCard

    win.set_layout("studio")
    win.resize(1300, 900)
    win.show()
    qapp.processEvents()
    cards = sorted(win.findChildren(SectionCard),
                   key=lambda c: c.mapTo(win, c.rect().topLeft()).y())
    titles = [c.header.lbl_title.text() for c in cards]
    want = ["证件照规格", "背景底色", "构图微调"]
    assert titles[:3] == want, "左列前三张应该是 %s，实际 %s" % (want, titles)
    assert titles.index("照片列表") > titles.index("构图微调"), (
        "「照片列表」应该排在标了编号的三张之后，实际顺序 %s" % titles)


def test_titlebar_menu_and_title_share_one_line(qapp):
    """标题栏里「标题 / 版本号 / 文件 / 帮助」必须在同一条线上。

    用户截图圈出过："这几个文字位置不太对，都没有对齐。"
    根因是 QMenuBar 被拉满整条标题栏、文字贴着顶画（实测差 7~8px）。
    这条测试直接量渲染出来的像素：几段文字的竖直中心不能差超过 2px。
    """
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage
    from PySide6.QtWidgets import QMenuBar, QWidget
    import numpy as np

    from app.ui import chrome

    holder = QWidget()
    bar = chrome.TitleBar(holder, "证件照排版助手", "1.5.3")
    mb = QMenuBar()
    mb.addMenu("文件")
    mb.addMenu("帮助")
    bar.attach_menubar(mb)
    bar.resize(760, bar.HEIGHT)
    bar.show()
    qapp.processEvents()

    img = bar.grab().toImage().convertToFormat(QImage.Format_RGBA8888)
    ptr = img.constBits()
    arr = np.frombuffer(bytes(ptr), np.uint8).reshape(img.height(), img.bytesPerLine())
    arr = arr[:, : img.width() * 4].reshape(img.height(), img.width(), 4).astype(float)
    a = arr[:, :, 3:4] / 255.0
    rgb = (arr[:, :, :3] * a + 255.0 * (1 - a)).astype(np.uint8)
    gray = rgb.mean(axis=2)

    def center(x0, x1):
        band = gray[0:bar.HEIGHT, x0:x1] < 165
        rows = np.where(band.any(axis=1))[0]
        assert len(rows), "x=%d..%d 这段没找到文字" % (x0, x1)
        return (rows[0] + rows[-1]) / 2.0

    title = center(48, 140)          # 证件照排版助手
    ver = center(150, 182)           # v1.5.3
    menu = center(*_menu_x_range(bar, mb, 760))   # 文件 / 帮助 两块
    assert abs(menu - title) <= 2, (
        "菜单文字（中心 %.1f）和标题（中心 %.1f）没对齐，差了 %.1fpx"
        % (menu, title, abs(menu - title)))
    assert abs(ver - title) <= 2, (
        "版本号（中心 %.1f）和标题（中心 %.1f）没对齐" % (ver, title))
    bar.close()


def _menu_x_range(bar, mb, width):
    """菜单栏在标题栏里的横向范围（前后各留 6px 余量）。"""
    x0 = mb.mapTo(bar, mb.rect().topLeft()).x()
    return (x0 + 4, min(width, x0 + mb.width() + 4))


def test_export_buttons_are_flat_pills_with_glow(win, qapp):
    """三个导出按钮必须是**胶囊状**（圆角 = 高度的一半）+ **平面**配色，主按钮带泛光。

    用户改了三轮，最后拍板的是这一版：
      "把这三个按钮的玻璃效果去掉吧，就改成平面就行，泛光保留。现在这样太丑。"
    所以这条测试守住三件事：**还是胶囊**、**确实画的是平涂纯色（上中下同色）**、
    **只有主按钮挂泛光（白胶囊不许再挂投影）**。
    """
    from PySide6.QtWidgets import QGraphicsDropShadowEffect
    from app.ui.widgets import PillButton

    for b in (win.btn_export_single, win.btn_export_layout, win.btn_export_all):
        assert isinstance(b, PillButton), "%s 不是胶囊按钮" % b.text()
        h = b.height() or b.minimumHeight()
        # 胶囊：圆角半径取高度一半（自绘里就是这么算的），高度得在合理区间
        assert 30 <= h <= 44, "%s 高度 %d 不像胶囊" % (b.text(), h)
        assert b.text(), "按钮文字不能为空"
    assert win.btn_export_all.primary is True, "主按钮没标记成 primary（配色会不对）"
    assert win.btn_export_single.primary is False
    # 主按钮要比另外两个大一点（醒目）
    assert win.btn_export_all.height() > win.btn_export_single.height()

    win.show()
    qapp.processEvents()

    def tone(btn, y):
        img = btn.grab().toImage()
        return img.pixelColor(img.width() // 2, y)

    # 平面 = 上中下同一片颜色（玻璃版有渐变，这里必须没有）
    for b in (win.btn_export_single, win.btn_export_all):
        top = tone(b, 4)
        bottom = tone(b, b.height() - 5)
        assert abs(top.red() - bottom.red()) <= 6, (
            "「%s」上下颜色差太多（%s vs %s），又变成渐变/玻璃了"
            % (b.text(), top.name(), bottom.name()))
        assert abs(top.blue() - bottom.blue()) <= 6, (
            "「%s」上下颜色差太多（%s vs %s）" % (b.text(), top.name(), bottom.name()))

    # 白胶囊：白底 + 深字；蓝胶囊：蓝底 + 白字
    ghost = tone(win.btn_export_single, win.btn_export_single.height() // 2 - 10)
    assert min(ghost.red(), ghost.green(), ghost.blue()) > 240, (
        "白胶囊不是纯白平涂：%s" % ghost.name())
    blue = tone(win.btn_export_all, win.btn_export_all.height() // 2 - 12)
    assert blue.blue() > blue.red() + 20, "主按钮不是蓝色平涂：%s" % blue.name()

    # 泛光只在主按钮上（用户："泛光保留"）
    assert isinstance(win.btn_export_all.graphicsEffect(), QGraphicsDropShadowEffect), (
        "主按钮没有泛光")
    for b in (win.btn_export_single, win.btn_export_layout):
        assert b.graphicsEffect() is None, (
            "「%s」是平面按钮，不该再挂投影/泛光" % b.text())


def test_preview_toggle_is_tall_enough(win, qapp):
    """右上角「证件照预览 / 排版预览」胶囊不能太扁（用户："调得稍微高一点"）。"""
    seg = getattr(win, "preview_toggle", None)
    assert seg is not None, "工作台布局里没有胶囊切换钮"
    assert seg.height() >= 34, "胶囊还是太扁：%d px" % seg.height()
    assert seg.width() >= 160, "胶囊太窄，文字会挤：%d px" % seg.width()


def test_card_summaries_follow_current_state(win, qapp):
    """左列每张卡的摘要必须跟着**当前状态**走。

    用户截图问过："为什么我选择 1 寸了，那块还显示小 1 寸" —— 因为摘要原来是建卡时
    写死的字符串。现在 MainWindow._refresh_card_summaries() 把它们接到真实状态上，
    这条测试守住：换规格 / 换底色 / 换相纸 / 换分辨率，卡头都要跟着变。
    """
    from app.ui.section_card import SectionCard

    cards = getattr(win, "card_summaries", None)
    assert cards, "工作台布局没有把卡片暴露给 MainWindow（card_summaries）"
    win.show()
    qapp.processEvents()

    win.ed_search.setText("")
    rows = [win.lst_specs.item(i).text() for i in range(win.lst_specs.count())]
    win.lst_specs.setCurrentRow(next(i for i, t in enumerate(rows) if t.startswith("一寸")))
    qapp.processEvents()
    assert cards["spec"].header.lbl_summary.text() == "一寸", (
        "选了「一寸」，卡头还是 %r" % cards["spec"].header.lbl_summary.text())

    win.on_bg_changed("red")
    qapp.processEvents()
    assert cards["bg"].header.lbl_summary.text() == "红色", (
        "换成红底了，卡头还是 %r" % cards["bg"].header.lbl_summary.text())

    win.cmb_paper.setCurrentIndex(0)                 # 5 寸
    qapp.processEvents()
    txt = cards["layout"].header.lbl_summary.text()
    assert txt.startswith("5寸") and "张" in txt, "相纸卡头没跟着变：%r" % txt

    win.cmb_dpi.setCurrentIndex(win.cmb_dpi.count() - 1)   # 600 dpi
    qapp.processEvents()
    assert cards["output"].header.lbl_summary.text().endswith("dpi"), (
        "分辨率卡头没跟着变：%r" % cards["output"].header.lbl_summary.text())

    # 摘要文字要能塞进卡头（太长会把标题挤没）
    for key, card in cards.items():
        assert len(card.header.lbl_summary.text()) <= 18, (
            "「%s」摘要太长：%r" % (key, card.header.lbl_summary.text()))

    # 恢复默认，别影响后面的测试
    win.cmb_paper.setCurrentIndex(1)
    win.cmb_dpi.setCurrentIndex(0)
    win.on_bg_changed("white")
    qapp.processEvents()
    assert isinstance(cards["spec"], SectionCard)


def test_first_four_cards_expanded_by_default(win, qapp):
    """左列前四张（证件照规格 / 背景底色 / 构图微调 / 相纸与排版）默认展开。

    用户 v1.5.6 反馈："把这四个默认设为展开状态。"
    """
    cards = getattr(win, "card_summaries", None)
    assert cards, "工作台布局没有把卡片暴露给 MainWindow（card_summaries）"
    win.set_layout("studio")
    win.show()
    qapp.processEvents()
    for key in ("spec", "bg", "adjust", "layout"):
        assert cards[key].is_expanded(), "「%s」这张卡默认应该展开" % key


def test_spin_and_combo_arrows_are_drawn(qapp):
    """下拉框/数字框的箭头必须是**画出来的三角形**，不能靠 QSS 的 border 拼。

    用户截图圈过"这块的图标显示好像有问题"：QSS 里用 `border-left/right/top` 拼三角形，
    在本机渲染成了——下拉框一个小方块、数字框两个灰色长方形。
    改成自绘之后，这里检查箭头区域确实有深色像素（三角形），而不是整块背景。
    """
    from app.ui.widgets import CheckBox, NoWheelComboBox, NoWheelSpinBox

    spin = NoWheelSpinBox()
    spin.setRange(0, 100)
    spin.resize(90, 32)
    spin.show()
    qapp.processEvents()
    img = spin.grab().toImage()
    dark = 0
    for y in range(3, 15):
        for x in range(img.width() - 18, img.width() - 4):
            c = img.pixelColor(x, y)
            if c.red() < 200 and c.alpha() > 200:
                dark += 1
    assert dark >= 3, "数字框的上箭头没画出来（只有 %d 个深色像素）" % dark

    combo = NoWheelComboBox()
    combo.addItems(["甲", "乙"])
    combo.resize(160, 32)
    combo.show()
    qapp.processEvents()
    img = combo.grab().toImage()
    dark = 0
    for y in range(6, img.height() - 6):
        for x in range(img.width() - 24, img.width() - 4):
            c = img.pixelColor(x, y)
            if c.red() < 200 and c.alpha() > 200:
                dark += 1
    assert dark >= 4, "下拉箭头没画出来（只有 %d 个深色像素）" % dark

    # 复选框：选中时要在蓝底里画出白色对勾
    cb = CheckBox("测试")
    cb.setChecked(True)
    cb.resize(140, 26)
    cb.show()
    qapp.processEvents()
    img = cb.grab().toImage()
    white = 0
    for y in range(2, img.height() - 2):
        for x in range(2, 22):
            c = img.pixelColor(x, y)
            if c.red() > 240 and c.green() > 240 and c.blue() > 240 and c.alpha() > 200:
                white += 1
    assert white >= 6, "复选框选中时只有蓝色方块、没有对勾（白点 %d 个）" % white
    for w in (spin, combo, cb):
        w.close()


def test_app_icon_comes_from_the_user_source(qapp):
    """程序图标必须由 app/resources/icon_source.png 生成（用户指定的那张图）。"""
    import os

    from PIL import Image

    from conftest import ROOT

    res = os.path.join(ROOT, "app", "resources")
    src = os.path.join(res, "icon_source.png")
    ico = os.path.join(res, "icon.ico")
    assert os.path.exists(src), "缺少图标源图 app/resources/icon_source.png"
    assert os.path.exists(ico), "缺少 icon.ico"
    with Image.open(src) as im:
        assert im.size[0] >= 512, "源图太小：%s" % (im.size,)
    with Image.open(ico) as im:
        sizes = {s[0] for s in im.ico.sizes()}
    for need in (16, 32, 48, 256):
        assert need in sizes, "icon.ico 缺少 %d×%d（任务栏/标题栏会糊）：%s" % (
            need, need, sorted(sizes))


def test_window_edges_are_not_resize_zones(win, qapp):
    """窗口**不能**拖边缘改大小（用户 v1.5.6："改成窗口默认不可随意拉拽调整窗口大小"）。

    这里的过程值得记一笔：v1.5.3 用户抱怨"无法随意拉动窗口大小"，于是做了原生缩放热区
    （拦 WM_NCHITTEST 返回 HTLEFT/HTTOPLEFT…）；用了两轮之后用户又要求固定，
    因为 6px 的热区太容易误触。所以现在 `chrome.ALLOW_EDGE_RESIZE = False`：
    四条边、四个角都不再返回 HT* 码，Windows 只当普通客户区，拖边缘不会改变窗口大小。
    想恢复缩放能力：把那个常量改回 True（测试也要跟着改）。
    """
    import ctypes
    import ctypes.wintypes as wt
    from app.ui import chrome

    assert chrome.ALLOW_EDGE_RESIZE is False, (
        "窗口缩放被重新打开了 —— 用户明确要求固定，请先确认是不是有意的")

    if not hasattr(ctypes, "windll"):                      # 非 Windows 直接跳过
        pytest.skip("只有 Windows 需要处理 WM_NCHITTEST")
    win.resize(1200, 800)
    win.show()
    qapp.processEvents()
    g = win.frameGeometry()
    x0, y0, w, h = g.x(), g.y(), g.width(), g.height()
    assert w > 100 and h > 100, "窗口几何异常：%s" % (g.getRect(),)

    def hit(dx, dy):
        msg = wt.MSG()
        msg.message = chrome.WM_NCHITTEST
        sx, sy = x0 + dx, y0 + dy
        msg.lParam = ((sy & 0xFFFF) << 16) | (sx & 0xFFFF)
        return chrome.native_hit_test(win, ctypes.addressof(msg))

    probes = [(1, 1), (1, h // 2), (w // 2, 1), (w - 2, h // 2), (w // 2, h - 2),
              (w - 2, h - 2), (w // 2, h // 2)]
    for (dx, dy) in probes:
        got = hit(dx, dy)
        assert got is None, (
            "窗口偏移 %s 处返回了缩放命中码 %s —— 边缘又变成缩放热区了" % ((dx, dy), got))

    # Frame 自绘的那套八方向热区也要一起关掉（否则光标还会变成缩放光标，误导人）
    from app.ui.chrome import Frame
    frames = win.findChildren(Frame)
    if frames:
        f = frames[0]
        for pt in (f.rect().topLeft(), f.rect().bottomRight(), f.rect().center()):
            edges = f._edges_at(pt)
            assert not edges, (
                "Frame 还在把窗口边角当缩放热区（%s 处返回了 %r）"
                % ((pt.x(), pt.y()), edges))


def test_window_rounding_attempted(win, qapp):
    """窗口圆角：走 DWM 圆角偏好，失败才退回 SetWindowRgn，绝不能两条都失败还不吭声。"""
    win.resize(1200, 800)
    win.show()
    qapp.processEvents()
    win._apply_round_region()
    mode = getattr(win, "_round_mode", None)
    if os.name != "nt":
        pytest.skip("圆角是 Windows 上的事")
    assert mode in ("dwm", "rgn", "none"), "圆角方式没有记录下来：%r" % (mode,)
    from app.ui import acrylic
    assert hasattr(acrylic, "set_round_corners"), "少了 DWM 圆角接口"


def test_rounded_dialog_buttons_and_radius(qapp):
    """问题 4：弹窗必须是自绘的大圆角，并且按钮返回正确选择。"""
    from app.ui.style import DIALOG_RADIUS
    from app.ui.widgets import RoundedDialog
    assert DIALOG_RADIUS >= 16, "弹窗圆角偏小：%d" % DIALOG_RADIUS

    dlg = RoundedDialog(None, title="测试", text="内容", kind="info",
                        buttons=("取消", "确定"))
    assert dlg.windowFlags() & Qt.FramelessWindowHint
    assert dlg._card.styleSheet().find("border-radius:%dpx" % DIALOG_RADIUS) >= 0
    assert len(dlg._buttons) == 2
    dlg._choose(1)
    assert dlg.result_index() == 1
    dlg.deleteLater()


def test_labels_do_not_paint_a_background(qapp):
    """回归（用户截图："字有灰色的底色"）。

    全局样式表里曾经写 `QWidget { background: BG }`，而 Qt 的类型选择器会命中
    **所有子类**——于是每个 QLabel 都在文字背后刷了一块窗口底色，白色卡片上就是
    一块块灰块。现在底色只由窗口/卡片负责，QLabel 显式 transparent。
    """
    from app.ui import style
    from PySide6.QtWidgets import QFrame, QLabel

    prev = qapp.styleSheet()
    qapp.setStyleSheet(style.STYLESHEET)
    try:
        holder = QFrame()
        holder.setObjectName("card")
        holder.setStyleSheet("QFrame#card{background:%s;border:none;}" % style.CARD)
        v = QVBoxLayout(holder)
        v.setContentsMargins(20, 20, 20, 20)
        lbl = QLabel("旋转 0.1°")
        v.addWidget(lbl)
        holder.resize(240, 90)
        holder.show()
        qapp.processEvents()

        img = holder.grab().toImage()
        # 取标签内部、文字右侧的空白处（一定不是笔画）
        pts = [(lbl.x() + lbl.width() - 3, lbl.y() + 2),
               (lbl.x() + lbl.width() - 3, lbl.y() + lbl.height() - 3)]
        for px, py in pts:
            c = img.pixelColor(px, py)
            got = (c.red(), c.green(), c.blue())
            assert got == (255, 255, 255), (
                "标签背后被刷了底色 %s（应为卡片白）——QLabel 的 background 又没兜住"
                % (got,))
        holder.close()
    finally:
        qapp.setStyleSheet(prev)


def test_ui_strings_avoid_missing_font_glyphs():
    """回归：界面上不许出现微软雅黑没有的符号字形。

    实测（离屏渲染逐字比对 + 真实截图确认）：U+2714 ✔、U+2713 ✓、U+2715 ✕、
    U+2717 ✗、U+26A0 ⚠、U+24D8 ⓘ 在 Microsoft YaHei 里**都没有字形**，
    渲染出来是豆腐块。这些东西出现在"可排 16 张"前面、规格列表的 C/D 级标记上，
    非常难看。改用颜色 + 文字 + 自绘色点表达。
    """
    bad = "✔✓✕✗⚠ⓘ"
    offenders = []
    for name in ("main_window.py", "widgets.py", "preview.py"):
        path = os.path.join(ROOT, "app", "ui", name)
        with open(path, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        # 只看字符串字面量：注释里为了说明问题会写到这些码点，不算违规
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            for ch in bad:
                if ch in node.value:
                    offenders.append("%s:%d 含 U+%04X" % (name, node.lineno, ord(ch)))
    assert not offenders, "界面上会出现豆腐块：%s" % "；".join(offenders)


def test_radio_checked_state_keeps_indicator_geometry():
    """回归（用户截图：选中的单选按钮是个"蓝色圆角方块"）。

    Qt 的 QSS 里子控件的 width/height 是**内容盒**，border 加在外面：
    没选中 15px+1px*2=17px，选中 15px+4px*2=23px —— 尺寸一跳，23px 的方块
    配 8px 圆角就渲染成圆角方块而不是圆点，行高也被撑大、把文字挤到裁切。
    所以选中态**只能换颜色，不能改边框宽度**。
    """
    import re
    from app.ui import style

    for sel in ("QRadioButton::indicator:checked", "QCheckBox::indicator:checked"):
        m = re.search(re.escape(sel) + r"\s*\{([^}]*)\}", style.STYLESHEET)
        assert m, "样式表里找不到 %s" % sel
        body = m.group(1)
        assert "border:" not in body and "border-width" not in body, (
            "%s 改了边框宽度，指示器尺寸会跳变（圆点会变成圆角方块）：%s"
            % (sel, " ".join(body.split())))


def test_radio_and_checkbox_have_room_for_their_text(win, qapp):
    """回归（用户反馈：点「排版预览」时字体显示不全）。

    指示器是固定像素、文字却按字体高度走；行高只要被指示器定死，文字底部就会被裁。
    这里要求每个单复选控件的 sizeHint 明显高于字体高度。
    """
    from PySide6.QtGui import QFontMetrics

    widgets = [win.rb_photo, win.rb_layout, win.rb_auto, win.rb_manual,
               win.cb_hollow, win.cb_single, win.cb_layout]
    for w in widgets:
        fm = QFontMetrics(w.font())
        h = w.sizeHint().height()
        assert h >= fm.height() + 6, (
            "%s/%r 的高度 %d 对 %d 的文字来说太紧，会被裁切"
            % (w.__class__.__name__, w.text(), h, fm.height()))


def test_default_output_dir_is_not_the_temp_extraction_dir(qapp):
    """回归：默认输出目录曾经是 `<解压目录>\\输出`。

    打包成单文件后那就是 PyInstaller 的 `_MEIxxxx`，**退出时会被整个删掉**，
    用户导出的照片会跟着消失（用户截图里输出目录正是
    `...\\成品软件\\_MEI00038102\\输出`）。
    """
    from app.paths import app_dir
    from app.ui.main_window import MainWindow, default_out_dir

    d = default_out_dir()
    assert "_MEI" not in d, "默认输出目录落在单文件解压目录里了：%s" % d
    assert os.path.isabs(d), d
    # 用户明确要求"别往 C 盘写，都在工作区内"：默认导出目录应该在程序自己所在的目录下
    assert d.startswith(app_dir()), (
        "默认输出目录应该放在程序目录下（%s），实际是 %s" % (app_dir(), d))
    assert os.path.basename(d) == "输出", d

    # 用一个独立窗口验证（共享的 win fixture 会被导出测试改掉 _out_dir）
    w = MainWindow(SpecLibrary.load())
    try:
        assert w._out_dir == d, "窗口没有用 default_out_dir()：%s" % w._out_dir
    finally:
        w.close()


# ==================== 多布局 ====================

REQUIRED_WIDGETS = (
    "lst_specs", "lst_photos", "canvas", "sl_zoom", "sl_offset_x", "sl_offset_y",
    "sl_rotate", "sl_head", "sl_center", "cmb_paper", "sp_gap", "sp_margin",
    "cmb_crop_line", "cmb_dpi", "sp_kb", "cb_single", "cb_layout",
    "btn_export_single", "btn_export_layout", "btn_export_all", "lbl_out",
)


def test_all_layouts_build_and_keep_every_widget(qapp):
    """每套布局都要能装配出来，并且装配后关键控件一个不少。

    这套架构的卖点是"四套布局共用同一批面板构造函数，功能完全一样、只是摆法不同"。
    最容易的破法就是某套布局漏调了某个 _group_*()，于是那套布局里就少了对应功能，
    而界面上未必看得出来（比如"导出内容"勾选框没了）。
    """
    from app.ui import layouts

    w = MainWindow(SpecLibrary.load())
    try:
        assert len(layouts.entries()) >= 1, "布局注册表为空（打包时模块没被收集？）"
        for key, name in layouts.entries():
            w.set_layout(key)
            qapp.processEvents()
            assert w.layout_id == key, "%s 没切换成功" % key
            for attr in REQUIRED_WIDGETS:
                assert getattr(w, attr, None) is not None, (
                    "布局「%s」(%s) 缺少控件 %s —— 换布局把功能弄丢了" % (name, key, attr))
            assert w.lst_specs.count() >= 40, "布局「%s」的规格列表是空的" % name
        w.set_layout(layouts.DEFAULT_LAYOUT)
    finally:
        w.close()


def test_layout_switch_keeps_loaded_photos(win, qapp):
    """切布局后照片列表不能变空。

    换布局时左栏是新建的控件，条目不会自己跟过去；不重建就会出现
    "预览里有图、左边列表却是空的"这种自相矛盾状态（实现时真踩到过）。
    """
    from app.ui import layouts

    if not win.items:
        pytest.skip("这个 fixture 没有已导入的照片")
    before = len(win.items)
    others = [k for k in layouts.keys() if k != win.layout_id]
    if not others:
        pytest.skip("只有一个布局")
    try:
        win.set_layout(others[0])
        qapp.processEvents()
        assert win.lst_photos.count() == before, (
            "切到 %s 后照片列表条目从 %d 变成 %d" % (others[0], before,
                                                     win.lst_photos.count()))
    finally:
        win.set_layout(layouts.DEFAULT_LAYOUT)


def test_glass_panels_do_not_overlap_and_preview_is_largest(qapp):
    """玻璃卡片布局的结构约束（工作台那套不用玻璃卡，自动跳过）。

    要求：**预览必须是"最大的那块"** —— 要么它自己是一张最大的卡片（仪表盘），
    要么它是铺满整个舞台的背景层（画布优先）；并且任何两张卡片都不许重叠。
    """
    from PySide6.QtWidgets import QWidget
    from app.ui import layouts
    from app.ui.glass_panel import GlassPanel
    from app.ui.main_window import MainWindow

    tested = 0
    w = MainWindow(SpecLibrary.load())
    try:
        for key, name in layouts.entries():
            w.set_layout(key)
            qapp.processEvents()
            for size in ((1600, 1000), (1180, 760), (1080, 700)):
                w.resize(*size)
                w.show()
                qapp.processEvents()
                panels = w.findChildren(GlassPanel)
                if not panels:
                    continue            # 这套界面不用玻璃卡片
                tested += 1
                geos = [(p.lbl_title.text(), p.geometry()) for p in panels]
                for i in range(len(geos)):
                    for j in range(i + 1, len(geos)):
                        a, b = geos[i], geos[j]
                        assert not a[1].intersects(b[1]), (
                            "「%s」窗口 %dx%d：卡片「%s」和「%s」重叠了：%s vs %s"
                            % (name, size[0], size[1], a[0], b[0], a[1], b[1]))

                stage = getattr(w, "glass_stage", None)
                bg = getattr(stage, "background", None)
                if bg is not None:
                    assert bg.geometry() == stage.rect(), (
                        "「%s」%dx%d：作为背景的预览画布没有铺满舞台"
                        % (name, size[0], size[1]))
                else:
                    by_area = sorted(geos, key=lambda x: x[1].width() * x[1].height(),
                                     reverse=True)
                    top2 = {by_area[0][0], by_area[1][0]}
                    assert "预览" in top2, (
                        "「%s」：预览卡不是最大的两张之一，实际排序：%s"
                        % (name, [g[0] for g in by_area]))
        assert tested >= 1, "没有任何界面用到玻璃卡片，这条测试等于没跑"
    finally:
        w.close()


def test_window_surface_has_no_fully_transparent_pixels(qapp):
    """窗口表面不能出现 alpha=0 的像素。

    毛玻璃用的是**分层窗口**（WA_TranslucentBackground），而 Windows 对分层窗口的
    鼠标命中是**按像素 alpha 判定**的：alpha=0 的地方会被当成"这里没东西"，
    点击直接穿透到后面的窗口 —— 用户实测过"能透过软件界面点到后面的东西"。
    所以窗口底色那层"几乎看不见的白雾"是不能删的，这条测试守住它。
    """
    from app.ui.main_window import MainWindow

    w = MainWindow(SpecLibrary.load())
    try:
        w.resize(1200, 800)
        w.show()
        qapp.processEvents()
        img = w.grab().toImage()
        holes = []
        for y in range(0, img.height(), 13):
            for x in range(0, img.width(), 13):
                if img.pixelColor(x, y).alpha() == 0:
                    holes.append((x, y))
        assert not holes, (
            "窗口表面有 %d 个全透明采样点（例如 %s），点击会穿透到后面的窗口"
            % (len(holes), holes[:3]))
    finally:
        w.close()


def test_reset_layout_restores_default_positions(qapp):
    """玻璃卡片被拖乱之后必须能一键还原（用户反馈过"拉不回去了"）。

    只对用玻璃卡片的界面有意义；工作台那套是普通布局（拖不动），自动跳过。
    """
    from PySide6.QtCore import QRect
    from app.ui import layouts
    from app.ui.glass_panel import GlassPanel
    from app.ui.main_window import MainWindow

    tested = 0
    w = MainWindow(SpecLibrary.load())
    try:
        for key, name in layouts.entries():
            w.set_layout(key)
            w.resize(1500, 950)
            w.show()
            qapp.processEvents()
            panels = w.findChildren(GlassPanel)
            if not panels:
                continue
            tested += 1
            default = {p.lbl_title.text(): p.geometry()
                       for p in w.findChildren(GlassPanel)}

            moved = w.findChildren(GlassPanel)[0]
            moved.setGeometry(QRect(300, 250, 800, 600))
            moved.userChanged.emit()
            qapp.processEvents()
            assert ({p.lbl_title.text(): p.geometry()
                     for p in w.findChildren(GlassPanel)} != default), (
                "「%s」拖动之后布局居然没变，测试本身有问题" % name)

            w.reset_layout()
            qapp.processEvents()
            after = {p.lbl_title.text(): p.geometry()
                     for p in w.findChildren(GlassPanel)}
            for t, g in default.items():
                assert after[t] == g, (
                    "「%s」的「%s」没有回到默认位置：%s，期望 %s" % (name, t, after[t], g))
        assert tested >= 1, "没有任何界面用到玻璃卡片，这条测试等于没跑"
    finally:
        w.close()


def test_dragging_a_card_never_covers_others(qapp):
    """拖动/拉伸卡片之后，其它卡片必须让位（缩小或挪开），**绝不允许互相覆盖**。

    用户的原话是"拉动直接就把别的卡片覆盖住了……不应该别的卡片跟着放大或者缩小吗"。
    实现里做了三级兜底：逐个挪 → 重新打包剩余空间 → 把用户拖的那张收回来。
    这里用几个刁钻的拖动目标（含"拉大到占掉大半个窗口"）把它钉住。
    """
    from PySide6.QtCore import QRect
    from app.ui import layouts
    from app.ui.glass_panel import GlassPanel
    from app.ui.main_window import MainWindow

    tested = 0
    w = MainWindow(SpecLibrary.load())
    try:
        for key, name in layouts.entries():
            w.set_layout(key)
            w.resize(1500, 950)
            w.show()
            qapp.processEvents()
            panels = w.findChildren(GlassPanel)
            if not panels:
                continue            # 这套界面不用玻璃卡片
            tested += 1
            moved = panels[0]
            cases = [QRect(400, 200, 900, 700),      # 拖到中间并放大
                     QRect(60, 60, 700, 500),        # 左上占一大块
                     QRect(10, 10, 1450, 880),       # 几乎铺满（其余卡片几乎没地方站）
                     QRect(0, 600, 1490, 340),       # 横向长条压在底部
                     QRect(20, 20, 300, 180)]        # 缩到很小
            for r in cases:
                moved.setGeometry(r)
                moved.userChanged.emit()
                qapp.processEvents()
                geos = [(p.lbl_title.text(), p.geometry())
                        for p in w.findChildren(GlassPanel)]
                for i in range(len(geos)):
                    for j in range(i + 1, len(geos)):
                        assert not geos[i][1].intersects(geos[j][1]), (
                            "「%s」拖到 %s 之后，「%s」和「%s」重叠了：%s vs %s"
                            % (name, r, geos[i][0], geos[j][0],
                               geos[i][1], geos[j][1]))
        assert tested >= 1, "没有任何界面用到玻璃卡片，这条测试等于没跑"
    finally:
        w.close()
