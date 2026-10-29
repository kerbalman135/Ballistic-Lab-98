"""Projectile calculations and grid-crossing times for constant acceleration.

Units: metres, seconds, kilograms, joules and degrees.
Positive y points upward; positive g acts downward.
"""

import math
from bisect import bisect_right
from dataclasses import dataclass
import numpy as np


class GravityField:
    """One uniform value or any number of equal-width horizontal regions."""

    def __init__(self, width, values):
        self.values = tuple(values)
        if (not math.isfinite(width) or width <= 0 or not self.values
                or not all(math.isfinite(value) for value in self.values)):
            raise ValueError("Gravity needs a positive width and at least one finite value.")
        self.width = width
        self.boundaries = tuple(width * index / len(self.values)
                                for index in range(1, len(self.values)))

    def gravity_at(self, x):
        # Exact internal boundaries belong to the region on their right.
        return self.values[bisect_right(self.boundaries, x)]


@dataclass(frozen=True)
class MotionSegment:
    start_time: float
    duration: float
    origin: tuple
    velocity: tuple
    gravity: float
    ax: float

    def position_at(self, local_time):
        return calculate_position(local_time, *self.velocity, self.gravity, *self.origin, self.ax)

    def velocity_at(self, local_time):
        return (self.velocity[0] + self.ax * local_time,
                self.velocity[1] - self.gravity * local_time)


def iter_motion_segments(origin, velocity, field, ax, duration):
    """Yield analytic segments, split at every outward/return zone crossing.

    Horizontal motion is independent of gravity. Solve all boundary times
    from the original x, vx and constant wind, then choose each interval's
    region by its midpoint. This avoids zero-duration boundary loops and
    also handles a tangent boundary touch without a region change.
    """
    if duration <= 0:
        raise ValueError("Motion duration must be positive.")
    events = {0.0, duration}
    for boundary in field.boundaries:
        events.update(times_at_coordinate(origin[0], velocity[0], ax, boundary, duration))
    events = sorted(events)
    position, current_velocity = origin, velocity
    for start, end in zip(events[:-1], events[1:]):
        if end <= start:
            continue
        middle = (start + end) / 2
        x_middle = origin[0] + velocity[0] * middle + 0.5 * ax * middle**2
        segment = MotionSegment(start, end - start, position, current_velocity,
                                field.gravity_at(x_middle), ax)
        yield segment
        position = segment.position_at(segment.duration)
        current_velocity = segment.velocity_at(segment.duration)


def calculate_initial_speed(charge_count, shell_mass, energy_per_charge):
    """Return launch speed from the effective energy supplied by the charges."""
    if shell_mass <= 0:
        raise ValueError("Shell mass must be greater than zero.")
    if charge_count < 0 or energy_per_charge < 0:
        raise ValueError("Charge count and energy must not be negative.")

    total_energy = charge_count * energy_per_charge
    return math.sqrt(2 * total_energy / shell_mass)


def calculate_velocity_components(initial_speed, angle_degrees, direction=1):
    """Return horizontal and vertical launch velocities."""
    if direction not in (-1, 1):
        raise ValueError("Direction must be -1 (left) or 1 (right).")
    angle = math.radians(angle_degrees)
    vx = direction * initial_speed * math.cos(angle)
    vy = initial_speed * math.sin(angle)
    return vx, vy


def calculate_position(t, vx, vy, g=9.8, x0=0.0, y0=0.0, ax=0.0):
    """Return position at one time or an array, with constant gravity and ax."""
    x = x0 + vx * t + 0.5 * ax * t**2
    y = y0 + vy * t - 0.5 * g * t**2
    return x, y


def times_at_coordinate(position, velocity, acceleration, coordinate, duration):
    """Solve p + v*t + a*t*t/2 = coordinate within [0, duration].

    This supplies exact grid-crossing events, independent of drawing frames.
    The stable quadratic formula avoids cancellation for fast projectiles.
    A stationary coordinate needs no event: interval probes handle it.
    """
    a = 0.5 * acceleration
    b = velocity
    c = position - coordinate
    if abs(a) < 1e-14:
        roots = [] if abs(b) < 1e-14 else [-c / b]
    else:
        discriminant = b * b - 4 * a * c
        if discriminant < 0:
            return []
        q = -0.5 * (b + math.copysign(math.sqrt(discriminant), b))
        roots = [-b / (2 * a)] if q == 0 else [q / a, c / q]
    return sorted({max(0.0, min(duration, t)) for t in roots
                   if -1e-10 <= t <= duration + 1e-10})


def first_circle_contact(origin, velocity, g, centre, radius, duration, ax=0.0):
    """Return first time a point projectile touches a circle, or None.

    Squared distance to the target is a quartic in time. Its derivative
    is cubic: the real roots divide the path into monotonic-distance
    intervals. Inspect those in order and bisect the first entry. Also
    test the turning points to include tangencies. No visual samples are
    used. Time is scaled to [0, 1] for the polynomial root calculation.
    """
    if radius <= 0 or duration < 0:
        raise ValueError("Circle radius must be positive and duration nonnegative.")
    dx, dy = origin[0] - centre[0], origin[1] - centre[1]
    if dx * dx + dy * dy <= radius * radius:
        return 0.0
    if duration == 0:
        return None

    x_terms = (dx, velocity[0] * duration, 0.5 * ax * duration**2)
    y_terms = (dy, velocity[1] * duration, -0.5 * g * duration**2)
    polynomial = np.polynomial.polynomial.polyadd(
        np.polynomial.polynomial.polymul(x_terms, x_terms),
        np.polynomial.polynomial.polymul(y_terms, y_terms))
    derivative = np.polynomial.polynomial.polyder(polynomial)
    roots = np.polynomial.polynomial.polyroots(derivative)
    events = sorted({0.0, 1.0} | {float(root.real) for root in roots
                    if abs(root.imag) < 1e-8 and 0 < root.real < 1})

    def distance_error(fraction):
        # Evaluate the coordinates directly, avoiding cancellation of the
        # expanded quartic near a small target at the end of a long path.
        x = x_terms[0] + fraction * (x_terms[1] + fraction * x_terms[2])
        y = y_terms[0] + fraction * (y_terms[1] + fraction * y_terms[2])
        return x * x + y * y - radius * radius

    tolerance = 1e-10 * max(1.0, radius * radius)
    for left, right in zip(events[:-1], events[1:]):
        if distance_error(left) <= tolerance:
            return left * duration
        right_error = distance_error(right)
        if right_error < 0:
            for _ in range(60):
                middle = (left + right) / 2
                if distance_error(middle) <= 0:
                    right = middle
                else:
                    left = middle
            return (left + right) * 0.5 * duration
        if right_error <= tolerance:
            return right * duration
    return None


def generate_trajectory(initial_speed, angle_degrees, g=9.8,
                        x0=0.0, y0=0.0, num_points=201):
    """Return time, x and y arrays ending at ground level (y = 0).

    This first version requires g > 0. Sampling the analytic solution
    does not use numerical integration.
    """
    if g <= 0:
        raise ValueError("This version requires constant downward gravity: g > 0.")
    if initial_speed < 0 or y0 < 0:
        raise ValueError("Initial speed and height must not be negative.")
    if num_points < 2:
        raise ValueError("Use at least two sample points.")

    vx, vy = calculate_velocity_components(initial_speed, angle_degrees)

    # Solve y0 + vy*t - 0.5*g*t**2 = 0 for the landing time.
    flight_time = (vy + math.sqrt(vy**2 + 2 * g * y0)) / g

    if flight_time == 0:
        times = np.array([0.0])
    else:
        times = np.linspace(0, flight_time, num_points)

    x, y = calculate_position(times, vx, vy, g, x0, y0)
    y[-1] = 0.0  # Remove tiny floating-point error at the landing point.
    return times, x, y


if __name__ == "__main__":
    speed = calculate_initial_speed(2, 1.0, 50.0)
    times, x, y = generate_trajectory(speed, 45)

    print(f"Initial speed: {speed:.2f} m/s")
    print(f"Flight time: {times[-1]:.2f} s")
    print(f"Range: {x[-1] - x[0]:.2f} m")
    print(f"Maximum sampled height: {y.max():.2f} m")
