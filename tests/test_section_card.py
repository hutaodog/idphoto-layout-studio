"""Card motion regressions: continuous reversals and independent live layouts."""
import math
import time
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QAbstractAnimation, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QVBoxLayout, QWidget

from app.ui import section_card as ui


@pytest.fixture
def panel():
    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    host = QScrollArea()
    host.setWidgetResizable(True)
    host.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    body = QWidget()
    layout = QVBoxLayout(body)
    labels, cards = [], []
    for title in ("证件照规格", "背景底色", "构图微调"):
        label = QLabel("固定尺寸正文\n" * 12)
        label.setWordWrap(True)
        card = ui.SectionCard(title, label, expanded=False)
        layout.addWidget(card)
        labels.append(label)
        cards.append(card)
    layout.addStretch(1)
    host.setWidget(body)
    host.resize(420, 700)
    host.show()
    QTest.qWait(50)
    yield SimpleNamespace(app=app, host=host, cards=cards, labels=labels)
    host.close()
    host.deleteLater()
    app.processEvents()


def click(card):
    QTest.mouseClick(card.header, Qt.LeftButton, pos=QPoint(80, 22))


def fake_clock(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(ui, "time", SimpleNamespace(perf_counter=lambda: now[0]))
    return now


def test_reverse_retains_position_and_velocity_without_setup_jumps(panel, monkeypatch):
    card = panel.cards[0]
    now = fake_clock(monkeypatch)
    click(card)
    # Showing a previously hidden body may deliver a new width synchronously;
    # that content measurement must retarget, without snapping it fully open.
    assert card._height == card._wrap.height() == 0
    assert card._animation.state() == QAbstractAnimation.Running
    now[0] += 0.085
    card._tick_transition()
    height, velocity = card._height, card._velocity
    assert height > 0 and velocity > 0
    # Reusing a stopped QVariantAnimation at a nonzero currentTime used to emit
    # several interpolated values from the old endpoints during setter calls.
    card._animation.setCurrentTime(185)
    applied = []
    original = card._apply_height
    monkeypatch.setattr(card, "_apply_height", lambda h: (applied.append(h), original(h)))
    # Input may arrive between shared-clock ticks: keep the rendered frame,
    # rather than sampling forward along the outgoing spring during the click.
    now[0] += 0.011
    click(card)
    assert card._start_height == pytest.approx(height)
    assert card._start_velocity == pytest.approx(velocity)
    assert applied == []
    card._tick_transition()
    assert card._height == pytest.approx(height)
    assert card._velocity == pytest.approx(velocity)
    now[0] += 0.06
    card._tick_transition()
    height, velocity = card._height, card._velocity
    click(card)
    assert card._start_height == pytest.approx(height)
    assert card._start_velocity == pytest.approx(velocity)


def test_animation_frames_never_remeasure_or_resize_body(panel, monkeypatch):
    card = panel.cards[0]
    now = fake_clock(monkeypatch)
    click(card)
    panel.app.processEvents()
    body_geometry = card._wrap.body.geometry()
    calls = []
    monkeypatch.setattr(card._wrap, "natural_height", lambda: calls.append(True) or 9999)
    for i in range(1, 61):
        now[0] += 0.006
        card._tick_transition()
    assert calls == []
    assert card._wrap.body.geometry() == body_geometry


def test_redundant_open_does_not_restart_motion(panel, monkeypatch):
    card = panel.cards[0]
    now = fake_clock(monkeypatch)
    click(card)
    started = card._started_at
    now[0] += 0.05
    card.set_expanded(True)
    assert card._started_at == started


def test_many_reversals_are_finite_and_reach_exact_endpoint(panel, monkeypatch):
    card = panel.cards[0]
    now = fake_clock(monkeypatch)
    for i in range(31):
        click(card)
        for _ in range(3):
            now[0] += 0.008
            card._tick_transition()
            assert math.isfinite(card._height) and math.isfinite(card._velocity)
            assert 0 <= card._height <= card._open_height * 1.03
    assert card.is_expanded()
    now[0] += 0.8
    card._tick_transition()
    assert card._animation.state() == QAbstractAnimation.Stopped
    assert card._wrap.height() == card._open_height
    assert card._velocity == 0
    click(card)
    now[0] += 0.8
    card._tick_transition()
    assert card._wrap.isHidden() and card._wrap.height() == 0
    assert card._velocity == 0


def test_dynamic_content_retargets_without_teleporting(panel, monkeypatch):
    card = panel.cards[0]
    now = fake_clock(monkeypatch)
    click(card)
    now[0] += 0.07
    card._tick_transition()
    height, velocity = card._height, card._velocity
    old_target = card._open_height
    now[0] += 0.011
    panel.labels[0].setText("增长的正文\n" * 22)
    for _ in range(5):
        panel.app.processEvents()
    assert card._open_height > old_target
    assert card._start_height == pytest.approx(height)
    assert card._start_velocity == pytest.approx(velocity)
    assert card._wrap.height() == round(height)
    now[0] += 0.8
    card._tick_transition()
    assert card._wrap.height() == card._open_height


def test_collapsed_content_change_stays_closed(panel):
    card = panel.cards[0]
    panel.labels[0].setText("更长的描述\n" * 30)
    QTest.qWait(30)
    assert card._wrap.isHidden() and card._wrap.height() == 0
    click(card)
    QTest.qWait(600)
    assert card._wrap.height() == card._open_height == card._wrap.natural_height()


def test_real_event_loop_two_cards_reverse_independently(panel):
    a, b, c = panel.cards
    click(a)
    QTest.qWait(70)
    click(b)
    natural = [card._wrap.body.height() for card in (a, b)]
    samples = []
    for i in range(16):
        click(b)
        if i % 3 == 0:
            click(a)
        QTest.qWait(14)
        samples.append((a._wrap.height(), b._wrap.height(), c.y()))
        assert [card._wrap.body.height() for card in (a, b)] == natural
    a.set_expanded(True)
    b.set_expanded(False)
    QTest.qWait(650)
    assert a._animation.state() == b._animation.state() == QAbstractAnimation.Stopped
    assert a._wrap.height() == a._open_height
    assert b._wrap.isHidden() and b._wrap.height() == 0
    assert len(set(samples)) > 8
    # The third card tracks the two animated heights, never a stale minimum.
    assert c.y() == b.y() + b.height() + panel.host.widget().layout().spacing()


def test_hiding_mid_motion_settles_without_running_timer(panel):
    card = panel.cards[0]
    click(card)
    QTest.qWait(50)
    panel.host.hide()
    assert card._animation.state() == QAbstractAnimation.Stopped
    assert card._wrap.height() == card._open_height
    panel.host.show()
    QTest.qWait(30)
    assert card._wrap.height() == card._open_height


@pytest.mark.parametrize("expanded", [True, False])
def test_disabling_mid_motion_settles_without_a_live_clock(panel, monkeypatch, expanded):
    card = panel.cards[0]
    card.set_expanded(not expanded, animate=False)
    now = fake_clock(monkeypatch)
    click(card)
    now[0] += 0.065
    card._tick_transition()
    assert card._animation.state() == QAbstractAnimation.Running
    card.setEnabled(False)
    target = card._open_height if expanded else 0
    assert card._height == card._wrap.height() == target
    assert card._velocity == 0 and card._wrap.isHidden() != expanded
    assert card._animation.state() == QAbstractAnimation.Stopped
    now[0] += 0.25
    card._tick_transition()
    card.setEnabled(True)
    assert card._height == target and card._animation.state() == QAbstractAnimation.Stopped


def test_scroll_host_is_notified_before_each_rendered_height_change(panel, monkeypatch):
    card = panel.cards[0]
    now = fake_clock(monkeypatch)
    click(card)
    observations = []
    card.heightAboutToChange.connect(lambda: observations.append(card._wrap.height()))
    natural_geometry = card._wrap.body.geometry()
    for _ in range(5):
        previous_height = card._wrap.height()
        now[0] += 0.025
        card._tick_transition()
        assert observations[-1] == previous_height
        assert card._wrap.height() > previous_height
        assert card._wrap.body.geometry() == natural_geometry
    assert len(observations) == 5
