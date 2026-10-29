"""Validated game/display/audio preferences stored beside sources or the EXE."""

import json
import math
from pathlib import Path
import sys
import tempfile

from . import game_data as data
from .themes import THEMES


def display_defaults():
    return {"theme": data.DEFAULT_THEME, "dither": data.DEFAULT_DITHER,
            "scanlines": data.DEFAULT_SCANLINES,
            "render_width": data.RENDER_WIDTH, "render_height": data.RENDER_HEIGHT,
            "lock_render_aspect": data.LOCK_RENDER_ASPECT,
            "target_fps": data.TARGET_FPS,
            "font_family": data.UI_FONT_FAMILY, "font_scale": data.UI_FONT_SCALE,
            "scanline_strength": data.SCANLINE_STRENGTH, "scanline_period": data.SCANLINE_PERIOD,
            "sound": data.DEFAULT_SOUND, "sound_volume": data.SOUND_VOLUME,
            "mixed_gravity_regions": data.MIXED_GRAVITY_REGIONS,
            "target_gravity_bias": data.TARGET_GRAVITY_BIAS}


def validated_settings(values):
    """Keep valid fields independently, so one typo does not discard a theme."""
    result, invalid = display_defaults(), []
    if not isinstance(values, dict):
        return result, ["settings"]
    for key, value in values.items():
        if key not in result:
            continue
        if key == "theme":
            valid = isinstance(value, str) and value in THEMES
        elif key in ("dither", "scanlines", "sound", "lock_render_aspect"):
            valid = type(value) is bool
        elif key == "font_family":
            valid = isinstance(value, str) and bool(value.strip()) and len(value) <= 128
        elif key in ("render_width", "render_height", "target_fps", "scanline_period", "mixed_gravity_regions"):
            low, high = {"render_width": (320, 7680), "render_height": (180, 4320),
                         "target_fps": (1, 60), "scanline_period": (2, 64),
                         "mixed_gravity_regions": (1, 16)}[key]
            valid = type(value) is int and low <= value <= high
        else:
            low, high = {"font_scale": (0.5, 2.0), "target_gravity_bias": (0.5, 1.0)}.get(key, (0.0, 1.0))
            valid = (type(value) in (int, float) and low <= value <= high
                     and math.isfinite(value))
        if valid:
            result[key] = value
        else:
            invalid.append(key)
    return result, invalid


class SettingsStore:
    def __init__(self, path=None):
        # Source launches keep preferences beside main.py, outside the package.
        folder = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
                  else Path(__file__).resolve().parents[1])
        self.path = Path(path) if path is not None else folder / "settings.json"

    def load(self):
        try:
            values = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return display_defaults(), ""
        except (OSError, UnicodeError, ValueError):
            return display_defaults(), "Could not read settings.json; using default preferences."
        values, invalid = validated_settings(values)
        warning = "Invalid settings use defaults: " + ", ".join(invalid) if invalid else ""
        return values, warning

    def save(self, values):
        values, invalid = validated_settings(values)
        if invalid:
            return False, "Preferences were invalid; settings.json was not changed."
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".settings-", suffix=".tmp", delete=False) as stream:
                temporary = Path(stream.name)
                json.dump(values, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            temporary.replace(self.path)
        except (OSError, UnicodeError, ValueError):
            return False, "Could not save settings.json; changes apply to this session only."
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return True, ""
