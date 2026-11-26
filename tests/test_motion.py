"""Physical invariants of the shared spring, independent of any Qt clock."""
from dataclasses import FrozenInstanceError
import math

import pytest

from app.ui.motion import (FEEDBACK, REVEAL_CLOSE, REVEAL_OPEN, SELECTION,
                           MotionProfile, busy_band, spring_state)


@pytest.mark.parametrize("damping", [0.0, 0.55, 0.999999, 1.0, 1.000001, 2.5, 10.0])
def test_spring_is_independent_of_frame_partition(damping):
    kwargs = {"frequency": 24.0, "damping": damping}
    expected = spring_state(18.0, -73.0, 140.0, 0.237, **kwargs)
    position, velocity = 18.0, -73.0
    for elapsed in (0.007, 0.041, 0.003, 0.086, 0.100):
        position, velocity = spring_state(position, velocity, 140.0, elapsed, **kwargs)
    assert (position, velocity) == pytest.approx(expected, rel=1e-10, abs=1e-9)


@pytest.mark.parametrize("damping", [0.0, 0.6, 1.0, 1.000001, 3.0])
def test_velocity_matches_position_derivative_and_spring_acceleration(damping):
    kwargs = {"frequency": 21.0, "damping": damping}
    dt, elapsed = 1e-6, 0.073
    before = spring_state(7.0, 19.0, 82.0, elapsed - dt, **kwargs)
    position, velocity = spring_state(7.0, 19.0, 82.0, elapsed, **kwargs)
    after = spring_state(7.0, 19.0, 82.0, elapsed + dt, **kwargs)
    assert (after[0] - before[0]) / (2 * dt) == pytest.approx(velocity, rel=1e-7)
    acceleration = -2 * damping * 21.0 * velocity - 21.0 ** 2 * (position - 82.0)
    assert (after[1] - before[1]) / (2 * dt) == pytest.approx(acceleration, rel=1e-7)


def test_undamped_motion_conserves_energy_without_clipping():
    energy = 13.0 ** 2 + 17.0 ** 2 * (8.0 - 5.0) ** 2
    positions = []
    for elapsed in (0.0, 0.03, 0.17, 0.4, 0.7, 1.2):
        position, velocity = spring_state(8.0, 13.0, 5.0, elapsed,
                                          frequency=17.0, damping=0.0)
        positions.append(position)
        assert velocity ** 2 + 17.0 ** 2 * (position - 5.0) ** 2 == pytest.approx(energy)
    assert min(positions) < 5.0 < max(positions)


@pytest.mark.parametrize("profile", [REVEAL_OPEN, REVEAL_CLOSE, SELECTION, FEEDBACK])
@pytest.mark.parametrize("start,target", [(0.0, 1.0), (300.0, 0.0)])
def test_profiles_arrive_monotonically_without_bounce(profile, start, target):
    samples = [spring_state(start, 0.0, target, i / 1000,
                            frequency=profile.frequency, damping=profile.damping)[0]
               for i in range(601)]
    direction = 1 if target > start else -1
    assert all(direction * (b - a) >= -1e-12 for a, b in zip(samples, samples[1:]))
    assert all(min(start, target) <= value <= max(start, target) for value in samples)
    assert abs(samples[-1] - target) < abs(target - start) * 0.00002


def test_reveals_take_longer_than_dismissal_and_profiles_are_frozen():
    def remaining(profile):
        position, _ = spring_state(0.0, 0.0, 1.0, 0.15,
                                   frequency=profile.frequency, damping=profile.damping)
        return 1.0 - position

    assert remaining(REVEAL_CLOSE) < remaining(REVEAL_OPEN)
    with pytest.raises(FrozenInstanceError):
        SELECTION.frequency = 99.0


@pytest.mark.parametrize("elapsed", [0.0, -0.05])
def test_retarget_starts_at_exact_position_and_velocity(elapsed):
    assert spring_state(0.42, 7.5, 0.0, elapsed,
                        frequency=SELECTION.frequency,
                        damping=SELECTION.damping) == (0.42, 7.5)


@pytest.mark.parametrize("frequency,damping", [(0.0, 1.0), (-1.0, 1.0),
                                               (math.inf, 1.0), (24.0, -0.5),
                                               (24.0, math.nan)])
def test_invalid_profiles_fail_explicitly(frequency, damping):
    with pytest.raises(ValueError):
        MotionProfile(frequency, damping)
    with pytest.raises(ValueError):
        spring_state(0.0, 0.0, 1.0, 0.1, frequency=frequency, damping=damping)


@pytest.mark.parametrize("state", [(math.nan, 0.0, 1.0, 0.1),
                                   (0.0, math.inf, 1.0, 0.1),
                                   (0.0, 0.0, math.nan, 0.1),
                                   (0.0, 0.0, 1.0, math.inf)])
def test_nonfinite_state_fails_explicitly(state):
    with pytest.raises(ValueError):
        spring_state(*state, frequency=24.0, damping=1.0)


@pytest.mark.parametrize("phase", [-2.75, -0.01, 0.0, 0.17, 0.5, 0.99, 4.0])
def test_busy_band_is_periodic_and_stays_within_its_clipped_track_extent(phase):
    offset, length = busy_band(phase)
    assert length == 0.30
    assert -length <= offset <= 1.0
    assert busy_band(phase + 3) == pytest.approx((offset, length))
    assert busy_band(phase - 2) == pytest.approx((offset, length))


def test_busy_band_turns_smoothly_and_crosses_the_track_in_both_directions():
    assert busy_band(0.0) == (-0.30, 0.30)
    assert busy_band(0.5) == (1.0, 0.30)
    assert busy_band(0.25) == pytest.approx(busy_band(0.75))
    for turn in (0.0, 0.5, 1.0):
        before = busy_band(turn - 1e-6)[0]
        after = busy_band(turn + 1e-6)[0]
        assert (after - before) / 2e-6 == pytest.approx(0.0, abs=1e-8)
        assert abs(after - busy_band(turn)[0]) < 1e-9
    assert busy_band(0.2)[0] < busy_band(0.3)[0]
    assert busy_band(0.7)[0] > busy_band(0.8)[0]


@pytest.mark.parametrize("phase", [math.inf, -math.inf, math.nan])
def test_busy_band_rejects_nonfinite_phase(phase):
    with pytest.raises(ValueError):
        busy_band(phase)
