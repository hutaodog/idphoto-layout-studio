# -*- coding: utf-8 -*-
"""A fixed combo surface with a clipped, naturally sized list and damped reveal.

A transient tool window avoids Qt.Popup's implicit mouse grab: dismissals can
finish their animation, and an outside click reaches its intended control. The
application filter manages this single, nonmodal surface without a nested loop.
"""
from __future__ import annotations

import math
import time
import weakref

from PySide6.QtCore import (QEvent, QItemSelectionModel, QPersistentModelIndex,
                            QPoint, QRect, QRectF, QSignalBlocker, QSize, Qt,
                            QTimer, QVariantAnimation)
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPalette, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QListView,
                               QStyledItemDelegate, QStyle, QStyleOptionViewItem,
                               QWidget)
from shiboken6 import isValid

from . import style
from .corners import continuous_path
from .motion import REVEAL_CLOSE, REVEAL_OPEN, spring_state


class _ItemDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):  # noqa: N802
        hint = super().sizeHint(option, index)
        return QSize(hint.width() + 24, max(32, hint.height() + 12))

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        selected = bool(opt.state & QStyle.State_Selected)
        hovered = bool(opt.state & QStyle.State_MouseOver)
        if selected or hovered:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(style.PRIMARY_SOFT if selected else "#f5f7fa"))
            painter.drawPath(continuous_path(QRectF(opt.rect).adjusted(2, 1, -2, -1), 7))
            painter.restore()
        opt.state &= ~(QStyle.State_Selected | QStyle.State_MouseOver | QStyle.State_HasFocus)
        opt.rect.adjust(10, 0, -8, 0)
        if selected:
            opt.palette.setColor(QPalette.Text, QColor(style.PRIMARY))
        super().paint(painter, opt, index)


class SpringComboPopup(QWidget):
    """One selection per open session, even during animated dismissal."""

    PAD = 6
    SHADOW = 5

    def __init__(self, combo):
        super().__init__(combo, Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
                         | Qt.WindowDoesNotAcceptFocus)
        self.combo = combo
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setObjectName("springComboPopup")
        self.setStyleSheet("QWidget#springComboPopup{background:transparent;border:none;}")
        self.clip = QWidget(self)
        self.clip.setObjectName("springComboClip")
        self.clip.setStyleSheet("QWidget#springComboClip{background:transparent;border:none;}")
        self.view = QListView(self.clip)
        self.view.setObjectName("springComboList")
        self.view.setStyleSheet(
            "QListView#springComboList{background:transparent;border:none;padding:0;outline:0;}")
        self.view.setItemDelegate(_ItemDelegate(self.view))
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setMouseTracking(True)
        self.view.setFocusPolicy(Qt.NoFocus)
        self.view.clicked.connect(self._choose)
        combo.currentIndexChanged.connect(self._owner_selection_changed)
        self._height = self._speed = self._start_height = self._start_speed = 0.0
        self._target = 0.0
        self._full_height = 1
        self._opening = self._accepting = self._committed = False
        self._above = self._return_focus = False
        self._started_at = time.perf_counter()
        self._omega, self._damping = REVEAL_OPEN.frequency, REVEAL_OPEN.damping
        self._animation = QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(1100)
        self._animation.valueChanged.connect(self._tick)
        self._animation.finished.connect(self._finish)
        self._selection = None
        self._model_connections = []
        self._deactivate_timer = QTimer(self)
        self._deactivate_timer.setSingleShot(True)
        self._deactivate_timer.timeout.connect(self._close_if_inactive)
        QApplication.instance().installEventFilter(self)

    def _bind_model(self):
        for signal in self._model_connections:
            try:
                signal.disconnect(self.dismiss)
            except (RuntimeError, TypeError):
                pass
        self._model_connections.clear()
        model = self.combo.model()
        # Invalidate the session before an index can start referring to new data.
        for name in ("modelAboutToBeReset", "rowsAboutToBeRemoved", "rowsAboutToBeInserted",
                     "columnsAboutToBeRemoved", "columnsAboutToBeInserted",
                     "layoutAboutToBeChanged", "destroyed"):
            signal = getattr(model, name)
            signal.connect(self.dismiss)
            self._model_connections.append(signal)

    def _measure(self):
        combo = self.combo
        if self._selection is not None and isValid(self._selection):
            self._selection.currentChanged.disconnect(self._highlight)
        self.view.setFont(combo.font())
        self.view.setModel(combo.model())
        self.view.setModelColumn(combo.modelColumn())
        self.view.setRootIndex(combo.rootModelIndex())
        self.view.doItemsLayout()
        rows = min(combo.count(), max(1, combo.maxVisibleItems()), 10)
        desired = sum(max(32, self.view.sizeHintForRow(row)) for row in range(rows)) + 2 * self.PAD
        screen = QGuiApplication.screenAt(combo.mapToGlobal(combo.rect().center()))
        available = (screen or QGuiApplication.primaryScreen()).availableGeometry()
        below = combo.mapToGlobal(QPoint(0, combo.height() + 3))
        top = combo.mapToGlobal(QPoint(0, -3))
        below_room = max(1, available.bottom() - below.y() - 2 * self.SHADOW)
        above_room = max(1, top.y() - available.top() - 2 * self.SHADOW)
        self._above = below_room < desired and above_room > below_room
        room = above_room if self._above else below_room
        self._full_height = max(1, min(desired, int(room / 1.06)))
        width = max(combo.width(), self.view.sizeHintForColumn(combo.modelColumn()) + 32)
        width = min(width, max(1, available.width() - 2 * self.SHADOW))
        extent = min(available.height(), math.ceil(self._full_height * 1.06) + 2 * self.SHADOW)
        x = max(available.left(), min(below.x() - self.SHADOW,
                                    available.right() - width - 2 * self.SHADOW + 1))
        y = top.y() - extent if self._above else below.y() - self.SHADOW
        y = max(available.top(), min(y, available.bottom() - extent + 1))
        self.setGeometry(x, y, width + 2 * self.SHADOW, extent)
        self.view.setGeometry(self.PAD, self.PAD, max(1, width - 2 * self.PAD),
                              max(1, self._full_height - 2 * self.PAD))
        self._selection = self.view.selectionModel()
        current = combo.model().index(combo.currentIndex(), combo.modelColumn(), combo.rootModelIndex())
        with QSignalBlocker(self._selection):
            self._selection.setCurrentIndex(current, QItemSelectionModel.ClearAndSelect)
        self._selection.currentChanged.connect(self._highlight)
        self.view.scrollTo(current, QAbstractItemView.EnsureVisible)
        self._bind_model()

    def open(self):
        if not self.combo.isVisible() or not self.combo.isEnabled() or not self.combo.count():
            return
        if self.isVisible() and self._opening:
            return
        app = QApplication.instance()
        ref = getattr(app, "_spring_combo_popup", None)
        active = ref() if ref is not None else None
        if active is not None and isValid(active) and active is not self:
            active.dismiss()
        app._spring_combo_popup = weakref.ref(self)
        self._committed = self._return_focus = False
        self._accepting = True
        if not self.isVisible():
            self._measure()
            self._height = self._speed = 0.0
            self._apply_height()
            self.show()
            self.raise_()
        # The owner keeps keyboard focus; this transient surface never steals
        # activation between the press and release of a click on another combo.
        self.combo.setFocus(Qt.PopupFocusReason)
        self._transition(True)

    def request_close(self, *, restore_focus=False):
        if not self.isVisible():
            return
        self._accepting = False
        self._return_focus = self._return_focus or restore_focus
        if self._opening:
            self._transition(False)

    def dismiss(self, *unused):
        """Settle immediately when the owner/model is no longer usable."""
        self._accepting = self._opening = self._return_focus = False
        self._animation.stop()
        self._target = self._height = self._speed = 0.0
        if self.isVisible():
            self.hide()

    def _state(self, elapsed):
        return spring_state(self._start_height, self._start_speed, self._target, elapsed,
                            frequency=self._omega, damping=self._damping)

    def _transition(self, opening):
        # Retarget the last displayed frame; setup must not advance old motion.
        with QSignalBlocker(self._animation):
            self._animation.stop()
            self._animation.setCurrentTime(0)
        self._opening = opening
        self._start_height, self._start_speed = self._height, self._speed
        self._target = float(self._full_height if opening else 0)
        profile = REVEAL_OPEN if opening else REVEAL_CLOSE
        self._omega, self._damping = profile.frequency, profile.damping
        self._started_at = time.perf_counter()
        self._animation.start()

    def _tick(self, unused=None):
        self._height, self._speed = self._state(time.perf_counter() - self._started_at)
        limit = self._full_height * 1.06
        if self._height < 0 or self._height > limit:
            self._height = max(0.0, min(limit, self._height))
            self._speed = 0.0
        self._apply_height()
        if abs(self._height - self._target) < .25 and abs(self._speed) < 3.0:
            self._finish()

    def _surface_rect(self):
        height = max(0, round(self._height))
        y = self.height() - self.SHADOW - height if self._above else self.SHADOW
        return QRect(self.SHADOW, y, self.width() - 2 * self.SHADOW, height)

    def _apply_height(self):
        rect = self._surface_rect()
        self.clip.setGeometry(rect)
        # Above a control, reveal from its bottom while the list never relayouts.
        self.view.move(self.PAD, (rect.height() - self._full_height if self._above else 0) + self.PAD)
        self.update()
        if isValid(self.combo):
            self.combo.update()

    def _finish(self):
        self._animation.stop()
        self._height, self._speed = self._target, 0.0
        self._apply_height()
        if not self._opening:
            self.hide()

    def _valid_index(self, index):
        return (index.isValid() and index.model() is self.combo.model()
                and index.parent() == self.combo.rootModelIndex()
                and index.column() == self.combo.modelColumn()
                and bool(index.flags() & Qt.ItemIsEnabled)
                and bool(index.flags() & Qt.ItemIsSelectable))

    def _owner_selection_changed(self, row):
        if self._accepting and self.isVisible():
            self.dismiss()

    def _highlight(self, current, previous):
        if self._accepting and self._valid_index(current):
            combo, persistent = self.combo, QPersistentModelIndex(current)
            text = combo.itemText(current.row())
            combo.highlighted.emit(current.row())
            if (isValid(combo) and persistent.isValid()
                    and persistent.model() is combo.model()):
                combo.textHighlighted.emit(text)

    def _choose(self, index):
        if not self._accepting or self._committed or not self._valid_index(index):
            return
        combo, persistent = self.combo, QPersistentModelIndex(index)
        row, text = index.row(), combo.itemText(index.row())
        # Lock before user callbacks: they can modify the model or destroy us.
        self._committed = True
        self.request_close(restore_focus=True)
        # QComboBox mirrors the new index into its hidden native view, whose
        # selection signal would emit a second highlighted pair for this click.
        native_selection = combo.view().selectionModel()
        blocked = native_selection.blockSignals(True)
        try:
            combo.setCurrentIndex(row)
        finally:
            if isValid(native_selection):
                native_selection.blockSignals(blocked)
        if (isValid(combo) and persistent.isValid() and persistent.model() is combo.model()
                and combo.currentIndex() == persistent.row()):
            combo.activated.emit(persistent.row())
            if (isValid(combo) and persistent.isValid()
                    and combo.currentIndex() == persistent.row()):
                combo.textActivated.emit(text)

    def _close_if_inactive(self):
        # Some QPA plugins activate even a WindowDoesNotAcceptFocus tool. Treat
        # that as our own surface, rather than an external loss of activation.
        if QApplication.activeWindow() is self or QGuiApplication.focusWindow() is self.windowHandle():
            return
        if self.isVisible() and not self.combo.window().isActiveWindow():
            self.request_close()

    def eventFilter(self, watched, event):  # noqa: N802
        if not self.isVisible():
            return False
        kind = event.type()
        if kind == QEvent.ApplicationDeactivate:
            self.request_close()
        elif kind == QEvent.WindowDeactivate and watched is self.combo.window():
            self._deactivate_timer.start(0)
        elif kind in (QEvent.Hide, QEvent.Close, QEvent.Move, QEvent.Resize, QEvent.EnabledChange):
            if (isinstance(watched, QWidget)
                    and (watched is self.combo or watched.isAncestorOf(self.combo))):
                self.dismiss()
        elif kind in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
            point = event.globalPosition().toPoint()
            in_popup = self._surface_rect().contains(self.mapFromGlobal(point))
            on_combo = self.combo.rect().contains(self.combo.mapFromGlobal(point))
            if not in_popup and not on_combo:
                self.request_close()
                # Consume the unused, transparent portion of this native window.
                return (isinstance(watched, QWidget)
                        and (watched is self or self.isAncestorOf(watched)))
            if (watched is self.view or watched is self.view.viewport()) and not self._accepting:
                return True
        elif kind == QEvent.KeyPress and watched in (self.combo, self.view, self):
            if not self._accepting:
                return True
            key, modifiers = event.key(), event.modifiers()
            if event.isAutoRepeat() and key in (Qt.Key_F4, Qt.Key_Space):
                return True
            if (key in (Qt.Key_Escape, Qt.Key_F4)
                    or (key in (Qt.Key_Up, Qt.Key_Down) and modifiers & Qt.AltModifier)):
                self.request_close(restore_focus=True)
                return True
            if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
                self._choose(self.view.currentIndex())
                return True
            if key in (Qt.Key_Tab, Qt.Key_Backtab):
                combo = self.combo
                self.dismiss()
                combo.setFocus(Qt.TabFocusReason)
                combo.focusNextPrevChild(key == Qt.Key_Tab and not modifiers & Qt.ShiftModifier)
                return True
            if watched is self.combo:
                QApplication.sendEvent(self.view, event)
                return True
        return False

    def mousePressEvent(self, event):  # noqa: N802
        if not self._surface_rect().contains(event.position().toPoint()):
            self.request_close()
        event.accept()

    def hideEvent(self, event):  # noqa: N802
        restore_focus = self._return_focus
        self._animation.stop()
        self._target = self._height = self._speed = 0.0
        self._opening = self._accepting = self._return_focus = False
        app = QApplication.instance()
        ref = getattr(app, "_spring_combo_popup", None)
        if ref is not None and ref() is self:
            app._spring_combo_popup = None
        if isValid(self.combo):
            self.combo._spring_popup_hidden()
            if restore_focus and app.applicationState() == Qt.ApplicationActive:
                self.combo.setFocus(Qt.PopupFocusReason)
        super().hideEvent(event)

    def paintEvent(self, event):  # noqa: N802
        rect = QRectF(self._surface_rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if rect.height() <= 1:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(Qt.NoBrush)
        for spread, alpha in ((4, 6), (2, 10), (1, 12)):
            painter.setPen(QPen(QColor(24, 36, 58, alpha), spread * 2))
            painter.drawPath(continuous_path(rect.translated(0, 1), 10))
        painter.setPen(QPen(QColor(style.BORDER_STRONG), 1))
        painter.setBrush(QColor(style.CARD))
        painter.drawPath(continuous_path(rect, min(10, rect.height() / 2)))
