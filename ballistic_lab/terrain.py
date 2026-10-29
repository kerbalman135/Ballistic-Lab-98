"""Persistent solid-cell terrain, contact queries and shell-shaped removal."""

import math
import numpy as np

from . import game_data as data
from .game_data import MAP_WIDTH, MAP_HEIGHT, CELL_SIZE, TERRAIN_PROFILE
from .physics import calculate_position, times_at_coordinate


class CircleShape:
    def __init__(self, settings):
        self.radius = settings["radius"]
        if not math.isfinite(self.radius) or self.radius <= 0:
            raise ValueError("Circle radius must be positive and finite.")

    def contains(self, along, across):
        return along**2 + across**2 <= self.radius**2 + 1e-10

    def outline_points(self):
        angles = np.linspace(0, 2 * math.pi, 96, endpoint=False)
        return np.column_stack((self.radius * np.cos(angles), self.radius * np.sin(angles)))


class RectangleShape:
    def __init__(self, settings):
        self.length, self.width = settings["length"], settings["width"]
        if not all(math.isfinite(value) and value > 0 for value in (self.length, self.width)):
            raise ValueError("Rectangle dimensions must be positive and finite.")

    def contains(self, along, across):
        return ((along >= -1e-10) & (along <= self.length + 1e-10)
                & (np.abs(across) <= self.width / 2 + 1e-10))

    def outline_points(self):
        half = self.width / 2
        return np.array(((0, -half), (self.length, -half), (self.length, half), (0, half)))


class SectorShape:
    """Forward circular sector, with its apex at the impact point."""

    def __init__(self, settings):
        self.radius = settings["radius"]
        self.angle_degrees = settings["angle_degrees"]
        if not math.isfinite(self.radius) or self.radius <= 0:
            raise ValueError("Sector radius must be positive and finite.")
        if not math.isfinite(self.angle_degrees) or not 0 < self.angle_degrees <= 180:
            raise ValueError("Forward sector angle must be in (0, 180] degrees.")
        self.half_angle = math.radians(self.angle_degrees / 2)

    def contains(self, along, across):
        distance_squared = along**2 + across**2
        return ((distance_squared <= self.radius**2 + 1e-10)
                & (along >= np.sqrt(distance_squared) * math.cos(self.half_angle) - 1e-10))

    def outline_points(self):
        angles = np.linspace(-self.half_angle, self.half_angle, 33)
        arc = np.column_stack((self.radius * np.cos(angles), self.radius * np.sin(angles)))
        return np.vstack(((0.0, 0.0), arc))


# A new geometry implements contains(along, across) and outline_points(),
# then registers here. The UI uses the same outline for every shell type.
IMPACT_SHAPES = {"circle": CircleShape, "rectangle": RectangleShape, "sector": SectorShape}


class ImpactArea:
    """One shared shape for terrain removal and the UI outline.

    AP's impact point is the centre of the rear short edge. Its forward
    axis follows impact velocity, not the original firing angle.
    A sector uses the impact point as its apex and the same forward axis.
    """

    def __init__(self, shell, centre, velocity, settings, fallback=(1.0, 0.0)):
        self.shape = settings.get("shape")
        if self.shape not in IMPACT_SHAPES:
            raise ValueError(f"Unknown impact shape: {self.shape}.")
        self.geometry = IMPACT_SHAPES[self.shape](settings)
        self.shell = shell
        self.centre = tuple(centre)
        length = math.hypot(*velocity)
        if length < 1e-10:
            velocity = fallback
            length = math.hypot(*velocity)
        if length < 1e-10:
            raise ValueError("An impact needs a nonzero fallback direction.")
        self.forward = (velocity[0] / length, velocity[1] / length)
        self.settings = dict(settings)

    def contains(self, x, y):
        """Accept scalars or arrays of points, including the shape boundary."""
        dx, dy = np.asarray(x) - self.centre[0], np.asarray(y) - self.centre[1]
        ux, uy = self.forward
        along = dx * ux + dy * uy
        across = -dx * uy + dy * ux
        return self.geometry.contains(along, across)

    def outline_points(self):
        """Transform the registered shape's local outline to world coordinates."""
        x, y = self.centre
        ux, uy = self.forward
        return [(x + ux * a - uy * b, y + uy * a + ux * b)
                for a, b in self.geometry.outline_points()]

    def corners(self):
        """Compatibility helper for the existing rectangle geometry checks."""
        return self.outline_points()


class Terrain:
    def __init__(self, width=MAP_WIDTH, height=MAP_HEIGHT, cell_size=CELL_SIZE,
                 profile=TERRAIN_PROFILE):
        if min(width, height, cell_size) <= 0:
            raise ValueError("Terrain dimensions must be positive.")
        self.width, self.height, self.cell_size = width, height, cell_size
        self.profile = tuple(profile)
        self.columns = round(width / cell_size)
        self.rows = round(height / cell_size)
        if not (math.isclose(self.columns * cell_size, width)
                and math.isclose(self.rows * cell_size, height)):
            raise ValueError("Map dimensions must be multiples of cell size.")
        self.x_edges = np.arange(self.columns + 1) * cell_size
        self.y_edges = np.arange(self.rows + 1) * cell_size
        self.centre_x, self.centre_y = np.meshgrid(
            (self.x_edges[:-1] + self.x_edges[1:]) / 2,
            (self.y_edges[:-1] + self.y_edges[1:]) / 2)
        surface = np.interp(self.centre_x[0], *zip(*self.profile))
        self.solid = self.centre_y < surface

    @classmethod
    def randomized(cls, generator):
        """Bounded hills with a safe flat launching platform; seedable for tests."""
        launch_clearance = max(data.TERRAIN_LAUNCH_CLEARANCE,
                               data.BARREL_LENGTH + data.MUZZLE_CLEARANCE + data.CELL_SIZE,
                               data.CANNON_BASE_REACH + data.CELL_SIZE)
        platform_end = data.CANNON_X + launch_clearance
        maximum = min(data.TERRAIN_MAX_HEIGHT, data.MAP_HEIGHT - 2)
        minimum = min(data.TERRAIN_MIN_HEIGHT, maximum)
        height = generator.uniform(max(minimum, 4), min(maximum, 10))

        def grid_height(value):
            return round(value / data.CELL_SIZE) * data.CELL_SIZE

        height = grid_height(height)
        profile = [(0.0, height), (platform_end, height)]
        for x in np.linspace(platform_end, data.MAP_WIDTH, data.TERRAIN_ANCHOR_COUNT + 1)[1:]:
            height = grid_height(min(maximum, max(minimum,
                height + generator.uniform(-data.TERRAIN_MAX_STEP, data.TERRAIN_MAX_STEP))))
            profile.append((float(x), height))
        return cls(profile=profile)

    def world_to_cell(self, x, y):
        """Return (row, column), or None outside the half-open map."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            return None
        return math.floor(y / self.cell_size), math.floor(x / self.cell_size)

    def surface_height(self, x):
        cell = self.world_to_cell(x, 0)
        if cell is None:
            raise ValueError("Surface query is outside the map.")
        occupied_rows = np.flatnonzero(self.solid[:, cell[1]])
        return (occupied_rows[-1] + 1) * self.cell_size if occupied_rows.size else 0.0

    def resting_circle_height(self, x, radius):
        """Centre height of a circle resting on the current grid surface.

        Consider the circle's whole footprint, so it neither sinks into a
        neighbouring slope nor floats above a tall cell at its edge.
        An empty column uses the bottom map boundary as its support.
        """
        first = max(0, math.floor((x - radius) / self.cell_size))
        last = min(self.columns - 1, math.floor((x + radius) / self.cell_size))
        height = radius
        for column in range(first, last + 1):
            nearest_x = min(max(x, self.x_edges[column]), self.x_edges[column + 1])
            dx = abs(x - nearest_x)
            if dx > radius:
                continue
            rows = np.flatnonzero(self.solid[:, column])
            surface = (rows[-1] + 1) * self.cell_size if rows.size else 0.0
            height = max(height, surface + math.sqrt(max(0.0, radius**2 - dx**2)))
        return height

    def circle_is_clear(self, x, y, radius):
        """Check the whole target disk against map bounds and solid squares.

        Tangency to terrain is allowed when placing a resting target;
        overlapping terrain is not. Test nearest points on cell squares.
        """
        if (radius <= 0 or x - radius < 0 or x + radius > self.width
                or y - radius < 0 or y + radius > self.height):
            return False
        first_col = max(0, math.floor((x - radius) / self.cell_size))
        last_col = min(self.columns - 1, math.floor((x + radius) / self.cell_size))
        first_row = max(0, math.floor((y - radius) / self.cell_size))
        last_row = min(self.rows - 1, math.floor((y + radius) / self.cell_size))
        rows, cols = np.nonzero(self.solid[first_row:last_row + 1, first_col:last_col + 1])
        rows, cols = rows + first_row, cols + first_col
        nearest_x = np.clip(x, self.x_edges[cols], self.x_edges[cols + 1])
        nearest_y = np.clip(y, self.y_edges[rows], self.y_edges[rows + 1])
        return not np.any((x - nearest_x)**2 + (y - nearest_y)**2 < radius**2 - 1e-10)

    def touches_solid(self, x, y):
        """Include either neighbouring cell at an exact grid edge or corner.

        Solid squares have closed boundaries: grazing a solid edge counts
        as contact, consistently with the cell outline shown on screen.
        """
        candidates = []
        for value in (y, x):
            scaled = value / self.cell_size
            nearest = round(scaled)
            if abs(scaled - nearest) < 1e-8:
                candidates.append((nearest - 1, nearest))
            else:
                candidates.append((math.floor(scaled),))
        return any(self.solid[row, col] for row in candidates[0]
                   for col in candidates[1]
                   if 0 <= row < self.rows and 0 <= col < self.columns)

    def trace_trajectory(self, x0, y0, vx, vy, g, duration, ax=0.0):
        """Return (time, reason) at first terrain contact, map exit or timeout.

        For constant acceleration, find every time x or y crosses a grid
        edge. Between consecutive events the parabola stays in one cell.
        Check events and interval interiors in time order. This catches
        thin cells, tangent contacts and reverse motion without stepping
        over them, and does not depend on visual sampling or frame rate.
        Future mixed gravity must call this separately for each gravity zone.
        """
        if duration <= 0:
            raise ValueError("Shot duration must be positive.")
        events = {0.0, duration}
        for coordinate in self.x_edges:
            events.update(times_at_coordinate(x0, vx, ax, coordinate, duration))
        for coordinate in self.y_edges:
            events.update(times_at_coordinate(y0, vy, -g, coordinate, duration))
        events = sorted(events)
        for index, time in enumerate(events):
            x, y = calculate_position(time, vx, vy, g, x0, y0, ax)
            if not (-1e-9 <= x <= self.width + 1e-9
                    and -1e-9 <= y <= self.height + 1e-9):
                return time, "out_of_bounds"
            if self.touches_solid(x, y):
                return time, "impact"
            if index + 1 == len(events):
                break
            middle = (time + events[index + 1]) / 2
            mx, my = calculate_position(middle, vx, vy, g, x0, y0, ax)
            cell = self.world_to_cell(mx, my)
            if cell is None:
                return time, "out_of_bounds"
            if self.solid[cell]:
                return time, "impact"
        return duration, "timeout"

    def destroy(self, area):
        """Clear occupied cells whose centres are in the area; return count."""
        removed = self.solid & area.contains(self.centre_x, self.centre_y)
        count = int(np.count_nonzero(removed))
        self.solid[removed] = False
        return count

    def outline_segments(self):
        """Expose the exact edges between solid cells and air, including holes."""
        # Pad with air so the map's outer solid boundary is also visible.
        padded = np.pad(self.solid, 1)
        horizontal = padded[:-1, 1:-1] != padded[1:, 1:-1]
        vertical = padded[1:-1, :-1] != padded[1:-1, 1:]
        segments = []
        for row, col in np.argwhere(horizontal):
            segments.append(((self.x_edges[col], self.y_edges[row]),
                             (self.x_edges[col + 1], self.y_edges[row])))
        for row, col in np.argwhere(vertical):
            segments.append(((self.x_edges[col], self.y_edges[row]),
                             (self.x_edges[col], self.y_edges[row + 1])))
        return segments
