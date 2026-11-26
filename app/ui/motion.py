"""Shared, frame-rate independent spring motion in seconds and logical units.

Profiles use angular natural frequency (radians/second) and damping ratio.
The solver returns both position and velocity, so a new target can start from
exactly the last rendered state. Clipping and endpoint settling belong to the
widget: this pure helper never silently discards momentum or changes bounds.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MotionProfile:
    frequency: float
    damping: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.frequency) or self.frequency <= 0.0:
            raise ValueError("frequency must be finite and greater than zero")
        if not math.isfinite(self.damping) or self.damping < 0.0:
            raise ValueError("damping must be finite and nonnegative")


# Critical damping gives quick, calm arrivals without a repeated bounce. A
# reveal affords time to read newly exposed content; dismissal is more direct.
REVEAL_OPEN = MotionProfile(frequency=24.0, damping=1.0)
REVEAL_CLOSE = MotionProfile(frequency=32.0, damping=1.0)
SELECTION = MotionProfile(frequency=36.0, damping=1.0)
FEEDBACK = MotionProfile(frequency=26.0, damping=1.0)


def busy_band(phase: float) -> tuple[float, float]:
    """Return a periodic busy indicator's normalized (offset, length).

    One phase unit is a full outward-and-return cycle. The band travels beyond
    both ends of a clipped track, with zero speed at each turn and no wrap jump.
    """
    if not math.isfinite(phase):
        raise ValueError("busy phase must be finite")
    length = 0.30
    travel = 0.5 - 0.5 * math.cos(math.tau * (phase % 1.0))
    return (1.0 + length) * travel - length, length


def spring_state(position: float, velocity: float, target: float, elapsed: float,
                 *, frequency: float, damping: float) -> tuple[float, float]:
    """Solve x'' + 2*damping*frequency*x' + frequency**2*(x-target) = 0.

    ``velocity`` is in logical units/second, and ``elapsed`` is in seconds.
    Nonpositive elapsed time preserves the supplied state exactly. All three
    damping regimes are supported, including an undamped oscillator. Inputs
    must be finite; frequency must be positive and damping nonnegative.
    """
    if not math.isfinite(frequency) or frequency <= 0.0:
        raise ValueError("frequency must be finite and greater than zero")
    if not math.isfinite(damping) or damping < 0.0:
        raise ValueError("damping must be finite and nonnegative")
    if not all(math.isfinite(value) for value in (position, velocity, target, elapsed)):
        raise ValueError("spring state and elapsed time must be finite")
    if elapsed <= 0.0:
        return position, velocity

    offset = position - target
    omega = frequency
    if damping < 1.0:
        decay_rate = damping * omega
        damped_frequency = omega * math.sqrt((1.0 - damping) * (1.0 + damping))
        phase = damped_frequency * elapsed
        cosine, sine = math.cos(phase), math.sin(phase)
        coefficient = (velocity + decay_rate * offset) / damped_frequency
        decay = math.exp(-decay_rate * elapsed)
        displacement = decay * (offset * cosine + coefficient * sine)
        speed = decay * (velocity * cosine
                         - (decay_rate * coefficient + damped_frequency * offset) * sine)
    elif damping == 1.0:
        coefficient = velocity + omega * offset
        decay = math.exp(-omega * elapsed)
        displacement = decay * (offset + coefficient * elapsed)
        speed = decay * (velocity - omega * coefficient * elapsed)
    else:
        # Separate decaying roots avoid cosh/sinh overflow. expm1 keeps this
        # expression accurate even for a damping ratio very close to one.
        root = math.sqrt((damping - 1.0) * (damping + 1.0))
        slow = -omega / (damping + root)
        fast = -omega * (damping + root)
        gap = fast - slow
        remainder = velocity - slow * offset
        displacement = math.exp(slow * elapsed) * (
            offset + remainder / gap * math.expm1(gap * elapsed))
        speed = slow * displacement + remainder * math.exp(fast * elapsed)
    return target + displacement, speed
