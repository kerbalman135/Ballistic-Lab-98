# Ballistic Lab 98

A 2D artillery game for the COMP9001 final project, inspired by Iron Nest.
Aim through changing gravity and wind to hit ground and air targets. Features
include four shell types, destructible terrain, timed fuses, a shop, timed and
unlimited rounds, and a saved leaderboard.

## Download for Windows

[Download Ballistic Lab 98 v0.8 for Windows](https://github.com/kerbalman135/Ballistic-Lab-98/releases/download/v0.8.0/BallisticLab98-v0.8-Windows.zip)

1. Download `BallisticLab98-v0.8-Windows.zip` using the link above.
2. Extract the **entire ZIP** to a writable folder before running the game.
3. Open the extracted folder and double-click `BallisticLab.exe`.

**No Python or library installation is needed for the Windows build.**
Keep `BallisticLab.exe` and the `_internal` folder together.

Other versions are available on the [Releases page](https://github.com/kerbalman135/Ballistic-Lab-98/releases).
The automatically generated **Source code** archives contain Python source;
choose the Windows ZIP above for the ready-to-run game.

## Requirements for Running from Source

- **Python 3.12** is recommended.
- **NumPy** and **Matplotlib** are the only third-party runtime dependencies.
- **Tkinter** and a desktop display are required for the game window.
  Check Tkinter with `python -m tkinter`; install your distribution's Tk support if missing.

Windows sound uses standard-library modules; other systems run silently.
No external media files or font installation is required.

## Run from Source

Keep `main.py` and the entire `ballistic_lab/` folder together. In a terminal
in the project folder:

```sh
python -m pip install numpy==1.26.4 matplotlib==3.8.4
python main.py
```

Use `python3` instead if needed. `main.py` selects the TkAgg backend and
opens the interactive window with resolution scaling enabled.

Choose **START**, a gravity mode, and **TIMED** or **UNLIMITED**.
**HOW TO PLAY** explains loading, aiming, and firing. Resize/maximize the
window normally, or press **F11** for fullscreen.
Control colours follow the theme. **LOAD** changes appearance when ready,
and an available **FIRE** button is bold and highlighted. Greyscale uses
dark selections and light loaded packs.

### Configuration and Saved Files

The first launch creates `settings.json` beside `main.py` or the EXE. **THEME**
saves palette, dithering, scanline, and sound choices. Close the game before
editing other settings, then restart:

| Setting | Purpose |
| --- | --- |
| `render_width`, `render_height` | Internal resolution cap; lower values can improve performance. |
| `lock_render_aspect` | Keep the configured aspect ratio; default `true`. `1600` × `1200` gives 4:3, with margins on wider screens. |
| `target_fps` | Animation frame target; default `12`, allowed integers `1`–`60`. |
| `font_family`, `font_scale` | Font and text size; missing fonts use a bundled fallback. |
| `sound_volume` | Sound amplitude from `0.0` to `1.0`; default `0.35`. |
| `mixed_gravity_regions` | MIXED region count; default `4`, allowed `1`–`16`. |
| `target_gravity_bias` | Default `0.8`: negative gravity favours air, positive gravity favours ground; zero gravity is 50/50. |

Missing/invalid settings use defaults; delete `settings.json` to reset it.
Timed results are saved to `scores.txt`. Keep the game in a writable folder.

## Program Structure

`main.py` stays in the project root. All other game modules are inside the
`ballistic_lab/` package; keep its `__init__.py` when copying or submitting it.

| Files | Role |
| --- | --- |
| `main.py` | TkAgg selection and application startup. |
| `ballistic_lab/ui.py` | Menus, controls, camera, and animation. |
| `ballistic_lab/game.py`, `ballistic_lab/game_data.py` | Game rules, round state, targets, scoring, and default configuration. |
| `ballistic_lab/physics.py`, `ballistic_lab/terrain.py` | Projectile motion, gravity transitions, collision detection, and the terrain grid. |
| `ballistic_lab/scores.py`, `ballistic_lab/settings.py` | Score and configuration file storage and validation. |
| `ballistic_lab/display.py`, `ballistic_lab/rendering.py` | Window scaling, scanlines, cached drawing, and partial updates. |
| `ballistic_lab/icons.py`, `ballistic_lab/themes.py` | Vector icons, palettes, and dithering. |
| `ballistic_lab/sound.py` | Procedural sound synthesis and optional Windows playback. |


