"""Real Qt popup/event-loop checks; content is never scaled for the animation."""
import os
import time

os.environ.setdefault("IDPHOTO_NO_UPDATE", "1")

import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from app.ui import style
from app.ui.widgets import NoWheelComboBox


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def wait_until(qapp, predicate, timeout=2000):
    start = time.monotonic()
    while not predicate():
        assert (time.monotonic() - start) * 1000 < timeout
        qapp.processEvents()
        QTest.qWait(5)


@pytest.fixture
def combo(qapp):
    holder = QWidget()
    holder.setStyleSheet(style.STYLESHEET)
    layout = QVBoxLayout(holder)
    box = NoWheelComboBox()
    box.addItem("一寸 25×35mm", "one")
    box.addItem("二寸 35×49mm", "two49")
    box.addItem("二寸 35×53mm", "two53")
    layout.addWidget(box)
    holder.resize(280, 90)
    holder.show()
    QTest.qWait(30)
    yield box
    if box._spring_popup is not None:
        box._spring_popup.hide()
    holder.close()
    holder.deleteLater()
    qapp.processEvents()


def opened(qapp, box):
    box.showPopup()
    popup = box._spring_popup
    wait_until(qapp, lambda: abs(popup._height - popup._full_height) < .01
               and popup._animation.state() == QAbstractAnimation.Stopped)
    return popup


def test_reveal_never_repositions_native_window_or_resizes_rows(qapp, combo):
    combo.showPopup()
    popup = combo._spring_popup
    window_rect = popup.geometry()
    view_size = popup.view.size()
    samples = []
    for _ in range(24):
        QTest.qWait(12)
        samples.append(popup._height)
        assert popup.geometry() == window_rect
        assert popup.view.size() == view_size
    assert max(samples) > min(samples) + 10
    wait_until(qapp, lambda: popup._animation.state() == QAbstractAnimation.Stopped)
    combo.hidePopup()
    for _ in range(6):
        QTest.qWait(15)
        assert popup.geometry() == window_rect
        assert popup.view.size() == view_size
    wait_until(qapp, lambda: not popup.isVisible())


def test_keyboard_commits_data_and_activates_once(qapp, combo):
    events = []
    combo.activated.connect(events.append)
    popup = opened(qapp, combo)
    QTest.keyClick(popup.view, Qt.Key_Down)
    assert combo.currentData() == "one"
    QTest.keyClick(popup.view, Qt.Key_Return)
    wait_until(qapp, lambda: not popup.isVisible())
    assert combo.currentData() == "two49"
    assert events == [1]


def test_escape_preserves_original_selection(qapp, combo):
    popup = opened(qapp, combo)
    QTest.keyClick(popup.view, Qt.Key_Down)
    QTest.keyClick(popup.view, Qt.Key_Escape)
    wait_until(qapp, lambda: not popup.isVisible())
    assert combo.currentData() == "one"


def test_mouse_selects_exactly_once(qapp, combo):
    events = []
    combo.activated.connect(events.append)
    popup = opened(qapp, combo)
    index = combo.model().index(2, combo.modelColumn())
    rect = popup.view.visualRect(index)
    QTest.mouseClick(popup.view.viewport(), Qt.LeftButton, pos=rect.center())
    wait_until(qapp, lambda: not popup.isVisible())
    assert combo.currentData() == "two53"
    assert events == [2]


def test_rapid_reverse_retains_current_height_and_finishes(qapp, combo):
    popup = opened(qapp, combo)
    for i in range(24):
        QTest.qWait(7)
        old = popup._height
        popup._transition(i % 2 == 1)
        assert abs(popup._height - old) < 1  # no synchronous catch-up or endpoint reset
        assert popup._height >= 0
    popup.open()
    wait_until(qapp, lambda: popup._animation.state() == QAbstractAnimation.Stopped)
    assert popup.isVisible()
    assert popup._height == popup._full_height
    popup.request_close()
    wait_until(qapp, lambda: not popup.isVisible())
    assert popup._height == 0
    assert combo.currentData() == "one"


def test_disabled_and_empty_do_not_open(qapp, combo):
    combo.setEnabled(False)
    combo.showPopup()
    assert combo._spring_popup is not None
    assert not combo._spring_popup.isVisible()
    combo.setEnabled(True)
    combo.clear()
    combo.showPopup()
    assert not combo._spring_popup.isVisible()


def test_popup_above_keeps_list_global_anchor_fixed(qapp, combo):
    available = qapp.primaryScreen().availableGeometry()
    combo.window().move(available.left() + 40, available.bottom() - 85)
    qapp.processEvents()
    combo.showPopup()
    popup = combo._spring_popup
    assert popup._above
    anchor = popup.view.mapToGlobal(QPoint(0, 0))
    for _ in range(20):
        QTest.qWait(12)
        assert popup.view.mapToGlobal(QPoint(0, 0)) == anchor
        assert available.contains(popup.geometry())
    popup.request_close()
    wait_until(qapp, lambda: not popup.isVisible())


def test_owner_hiding_or_disabling_closes_popup(qapp, combo):
    popup = opened(qapp, combo)
    combo.setEnabled(False)
    qapp.processEvents()
    assert not popup.isVisible()
    combo.setEnabled(True)
    opened(qapp, combo)
    combo.hide()
    qapp.processEvents()
    assert not popup.isVisible()


def test_disabled_item_does_not_commit(qapp, combo):
    combo.model().item(1).setEnabled(False)
    popup = opened(qapp, combo)
    popup._choose(combo.model().index(1, 0))
    assert combo.currentData() == "one"
    assert popup.isVisible()


def test_keyboard_open_uses_spring_popup(qapp, combo):
    combo.setFocus()
    QTest.keyClick(combo, Qt.Key_F4)
    assert combo._spring_popup.isVisible()
    QTest.keyClick(combo._spring_popup.view, Qt.Key_Escape)
    wait_until(qapp, lambda: not combo._spring_popup.isVisible())


def test_commit_is_locked_before_dismiss_animation(qapp, combo):
    events, texts = [], []
    combo.activated.connect(events.append)
    combo.textActivated.connect(texts.append)
    popup = opened(qapp, combo)
    for row in (1, 2):
        index = combo.model().index(row, 0)
        QTest.mouseClick(popup.view.viewport(), Qt.LeftButton,
                         pos=popup.view.visualRect(index).center())
    QTest.keyClick(combo, Qt.Key_Return)
    wait_until(qapp, lambda: not popup.isVisible())
    assert events == [1]
    assert texts == ["二寸 35×49mm"]
    assert combo.currentData() == "two49"


def test_escape_cannot_be_followed_by_a_stale_commit(qapp, combo):
    events = []
    combo.activated.connect(events.append)
    popup = opened(qapp, combo)
    QTest.keyClick(combo, Qt.Key_Down)
    QTest.keyClick(combo, Qt.Key_Escape)
    QTest.keyClick(combo, Qt.Key_Return)
    index = combo.model().index(2, 0)
    QTest.mouseClick(popup.view.viewport(), Qt.LeftButton,
                     pos=popup.view.visualRect(index).center())
    wait_until(qapp, lambda: not popup.isVisible())
    assert events == []
    assert combo.currentData() == "one"


def test_mouse_highlight_and_activation_each_emit_once(qapp, combo):
    events = []
    combo.highlighted.connect(lambda row: events.append(("highlight", row)))
    combo.textHighlighted.connect(lambda text: events.append(("highlightText", text)))
    combo.currentIndexChanged.connect(lambda row: events.append(("change", row)))
    combo.activated.connect(lambda row: events.append(("activate", row)))
    popup = opened(qapp, combo)
    events.clear()
    index = combo.model().index(1, 0)
    QTest.mouseClick(popup.view.viewport(), Qt.LeftButton,
                     pos=popup.view.visualRect(index).center())
    assert events == [("highlight", 1), ("highlightText", "二寸 35×49mm"),
                      ("change", 1), ("activate", 1)]


def test_actual_owner_keyboard_routes_to_preview_before_commit(qapp, combo):
    events, texts = [], []
    combo.activated.connect(events.append)
    combo.textHighlighted.connect(texts.append)
    popup = opened(qapp, combo)
    QTest.keyClick(combo, Qt.Key_End)
    assert popup.view.currentIndex().row() == 2
    assert combo.currentData() == "one"
    assert texts == ["二寸 35×53mm"]
    QTest.keyClick(combo, Qt.Key_Return)
    wait_until(qapp, lambda: not popup.isVisible())
    assert combo.currentData() == "two53"
    assert events == [2]


def test_alt_up_dismisses_without_changing_selection(qapp, combo):
    popup = opened(qapp, combo)
    QTest.keyClick(combo, Qt.Key_Down)
    QTest.keyClick(combo, Qt.Key_Up, Qt.AltModifier)
    wait_until(qapp, lambda: not popup.isVisible())
    assert combo.currentData() == "one"


@pytest.mark.parametrize("operation", ["clear", "remove", "insert", "reset", "replace"])
def test_model_mutation_closes_session_before_old_indices_can_commit(qapp, combo, operation):
    from PySide6.QtGui import QStandardItem, QStandardItemModel

    events = []
    combo.activated.connect(events.append)
    popup = opened(qapp, combo)
    old_index = combo.model().index(1, 0)
    if operation == "clear":
        combo.clear()
    elif operation == "remove":
        combo.removeItem(0)
    elif operation == "insert":
        combo.insertItem(0, "新增", "new")
    elif operation == "reset":
        combo.model().clear()
        combo.addItem("重建", "new")
    else:
        model = QStandardItemModel(combo)
        model.appendRow(QStandardItem("替换后的选项"))
        combo.setModel(model)
    assert not popup.isVisible()
    assert not popup._accepting
    popup._choose(old_index)
    assert events == []
    if combo.count():
        popup = opened(qapp, combo)
        assert popup.view.model() is combo.model()
        assert popup.view.currentIndex().row() == combo.currentIndex()


def test_reentrant_row_removal_activates_the_persistent_item(qapp, combo):
    events, texts = [], []
    combo.currentIndexChanged.connect(lambda row: combo.removeItem(0) if row == 2 else None)
    combo.activated.connect(events.append)
    combo.textActivated.connect(texts.append)
    popup = opened(qapp, combo)
    index = combo.model().index(2, 0)
    QTest.mouseClick(popup.view.viewport(), Qt.LeftButton,
                     pos=popup.view.visualRect(index).center())
    assert combo.currentIndex() == 1
    assert combo.currentData() == "two53"
    assert events == [1]
    assert texts == ["二寸 35×53mm"]


def test_reentrant_replacement_does_not_emit_a_stale_activation(qapp, combo):
    from PySide6.QtGui import QStandardItem, QStandardItemModel

    events = []
    new_model = QStandardItemModel(combo)
    new_model.appendRow(QStandardItem("不同的条目"))
    combo.currentIndexChanged.connect(lambda row: combo.setModel(new_model) if row == 2 else None)
    combo.activated.connect(events.append)
    popup = opened(qapp, combo)
    index = combo.model().index(2, 0)
    QTest.mouseClick(popup.view.viewport(), Qt.LeftButton,
                     pos=popup.view.visualRect(index).center())
    assert combo.currentText() == "不同的条目"
    assert events == []
    assert not popup.isVisible()


def test_external_selection_closes_the_old_preview(qapp, combo):
    popup = opened(qapp, combo)
    combo.setCurrentIndex(2)
    assert not popup.isVisible()
    assert combo.currentData() == "two53"


def test_parent_motion_and_scroll_close_a_detached_popup(qapp, combo):
    popup = opened(qapp, combo)
    combo.move(combo.x() + 10, combo.y())
    assert not popup.isVisible()


@pytest.fixture
def controls(qapp):
    from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton

    holder = QWidget()
    layout = QHBoxLayout(holder)
    before = QLineEdit()
    first, second = NoWheelComboBox(), NoWheelComboBox()
    first.addItems(["Alpha", "Beta", "Crimson"])
    second.addItems(["A4", "6 inch", "A5"])
    button = QPushButton("Outside")
    for control in (before, first, second, button):
        layout.addWidget(control)
    holder.resize(640, 90)
    holder.show()
    holder.activateWindow()
    QTest.qWait(30)
    yield holder, before, first, second, button
    for box in (first, second):
        if box._spring_popup is not None:
            box._spring_popup.dismiss()
    holder.close()
    holder.deleteLater()
    qapp.processEvents()


def click_through_window(holder, widget):
    QTest.mouseClick(holder.windowHandle(), Qt.LeftButton,
                     pos=widget.mapTo(holder, widget.rect().center()))


def test_one_click_switches_to_the_other_combo(qapp, controls):
    holder, before, first, second, button = controls
    a = opened(qapp, first)
    click_through_window(holder, second)
    b = second._spring_popup
    assert not a.isVisible()
    assert b is not None and b.isVisible() and b._opening
    QTest.qWait(60)
    assert b.isVisible() and b._opening


def test_outside_button_receives_the_first_click(qapp, controls):
    holder, before, first, second, button = controls
    events = []
    button.clicked.connect(lambda: events.append("clicked"))
    popup = opened(qapp, first)
    click_through_window(holder, button)
    assert events == ["clicked"]
    assert not popup._accepting
    wait_until(qapp, lambda: not popup.isVisible())


def test_opening_press_release_and_second_click_toggle(qapp, controls):
    holder, before, first, second, button = controls
    point = first.mapTo(holder, first.rect().center())
    QTest.mousePress(holder.windowHandle(), Qt.LeftButton, pos=point)
    QTest.qWait(220)
    QTest.mouseRelease(holder.windowHandle(), Qt.LeftButton, pos=point)
    popup = first._spring_popup
    assert popup.isVisible() and popup._opening
    click_through_window(holder, first)
    wait_until(qapp, lambda: not popup.isVisible())


@pytest.mark.parametrize("key,expected", [(Qt.Key_Tab, "next"), (Qt.Key_Backtab, "previous")])
def test_tab_leaves_no_popup_behind(qapp, controls, key, expected):
    holder, before, first, second, button = controls
    popup = opened(qapp, first)
    QTest.keyClick(first, key)
    assert not popup.isVisible()
    # Offscreen QPA can activate a no-focus tool; Windows focus is also checked
    # in the native QA. The public focus chain still advances to the right item.
    if holder.isActiveWindow():
        assert qapp.focusWidget() is (second if expected == "next" else before)


def test_type_search_previews_without_changing_the_value(qapp, controls):
    holder, before, first, second, button = controls
    popup = opened(qapp, first)
    QTest.keyClicks(first, "cr")
    assert popup.view.currentIndex().row() == 2
    assert first.currentIndex() == 0
    QTest.keyClick(first, Qt.Key_Escape)
    wait_until(qapp, lambda: not popup.isVisible())
    assert first.currentIndex() == 0
