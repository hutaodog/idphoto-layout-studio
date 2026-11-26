# -*- coding: utf-8 -*-
"""Continuous-curvature corners shared by painting, clipping and window regions.

Each quarter uses two cubic Beziers.  The first three control points at a
straight edge are collinear, so the normal second derivative (and curvature)
is exactly zero there.  The two cubics have matching first *and* second
derivatives at their midpoint.  This is a G2 edge join, not a circular arc or
an enlarged QSS border-radius.  ``radius`` is the original edge-to-tangent
distance, clamped to half the smaller dimension.
"""
from __future__ import annotations

import math
import re
from typing import Callable, Mapping

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QRegion
from PySide6.QtWidgets import QWidget

_CORNERS = ("top-left", "top-right", "bottom-right", "bottom-left")


def _path(rect: QRectF, radius: float, corners=None) -> QPainterPath:
    path = QPainterPath()
    r = QRectF(rect)
    if r.isEmpty() or not all(math.isfinite(v) for v in
                             (r.x(), r.y(), r.width(), r.height())):
        return path
    radius = float(radius)
    if not math.isfinite(radius):
        radius = 0.0
    radius = max(0.0, min(radius, r.width() / 2.0, r.height() / 2.0))
    enabled = set(_CORNERS if corners is None else corners)
    radii = [radius if name in enabled else 0.0 for name in _CORNERS]
    tl, tr, br, bl = radii
    l, t, right, bottom = r.left(), r.top(), r.right(), r.bottom()
    path.moveTo(l + tl, t)
    path.lineTo(right - tr, t)

    def turn(x: float, y: float, ux: float, uy: float,
             vx: float, vy: float, amount: float) -> None:
        # A=(0,0), B=(.2,0), C=(.6,0), D=(.8,.2);
        # E=(1,.4), F=(1,.8), G=(1,1).  At D: A'(1)=B'(0),
        # A''(1)=B''(0). At A/G: cross(P',P'')=0.
        if amount <= 0.0:
            return
        def point(a, b):
            return (x + amount * (a * ux + b * vx),
                    y + amount * (a * uy + b * vy))
        path.cubicTo(*point(.2, 0), *point(.6, 0), *point(.8, .2))
        path.cubicTo(*point(1, .4), *point(1, .8), *point(1, 1))

    turn(right - tr, t, 1, 0, 0, 1, tr)
    path.lineTo(right, bottom - br)
    turn(right, bottom - br, 0, 1, -1, 0, br)
    path.lineTo(l + bl, bottom)
    turn(l + bl, bottom, -1, 0, 0, -1, bl)
    path.lineTo(l, t + tl)
    turn(l, t + tl, 0, -1, 1, 0, tl)
    path.closeSubpath()
    return path


def continuous_path(rect: QRectF, radius: float) -> QPainterPath:
    """Return a closed path with zero corner curvature at each straight edge."""
    return _path(rect, radius)


def capsule_path(rect: QRectF) -> QPainterPath:
    """Return a true stadium: straight sides joined by semicircular ends."""
    path = QPainterPath()
    r = QRectF(rect)
    if r.isEmpty() or not all(math.isfinite(v) for v in
                             (r.x(), r.y(), r.width(), r.height())):
        return path
    radius = min(r.width(), r.height()) / 2.0
    path.addRoundedRect(r, radius, radius)
    return path


def continuous_region(rect: QRectF, radius: float) -> QRegion:
    """Binary fallback mask derived from the same path as antialiased painting."""
    return QRegion(continuous_path(rect, radius).toFillPolygon().toPolygon())


def draw_surface(painter: QPainter, rect: QRectF, fill, border, radius: float,
                 border_width: float = 1.0, corners=None, *, capsule=False) -> None:
    """Paint a continuous corner or explicit capsule without changing box metrics."""
    width = max(0.0, float(border_width))
    inset = width / 2.0
    inner = QRectF(rect).adjusted(inset, inset, -inset, -inset)
    path = (capsule_path(inner) if capsule else
            _path(inner, max(0.0, radius - inset), corners))
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(QBrush(fill) if isinstance(fill, (QBrush, QColor))
                     else QBrush(QColor(fill or "transparent")))
    if width > 0.0 and border:
        pen = QPen(QColor(border), width)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
    else:
        painter.setPen(Qt.NoPen)
    painter.drawPath(path)
    painter.restore()


def _resolve(value, widget):
    return value(widget) if callable(value) else value


def _css_color(value):
    """Read this theme's solid CSS colors, including rgba's fractional alpha."""
    if not value:
        return None
    value = value.strip()
    rgba = re.fullmatch(r"rgba?\(([^)]+)\)", value, re.I)
    if rgba:
        pieces = [part.strip() for part in rgba.group(1).split(",")]
        if len(pieces) not in (3, 4):
            return None
        try:
            channels = [float(part[:-1]) * 2.55 if part.endswith("%") else float(part)
                        for part in pieces[:3]]
            alpha = pieces[3] if len(pieces) == 4 else "1"
            opacity = float(alpha[:-1]) / 100 if alpha.endswith("%") else float(alpha)
            if opacity > 1 and not alpha.endswith("%"):
                opacity /= 255
            color = QColor(*(max(0, min(255, round(part))) for part in channels),
                           max(0, min(255, round(opacity * 255))))
        except ValueError:
            return None
    else:
        color = QColor(value)
    return color if color.isValid() else None


def _declared_surface_values(widget, source, *, require_radius=True):
    # Only local solid declarations for the widget itself.  Descendant rules,
    # pseudo controls/states, gradients and inherited application QSS are not
    # guessed; their explicit painters remain the authority.
    rules = re.findall(r"([^{}]+)\{([^{}]*)\}", source)
    bodies = []
    if not rules:
        bodies.append(source)
    for selectors, body in rules:
        for selector in selectors.split(","):
            match = re.fullmatch(r"\s*([A-Za-z_]\w*)?(?:#([\w-]+))?\s*", selector)
            if match and (match.group(1) or match.group(2)):
                kind, name = match.groups()
                if (not kind or widget.inherits(kind)) and (not name or widget.objectName() == name):
                    bodies.append(body)
                    break
    declarations = {}
    for body in bodies:
        for key, value in re.findall(r"([\w-]+)\s*:\s*([^;]+)", body):
            declarations[key.lower()] = value.strip()
    raw_radius = declarations.get("border-radius", "")
    match = re.fullmatch(r"([\d.]+)(?:px)?", raw_radius)
    if require_radius and not match:
        return None
    radius = float(match.group(1)) if match else 0.0
    if (widget.minimumSize() == widget.maximumSize() and widget.width() == widget.height()
            and radius >= widget.width() / 2 and widget.width() > 0):
        return None  # Fixed circular status dots intentionally stay circles.
    fill = _css_color(declarations.get("background-color", declarations.get("background")))
    if require_radius and fill is None:
        return None
    border = _css_color(declarations.get("border-color"))
    raw_width = re.fullmatch(r"([\d.]+)(?:px)?", declarations.get("border-width", "0"))
    width = float(raw_width.group(1)) if raw_width else 0.0
    shorthand = declarations.get("border", "")
    match = re.fullmatch(r"([\d.]+)px\s+solid\s+(.+)", shorthand)
    if match:
        width = float(match.group(1))
        border = _css_color(match.group(2))
    if shorthand in ("none", "0", "0px"):
        width = 0.0
    return dict(fill=fill or QColor("transparent"), border=border,
                radius=radius, border_width=width)


class SurfacePainter(QObject):
    """A persistent underlay; native paint events still draw text/icons/carets.

    No stylesheet is changed by hover, focus, checked or pressed transitions.
    ``states`` maps state names to overrides for fill/border/border_width.
    Values (including the base ones) may be callable(widget).  Priority is
    checked < hover < focus < pressed < disabled, matching this application's
    theme.  ``rect`` may be a QRectF or callable(widget) returning one.
    """

    def __init__(self, widget: QWidget):
        super().__init__(widget)
        self.widget = widget
        # Publish before changing QSS: polish/style events can reenter the
        # application filter while this underlay is still being constructed.
        widget._continuous_surface = self
        self.hovered = widget.underMouse()
        self.original_stylesheet = widget.styleSheet()
        self._applying = False
        self._style_refresh = QTimer(self)
        self._style_refresh.setSingleShot(True)
        self._style_refresh.timeout.connect(self._refresh_stylesheet)
        widget.installEventFilter(self)
        widget.setAttribute(Qt.WA_Hover, True)
        widget.setProperty("_continuousSurface", True)
        self._transparent_stylesheet()

    def _transparent_stylesheet(self):
        # Only this widget is affected: descendants such as spinbox arrows,
        # checkbox indicators, label text and the palette retain native QSS.
        name = self.widget.objectName()
        ident = "#" + name if name and re.fullmatch(r"[\w-]+", name) else ""
        selector = "QWidget" + ident + '[_continuousSurface="true"]' * 3
        self._applying = True
        self.widget.setStyleSheet(self.original_stylesheet +
                                 "\n" + selector + "{background:transparent;"
                                 "background-color:transparent;border-color:transparent;}")
        self._applying = False

    def _refresh_stylesheet(self):
        # setStyleSheet inside StyleChange can invalidate a QStyle still in
        # use by Qt. Reapply after the original event has completely returned.
        current = self.widget.styleSheet()
        if '_continuousSurface="true"' in current:
            return
        self.original_stylesheet = current
        if getattr(self, "_declared", False):
            values = _declared_surface_values(self.widget, current, require_radius=False)
            values = values or dict(fill="transparent", border=None, radius=0, border_width=0)
            self.configure(**values, states=None, rect=None, corners=None, edges=None)
        self._transparent_stylesheet()

    def configure(self, fill, border, radius, border_width, states, rect, corners, edges):
        self.fill, self.border, self.radius = fill, border, float(radius)
        self.border_width = border_width
        self.states = states or {}
        self.rect = rect
        self.corners = corners
        self.edges = edges or {}
        self.widget.update()
        return self

    def values(self):
        w = self.widget
        values = dict(fill=self.fill, border=self.border, border_width=self.border_width)
        tests = (("checked", bool(getattr(w, "isChecked", lambda: False)())),
                 ("hover", self.hovered), ("focus", w.hasFocus()),
                 ("pressed", bool(getattr(w, "isDown", lambda: False)())),
                 ("disabled", not w.isEnabled()))
        for state, active in tests:
            if active:
                values.update(self.states.get(state, {}))
        return {key: _resolve(value, w) for key, value in values.items()}

    def paint(self):
        values = self.values()
        rect = _resolve(self.rect, self.widget) if self.rect is not None else self.widget.rect()
        p = QPainter(self.widget)
        draw_surface(p, QRectF(rect), values["fill"], values["border"], self.radius,
                     values["border_width"], self.corners)
        r = QRectF(rect)
        for edge, color in self.edges.items():
            p.setPen(QPen(QColor(color), 1))
            if edge == "top":
                p.drawLine(r.topLeft() + QPointF(0, .5), r.topRight() + QPointF(0, .5))
            elif edge == "bottom":
                p.drawLine(r.bottomLeft() - QPointF(0, .5), r.bottomRight() - QPointF(0, .5))
        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            overlay(p, self.widget)
        p.end()

    def eventFilter(self, watched, event):  # noqa: N802
        kind = event.type()
        if kind == QEvent.Paint and hasattr(self, "fill"):
            self.paint()
        elif kind in (QEvent.Enter, QEvent.HoverEnter):
            self.hovered = True
            watched.update()
        elif kind in (QEvent.Leave, QEvent.HoverLeave):
            self.hovered = False
            watched.update()
        elif kind in (QEvent.FocusIn, QEvent.FocusOut, QEvent.EnabledChange,
                      QEvent.MouseButtonPress, QEvent.MouseButtonRelease,
                      QEvent.KeyPress, QEvent.KeyRelease):
            watched.update()
        elif kind == QEvent.StyleChange and not self._applying:
            self._style_refresh.start(0)
        return False


def apply_surface(widget: QWidget, fill, border, radius: float, *,
                  border_width: float = 1.0, states: Mapping | None = None,
                  rect: QRectF | Callable | None = None, corners=None, edges=None) -> SurfacePainter:
    """Install/update a continuous background while native content paints normally.

    Keep the existing QSS border widths, padding and font rules.  This adds a
    single local rule making *only* the background and border colors transparent.
    For a partial window cap use ``corners=("top-left", "top-right")``.
    Repeated calls update the persistent painter and do not repolish the widget.
    """
    surface = getattr(widget, "_continuous_surface", None)
    if surface is None:
        surface = SurfacePainter(widget)
        widget._continuous_surface = surface
    surface._declared = False
    return surface.configure(fill, border, radius, border_width, states, rect, corners, edges)


def apply_declared_surface(widget: QWidget) -> SurfacePainter | None:
    """Convert a widget's local solid QSS background/radius into real curves.

    Existing explicit ``apply_surface`` painters take priority.  The original
    QSS still controls text and box metrics; later caller ``setStyleSheet``
    changes update the declared fill/border/radius in the same persistent
    painter, including dynamic information and warning label palettes.
    """
    surface = getattr(widget, "_continuous_surface", None)
    if surface is not None and not getattr(surface, "_declared", False):
        return surface
    source = surface.original_stylesheet if surface is not None else widget.styleSheet()
    values = _declared_surface_values(widget, source)
    if values is None:
        return None
    surface = apply_surface(widget, **values)
    surface._declared = True
    return surface


def remove_surface(widget: QWidget) -> None:
    """Remove an explicit surface and restore its original local stylesheet."""
    surface = getattr(widget, "_continuous_surface", None)
    if surface is None:
        return
    widget.removeEventFilter(surface)
    surface._applying = True
    widget.setStyleSheet(surface.original_stylesheet)
    widget.setProperty("_continuousSurface", False)
    del widget._continuous_surface
    surface.deleteLater()
    widget.update()
