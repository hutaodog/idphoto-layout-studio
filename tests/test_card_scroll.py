"""Real MainWindow/event-loop regressions for accordion layout and scrolling.

The measured coordinates are screen coordinates, not the spring's internal
height. Keep all Qt layouts, focus hand-off and native wheel handling active.
"""
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("IDPHOTO_NO_UPDATE", "1")

import pytest
from PySide6.QtCore import QAbstractAnimation, QEventLoop, QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QFontDatabase, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QScrollArea

from app.core import settings
from app.ui.main_window import MainWindow
from app.ui.section_card import HEAD_H


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    if not QFontDatabase.families():
        QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\msyh.ttc")
    return app


@pytest.fixture
def studio(qapp, monkeypatch, tmp_path):
    monkeypatch.setenv("IDPHOTO_NO_UPDATE", "1")
    monkeypatch.setattr(settings, "settings_path", lambda: str(tmp_path / "settings.json"))
    win = MainWindow()
    win.resize(1340, 860)
    win.show()
    QTest.qWait(60)
    cards = list(win.card_summaries.values())
    for card in cards:
        card.set_expanded(True, animate=False)
    scroll = next(s for s in win.findChildren(QScrollArea)
                  if s.widget() is not None and s.widget().isAncestorOf(cards[0]))
    QTest.qWait(50)
    scroll.setFocus(Qt.OtherFocusReason)
    yield SimpleNamespace(app=qapp, win=win, cards=cards, scroll=scroll,
                          bar=scroll.verticalScrollBar(), inner=scroll.widget())
    win.close()
    win.deleteLater()
    qapp.processEvents()


def frame(studio):
    return {
        "screen_y": [c.mapToGlobal(QPoint()).y() for c in studio.cards],
        "local_y": [c.y() for c in studio.cards],
        "height": [c.height() for c in studio.cards],
        "body": [c._wrap.body.geometry() for c in studio.cards],
        "value": studio.bar.value(),
        "maximum": studio.bar.maximum(),
        "inner": studio.inner.height(),
    }


def observe(studio, action, duration=650):
    samples = [frame(studio)]
    timer = QTimer()
    timer.setInterval(4)
    timer.timeout.connect(lambda: samples.append(frame(studio)))
    timer.start()
    action()
    loop = QEventLoop()
    QTimer.singleShot(duration, loop.quit)
    loop.exec()
    timer.stop()
    samples.append(frame(studio))
    return samples


def click(studio, index):
    header = studio.cards[index].header
    center = header.mapTo(studio.scroll.viewport(), QPoint(80, HEAD_H // 2))
    assert studio.scroll.viewport().rect().contains(center), center
    QTest.mouseClick(header, Qt.LeftButton, pos=QPoint(80, HEAD_H // 2))


def assert_settled(studio, closed):
    for i, card in enumerate(studio.cards):
        assert card._animation.state() == QAbstractAnimation.Stopped
        if i in closed:
            assert card.height() == HEAD_H
            assert card._wrap.isHidden() and card._wrap.height() == 0
        else:
            assert not card._wrap.isHidden()
            assert card._wrap.height() == card._open_height
    for a, b in zip(studio.cards, studio.cards[1:]):
        assert b.y() == a.y() + a.height() + studio.inner.layout().spacing()


def assert_screen_anchor(samples, indices):
    for index in indices:
        ys = [s["screen_y"][index] for s in samples]
        assert max(ys) - min(ys) == 0, (index, ys)
    assert len(samples) > 10
    assert len({tuple(s["height"]) for s in samples}) >= 5
    assert all(s["body"] == samples[0]["body"] for s in samples)


@pytest.mark.parametrize("position,index", [(0, 1), (400, 2), ("near-bottom", 3), ("bottom", 3)])
def test_collapsing_preserves_card_and_above_screen_positions(studio, position, index):
    value = {"near-bottom": studio.bar.maximum() - 20,
             "bottom": studio.bar.maximum()}.get(position, position)
    studio.bar.setValue(value)
    QTest.qWait(20)
    samples = observe(studio, lambda: click(studio, index))
    assert_screen_anchor(samples, range(index + 1))
    assert {s["value"] for s in samples} == {value}
    assert_settled(studio, {index})


def test_bottom_two_visible_cards_collapse_without_scroll_clamping(studio):
    studio.bar.setValue(studio.bar.maximum())
    QTest.qWait(20)
    samples = observe(studio, lambda: (click(studio, 3), click(studio, 4)))
    assert_screen_anchor(samples, range(4))
    assert len({s["value"] for s in samples}) == 1
    assert_settled(studio, {3, 4})


def test_focused_editor_does_not_trigger_hidden_focus_autoscroll(studio):
    # Programmatic folding preserves the editor's focus until SectionCard
    # handles it; a mouse click could move focus before the animation starts.
    editor = studio.cards[3].findChildren(QLineEdit)[0]
    editor.setFocus(Qt.OtherFocusReason)
    QTest.qWait(20)
    assert studio.cards[3]._wrap.isAncestorOf(studio.app.focusWidget())
    studio.bar.setValue(studio.bar.maximum())
    QTest.qWait(20)
    samples = observe(studio, lambda: studio.cards[3].set_expanded(False))
    assert_screen_anchor(samples, range(4))
    assert len({s["value"] for s in samples}) == 1
    assert not studio.cards[3]._wrap.isAncestorOf(studio.app.focusWidget())
    assert_settled(studio, {3})


def test_focused_first_editor_cannot_scroll_on_final_hide(studio):
    studio.win.ed_search.setFocus(Qt.OtherFocusReason)
    QTest.qWait(20)
    assert studio.app.focusWidget() is studio.win.ed_search
    studio.bar.setValue(200)
    QTest.qWait(20)
    events = []
    studio.bar.valueChanged.connect(
        lambda value: events.append((value, studio.cards[0]._wrap.height(),
                                     studio.cards[0].mapToGlobal(QPoint()).y())))
    samples = observe(studio, lambda: studio.cards[0].set_expanded(False))
    # The visible header may be followed as content ABOVE it shrinks, but the
    # final hide must not focus a later input and produce another scroll jump.
    assert events
    assert all(body_height > 0 for _, body_height, _ in events), events
    assert all(a["value"] >= b["value"] for a, b in zip(samples, samples[1:]))
    focus = studio.app.focusWidget()
    assert focus is None or not any(c._wrap.isAncestorOf(focus) for c in studio.cards)
    assert_settled(studio, {0})


def test_above_viewport_collapse_keeps_reachable_header_on_screen(studio):
    studio.bar.setValue(studio.bar.maximum())
    QTest.qWait(20)
    # Folding a card above the viewport must follow the visible header. Just
    # freezing the old scroll range here would leave the whole viewport blank.
    value = studio.bar.value()
    local = studio.cards[3].y()
    samples = observe(studio, lambda: (studio.cards[2].set_expanded(False),
                                      studio.cards[3].set_expanded(False)))
    assert_screen_anchor(samples, [3])
    assert studio.bar.value() == value + studio.cards[3].y() - local
    assert studio.scroll.viewport().rect().contains(
        studio.cards[3].header.mapTo(studio.scroll.viewport(), QPoint(80, 22)))
    assert_settled(studio, {2, 3})


def wheel_up(studio):
    viewport = studio.scroll.viewport()
    pos = viewport.rect().center()
    event = QWheelEvent(QPointF(pos), QPointF(viewport.mapToGlobal(pos)),
                        QPoint(), QPoint(0, 120), Qt.NoButton, Qt.NoModifier,
                        Qt.NoScrollPhase, False)
    QApplication.sendEvent(viewport, event)


def test_native_wheel_releases_tail_and_restores_natural_scroll_range(studio):
    studio.bar.setValue(studio.bar.maximum())
    QTest.qWait(20)
    samples = observe(studio, lambda: (click(studio, 3), click(studio, 4)))
    assert_screen_anchor(samples, range(4))
    retained = studio.inner.minimumHeight()
    before = studio.bar.value()
    wheel_up(studio)
    QTest.qWait(10)
    assert studio.bar.value() < before
    assert studio.inner.minimumHeight() < retained
    for _ in range(80):
        wheel_up(studio)
    QTest.qWait(30)
    assert studio.bar.value() == 0
    assert studio.inner.minimumHeight() == 0
    natural = studio.inner.layout().minimumSize().height()
    assert studio.bar.maximum() == max(0, natural - studio.scroll.viewport().height())
    assert studio.inner.height() == max(natural, studio.scroll.viewport().height())


def test_native_wheel_during_collapse_is_not_undone_by_next_frame(studio):
    studio.bar.setValue(studio.bar.maximum())
    QTest.qWait(20)
    initial = studio.bar.value()
    wheel_values = []

    def scroll_while_moving():
        before = studio.bar.value()
        wheel_up(studio)
        wheel_values.extend((before, studio.bar.value()))

    def collapse_and_scroll():
        click(studio, 3)
        QTimer.singleShot(85, scroll_while_moving)

    samples = observe(studio, collapse_and_scroll)
    assert len(wheel_values) == 2 and wheel_values[0] == initial
    assert wheel_values[1] < initial
    assert studio.bar.value() == wheel_values[1]
    assert {s["value"] for s in samples} == set(wheel_values)
    for i in range(4):
        # The only screen movement is exactly the user's native wheel delta.
        assert {s["screen_y"][i] + s["value"] for s in samples} == {
            samples[0]["screen_y"][i] + initial}
    assert_settled(studio, {3})


def test_reversing_two_cards_keeps_screen_anchor_and_reopening_absorbs_tail(studio):
    studio.bar.setValue(studio.bar.maximum())
    QTest.qWait(20)
    initial_maximum = studio.bar.maximum()

    def reverse_sequence():
        click(studio, 3)
        click(studio, 4)
        QTimer.singleShot(55, lambda: studio.cards[3].set_expanded(True))
        QTimer.singleShot(90, lambda: studio.cards[4].set_expanded(True))
        QTimer.singleShot(125, lambda: studio.cards[3].set_expanded(False))
        QTimer.singleShot(155, lambda: studio.cards[4].set_expanded(False))

    samples = observe(studio, reverse_sequence, duration=850)
    assert_screen_anchor(samples, range(4))
    assert_settled(studio, {3, 4})
    for _ in range(3):
        samples = observe(studio, lambda: (studio.cards[3].set_expanded(True),
                                          studio.cards[4].set_expanded(True)))
        assert_screen_anchor(samples, range(4))
        assert studio.bar.maximum() == initial_maximum
        assert studio.inner.minimumHeight() == 0
        assert_settled(studio, set())
        samples = observe(studio, lambda: (studio.cards[3].set_expanded(False),
                                          studio.cards[4].set_expanded(False)))
        assert_screen_anchor(samples, range(4))
        assert studio.bar.maximum() == initial_maximum
        assert studio.inner.minimumHeight() == studio.scroll.viewport().height() + studio.bar.value()
