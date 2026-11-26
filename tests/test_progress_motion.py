"""Visible feedback advances by elapsed time and stops when no longer visible."""
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QProgressBar

from app.ui import style, task_window
from app.ui.task_window import ProgressBar, TaskWindow


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def wait_until(app, predicate, timeout=1800):
    start = time.monotonic()
    while not predicate():
        assert (time.monotonic() - start) * 1000 < timeout
        app.processEvents()
        QTest.qWait(5)


def test_custom_busy_feedback_is_self_driven_and_stops_while_hidden(app):
    bar = ProgressBar()
    bar.resize(260, 8)
    bar.set_indeterminate(True)
    assert not bar._timer.isActive()
    bar.show()
    wait_until(app, lambda: bar._phase > .08)
    first = bar.grab().toImage()
    QTest.qWait(180)
    assert bar.grab().toImage() != first
    bar.hide()
    phase = bar._phase
    assert not bar._timer.isActive()
    QTest.qWait(70)
    assert bar._phase == phase
    bar.show()
    wait_until(app, lambda: bar._phase != phase)
    bar.set_indeterminate(False)
    wait_until(app, lambda: not bar._timer.isActive())
    bar.close()


def test_task_window_plays_waiting_feedback_without_an_external_tick(app):
    window = TaskWindow("测试等待状态")
    try:
        window.show()
        wait_until(app, lambda: window.bar._timer.isActive() and window.bar._phase > .03)
        window.set_success()
        wait_until(app, lambda: window.bar._display_value == 1)
        assert not window.bar._timer.isActive()
    finally:
        window._finished = True
        window.close()


def test_progress_target_changes_retain_rendered_position_and_velocity(app):
    bar = ProgressBar()
    bar.show()
    try:
        bar.set_value(.8)
        wait_until(app, lambda: .2 < bar._display_value < .75)
        position, velocity = bar._display_value, bar._velocity
        bar.set_value(.35)
        assert bar._value == .35
        assert bar._display_value == position
        assert bar._velocity == velocity
        wait_until(app, lambda: not bar._timer.isActive())
        assert bar._display_value == .35
        assert bar._velocity == 0
        bar.set_value(1)
        wait_until(app, lambda: not bar._timer.isActive())
        assert bar._display_value == 1
    finally:
        bar.close()


def test_hidden_or_disabled_progress_settles_without_an_idle_clock(app):
    bar = ProgressBar()
    bar.set_value(.4)
    assert bar._display_value == .4
    assert not bar._timer.isActive()
    bar.show()
    bar.set_value(.9)
    assert bar._timer.isActive()
    bar.setEnabled(False)
    assert bar._display_value == .9
    assert not bar._timer.isActive()
    bar.setEnabled(True)
    bar.set_indeterminate(True)
    assert bar._timer.isActive()
    bar.hide()
    assert not bar._timer.isActive()
    bar.close()


def test_busy_position_depends_on_elapsed_time_not_tick_count(app, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(task_window, "time", SimpleNamespace(perf_counter=lambda: clock[0]))
    bar = ProgressBar()
    bar.show()
    bar.set_indeterminate(True)
    bar._timer.stop()  # Manual delivery to model unequal event-loop scheduling.
    clock[0] += .28
    bar._advance()
    bar._timer.stop()
    assert bar._phase == pytest.approx(.2)
    clock[0] += .14
    bar._advance()
    bar._timer.stop()
    assert bar._phase == pytest.approx(.3)
    bar.hide()
    bar.close()


@pytest.mark.parametrize("orientation", [Qt.Horizontal, Qt.Vertical])
def test_native_busy_feedback_moves_and_releases_hidden_bars(app, orientation):
    painter = style.install_continuous_style(app)
    bar = QProgressBar()
    bar.setOrientation(orientation)
    bar.setTextVisible(False)
    bar.setStyleSheet(style.STYLESHEET)
    bar.resize(240, 10) if orientation == Qt.Horizontal else bar.resize(10, 240)
    bar.setRange(0, 0)
    bar.show()
    try:
        wait_until(app, lambda: bar in painter._busy and painter._timer.isActive())
        first = bar.grab().toImage()
        QTest.qWait(197)
        second = bar.grab().toImage()
        assert second != first
        # A vertical bar must carry the band along its length, not its 10px width.
        blue = []
        for n in range(240):
            x, y = (n, 5) if orientation == Qt.Horizontal else (5, n)
            if second.pixelColor(x, y).name() == style.PRIMARY:
                blue.append(n)
        assert 0 < len(blue) < 100
        bar.hide()
        wait_until(app, lambda: bar not in painter._busy)
        assert not painter._timer.isActive()
    finally:
        bar.close()
