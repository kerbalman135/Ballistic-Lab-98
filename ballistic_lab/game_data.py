"""Shared settings. Values marked provisional can be tuned after playtesting."""

# Provisional map and grid. Each boolean cell represents a solid square.
MAP_SCALE = 2.0  # Base landscape scale; the cannon remains at x=12.
MAP_WIDTH = 120.0 * MAP_SCALE
MAP_HEIGHT = 200.0  # Headroom for high-angle shots and negative-gravity flight.
VIEW_WIDTH = 120.0
VIEW_HEIGHT = 68.0  # Camera follows shots instead of shrinking the whole map.
CELL_SIZE = 0.25
TERRAIN_PROFILE = tuple((x * MAP_SCALE * 2, y * MAP_SCALE) for x, y in (
    (0, 3), (12, 3), (18, 6), (24, 15), (30, 14),
    (36, 5), (44, 8), (50, 4), (60, 5),
))

GRAVITY = 9.8
GRAVITY_MODES = {"normal": "NORMAL", "abnormal": "ABNORMAL", "mixed": "MIXED"}
DEFAULT_GRAVITY_MODE = "normal"
RANDOM_GRAVITY_RANGE = (-12.0, 12.0)
MIXED_GRAVITY_REGIONS = 4  # Equal-width regions; settings.json can override this.
TARGET_GRAVITY_BIAS = 0.80  # Preferred target chance: air for g<0, ground for g>0.
# Provisional wind acceleration magnitudes, indexed by level (0 = no wind).
WIND_ACCELERATIONS = (0.0, 0.5, 1.0, 2.0)
WIND_OPTIONS = ((0, 0), (-1, 1), (-1, 2), (-1, 3), (1, 1), (1, 2), (1, 3))
CHARGE_MIN = 1
CHARGE_MAX = 6
DEFAULT_CHARGES = 3
DEFAULT_ANGLE = 45
# 3 kg / six packs / 45 degrees reaches x=240 at g=9.8, with room for
# the strongest headwind and 30 m terrain (about 752 J/pack required).
ENERGY_PER_CHARGE = 800.0  # Effective joules per charge, not chemical energy.
SHELLS = {
    "HE": {"mass": 2.0, "shape": "circle", "radius": 5.0, "destroys_terrain": True},
    "AP": {"mass": 3.0, "shape": "rectangle", "length": 12.0, "width": 2.0,
           "destroys_terrain": True},
    "AA": {"mass": 1.0, "shape": "sector", "radius": 7.0, "angle_degrees": 80.0,
           "destroys_terrain": False},
    "ExAA": {"mass": 1.2, "shape": "circle", "radius": 10.0,
             "destroys_terrain": False, "timed_only": True},
}
DEFAULT_SHELL = "HE"
# Add another entry to expose it in the selection cycle. Supported shapes:
# circle: radius; rectangle: length and width, extending forward from impact.
# sector: radius and total angle_degrees, centred on the impact direction.
# destroys_terrain: False keeps the grid intact; target hits still apply.
# timed_only: True requires a timer and prevents detonation on contact.
# HE/AP masses remain provisional; AA mass and effect dimensions are confirmed.
CANNON_X = 6.0 * MAP_SCALE
RANDOM_TERRAIN = True
TERRAIN_ANCHOR_COUNT = 12
TERRAIN_MIN_HEIGHT = 3.0
TERRAIN_MAX_HEIGHT = 30.0
TERRAIN_MAX_STEP = 8.0
TERRAIN_LAUNCH_CLEARANCE = 6.0  # Flat ground beyond the cannon, in either direction.
CANNON_ICON_SCALE = 2.5  # Main graphic size; the mounting height follows its proportions.
CANNON_TURRET_SCALE = 1.2  # Turret/mount size; barrel thickness uses CANNON_ICON_SCALE.
CANNON_PIVOT_HEIGHT = 1.295 * CANNON_ICON_SCALE * CANNON_TURRET_SCALE  # Feet stay on the ground.
CANNON_BASE_REACH = 2.726 * CANNON_ICON_SCALE * CANNON_TURRET_SCALE  # Reserve flat ground for the feet.
BARREL_LENGTH = 6.0
MUZZLE_CLEARANCE = 0.15
MAX_SHOT_TIME = 20.0
DEFAULT_FUSE_TIME = 2.0  # Seconds after launch; the timer is initially disabled.
TARGET_FPS = 12  # Animation frame target; settings.json can override this.
PLAYBACK_SPEED = 1.5  # Simulated seconds per real second; not a round clock.
TRAIL_SAMPLE_INTERVAL = 0.025  # Drawing only; collision does not use samples.
# Fractions of the visible width/height. The camera moves only outside this box.
CAMERA_SAFE_X = (0.20, 0.80)
CAMERA_SAFE_Y = (0.20, 0.75)
# Maximum internal rendering resolution. The window remains freely resizable.
# Desktop/main launches use settings.json overrides for the display defaults below.
# Try 800 x 600, 1024 x 768 or 1280 x 960; restart the program after changing.
# Integer zoom preserves the chosen ratio; fullscreen can add side margins.
RENDER_WIDTH = 1600
RENDER_HEIGHT = 1200
LOCK_RENDER_ASPECT = True  # Preserve the configured ratio when resizing or using fullscreen.
RENDER_DPI = 100  # Fixed internal coordinate scale; tune WIDTH/HEIGHT instead.
# Game typography. Use an installed font name; missing fonts fall back safely.
UI_FONT_FAMILY = "Microsoft Sans Serif"
UI_FONT_SCALE = 1.0  # Overall text size: e.g. 1.1 is 10% larger. Restart to apply.
MENU_TITLE_FONT_FAMILY = "Eras Demi ITC"
MENU_CREDIT_FONT_FAMILY = "Eras Light ITC"
MENU_FONT_FALLBACK = "Microsoft Sans Serif"
MENU_TITLE_FONT_SIZE = 48
DEFAULT_THEME = "win98"  # Main menu -> THEME saves this choice in settings.json.
DEFAULT_DITHER = True
DEFAULT_SCANLINES = True
SCANLINE_STRENGTH = 0.12  # Dark rows lose 12% brightness; 0.0-1.0. Restart after editing.
SCANLINE_PERIOD = 4  # One dark row per N internal pixel rows; scales with the picture.
DEFAULT_SOUND = True
SOUND_VOLUME = 0.35  # WAV amplitude, 0.0-1.0; settings.json overrides this default.
ROUND_DURATION_SECONDS = 300.0
LEADERBOARD_LIMIT = 10
MIN_SCORE = -20  # Shop purchases may use up to 20 points of credit.
SHOP_ITEMS = {
    "gravity_reroll": {"name": "REROLL MIXED GRAVITY", "price": 200,
                       "effect": "reroll_mixed_gravity"},
    "map_reset": {"name": "RESET MAP", "price": 20, "effect": "reset_map"},
}

# Provisional target/scoring rules from the requirements' suggested defaults.
TARGET_COUNT = 5
TARGET_RADIUS = 1.2  # Hidden contact region, independent of the decorative icon.
TARGET_MARKER_RADIUS = 0.65  # Original aiming circle; does not define contact geometry.
POINTS_PER_TARGET = 100
TARGET_CANNON_CLEARANCE = 5.0
TARGET_SEPARATION = 0.5
TARGET_AIR_MIN_HEIGHT = 3.0  # Clearance above a legal resting position.
TARGET_AIR_MAX_HEIGHT = 80.0
TARGET_SPAWN_ATTEMPTS = 150

# Every base colour below is selected from the supplied Win_256.act table.
# Separate light controls from the dark playfield; no external palette file is
# needed at runtime. Text antialiasing can still produce intermediate shades.
PALETTE = {
    "background": "#000000",
    "panel": "#A0A0A4",
    "terrain": "#008000",
    "terrain_edge": "#00FF00",
    "text": "#FFFFFF",
    "muted": "#A0A0A4",
    "trajectory": "#00FFFF",
    "projectile": "#FFFF00",
    "effect": "#FF0000",
    "hover": "#A6CAF0",
    "button_text": "#000000",
    "disabled_text": "#2A3F55",
    "selected": "#000080",
    "selected_text": "#FFFFFF",
    "selected_hover": "#2A3FAA",
    "loaded": "#008000",
    "loaded_text": "#FFFFFF",
    "fuse_impact": "#000080", "fuse_impact_text": "#FFFFFF",
    "fuse_timed": "#FFFF00", "fuse_timed_text": "#000000",
    "fire_ready": "#FF0000", "fire_ready_text": "#000000",
    "border": "#808080",
    "bevel_light": "#FFFFFF",
    "bevel_dark": "#000000",
    "input_background": "#FFFFFF",
    "input_text": "#000000",
    "enemy_ground": "#FF0000",
    "enemy_air": "#FF00FF",
}
