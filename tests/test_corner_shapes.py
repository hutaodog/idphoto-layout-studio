"""Larger continuous surfaces, true capsules, and compositor-aware window modes."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QProgressBar, QScrollBar, QSlider, QStyle, QStyleOptionSlider

from app.ui import chrome, style
from app.ui.corners import capsule_path, continuous_path
from app.ui.segmented import SegmentedControl
from app.ui.widgets import PillButton


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


def render(widget):
    image = QImage(widget.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    widget.render(image)
    return image


@pytest.mark.parametrize("rect", [QRectF(0, 0, 180, 34), QRectF(0, 0, 12, 90)])
def test_capsule_has_semicircles_instead_of_squircle_ends(rect):
    path = capsule_path(rect)
    radius = min(rect.width(), rect.height()) / 2
    corner = QPointF(radius * .25, radius * .25)
    assert path.boundingRect() == rect
    assert path.contains(rect.center())
    assert not path.contains(corner)
    assert continuous_path(rect, radius).contains(corner)
    assert capsule_path(QRectF()).isEmpty()


def test_export_button_keeps_true_capsule_pixels(app):
    button = PillButton("Export")
    button.resize(180, 34)
    image = render(button)
    assert image.pixelColor(4, 4).alpha() == 0
    assert image.pixelColor(12, 12).alpha() > 200
    assert image.pixelColor(80, 8).alpha() > 200
    button.close()


def test_segmented_shell_and_selected_thumb_are_capsules(app):
    control = SegmentedControl(["Photo", "Layout"])
    control.setStyleSheet("background:transparent;")
    image = render(control)
    assert image.pixelColor(4, 4).alpha() == 0
    assert image.pixelColor(7, 7).name() == "#eceef2"
    assert image.pixelColor(control.width() // 4, 10).name() == style.CARD
    control.close()


def test_theme_uses_larger_continuous_corners_without_enlarging_boxes():
    from app.ui.section_card import RADIUS
    assert (style.RADIUS, style.PANEL_RADIUS, style.DIALOG_RADIUS) == (12, 20, 26)
    assert RADIUS == style.PANEL_RADIUS
    rect = QRectF(0, 0, 180, 100)
    assert continuous_path(rect, 12).contains(QPointF(3, 3))
    assert not continuous_path(rect, style.PANEL_RADIUS).contains(QPointF(3, 3))
    assert continuous_path(rect, style.PANEL_RADIUS).boundingRect() == rect


def expected_capsule(size, rect):
    image = QImage(size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("white"))
    painter.drawPath(capsule_path(QRectF(rect)))
    painter.end()
    return image


@pytest.mark.parametrize("orientation", [Qt.Horizontal, Qt.Vertical])
def test_scrollbar_thumb_keeps_half_circle_ends(app, orientation):
    style.install_continuous_style(app)
    bar = QScrollBar(orientation)
    bar.setAttribute(Qt.WA_TranslucentBackground)
    bar.setStyleSheet(style.STYLESHEET)
    bar.resize(220, 9) if orientation == Qt.Horizontal else bar.resize(9, 220)
    bar.setRange(0, 100)
    bar.setPageStep(40)
    bar.setValue(50)
    bar.ensurePolished()
    option = QStyleOptionSlider()
    bar.initStyleOption(option)
    rect = bar.style().subControlRect(QStyle.CC_ScrollBar, option,
                                     QStyle.SC_ScrollBarSlider, bar)
    image = render(bar)
    expected = expected_capsule(bar.size(), rect)
    assert image.size() == bar.size()
    for y in range(bar.height()):
        for x in range(bar.width()):
            assert abs(image.pixelColor(x, y).alpha() -
                       expected.pixelColor(x, y).alpha()) <= 1
    assert bar.value() == 50 and bar.pageStep() == 40
    bar.close()


def test_slider_track_is_a_capsule_and_thumb_remains_a_circle(app):
    style.install_continuous_style(app)
    slider = QSlider(Qt.Horizontal)
    slider.setAttribute(Qt.WA_TranslucentBackground)
    slider.setStyleSheet(style.STYLESHEET)
    slider.resize(240, 28)
    slider.setRange(0, 100)
    slider.setValue(0)
    slider.ensurePolished()
    option = QStyleOptionSlider()
    slider.initStyleOption(option)
    track = slider.style().subControlRect(QStyle.CC_Slider, option,
                                         QStyle.SC_SliderGroove, slider)
    expected = expected_capsule(slider.size(), track)
    image = render(slider)
    # The right end is unobstructed by the circular thumb at the minimum value.
    for y in range(track.top(), track.bottom() + 1):
        for x in range(track.right() - track.height() * 2, track.right() + 1):
            assert abs(image.pixelColor(x, y).alpha() -
                       expected.pixelColor(x, y).alpha()) <= 1
    assert slider.value() == 0
    slider.close()


@pytest.mark.parametrize("orientation", [Qt.Horizontal, Qt.Vertical])
def test_standard_progress_track_and_fill_keep_capsule_ends(app, orientation):
    style.install_continuous_style(app)
    bar = QProgressBar()
    bar.setAttribute(Qt.WA_TranslucentBackground)
    bar.setStyleSheet(style.STYLESHEET)
    bar.setTextVisible(False)
    bar.setOrientation(orientation)
    bar.resize(200, 20) if orientation == Qt.Horizontal else bar.resize(20, 200)
    bar.setValue(0)
    bar.ensurePolished()
    track = render(bar)
    expected = expected_capsule(bar.size(), bar.rect())
    bar.setValue(50)
    image = render(bar)
    for y in range(bar.height()):
        for x in range(bar.width()):
            alpha = expected.pixelColor(x, y).alpha()
            assert abs(track.pixelColor(x, y).alpha() - alpha) <= 1
            if alpha == 0:
                assert image.pixelColor(x, y).alpha() == 0
    if orientation == Qt.Horizontal:
        assert image.pixelColor(50, 10).name() == style.PRIMARY
        assert image.pixelColor(150, 10).name() == "#e9ecf1"
        assert image.pixelColor(95, 0).name() == "#e9ecf1"
        assert image.pixelColor(95, 10).name() == style.PRIMARY
    else:
        assert image.pixelColor(10, 150).name() == style.PRIMARY
        assert image.pixelColor(10, 50).name() == "#e9ecf1"
        assert image.pixelColor(0, 104).name() == "#e9ecf1"
        assert image.pixelColor(10, 104).name() == style.PRIMARY
    bar.close()


def test_task_progress_track_fill_and_busy_band_are_capsules(app):
    from app.ui.task_window import ProgressBar
    bar = ProgressBar()
    bar.setAttribute(Qt.WA_TranslucentBackground)
    bar.resize(240, 8)
    expected = expected_capsule(bar.size(), bar.rect())
    bar.set_value(0)
    track = render(bar)
    bar.set_value(.5)
    image = render(bar)
    assert image.pixelColor(119, 0).name() != style.PRIMARY
    assert image.pixelColor(60, 4).name() == style.PRIMARY
    assert image.pixelColor(180, 4).name() == style.BORDER
    bar.set_indeterminate(True)
    bar.tick(.25)  # Midway across the new smooth outward/return cycle.
    busy = render(bar)
    for y in range(bar.height()):
        for x in range(bar.width()):
            alpha = expected.pixelColor(x, y).alpha()
            assert abs(track.pixelColor(x, y).alpha() - alpha) <= 1
            if alpha == 0:
                assert image.pixelColor(x, y).alpha() == 0
                assert busy.pixelColor(x, y).alpha() == 0
    assert busy.pixelColor(120, 4).name() == style.PRIMARY
    assert busy.pixelColor(10, 4).name() == style.BORDER
    assert busy.pixelColor(84, 0).name() == style.BORDER
    assert busy.pixelColor(85, 4).name() == style.PRIMARY
    assert bar.size() == image.size()
    bar.close()


@pytest.mark.parametrize("compositor_ok, maximized, expected", [
    (True, False, "dwm"), (False, False, "continuous"), (True, True, "maximized")])
def test_sca_window_never_relies_on_an_ineffective_region(
        app, monkeypatch, tmp_path, compositor_ok, maximized, expected):
    from app.core import settings
    from app.ui import acrylic
    from app.ui.main_window import MainWindow
    monkeypatch.setenv("IDPHOTO_NO_UPDATE", "1")
    monkeypatch.setattr(settings, "settings_path", lambda: str(tmp_path / "settings.json"))
    calls = []
    monkeypatch.setattr(acrylic, "clear_round_region", lambda hwnd: calls.append("clear-native"))
    monkeypatch.setattr(acrylic, "set_round_corners",
                        lambda hwnd: calls.append("dwm") or compositor_ok)
    monkeypatch.setattr(acrylic, "disable_system_round_corners", lambda hwnd: calls.append("no-dwm"))
    monkeypatch.setattr(acrylic, "disable_glass", lambda hwnd: calls.append("disable-sca"))
    window = MainWindow()
    try:
        window.glass_mode = "sca-acrylic"
        monkeypatch.setattr(window, "isMaximized", lambda: maximized)
        window._apply_round_region()
        assert window._round_mode == expected
        assert window.centralWidget().outline_mode == expected
        assert calls[0] == "clear-native"
        if expected == "dwm":
            assert window.mask().isEmpty()
            assert calls == ["clear-native", "dwm"]
        elif expected == "continuous":
            assert calls == ["clear-native", "dwm", "disable-sca", "no-dwm"]
            assert window.glass_mode == "none"
            assert not window.mask().contains(window.rect().topLeft())
            assert window.mask().contains(window.rect().center())
            assert chrome.WINDOW_RADIUS == 32
        else:
            assert calls == ["clear-native"]
            assert window.mask().isEmpty()
    finally:
        window.close()
        app.processEvents()
