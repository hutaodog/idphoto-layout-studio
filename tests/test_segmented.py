"""Capsule interaction regressions, including the studio radio feedback path."""
import math
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("IDPHOTO_NO_UPDATE", "1")

import pytest
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from app.ui import segmented as ui


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    instance.setQuitOnLastWindowClosed(False)
    return instance


@pytest.fixture
def control(app):
    widget = ui.SegmentedControl(["单个", "排版", "对比"])
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def click(control, index):
    QTest.mouseClick(control, Qt.LeftButton, pos=control._seg_rect(index).center().toPoint())


def fake_clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(ui, "time", SimpleNamespace(perf_counter=lambda: now[0]))
    return now


def test_click_reversal_preserves_last_rendered_position_and_speed(control, monkeypatch):
    now = fake_clock(monkeypatch)
    signals = QSignalSpy(control.currentChanged)
    click(control, 2)
    now[0] += 0.055
    control._anim.setCurrentTime(185)
    position, velocity = control._pos, control._velocity
    rectangle = control._seg_rect(position)
    assert 0 < position < 2 and velocity > 0

    # A click between frames must not sample ahead along the old trajectory.
    now[0] += 0.011
    applied = []
    original = control._set_pos
    monkeypatch.setattr(control, "_set_pos", lambda value: (applied.append(value), original(value)))
    click(control, 0)
    assert control.current() == 0
    assert control._start_pos == control._pos == position
    assert control._start_velocity == control._velocity == velocity
    assert control._seg_rect(control._pos) == rectangle
    assert applied == []
    control._tick_transition()
    assert control._pos == position and control._velocity == velocity
    now[0] += 0.001
    control._tick_transition()
    assert control._pos > position  # Momentum decelerates before direction changes.
    assert [signals.at(i)[0] for i in range(signals.count())] == [2, 0]


def test_rapid_clicks_stay_inside_shell_and_stop_exactly(control, monkeypatch):
    now = fake_clock(monkeypatch)
    signals = QSignalSpy(control.currentChanged)
    choices = [2, 0, 1, 2, 0] * 8
    for index in choices:
        position, velocity = control._pos, control._velocity
        click(control, index)
        assert control._pos == position and control._velocity == velocity
        for _ in range(4):
            now[0] += 0.004
            control._tick_transition()
            assert math.isfinite(control._pos) and math.isfinite(control._velocity)
            assert 0 <= control._pos <= 2
            rectangle = control._seg_rect(control._pos)
            assert rectangle.left() >= ui.PAD
            assert rectangle.right() <= control.width() - ui.PAD
    assert signals.count() == len(choices)
    now[0] += 0.8
    control._tick_transition()
    assert control.current() == control._pos == 0
    assert control._velocity == 0
    assert control._anim.state() == QAbstractAnimation.Stopped
    stopped = (control._pos, control._velocity)
    now[0] += 5
    control._tick_transition()
    assert (control._pos, control._velocity) == stopped


@pytest.mark.parametrize("target", [1, 2])
def test_explicit_snap_cancels_old_animation_including_same_index(control, monkeypatch, target):
    now = fake_clock(monkeypatch)
    signals = QSignalSpy(control.currentChanged)
    click(control, 2)
    now[0] += 0.04
    control._tick_transition()
    assert 0 < control._pos < 2
    control.set_current(target, animate=False)
    assert control._anim.state() == QAbstractAnimation.Stopped
    assert control._pos == control.current() == target and control._velocity == 0
    assert signals.count() == (1 if target == 2 else 2)
    now[0] += 0.5
    control._tick_transition()
    assert control._pos == target


def test_clicking_back_before_first_frame_leaves_no_idle_clock(control, monkeypatch):
    fake_clock(monkeypatch)
    signals = QSignalSpy(control.currentChanged)
    click(control, 2)
    assert control._anim.state() == QAbstractAnimation.Running
    click(control, 0)
    assert control._pos == 0 and control._velocity == 0
    assert control._anim.state() == QAbstractAnimation.Stopped
    assert [signals.at(i)[0] for i in range(signals.count())] == [2, 0]


def test_redundant_selection_and_invalid_index_do_not_restart_or_emit(control, monkeypatch):
    now = fake_clock(monkeypatch)
    signals = QSignalSpy(control.currentChanged)
    click(control, 1)
    started_at = control._started_at
    now[0] += 0.035
    control._tick_transition()
    position, velocity = control._pos, control._velocity
    click(control, 1)
    control.set_current(-1)
    control.set_current(9)
    assert control._started_at == started_at
    assert (control._pos, control._velocity) == (position, velocity)
    assert signals.count() == 1


@pytest.mark.parametrize("action", ["hide", "disable"])
def test_hidden_or_disabled_capsule_settles_without_running_clock(control, monkeypatch, action):
    now = fake_clock(monkeypatch)
    signals = QSignalSpy(control.currentChanged)
    click(control, 2)
    now[0] += 0.045
    control._tick_transition()
    assert 0 < control._pos < 2
    control.hide() if action == "hide" else control.setEnabled(False)
    assert control._anim.state() == QAbstractAnimation.Stopped
    assert control._pos == 2 and control._velocity == 0
    control.set_current(1)
    assert control._pos == 1 and control._anim.state() == QAbstractAnimation.Stopped
    control.show() if action == "hide" else control.setEnabled(True)
    assert signals.count() == 2
    assert control._pos == 1 and control._anim.state() == QAbstractAnimation.Stopped


def test_real_event_loop_reverses_and_reaches_idle(control):
    signals = QSignalSpy(control.currentChanged)
    click(control, 2)
    QTest.qWait(70)
    position = control._pos
    assert 0 < position < 2
    click(control, 0)
    assert control._pos == position
    QTest.qWait(600)
    assert control._pos == 0 and control._velocity == 0
    assert control._anim.state() == QAbstractAnimation.Stopped
    assert [signals.at(i)[0] for i in range(signals.count())] == [2, 0]


def test_studio_radio_sync_does_not_cancel_capsule_motion(app, monkeypatch, tmp_path):
    from app.core import settings
    from app.ui.main_window import MainWindow

    monkeypatch.setattr(settings, "settings_path", lambda: str(tmp_path / "settings.json"))
    win = MainWindow()
    win.resize(1340, 860)
    win.show()
    QTest.qWait(60)
    try:
        control = win.preview_toggle
        signals = QSignalSpy(control.currentChanged)
        click(control, 1)
        assert win.rb_layout.isChecked()
        assert control.current() == 1 and control._pos == 0
        assert control._anim.state() == QAbstractAnimation.Running
        QTest.qWait(65)
        assert 0 < control._pos < 1
        click(control, 0)
        assert win.rb_photo.isChecked()
        assert control._anim.state() == QAbstractAnimation.Running
        QTest.qWait(600)
        assert control._pos == 0 and control._velocity == 0
        assert control._anim.state() == QAbstractAnimation.Stopped
        assert [signals.at(i)[0] for i in range(signals.count())] == [1, 0]
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()
