"""Geometry and real Qt paint regressions for continuous-curvature corners."""
import math
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QLineEdit, QProgressBar, QPushButton,
    QSlider, QSpinBox, QVBoxLayout, QWidget, QListWidget, QMenu,
    QTextBrowser, QLabel,
)

from app.ui.corners import (apply_declared_surface, apply_surface, continuous_path,
                            continuous_region)
from app.ui import style


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


def _point(element):
    return QPointF(element.x, element.y)


def _cross(a, b):
    return a.x() * b.y() - a.y() * b.x()


def _derivatives(points, t):
    a, b, c, d = points
    first = 3 * ((1-t)**2 * (b-a) + 2*(1-t)*t*(c-b) + t*t*(d-c))
    second = 6 * ((1-t)*(c-2*b+a) + t*(d-2*c+b))
    return first, second


def _curvature(points, t):
    first, second = _derivatives(points, t)
    return abs(_cross(first, second)) / math.hypot(first.x(), first.y())**3


def _cubics(path):
    curves = []
    point = None
    i = 0
    while i < path.elementCount():
        element = path.elementAt(i)
        if element.type == QPainterPath.CurveToElement:
            curves.append((point, _point(element), _point(path.elementAt(i+1)),
                           _point(path.elementAt(i+2))))
            point = curves[-1][-1]
            i += 3
        else:
            point = _point(element)
            i += 1
    return curves


def test_geometry_clamps_radius_and_keeps_original_bounds():
    rect = QRectF(13, 29, 120, 46)
    path = continuous_path(rect, 8)
    assert path.boundingRect() == rect
    assert path.elementAt(0).x == 21
    assert path.elementAt(1).x == 125
    assert path.contains(rect.center())
    assert not path.contains(rect.topLeft())
    assert continuous_path(rect, 1000) == continuous_path(rect, 23)
    assert continuous_path(rect, -1).boundingRect() == rect
    assert continuous_path(QRectF(), 8).isEmpty()
    assert continuous_path(QRectF(0, 0, -2, 3), 8).isEmpty()
    assert continuous_path(rect, float("nan")).boundingRect() == rect


def test_all_edge_joins_have_zero_curvature_and_midpoints_are_c2():
    curves = _cubics(continuous_path(QRectF(0, 0, 173, 61), 14))
    assert len(curves) == 8
    for a, b in zip(curves[::2], curves[1::2]):
        assert _curvature(a, 0) == pytest.approx(0, abs=1e-12)
        assert _curvature(b, 1) == pytest.approx(0, abs=1e-12)
        assert _curvature(a, .001) < _curvature(a, .01) < _curvature(a, .1)
        ad, add = _derivatives(a, 1)
        bd, bdd = _derivatives(b, 0)
        assert ad.x() == pytest.approx(bd.x())
        assert ad.y() == pytest.approx(bd.y())
        assert add.x() == pytest.approx(bdd.x())
        assert add.y() == pytest.approx(bdd.y())
        assert _curvature(a, 1) == pytest.approx(_curvature(b, 0))


def _image(widget):
    image = QImage(widget.size(), QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    widget.render(image)
    return image


def _rgb(image, x, y):
    return image.pixelColor(x, y).name()


def test_surface_native_button_has_transparent_corners_and_keeps_text(app):
    button = QPushButton("VISIBLE")
    button.setAttribute(Qt.WA_TranslucentBackground)
    button.setStyleSheet("QPushButton{background:#e13122;border:1px solid #cc1111;"
                        "border-radius:16px;padding:7px 14px;color:#102030;font-size:13px;}")
    button.resize(130, 42)
    button.ensurePolished()
    before = button.sizeHint(), button.font().toString(), button.contentsRect()
    surface = apply_surface(button, "#e13122", "#cc1111", 16)
    after = button.sizeHint(), button.font().toString(), button.contentsRect()
    assert before == after
    image = _image(button)
    assert image.pixelColor(0, 0).alpha() == 0
    assert _rgb(image, 65, 6) == "#e13122"
    # The continuous curve fills an area that the old circular arc leaves out.
    assert image.pixelColor(4, 4).alpha() > 220
    assert any(image.pixelColor(x, y).red() < 80
               for y in range(12, 31) for x in range(28, 103))
    previous_css = button.styleSheet()
    assert apply_surface(button, "#e13122", "#cc1111", 16) is surface
    assert button.styleSheet() == previous_css
    button.deleteLater()


def test_surface_state_changes_never_rewrite_qss_or_layout(app):
    button = QPushButton("State")
    button.setStyleSheet(style.STYLESHEET)
    button.resize(130, 42)
    surface = apply_surface(button, "#ffffff", "#d8dbe3", 8,
                            states={"hover": {"fill": "#f7f9fc"},
                                    "pressed": {"fill": "#eef1f6"},
                                    "disabled": {"fill": "#f7f8fa"},
                                    "focus": {"border": style.PRIMARY}})
    button.ensurePolished()
    snapshot = button.styleSheet(), button.sizeHint(), button.font().toString(), button.contentsRect()
    surface.hovered = True
    assert _rgb(_image(button), 65, 5) == "#f7f9fc"
    button.setDown(True)
    assert _rgb(_image(button), 65, 5) == "#eef1f6"
    button.setEnabled(False)
    assert _rgb(_image(button), 65, 5) == "#f7f8fa"
    assert snapshot == (button.styleSheet(), button.sizeHint(), button.font().toString(), button.contentsRect())
    button.deleteLater()


def test_standard_controls_install_once_and_preserve_metrics(app):
    host = QWidget()
    host.setStyleSheet(style.STYLESHEET)
    layout = QVBoxLayout(host)
    controls = [QPushButton("ordinary"), QLineEdit("input"), QComboBox(), QSpinBox(),
                QCheckBox("checked"), QSlider(Qt.Horizontal), QProgressBar()]
    controls[2].addItems(["one", "two"])
    controls[4].setChecked(True)
    controls[-1].setValue(60)
    for control in controls:
        layout.addWidget(control)
    host.ensurePolished()
    host.resize(320, 370)
    layout.activate()
    baseline = [(c.sizeHint(), c.minimumSizeHint(), c.font().toString()) for c in controls]
    install = style.install_continuous_style(app)
    assert style.install_continuous_style(app) is install
    layout.activate()
    assert baseline == [(c.sizeHint(), c.minimumSizeHint(), c.font().toString()) for c in controls]
    host.show()
    app.processEvents()
    image = _image(host)
    assert not image.isNull()
    assert all(getattr(c, "_continuous_configured", False) for c in controls)
    inputs = controls[1:4]
    for control in inputs:
        control.setFocus()
        app.processEvents()
        assert control._continuous_surface.values()["border"] == style.PRIMARY
        controls[0].setFocus()
        app.processEvents()
        assert control._continuous_surface.values()["border"] != style.PRIMARY
        control.setEnabled(False)
        assert control._continuous_surface.values()["fill"] == "#f7f8fa"
        control.setEnabled(True)
    host.close()
    host.deleteLater()
    app.processEvents()


def test_binary_fallback_comes_from_same_geometry():
    rect = QRectF(0, 0, 120, 70)
    region = continuous_region(rect, 16)
    path = continuous_path(rect, 16)
    assert not region.contains(QPoint(0, 0))
    assert region.contains(QPoint(60, 0))
    assert region.contains(QPoint(4, 4))
    for x, y in ((1, 1), (5, 6), (60, 30), (118, 68)):
        assert region.contains(QPoint(x, y)) == path.contains(QPointF(x+.1, y+.1))


def test_local_qss_surfaces_update_dynamic_colors_without_changing_box(app):
    style.install_continuous_style(app)
    label = QLabel("Information")
    label.setAttribute(Qt.WA_TranslucentBackground)
    label.setStyleSheet("color:#2f6fd0;background:#eaf1fd;border-radius:8px;"
                        "padding:9px 11px;font-size:12px;font-weight:600;")
    label.resize(170, 44)
    label.ensurePolished()
    surface = label._continuous_surface
    assert surface._declared
    baseline = label.sizeHint(), label.minimumSizeHint(), label.contentsRect(), label.font().toString()
    assert _image(label).pixelColor(0, 0).alpha() == 0
    assert _rgb(_image(label), 85, 4) == style.PRIMARY_SOFT
    label.setStyleSheet("color:#c8860a;background:#fdf5e6;border-radius:8px;"
                        "padding:9px 11px;font-size:12px;font-weight:600;")
    assert label._continuous_surface is surface
    # QSS repolish must complete before the deferred transparency overlay.
    app.processEvents()
    app.processEvents()
    assert _rgb(_image(label), 85, 4) == "#fdf5e6"
    assert baseline == (label.sizeHint(), label.minimumSizeHint(), label.contentsRect(), label.font().toString())
    label.deleteLater()
    dot = QLabel()
    dot.setFixedSize(10, 10)
    dot.setStyleSheet("background:#2f6fd0;border-radius:5px;")
    dot.ensurePolished()
    assert apply_declared_surface(dot) is None
    assert getattr(dot, "_continuous_surface", None) is None
    dot.deleteLater()


def test_menu_and_list_selection_backgrounds_survive_native_content(app):
    style.install_continuous_style(app)
    menu = QMenu()
    menu.setStyleSheet(style.STYLESHEET)
    first = menu.addAction("Selected text")
    menu.addAction("Second item")
    menu.ensurePolished()
    menu.resize(menu.sizeHint())
    menu.setActiveAction(first)
    image = _image(menu)
    rect = menu.actionGeometry(first)
    assert image.pixelColor(0, 0).alpha() == 0
    assert _rgb(image, rect.right() - 12, rect.center().y()) == style.PRIMARY_SOFT
    assert any(_rgb(image, x, y) == style.PRIMARY for y in range(rect.top(), rect.bottom())
               for x in range(rect.left(), rect.right()))
    menu.deleteLater()
    items = QListWidget()
    items.setStyleSheet(style.STYLESHEET)
    items.addItems(["Selected row", "Other row"])
    items.resize(240, 130)
    items.show()
    items.setCurrentRow(0)
    app.processEvents()
    image = _image(items.viewport())
    rect = items.visualItemRect(items.item(0))
    assert _rgb(image, rect.right() - 10, rect.center().y()) == style.PRIMARY_SOFT
    assert _rgb(image, rect.left() + 1, rect.top() + 1) != style.PRIMARY_SOFT
    assert any(_rgb(image, x, y) == style.PRIMARY for y in range(rect.top(), rect.bottom())
               for x in range(rect.left(), min(rect.right(), 160)))
    items.close()
    items.deleteLater()
    app.processEvents()


def test_declared_scroll_surface_keeps_transparent_corner_and_text(app):
    style.install_continuous_style(app)
    browser = QTextBrowser()
    browser.setAttribute(Qt.WA_TranslucentBackground)
    browser.setStyleSheet("QTextBrowser{background:#fafbfc;border:1px solid #e7e9ee;"
                          "border-radius:8px;padding:9px;color:#223344;}")
    browser.setPlainText("Native text remains visible")
    browser.resize(260, 110)
    browser.ensurePolished()
    image = _image(browser)
    assert image.pixelColor(0, 0).alpha() == 0
    assert _rgb(image, 130, 4) == "#fafbfc"
    assert any(image.pixelColor(x, y).red() < 100 and image.pixelColor(x, y).alpha() > 200
               for y in range(10, 60) for x in range(10, 230))
    browser.deleteLater()


def test_preview_opaque_photo_is_clipped_to_continuous_viewport(app):
    from app.ui.preview import PreviewCanvas
    preview = PreviewCanvas()
    preview.setAttribute(Qt.WA_TranslucentBackground)
    preview.resize(400, 360)
    photo = QImage(440, 280, QImage.Format_RGB32)
    photo.fill(QColor("#d93220"))
    preview.set_pixmap(QPixmap.fromImage(photo))
    preview.zoom_view(4)
    image = _image(preview)
    assert image.pixelColor(0, 0).alpha() == 0
    assert _rgb(image, 200, 180) == "#d93220"
    assert image.pixelColor(3, 3).alpha() > 180
    preview.deleteLater()


def test_window_caps_round_only_their_outer_corners(app):
    for corners, transparent_row, filled_row in (
            (("top-left", "top-right"), 0, 43),
            (("bottom-left", "bottom-right"), 43, 0)):
        cap = QWidget()
        cap.setAttribute(Qt.WA_TranslucentBackground)
        cap.resize(160, 44)
        apply_surface(cap, "#ffffff", None, 12, border_width=0, corners=corners)
        image = _image(cap)
        assert image.pixelColor(0, transparent_row).alpha() == 0
        assert image.pixelColor(159, transparent_row).alpha() == 0
        assert image.pixelColor(0, filled_row).alpha() == 255
        assert image.pixelColor(159, filled_row).alpha() == 255
        cap.deleteLater()


def test_local_surface_can_be_declared_after_widget_is_shown(app):
    style.install_continuous_style(app)
    label = QLabel("Later")
    label.setAttribute(Qt.WA_TranslucentBackground)
    label.resize(160, 44)
    label.show()
    app.processEvents()
    assert getattr(label, "_continuous_surface", None) is None
    label.setStyleSheet("background:#eaf1fd;border-radius:8px;padding:9px 11px;")
    app.processEvents()
    app.processEvents()
    image = _image(label)
    assert image.pixelColor(0, 0).alpha() == 0
    assert _rgb(image, 80, 4) == style.PRIMARY_SOFT
    label.close()
    label.deleteLater()
    app.processEvents()
