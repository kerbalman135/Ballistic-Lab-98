"""Display-only palettes and cached, world-anchored ordered dithering.

Dante 98 source: https://lospec.com/palette-list/rpg-tsukuru-dante-98
The published sixteen colours are preserved without modification.
"""

import numpy as np
from . import game_data as data


DANTE98_SWATCHES = (
    "#FFEE00", "#FFBB55", "#FF9911", "#FF6666", "#DD0000", "#AA2222",
    "#000000", "#998888", "#CCBBBB", "#FFFFFF", "#00FF00", "#009900",
    "#005555", "#0000BB", "#0066FF", "#00BBFF",
)

DANTE98_PALETTE = {
    "background": "#CCBBBB", "panel": "#005555", "terrain": "#009900",
    "terrain_edge": "#00FF00", "text": "#FFFFFF", "muted": "#CCBBBB",
    "trajectory": "#00BBFF", "projectile": "#FFEE00", "effect": "#FF9911",
    "hover": "#0000BB", "button_text": "#FFFFFF", "disabled_text": "#998888",
    "selected": "#AA2222", "selected_text": "#FFFFFF", "selected_hover": "#DD0000",
    "loaded": "#009900", "loaded_text": "#000000", "border": "#998888",
    "fuse_impact": "#0000BB", "fuse_impact_text": "#FFFFFF",
    "fuse_timed": "#FFEE00", "fuse_timed_text": "#000000",
    "fire_ready": "#DD0000", "fire_ready_text": "#FFFFFF",
    "bevel_light": "#CCBBBB", "bevel_dark": "#000000",
    "input_background": "#CCBBBB", "input_text": "#000000",
    "enemy_ground": "#FF6666", "enemy_air": "#FFBB55",
    # Separate light interface ink from the unchanged map and icon colours.
    "ui_text": "#000000", "ui_muted": "#000000", "readout": "#000000",
    "plot_background": "#000000", "plot_text": "#FFFFFF",
    "target_background": "#000000",
    "cannon_outline": "#000000",
}

# Sixteen warm greys supplied in the user's Greyscale palette reference.
GREYSCALE_SWATCHES = (
    "#1B1A19", "#292827", "#383734", "#464542",
    "#555350", "#63625E", "#72706B", "#807F79",
    "#8F8D87", "#9D9B94", "#ACA9A2", "#BAB8B0",
    "#C9C6BE", "#D7D4CC", "#E6E3D9", "#F4F1E7",
)

GREYSCALE_PALETTE = {
    "background": "#BAB8B0", "panel": "#383734", "terrain": "#807F79",
    "terrain_edge": "#D7D4CC", "text": "#1B1A19", "muted": "#464542",
    "trajectory": "#E6E3D9", "projectile": "#F4F1E7", "effect": "#F4F1E7",
    "hover": "#555350", "button_text": "#F4F1E7", "disabled_text": "#8F8D87",
    "selected": "#1B1A19", "selected_text": "#F4F1E7", "selected_hover": "#292827",
    "loaded": "#D7D4CC", "loaded_text": "#1B1A19", "border": "#63625E",
    "fuse_impact": "#292827", "fuse_impact_text": "#F4F1E7",
    "fuse_timed": "#E6E3D9", "fuse_timed_text": "#1B1A19",
    "fire_ready": "#F4F1E7", "fire_ready_text": "#1B1A19",
    "bevel_light": "#E6E3D9", "bevel_dark": "#1B1A19",
    "input_background": "#F4F1E7", "input_text": "#1B1A19",
    "enemy_ground": "#E6E3D9", "enemy_air": "#ACA9A2",
    "plot_background": "#1B1A19", "plot_text": "#E6E3D9",
    "header_text": "#F4F1E7", "readout": "#1B1A19",
    "projectile_edge": "#1B1A19", "target_background": "#1B1A19",
    "cannon_outline": "#1B1A19", "cannon_highlight": "#C9C6BE",
}

# Windows 98 colour roles, using only the supplied Win_256.act entries.
# Reference screenshots: https://guidebookgallery.org/screenshots/win98/
# ACT has no #C0C0C0: #A0A0A4 is the available neutral control-face grey.
WIN98_SWATCHES = (
    "#000000", "#FFFFFF", "#A0A0A4", "#808080",
    "#000080", "#008080", "#009FAA", "#C0DCC0",
    "#008000", "#2A5F00", "#557F55", "#553F00",
    "#FFFF00", "#FF7F00", "#FF0000", "#800080",
)

WIN98_PALETTE = {
    "background": "#A0A0A4", "panel": "#A0A0A4", "terrain": "#2A5F00",
    "terrain_edge": "#C0DCC0", "text": "#000000", "muted": "#000080",
    "trajectory": "#800080", "projectile": "#FFFF00", "effect": "#FF7F00",
    "hover": "#A0A0A4", "button_text": "#000000", "disabled_text": "#808080",
    "selected": "#000080", "selected_text": "#FFFFFF", "selected_hover": "#000080",
    "loaded": "#008000", "loaded_text": "#FFFFFF", "border": "#808080",
    "fuse_impact": "#000080", "fuse_impact_text": "#FFFFFF",
    "fuse_timed": "#FFFF00", "fuse_timed_text": "#000000",
    "fire_ready": "#FF0000", "fire_ready_text": "#000000",
    "bevel_light": "#FFFFFF", "bevel_dark": "#000000",
    "input_background": "#FFFFFF", "input_text": "#000000",
    "enemy_ground": "#FF0000", "enemy_air": "#800080",
    # Light application chrome, a teal map and a dark title bar need separate inks.
    "plot_background": "#008080", "plot_text": "#FFFFFF",
    "cannon_highlight": "#557F55",
    "header_text": "#FFFFFF", "readout": "#000080", "projectile_edge": "#000000",
    "menu_background": "#008080", "menu_text": "#FFFFFF",
}

THEMES = {
    "win256": {
        "label": "Dark", "colours": data.PALETTE, "bevel": True,
        "header": data.PALETTE["selected"],
        "legend": "BLUE: SELECTED", "loaded_legend": "GREEN: LOADED",
        "swatches": tuple(dict.fromkeys(data.PALETTE.values())),
        "sky": ("#000000", "#000080"),
        "ground": ("#008000", "#00FF00"),
    },
    "dante98": {
        "label": "Dante 98", "colours": DANTE98_PALETTE, "bevel": False,
        "header": "#005555", "legend": "RED: SELECTED", "loaded_legend": "GREEN: LOADED",
        "swatches": DANTE98_SWATCHES,
        "sky": ("#000000", "#0000BB", "#0066FF"),
        "ground": ("#005555", "#009900", "#00FF00"),
    },
    "bluegrey": {  # Keep the saved identifier when replacing the former palette.
        "label": "Greyscale", "colours": GREYSCALE_PALETTE, "bevel": False,
        "header": "#292827", "legend": "DARK: SELECTED", "loaded_legend": "LIGHT: LOADED",
        "swatches": GREYSCALE_SWATCHES,
        "sky": ("#1B1A19", "#292827", "#383734"),
        "ground": ("#555350", "#72706B", "#9D9B94", "#BAB8B0"),
    },
    "win98": {
        "label": "Win 98", "colours": WIN98_PALETTE, "bevel": True,
        "header": "#000080", "legend": "BLUE: SELECTED", "loaded_legend": "GREEN: LOADED",
        "swatches": WIN98_SWATCHES,
        "sky": ("#008080", "#009FAA"),
        "ground": ("#553F00", "#2A5F00", "#557F55"),
    },
}

_BAYER = (np.array(((0, 8, 2, 10), (12, 4, 14, 6),
                    (3, 11, 1, 9), (15, 7, 13, 5)), dtype=np.float32) + 0.5) / 16


def terrain_texture(terrain, theme, dither=False):
    """Return image indices + colour table; never mutate the collision grid.

    Call when the scene/theme changes, not while animating. Pattern coordinates
    are fixed to world cells, so camera movement cannot regenerate random noise.
    """
    colours = theme["colours"]
    if not dither:
        return terrain.solid, (colours.get("plot_background", colours["background"]), colours["terrain"])
    solid = terrain.solid
    rows = np.arange(solid.shape[0])[:, None]
    columns = np.arange(solid.shape[1])[None, :]
    threshold = _BAYER[rows % 4, columns % 4]

    def ramp(amount, count):
        position = np.clip(amount, 0, 1) * (count - 1)
        low = np.floor(position).astype(np.uint8)
        return low + (position - low > threshold).astype(np.uint8)

    sky = theme["sky"]
    ground = theme["ground"]
    world_y = (rows + 0.5) * terrain.cell_size
    sky_indices = ramp(1 - world_y / (data.VIEW_HEIGHT * 0.95), len(sky))
    surface = solid.shape[0] - 1 - np.argmax(solid[::-1], axis=0)
    surface = np.where(solid.any(axis=0), surface, -1)
    depth = (surface[None, :] - rows) * terrain.cell_size
    ground_indices = ramp(1 - depth / 10.0, len(ground))
    pixels = np.where(solid, ground_indices + len(sky), sky_indices).astype(np.uint8)
    return pixels, (*sky, *ground)
