"""Targets, scoring and safe shot lifecycle, independent of the UI."""

from dataclasses import dataclass
import math
import random
import time
from datetime import datetime, timezone
import numpy as np

from . import game_data as data
from .physics import (calculate_initial_speed, calculate_velocity_components,
                     calculate_position, first_circle_contact, GravityField,
                     MotionSegment, iter_motion_segments)
from .terrain import Terrain, ImpactArea
from .scores import ScoreStore


_KEEP_FUSE = object()


@dataclass(frozen=True)
class Target:
    identifier: int
    position: tuple
    kind: str
    radius: float = data.TARGET_RADIUS


@dataclass
class Shot:
    shell: str
    origin: tuple
    velocity: tuple
    gravity: float
    duration: float
    reason: str
    times: np.ndarray
    x: np.ndarray
    y: np.ndarray
    area: object = None
    removed_cells: int = 0
    resolved: bool = False
    direct_target_id: object = None
    hit_target_ids: tuple = ()
    points_earned: int = 0
    segments: tuple = ()
    gravity_field: object = None
    wind_ax: float = 0.0
    fuse_time: object = None
    charges: int = 0

    def _segment_at(self, time):
        return next(segment for segment in reversed(self.segments)
                    if segment.start_time <= max(0.0, time))

    def position_at(self, time):
        if self.segments:
            segment = self._segment_at(time)
            return segment.position_at(min(max(0.0, time - segment.start_time), segment.duration))
        return calculate_position(time, *self.velocity, self.gravity, *self.origin, self.wind_ax)

    def velocity_at(self, time):
        segment = self._segment_at(time)
        return segment.velocity_at(min(max(0.0, time - segment.start_time), segment.duration))

    def gravity_at(self, time):
        return self.gravity_field.gravity_at(self.position_at(time)[0])


class Game:
    def __init__(self, random_seed=None, score_store=None, clock=None,
                 mixed_gravity_regions=None, target_gravity_bias=None):
        self.mixed_gravity_regions = (data.MIXED_GRAVITY_REGIONS if mixed_gravity_regions is None
                                      else mixed_gravity_regions)
        self.target_gravity_bias = data.TARGET_GRAVITY_BIAS if target_gravity_bias is None else target_gravity_bias
        if type(self.mixed_gravity_regions) is not int or not 1 <= self.mixed_gravity_regions <= 16:
            raise ValueError("Use 1-16 mixed gravity regions.")
        if (type(self.target_gravity_bias) not in (int, float)
                or not 0.5 <= self.target_gravity_bias <= 1 or not math.isfinite(self.target_gravity_bias)):
            raise ValueError("Target gravity bias must be between 0.5 and 1.")
        self.random = random.Random(random_seed)
        self.clock = time.monotonic if clock is None else clock
        self.score_store = ScoreStore() if score_store is None else score_store
        self.state = "idle"
        self.timed = False
        self.random_terrain = data.RANDOM_TERRAIN
        self.charges = data.DEFAULT_CHARGES
        self.angle = data.DEFAULT_ANGLE
        self.direction = 1
        self.fuse_time = None
        if not data.SHELLS or data.DEFAULT_SHELL not in data.SHELLS:
            raise ValueError("SHELLS must contain DEFAULT_SHELL.")
        self.shell = data.DEFAULT_SHELL
        if data.SHELLS[self.shell].get("timed_only", False):
            self.fuse_time = data.DEFAULT_FUSE_TIME
        self.gravity_mode = data.DEFAULT_GRAVITY_MODE
        self.new_map()

    @property
    def gravity(self):
        """Gravity at the cannon; tests can assign a uniform override."""
        return self.gravity_field.gravity_at(self.cannon[0])

    @gravity.setter
    def gravity(self, value):
        self.gravity_field = GravityField(self.terrain.width, (value,))

    @property
    def wind_acceleration(self):
        direction, level = self.wind
        return direction * data.WIND_ACCELERATIONS[level]

    @property
    def wind_label(self):
        direction, level = self.wind
        return "NONE" if level == 0 else f"{'LEFT' if direction < 0 else 'RIGHT'} {level}"

    def new_map(self, gravity_mode=None, timed=None, random_terrain=None):
        """Start a fresh map, targets and score, retaining launch controls."""
        mode = self.gravity_mode if gravity_mode is None else gravity_mode
        if mode not in data.GRAVITY_MODES:
            raise ValueError("Unknown gravity mode.")
        if self.state == "playing" and self.timed:
            self.end_round("restarted")
        self.timed = self.timed if timed is None else bool(timed)
        self.random_terrain = self.random_terrain if random_terrain is None else bool(random_terrain)
        self.gravity_mode = mode
        self._generate_map()
        self.shots_fired = 0
        self.cells_removed = 0
        self.score = 0
        self.targets_hit = 0
        self.last_fired_shot = None
        self.state = "playing"
        self.started_at = self.clock()
        self.ended_at = None
        self.duration_limit = data.ROUND_DURATION_SECONDS
        self.end_reason = ""
        self.score_save_attempted = False
        self.score_saved = False
        self.result_message = ""

    def _generate_map(self):
        """Replace the landscape and environment without restarting the round."""
        self.terrain = Terrain.randomized(self.random) if self.random_terrain else Terrain()
        self.cannon = (data.CANNON_X,
                       self.terrain.surface_height(data.CANNON_X) + data.CANNON_PIVOT_HEIGHT)
        self.gravity_field = self._new_gravity_field()
        self.wind = self.random.choice(data.WIND_OPTIONS)
        self.active_shot = None
        self.last_shot = None
        self.targets = []
        self.next_target_id = 1
        self._replenish_targets()

    def _new_gravity_field(self):
        if self.gravity_mode == "normal":
            values = (data.GRAVITY,)
        else:
            count = self.mixed_gravity_regions if self.gravity_mode == "mixed" else 1
            values = tuple(round(self.random.uniform(*data.RANDOM_GRAVITY_RANGE), 1) for _ in range(count))
        return GravityField(self.terrain.width, values)

    @property
    def elapsed_seconds(self):
        end = self.clock() if self.ended_at is None else self.ended_at
        return max(0.0, end - self.started_at)

    @property
    def remaining_seconds(self):
        return max(0.0, self.duration_limit - self.elapsed_seconds) if self.timed else None

    def tick(self):
        if self.state == "playing" and self.timed and self.remaining_seconds <= 0:
            self.end_round("time_up")
        return self.state == "playing"

    def end_round(self, reason="finished"):
        """Freeze the result, discard pending hits and attempt a timed save once."""
        if self.state != "playing":
            return False
        self.state = "ended"
        self.ended_at = self.clock()
        self.end_reason = reason
        self.active_shot = None
        if self.timed and not self.score_save_attempted:
            self.score_save_attempted = True
            direction, level = self.wind
            record = {"score": self.score, "gravity_mode": self.gravity_mode,
                      "wind_direction": direction, "wind_level": level,
                      "played_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            self.score_saved, self.result_message = self.score_store.save(record)
        else:
            self.result_message = "Unlimited round: score is not added to the leaderboard."
        return True

    def next_shell(self):
        """Cycle every configured shell in dictionary order."""
        names = tuple(data.SHELLS)
        return self.configure(shell=names[(names.index(self.shell) + 1) % len(names)])

    def purchase(self, item_id):
        """Apply a shop effect and charge points only on a successful purchase."""
        if not self.tick():
            return False, "The round has ended."
        if self.active_shot is not None:
            return False, "Wait for the shell to finish before shopping."
        item = data.SHOP_ITEMS.get(item_id)
        if item is None:
            return False, "Unknown shop item."
        if self.score - item["price"] < data.MIN_SCORE:
            return False, (f"Not enough points: price {item['price']}, balance {self.score}. "
                           f"Minimum balance is {data.MIN_SCORE}.")
        effects = {"reroll_mixed_gravity": self._reroll_mixed_gravity,
                   "reset_map": self._reset_map}
        success, message = effects[item["effect"]]()
        if success:
            self.score -= item["price"]
        return success, message

    def _reroll_mixed_gravity(self):
        if self.gravity_mode != "mixed":
            return False, "This item requires MIXED gravity mode."
        self.gravity_field = self._new_gravity_field()
        return True, f"Purchased: all {self.mixed_gravity_regions} gravity regions have been randomised."

    def _reset_map(self):
        self._generate_map()
        return True, "Purchased: map, targets and environment reset. Round score and clock retained."

    def _target_position_is_legal(self, position, radius, excluded_area):
        if not self.terrain.circle_is_clear(*position, radius):
            return False
        if math.dist(position, self.cannon) < data.TARGET_CANNON_CLEARANCE + radius:
            return False
        if any(math.dist(position, target.position)
               < radius + target.radius + data.TARGET_SEPARATION for target in self.targets):
            return False
        # Avoid a replacement immediately reappearing inside this shot's outline.
        return excluded_area is None or not excluded_area.contains(*position)

    def _target_kind_at(self, x):
        gravity = self.gravity_field.gravity_at(x)
        air_chance = (self.target_gravity_bias if gravity < 0 else
                      1 - self.target_gravity_bias if gravity > 0 else 0.5)
        return "air" if self.random.random() < air_chance else "ground"

    def _place_target(self, kind=None, excluded_area=None):
        radius = data.TARGET_RADIUS
        minimum_x = max(radius, self.cannon[0] + data.TARGET_CANNON_CLEARANCE)
        maximum_x = self.terrain.width - radius

        def candidate(x, air_fraction, chosen_kind):
            y = self.terrain.resting_circle_height(x, radius)
            if chosen_kind == "air":
                minimum_y = y + data.TARGET_AIR_MIN_HEIGHT
                maximum_y = min(self.terrain.height - radius, y + data.TARGET_AIR_MAX_HEIGHT)
                if minimum_y > maximum_y:
                    return None
                y = minimum_y + air_fraction * (maximum_y - minimum_y)
            position = (float(x), float(y))
            return position if self._target_position_is_legal(position, radius, excluded_area) else None

        if minimum_x > maximum_x:
            return None
        for _ in range(data.TARGET_SPAWN_ATTEMPTS):
            x = self.random.uniform(minimum_x, maximum_x)
            chosen_kind = kind if kind is not None else self._target_kind_at(x)
            position = candidate(x, self.random.random(), chosen_kind)
            if position is not None:
                break
        else:
            # Bounded fallback avoids hanging if random placements keep failing.
            position = None
            for x in np.arange(minimum_x, maximum_x + 1e-9,
                               max(2 * radius + data.TARGET_SEPARATION, self.terrain.cell_size)):
                primary = kind if kind is not None else self._target_kind_at(x)
                kinds = (primary,) if kind is not None else (primary, "ground" if primary == "air" else "air")
                for chosen_kind in kinds:
                    for fraction in ((0.0,) if chosen_kind == "ground" else (0.0, 0.25, 0.5, 0.75, 1.0)):
                        position = candidate(x, fraction, chosen_kind)
                        if position is not None:
                            break
                    if position is not None:
                        break
                if position is not None:
                    break
        if position is None:
            return None
        target = Target(self.next_target_id, position, chosen_kind, radius)
        self.next_target_id += 1
        return target

    def _replenish_targets(self, excluded_area=None):
        """Called only when a new map starts or a whole shot has resolved."""
        while len(self.targets) < data.TARGET_COUNT:
            target = self._place_target(excluded_area=excluded_area)
            if target is None:
                break  # A full map can legitimately have no legal place left.
            self.targets.append(target)

    def configure(self, charges=None, angle=None, direction=None, shell=None,
                  fuse_time=_KEEP_FUSE):
        if not self.tick() or self.active_shot is not None:
            return False
        charges = self.charges if charges is None else charges
        angle = self.angle if angle is None else angle
        direction = self.direction if direction is None else direction
        shell = self.shell if shell is None else shell
        keep_fuse = fuse_time is _KEEP_FUSE
        fuse_time = self.fuse_time if keep_fuse else fuse_time
        if not isinstance(charges, int) or not data.CHARGE_MIN <= charges <= data.CHARGE_MAX:
            raise ValueError("Charge count is outside its allowed integer range.")
        if not math.isfinite(angle) or not 0 <= angle <= 90:
            raise ValueError("Angle must be between 0 and 90 degrees.")
        if direction not in (-1, 1) or shell not in data.SHELLS:
            raise ValueError("Unknown direction or shell.")
        if data.SHELLS[shell].get("timed_only", False) and fuse_time is None:
            if not keep_fuse:
                raise ValueError(f"{shell} requires a timed fuse.")
            fuse_time = data.DEFAULT_FUSE_TIME
        if fuse_time is not None and (isinstance(fuse_time, bool)
                or not isinstance(fuse_time, (int, float)) or not math.isfinite(fuse_time)
                or not 0 < fuse_time <= data.MAX_SHOT_TIME):
            raise ValueError(f"Fuse time must be greater than 0 and at most {data.MAX_SHOT_TIME:g} s.")
        self.charges, self.angle, self.direction, self.shell = charges, angle, direction, shell
        self.fuse_time = fuse_time
        return True

    def muzzle(self):
        ux, uy = calculate_velocity_components(1.0, self.angle, self.direction)
        offset = data.BARREL_LENGTH + data.MUZZLE_CLEARANCE
        return self.cannon[0] + offset * ux, self.cannon[1] + offset * uy

    def _trace_shot(self, origin, velocity):
        path = []
        direct_target = None
        reason = "timeout"
        limit = data.MAX_SHOT_TIME if self.fuse_time is None else self.fuse_time
        for segment in iter_motion_segments(origin, velocity, self.gravity_field,
                                            self.wind_acceleration, limit):
            duration, reason = self.terrain.trace_trajectory(
                *segment.origin, *segment.velocity, segment.gravity, segment.duration, segment.ax)
            direct_target = None
            for target in self.targets:
                contact = first_circle_contact(segment.origin, segment.velocity, segment.gravity,
                                               target.position, target.radius, duration, segment.ax)
                if contact is not None and (direct_target is None or contact < duration):
                    duration, reason, direct_target = contact, "target", target.identifier
            path.append(MotionSegment(segment.start_time, duration, segment.origin,
                                      segment.velocity, segment.gravity, segment.ax))
            if reason != "timeout":
                break
        if reason == "timeout" and self.fuse_time is not None:
            reason = "fuse"
        return tuple(path), reason, direct_target

    def fire(self):
        if not self.tick() or self.active_shot is not None:
            return None
        settings = data.SHELLS[self.shell]
        timed_only = settings.get("timed_only", False)
        if timed_only and self.fuse_time is None:
            raise ValueError(f"{self.shell} requires a timed fuse.")
        origin = self.muzzle()
        if self.terrain.world_to_cell(*origin) is None or self.terrain.touches_solid(*origin):
            raise ValueError("The muzzle is blocked. Choose another angle.")
        speed = calculate_initial_speed(self.charges, settings["mass"],
                                        data.ENERGY_PER_CHARGE)
        velocity = calculate_velocity_components(speed, self.angle, self.direction)
        path, reason, direct_target = self._trace_shot(origin, velocity)
        duration = path[-1].start_time + path[-1].duration
        samples = []
        for index, segment in enumerate(path):
            count = max(2, math.ceil(segment.duration / data.TRAIL_SAMPLE_INTERVAL) + 1)
            local_times = np.linspace(0, segment.duration, count)
            x, y = segment.position_at(local_times)
            values = np.array((segment.start_time + local_times, x, y))
            samples.append(values[:, 1:] if index else values)
        times, x, y = np.concatenate(samples, axis=1)
        shot = Shot(self.shell, origin, velocity, self.gravity, duration, reason, times, x, y)
        shot.charges = self.charges
        shot.segments = path
        shot.gravity_field = self.gravity_field
        shot.wind_ax = self.wind_acceleration
        shot.fuse_time = self.fuse_time
        shot.direct_target_id = direct_target
        if reason == "fuse" or (not timed_only and reason in ("impact", "target")):
            impact_velocity = shot.velocity_at(duration)
            shot.area = ImpactArea(self.shell, (x[-1], y[-1]), impact_velocity,
                                   settings, fallback=velocity)
        if not self.tick():
            return None
        self.active_shot = shot
        self.last_fired_shot = shot
        self.shots_fired += 1
        return shot

    def finish_shot(self, shot):
        """Apply an impact once, only when its playback reaches the result."""
        if not self.tick() or shot is None or shot is not self.active_shot or shot.resolved:
            return False
        if shot.area is not None:
            if shot.area.settings.get("destroys_terrain", True):
                shot.removed_cells = self.terrain.destroy(shot.area)
            self.cells_removed += shot.removed_cells
            hit_targets = [target for target in self.targets
                           if target.identifier == shot.direct_target_id
                           or shot.area.contains(*target.position)]
            shot.hit_target_ids = tuple(target.identifier for target in hit_targets)
            shot.points_earned = len(hit_targets) * data.POINTS_PER_TARGET
            self.score += shot.points_earned
            self.targets_hit += len(hit_targets)
            self.targets = [target for target in self.targets
                            if target.identifier not in shot.hit_target_ids]
        else:
            hit_targets = []
        shot.resolved = True
        self.last_shot = shot
        self.active_shot = None
        self._replenish_targets(excluded_area=shot.area)
        return True

    def cancel_shot(self):
        """Discard the pending result; cancellation cannot damage terrain."""
        self.active_shot = None
