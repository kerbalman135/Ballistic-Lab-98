"""Matplotlib controls and playback for the target-shooting prototype."""

import time
import math
import textwrap
import weakref
from datetime import datetime
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
from matplotlib.colors import ListedColormap
from matplotlib.font_manager import FontProperties, findfont
from matplotlib.patches import Circle, Polygon
from matplotlib.patheffects import withStroke
from matplotlib.widgets import Button, Slider

from . import game_data as data
from .game import Game
from .display import LETTERBOX_COLOUR, create_game_figure
from .icons import CannonIcon, enemy_icon
from .rendering import ControlRenderer, FlightRenderer, ResponsiveTextBox
from .themes import THEMES, terrain_texture
from .settings import display_defaults


class TrajectoryUI:
    WINDOW_NAME = "Ballistic Lab 98"

    def __init__(self, start_page="menu", game=None, settings_store=None, audio=None):
        self.audio = audio
        self.settings_store = settings_store
        self.settings_warning = ""
        self.display_settings = display_defaults()
        if settings_store is not None:
            self.display_settings, self.settings_warning = settings_store.load()
            if not settings_store.path.exists():
                _, self.settings_warning = settings_store.save(self.display_settings)
        self.frame_interval_ms = 1000 / self.display_settings["target_fps"]
        self.game = (Game(mixed_gravity_regions=self.display_settings["mixed_gravity_regions"],
                          target_gravity_bias=self.display_settings["target_gravity_bias"])
                     if game is None else game)
        self.page = start_page
        self.page_buttons = {}
        self.page_text = []
        self.page_axes = []
        self.theme_preview = None
        self.selected_gravity = self.game.gravity_mode
        self.leaderboard_mode = data.DEFAULT_GRAVITY_MODE
        self.shot = None
        self.is_flying = False
        self.effect = None
        self.closed = False
        self.started_at = 0.0
        self._cannon_state = None
        self.buttons = {}
        self.control_text = []
        self._layout_scale = 1.0
        self._font_sizes = weakref.WeakKeyDictionary()
        # Selection becomes ammunition only through LOAD; firing consumes it.
        self.loaded_shell = None
        self.pending_charges = set()
        self.loaded_charges = set()
        self.theme_id = self.display_settings["theme"]
        self.theme = THEMES[self.theme_id]
        self.dither = self.display_settings["dither"]
        self.scanlines = self.display_settings["scanlines"]
        self.sound_enabled = self.display_settings["sound"]
        self.colours = self.theme["colours"]
        self.font_family = self._font_or_fallback(self.display_settings["font_family"], "DejaVu Sans Mono")
        self.font_scale = self.display_settings["font_scale"]
        self.menu_title_font_family = self._font_or_fallback(data.MENU_TITLE_FONT_FAMILY, data.MENU_FONT_FALLBACK)
        self.menu_credit_font_family = self._font_or_fallback(data.MENU_CREDIT_FONT_FAMILY, data.MENU_FONT_FALLBACK)

        # Re-running the launcher replaces its previous window and timer.
        plt.close(self.WINDOW_NAME)
        self.fig = create_game_figure(self.WINDOW_NAME, self.colours["background"],
                                     self.display_settings if settings_store is not None else None)
        # The UI requests its own draws; pyplot's automatic draws defeat blitting.
        self.fig.stale_callback = None
        self.header_ax = self.fig.add_axes([0, 0.94, 1, 0.06],
                                           facecolor=self.theme["header"], zorder=-1)
        self.header_ax.set_xticks([])
        self.header_ax.set_yticks([])
        self.header_ax.set_navigate(False)
        for spine in self.header_ax.spines.values():
            spine.set_visible(False)
        self.ax = self.fig.add_axes([0.235, 0.34, 0.585, 0.56])
        self._build_plot()
        self._build_controls()
        self.caption = self.fig.text(0.66, 0.96, "", ha="center",
                      color=self.colours.get("header_text", self.colours["text"]),
                      fontsize=9, fontfamily=self.font_family)
        self.environment = self.fig.text(
            0.025, 0.96, "",
            color=self.colours.get("header_text", self.colours["text"]),
            fontsize=9, fontfamily=self.font_family)
        self.status = self.fig.text(
            0.025, 0.04, "SELECT SHELL + CHARGES -> LOAD -> AIM -> FIRE.",
            color=self._ui_colour(), fontsize=10, fontfamily=self.font_family)
        self.time_label = self.fig.text(
            0.5275, 0.268, "t = 0.00 s", ha="center",
            color=self.colours.get("readout", self.colours["projectile"]),
            fontsize=12, fontfamily=self.font_family)
        self.summary = self.fig.text(
            0.025, 0.012, "", color=self._ui_colour("muted"), fontsize=9,
            fontfamily=self.font_family)
        self.round_label = self.fig.text(0.975, 0.96, "", ha="right",
                                          color=self.colours.get("header_text", self.colours["projectile"]),
                                          fontsize=12,
                                          fontfamily=self.font_family)
        self.timer = self.fig.canvas.new_timer(interval=round(self.frame_interval_ms))
        self.timer.add_callback(self._on_timer_frame)
        self._aim_pending = False
        self.aim_timer = self.fig.canvas.new_timer(interval=33)
        self.aim_timer.add_callback(self._flush_aim)
        self.flight_renderer = FlightRenderer(self.ax, (self.time_label, self.environment, self.round_label),
                                              motion=(self.trail, self.projectile))
        self.control_renderer = ControlRenderer(self.fig, self.ax, self.flight_renderer)
        self._apply_layout()
        self.fig.canvas.mpl_connect("resize_event", self._on_resize)
        self.fig.canvas.mpl_connect("close_event", self._on_close)
        self.fig.canvas.mpl_connect("button_release_event", self._flush_aim)
        if start_page == "game":
            self._set_page("game")
        else:
            self.game.end_round("menu")
            self._show_menu()

    @staticmethod
    def _font_or_fallback(family, fallback):
        for candidate in (family, fallback):
            try:
                findfont(FontProperties(family=candidate), fallback_to_default=False)
            except ValueError:
                continue
            return candidate
        return "DejaVu Sans"

    def _ui_colour(self, role="text"):
        return self.colours.get(f"ui_{role}", self.colours[role])

    def _build_plot(self):
        colours = self.colours
        terrain = self.game.terrain
        self.ax.set_facecolor(colours.get("plot_background", colours["background"]))
        self.ax.set_xlim(0, min(data.VIEW_WIDTH, terrain.width))
        self.ax.set_ylim(0, min(data.VIEW_HEIGHT, terrain.height))
        self.ax.set_aspect("equal", adjustable="box")
        self.ax.set_xlabel("DISTANCE (m)", color=self._ui_colour(), fontfamily=self.font_family)
        self.ax.set_ylabel("HEIGHT (m)", color=self._ui_colour(), fontfamily=self.font_family)
        self.ax.tick_params(colors=self._ui_colour())
        for spine in self.ax.spines.values():
            spine.set_color(colours["border"])
        pixels, colour_table = terrain_texture(terrain, self.theme, self.dither)
        self.terrain_image = self.ax.imshow(
            pixels, origin="lower", extent=(0, terrain.width, 0, terrain.height),
            cmap=ListedColormap(colour_table), vmin=0, vmax=len(colour_table)-1,
            interpolation="nearest", zorder=0)
        self.terrain_outline = LineCollection(
            terrain.outline_segments(), colors=colours["terrain_edge"],
            linewidths=0.6, antialiaseds=False, zorder=1)
        self.ax.add_collection(self.terrain_outline)
        self.cannon_icon = CannonIcon(self.ax, colours)
        self.trail, = self.ax.plot([], [], color=colours["trajectory"], linewidth=1.4,
                                    antialiased=False, zorder=3)
        self.projectile, = self.ax.plot([], [], marker="o", linestyle="none",
                                         color=colours["projectile"],
                                         markeredgecolor=colours.get("projectile_edge", colours["projectile"]),
                                         markersize=5, zorder=5)
        self.target_artists = []
        self._displayed_targets = None
        self.environment_artists = []
        self.gravity_labels = []
        self._refresh_targets()
        self._refresh_environment()

    def _invalidate_controls(self):
        if hasattr(self, "control_renderer"):
            self.control_renderer.invalidate()
            self.flight_renderer.invalidate()

    def _refresh_environment(self):
        self._invalidate_controls()
        for artist in self.environment_artists:
            artist.remove()
        self.environment_artists = []
        self.gravity_labels = []
        field = self.game.gravity_field
        for boundary in field.boundaries:
            line = self.ax.axvline(boundary, color=self.colours["terrain_edge"],
                                   linestyle="--", linewidth=0.9, zorder=2)
            self.environment_artists.append(line)
        if field.boundaries:
            for index, gravity in enumerate(field.values):
                x = field.width * (index + 0.5) / len(field.values)
                label = self.ax.text(x, self.ax.get_ylim()[1] - 1.5, f"g={gravity:+.1f}",
                                     color=self.colours.get("plot_text", self.colours["text"]),
                                     fontsize=8 * self._layout_scale * self.font_scale,
                                     ha="center", va="center", fontfamily=self.font_family, zorder=7)
                self.environment_artists.append(label)
                self.gravity_labels.append((index, label))
        if self.shot is not None and not self.is_flying:
            self._set_camera(*self.shot.position_at(self.shot.duration), follow=True)
        else:
            self._set_camera()

    def _update_environment_label(self, elapsed=None):
        gravity = self.game.gravity if elapsed is None else self.shot.gravity_at(elapsed)
        settings = data.SHELLS[self.game.shell]
        if settings["shape"] == "circle":
            dimensions = f"r={settings['radius']:g}"
        elif settings["shape"] == "rectangle":
            dimensions = f"{settings['length']:g}x{settings['width']:g}"
        elif settings["shape"] == "sector":
            dimensions = f"r={settings['radius']:g}/{settings['angle_degrees']:g}deg"
        else:
            dimensions = settings["shape"]
        self.environment.set_text(f"g={gravity:+.1f} | WIND: {self.game.wind_label}"
                                  f" | {self.game.shell}: {dimensions}")

    def _refresh_targets(self):
        targets = tuple(self.game.targets)
        if (targets == self._displayed_targets and
                getattr(self, "_displayed_icon_scale", None) == self._layout_scale):
            return
        self._invalidate_controls()
        self._displayed_targets = targets
        self._displayed_icon_scale = self._layout_scale
        for artist in self.target_artists:
            artist.remove()
        self.target_artists = []
        for target in self.game.targets:
            colour = self.colours["enemy_ground" if target.kind == "ground" else "enemy_air"]
            badge = enemy_icon(self.ax, target, self.colours, scale=self._layout_scale)
            circle = Circle(target.position, data.TARGET_MARKER_RADIUS,
                            facecolor=self.colours.get("target_background", self.colours["background"]),
                            edgecolor=colour,
                            linewidth=1.0, antialiased=False, zorder=5)
            self.ax.add_patch(circle)
            self.target_artists.extend((badge, circle))

    def _bevel(self, axis, sunken=False):
        light, dark = self.colours["bevel_light"], self.colours["bevel_dark"]
        for side, spine in axis.spines.items():
            top_left = side in ("left", "top")
            spine.set_edgecolor((light if top_left != sunken else dark)
                                if self.theme["bevel"] else self.colours["border"])
            spine.set_linewidth(1)
            spine.set_antialiased(False)
            spine.set_capstyle("butt")
            spine.set_joinstyle("miter")

    def _add_button(self, name, label, bounds, callback, page=False, size=10):
        axis = self.fig.add_axes(bounds)
        button = Button(axis, label, color=self.colours["panel"],
                        hovercolor=self.colours["hover"])
        button.label.set_color(self.colours["button_text"])
        button.label.set_fontfamily(self.font_family)
        self._font_sizes[button.label] = size
        button.label.set_fontsize(size * self._layout_scale * self.font_scale)
        self._bevel(axis)
        def clicked(event):
            if name not in ("load", "fire", "exit", "sound"):
                self._play_sound("click")
            callback(event)
        button.on_clicked(clicked)
        (self.page_buttons if page else self.buttons)[name] = button
        return button

    def _build_controls(self):
        def label(x, y, value, size=10, **kwargs):
            artist = self.fig.text(x, y, value, color=self._ui_colour(),
                                   fontfamily=self.font_family, fontsize=size, **kwargs)
            self.control_text.append(artist)
            return artist

        self.shell_heading = label(0.035, 0.89, "1 / SHELL", size=11)
        step = 0.18 / len(data.SHELLS)
        for index, (shell, settings) in enumerate(data.SHELLS.items()):
            self._add_button(f"shell_{shell}", f"{shell} {settings['mass']:g}kg",
                             [0.035, 0.85 - (index + 1) * step, 0.145, step - 0.01],
                             lambda event, selected=shell: self._select_shell(selected))
        self.shell_label = label(0.1075, 0.625, "BREECH EMPTY", size=9, ha="center")
        self.charges_heading = label(0.035, 0.545, "2 / CHARGES", size=11)
        width = 0.026
        height = width * self.fig.get_figwidth() / self.fig.get_figheight()
        for index in range(data.CHARGE_MAX):
            self._add_button(f"charge_{index + 1}", str(index + 1),
                             [0.1075 - width / 2, 0.485 - index * 0.05, width, height],
                             lambda event, slot=index + 1: self._select_charge(slot))
        self.load_button = self._add_button("load", "LOAD", [0.035, 0.155, 0.145, 0.055], self.load)
        self.charge_label = label(0.1075, 0.13, "", size=9, ha="center")
        self.pending_legend = label(0.035, 0.10, self.theme["legend"], size=8)
        self.loaded_legend = label(0.035, 0.075, self.theme["loaded_legend"], size=8)

        axis = self.fig.add_axes([0.35, 0.135, 0.33, 0.025], facecolor=self.colours["panel"])
        self.angle_slider = Slider(
            axis, "ANGLE", 0, 90, valinit=self.game.angle, valstep=1, valfmt="%0.0f",
            color=self.colours["selected"], track_color=self.colours["panel"],
            handle_style={"facecolor": self.colours["panel"],
                          "edgecolor": self.colours["bevel_dark"]})
        self.angle_slider._handle.set_marker("s")
        self.angle_slider.vline.set_color(self.colours["border"])
        for artist in (self.angle_slider.label, self.angle_slider.valtext):
            artist.set_color(self._ui_colour())
            artist.set_fontfamily(self.font_family)
        self.angle_slider.on_changed(self._change_angle)
        # The callback redraws the updated cannon and controls once.
        self.angle_slider.drawon = False
        self._add_button("direction", "RIGHT", [0.72, 0.12, 0.10, 0.055], self._toggle_direction)
        self.fire_button = self._add_button("fire", "FIRE", [0.455, 0.065, 0.145, 0.05], self.fire, size=12)
        self._add_button("shop", "SHOP", [0.85, 0.82, 0.125, 0.06], self._show_shop)
        self._add_button("clear", "CLEAR SHOT", [0.85, 0.70, 0.125, 0.06], self.clear_shot)
        self._add_button("end", "END ROUND", [0.85, 0.58, 0.125, 0.06], self._end_game)
        self._add_button("menu", "MENU", [0.85, 0.46, 0.125, 0.06], self._return_menu)
        self._add_button("cannon", "TO CANNON", [0.875, 0.34, 0.085, 0.04],
                         self._return_to_cannon, size=9)
        self._add_button("fuse", "FUSE: IMPACT", [0.235, 0.21, 0.155, 0.045], self._toggle_fuse)
        axis = self.fig.add_axes([0.525, 0.21, 0.09, 0.045])
        fuse_time = self.game.fuse_time if self.game.fuse_time is not None else data.DEFAULT_FUSE_TIME
        self.fuse_title = label(0.43, 0.2325, "FUSE t (s)", va="center")
        self.fuse_box = ResponsiveTextBox(axis, "", initial=f"{fuse_time:g}",
                                color=self.colours["input_background"],
                                hovercolor=self.colours["input_background"])
        for artist in (self.fuse_box.label, self.fuse_box.text_disp):
            artist.set_color(self.colours["input_text"])
            artist.set_fontfamily(self.font_family)
        self.fuse_box.text_disp.set_fontsize(12)
        self.fuse_box.cursor.set_color(self.colours["input_text"])
        self._bevel(axis, sunken=True)
        self.fuse_box.on_submit(self._change_fuse_time)
        self.fuse_hint = self.fig.text(0.64, 0.2325, f"0 < t <= {data.MAX_SHOT_TIME:g} s",
                                      va="center", fontsize=9, color=self._ui_colour("muted"),
                                      fontfamily=self.font_family)

    def _apply_layout(self):
        """Scale type and spacing together, independently of Windows monitor DPI."""
        width, height = self.fig.bbox.size
        scale = min(width / 1280, height / 720)
        self._layout_scale = scale

        def text_at(artist, x, y):
            artist.set_position((x / width, y / height))

        def bounds(axis, x, y, w, h):
            axis.set_position((x / width, y / height, w / width, h / height))

        s = scale
        bounds(self.header_ax, 0, height - 44*s, width, 44*s)
        # Sidebars use square charge buttons; the plot takes the remaining width.
        bounds(self.ax, 270*s, 290*s, width - 470*s, height - 380*s)
        # Anchor the whole loading sequence above LOAD, including on taller windows.
        charge_bottom = (140 + 34 + 16) * s
        sidebar_top = charge_bottom + (data.CHARGE_MAX - 1)*34*s + 353*s
        text_at(self.shell_heading, 16*s, sidebar_top - 78*s)
        shell_step = 144 / len(data.SHELLS)
        for index, shell in enumerate(data.SHELLS):
            bounds(self.buttons[f"shell_{shell}"].ax,
                   16*s, sidebar_top - (100 + (index+1)*shell_step - 6)*s,
                   180*s, (shell_step - 6)*s)
        text_at(self.shell_label, 106*s, sidebar_top - 255*s)
        text_at(self.charges_heading, 16*s, sidebar_top - 305*s)
        for index in range(data.CHARGE_MAX):
            bounds(self.buttons[f"charge_{index+1}"].ax,
                   92*s, charge_bottom + (data.CHARGE_MAX-index-1)*34*s, 28*s, 28*s)
        bounds(self.load_button.ax, 16*s, 140*s, 180*s, 34*s)
        text_at(self.charge_label, 106*s, 120*s)
        text_at(self.pending_legend, 16*s, 98*s)
        text_at(self.loaded_legend, 16*s, 80*s)
        right_top = sidebar_top - 100*s
        for index, name in enumerate(("shop", "clear", "end", "menu")):
            bounds(self.buttons[name].ax, width - 161*s,
                   right_top - (40 + index*90)*s, 145*s, 40*s)
        bounds(self.buttons["cannon"].ax, width - 143.5*s, right_top - 370*s, 110*s, 30*s)

        left, right = 235*s, width - 181*s
        middle = (left + right) / 2
        text_at(self.time_label, middle, 230*s)
        bounds(self.buttons["fuse"].ax, left, 183*s, 190*s, 32*s)
        text_at(self.fuse_title, left + 220*s, 199*s)
        bounds(self.fuse_box.ax, left + 330*s, 183*s, 90*s, 32*s)
        text_at(self.fuse_hint, left + 440*s, 199*s)
        bounds(self.angle_slider.ax, left + 90*s, 126*s,
               right - left - 270*s, 12*s)
        bounds(self.buttons["direction"].ax, right - 120*s, 115*s, 120*s, 34*s)
        bounds(self.fire_button.ax, middle - 120*s, 60*s, 240*s, 40*s)
        text_at(self.environment, 16*s, height - 24*s)
        text_at(self.caption, width / 2, height - 24*s)
        text_at(self.round_label, width - 16*s, height - 24*s)
        text_at(self.status, 16*s, 30*s)
        text_at(self.summary, 16*s, 8*s)

        # Cache original point sizes so repeated monitor/window changes do not
        # compound the scaling. Page widgets created later register their bases.
        artists = list(self.fig.texts)
        for axis in self.fig.axes:
            if axis is not self.ax:
                artists.extend(axis.texts)
        for artist in artists:
            base = self._font_sizes.setdefault(artist, artist.get_fontsize())
            artist.set_fontsize(base * s * self.font_scale)
        fs = s * self.font_scale
        self.status.set_fontsize(8.5*fs)
        self.summary.set_fontsize(8*fs)
        self.ax.tick_params(labelsize=10*fs, labelfontfamily=self.font_family,
                            pad=3.5*s, length=3.5*s, width=0.8*s)
        self.ax.xaxis.label.set_fontsize(10*fs)
        self.ax.yaxis.label.set_fontsize(10*fs)
        self.ax.xaxis.labelpad = self.ax.yaxis.labelpad = 4*s
        for _, label in self.gravity_labels:
            label.set_fontsize(8*fs)
        self.angle_slider._handle.set_markersize(10*s)
        self.projectile.set_markersize(5*s)
        self.trail.set_linewidth(1.4*s)
        self._refresh_targets()

    def _on_resize(self, event):
        active = self.flight_renderer.active
        self.flight_renderer.stop()
        self._apply_layout()
        self.control_renderer.invalidate()
        if active:
            self.flight_renderer.start()
        self.fig.canvas.draw_idle()

    def _sync_controls(self, redraw=True):
        game = self.game
        before = {name: (button.label.get_text(), button.label.get_color(), button.ax.get_facecolor())
                  for name, button in self.buttons.items()}
        changed_axes = []
        self.charge_label.set_text(f"{len(self.loaded_charges)} LOADED + {len(self.pending_charges)} SELECTED")
        self.shell_label.set_text("BREECH EMPTY" if self.loaded_shell is None else f"{self.loaded_shell} LOADED")
        self.buttons["direction"].label.set_text("RIGHT" if game.direction == 1 else "LEFT")
        timed_only = data.SHELLS[game.shell].get("timed_only", False)
        self.buttons["fuse"].label.set_text("FUSE: TIMED ONLY" if timed_only else
                                             "FUSE: IMPACT" if game.fuse_time is None else "FUSE: TIMED")
        self.caption.set_text(f"{data.GRAVITY_MODES[game.gravity_mode]} / {'TIMED' if game.timed else 'UNLIMITED'}")
        self._update_environment_label()
        playing = self.page == "game" and game.state == "playing"
        self.angle_slider.set_active(playing and not self.is_flying)
        self.fuse_box.set_active(playing and not self.is_flying and game.fuse_time is not None)
        occupied_charges = self.pending_charges | self.loaded_charges
        for name, button in self.buttons.items():
            enabled = playing and (not self.is_flying or name in ("clear", "end", "menu"))
            if name.startswith("shell_"):
                enabled = enabled and self.loaded_shell is None
            elif name.startswith("charge_"):
                slot = int(name.removeprefix("charge_"))
                enabled = enabled and slot == len(occupied_charges) + 1
            elif name == "load":
                enabled = enabled and (self.loaded_shell is None or bool(self.pending_charges))
            elif name == "fire":
                enabled = enabled and self._ready_to_fire()
            elif name == "fuse":
                enabled = enabled and not timed_only
            face = self.colours["panel"]
            ink = self.colours["button_text" if enabled else "disabled_text"]
            hover = self.colours["hover"]
            sunken = False
            if name.startswith("shell_") and name == f"shell_{game.shell}":
                face = self.colours["loaded" if self.loaded_shell else "selected"]
                ink = self.colours["loaded_text" if self.loaded_shell else "selected_text"]
                hover = face if self.loaded_shell else self.colours["selected_hover"]
                sunken = True
            elif name.startswith("charge_"):
                slot = int(name.removeprefix("charge_"))
                if slot in self.loaded_charges:
                    face, ink = self.colours["loaded"], self.colours["loaded_text"]
                    hover, sunken = face, True
                elif slot in self.pending_charges:
                    face, ink = self.colours["selected"], self.colours["selected_text"]
                    hover, sunken = self.colours["selected_hover"], True
            elif name == "fuse":
                # Retain a legible state colour even for the locked timed-only fuse.
                mode = "impact" if game.fuse_time is None else "timed"
                face, ink = self.colours[f"fuse_{mode}"], self.colours[f"fuse_{mode}_text"]
                hover, sunken = face, mode == "timed"
            elif name == "load" and self._ready_to_fire():
                # Keep the theme's loaded style even when LOAD is disabled.
                face, ink = self.colours["loaded"], self.colours["loaded_text"]
                hover, sunken = face, True
            elif name == "fire" and enabled:
                face, ink = self.colours["fire_ready"], self.colours["fire_ready_text"]
                hover = face
            weight = "bold" if name == "fire" and enabled else "normal"
            border_width = 1.8 if name == "fire" and enabled else 1.0
            style = (enabled, face, ink, hover, sunken, self.theme_id, weight, border_width)
            style_changed = getattr(button, "_game_style", None) != style
            if style_changed:
                button.set_active(enabled)
                button.color = face
                button.hovercolor = hover
                button.label.set_color(ink)
                button.label.set_fontweight(weight)
                button.ax.set_facecolor(face)
                self._bevel(button.ax, sunken=sunken)
                for spine in button.ax.spines.values():
                    spine.set_linewidth(border_width)
                button._game_style = style
            if style_changed or before[name] != (button.label.get_text(), button.label.get_color(), button.ax.get_facecolor()):
                changed_axes.append(button.ax)
        cannon_state = (game.cannon, game.angle, game.direction)
        if cannon_state != self._cannon_state:
            self.cannon_icon.update(*cannon_state)
            self._cannon_state = cannon_state
            changed_axes.extend((self.ax, self.angle_slider.ax))
        previous = game.last_fired_shot
        combination = "NONE" if previous is None else (
            f"{previous.shell} + {previous.charges} {'PACK' if previous.charges == 1 else 'PACKS'}")
        self.summary.set_text(f"SCORE: {game.score}  |  HITS: {game.targets_hit}"
                              f"  |  TARGETS: {len(game.targets)}/{data.TARGET_COUNT}"
                              f"  |  SHOTS: {game.shots_fired}  |  CELLS REMOVED: {game.cells_removed}"
                              f"  |  LAST: {combination}")
        self._update_round_clock()
        if redraw:
            self.control_renderer.draw(axes=changed_axes, texts=self.fig.texts)

    def _change_angle(self, value):
        if not self.is_flying:
            self.game.configure(angle=float(value))
            if self.angle_slider.drag_active and hasattr(self.fig.canvas, "get_tk_widget"):
                if not self._aim_pending:
                    self._aim_pending = True
                    self.aim_timer.start()
            else:
                self._sync_controls()

    def _cancel_aim(self):
        self.aim_timer.stop()
        self._aim_pending = False

    def _flush_aim(self, event=None):
        pending = self._aim_pending
        self._cancel_aim()
        if pending and not self.closed and self.page == "game" and not self.is_flying:
            self._sync_controls()

    def _ready_to_fire(self):
        return self.loaded_shell is not None and bool(self.loaded_charges) and not self.pending_charges

    def _reset_loading(self):
        self.loaded_shell = None
        self.pending_charges.clear()
        self.loaded_charges.clear()

    def _play_sound(self, name):
        if self.audio is not None and self.sound_enabled:
            self.audio.play(name)

    def _select_shell(self, shell):
        if self.page == "game" and self.loaded_shell is None and self.game.configure(shell=shell):
            if data.SHELLS[shell].get("timed_only", False):
                self.fuse_box.set_val(f"{self.game.fuse_time:g}")
            self._sync_controls()

    def _select_charge(self, slot):
        if (self.page != "game" or self.is_flying or not self.game.tick()
                or not 1 <= slot <= data.CHARGE_MAX
                or slot != len(self.pending_charges | self.loaded_charges) + 1):
            return
        self.pending_charges.add(slot)
        self.status.set_text("Charge selected. Continue in order or press LOAD; selection is permanent.")
        self._sync_controls()

    def load(self, event=None):
        if self.page != "game" or self.is_flying:
            return
        count = len(self.loaded_charges | self.pending_charges)
        shell = self.loaded_shell or self.game.shell
        if not self.game.configure(shell=shell, charges=count if count else None):
            return
        changed = self.loaded_shell is None or bool(self.pending_charges)
        self.loaded_shell = shell
        self.loaded_charges.update(self.pending_charges)
        self.pending_charges.clear()
        self.status.set_text(f"LOADED {shell} / {count} charge(s). " +
                             ("Aim and FIRE, or add more charges." if count else "Select charges and LOAD."))
        self._sync_controls()
        if changed:
            self._play_sound("load")

    def _toggle_direction(self, event=None):
        if self.game.configure(direction=-self.game.direction):
            self._sync_controls()

    def _apply_fuse_time(self):
        try:
            return self.game.configure(fuse_time=float(self.fuse_box.text))
        except ValueError:
            self.status.set_text(f"Enter a fuse time: 0 < t <= {data.MAX_SHOT_TIME:g} seconds.")
            self.control_renderer.draw(texts=(self.status,))
            return False

    def _change_fuse_time(self, value):
        if self.game.fuse_time is not None and not self.is_flying and self.page == "game":
            if self._apply_fuse_time():
                contact_rule = ("Contact ends the shot without a burst." if
                                data.SHELLS[self.game.shell].get("timed_only", False) else
                                "Earlier contact still detonates.")
                self.status.set_text(f"TIMED FUSE: {self.game.fuse_time:g} s. {contact_rule}")
                self._sync_controls()

    def _toggle_fuse(self, event=None):
        if (self.is_flying or self.page != "game"
                or data.SHELLS[self.game.shell].get("timed_only", False)):
            return
        if self.game.fuse_time is None:
            changed = self._apply_fuse_time()
        else:
            changed = self.game.configure(fuse_time=None)
        if changed:
            self.status.set_text("CONTACT FUSE." if self.game.fuse_time is None else
                                 f"TIMED FUSE: {self.game.fuse_time:g} s (or earlier contact).")
            self._sync_controls()

    def _remove_effect(self):
        if self.effect is not None:
            self.effect.remove()
            self.effect = None

    def fire(self, event=None):
        if self.is_flying or self.closed or self.page != "game":
            return
        self._cancel_aim()
        if not self._ready_to_fire():
            self.status.set_text("Select a shell and charges, then press LOAD before firing.")
            self.control_renderer.draw(texts=(self.status,))
            return
        if self.game.fuse_time is not None and not self._apply_fuse_time():
            if self.game.state == "ended":
                self._show_results()
            return
        try:
            shot = self.game.fire()
        except ValueError as error:
            self.status.set_text(str(error))
            self.control_renderer.draw(texts=(self.status,))
            return
        if shot is None:
            if self.game.state == "ended":
                self._show_results()
            return
        self._remove_effect()
        self._reset_loading()
        self.shot = shot
        self.is_flying = True
        self._set_camera()  # Each shot starts at the cannon before safe-area tracking.
        self.started_at = time.monotonic()
        terrain_damage = "ON" if data.SHELLS[shot.shell].get("destroys_terrain", True) else "OFF"
        fuse = "CONTACT" if shot.fuse_time is None else f"{shot.fuse_time:g}s"
        self.status.set_text(f"FIRING {shot.shell} - terrain damage {terrain_damage}; fuse {fuse}.")
        self._sync_controls(redraw=False)
        self.flight_renderer.start()
        self._draw_frame(0.0)
        self._play_sound("fire")
        self.timer.start()

    def _on_timer_frame(self):
        started = time.perf_counter()
        self._advance_frame()
        # Tk schedules its next wait after this callback finishes drawing.
        spent_ms = (time.perf_counter() - started) * 1000
        self.timer.interval = max(1, round(self.frame_interval_ms - spent_ms))

    def _advance_frame(self):
        if self.closed or self.page not in ("game", "shop"):
            return
        if not self.game.tick():
            self._show_results()
            return
        if not self.is_flying:
            if self._update_round_clock():
                self.control_renderer.draw(texts=(self.round_label,))
            return
        elapsed = (time.monotonic() - self.started_at) * data.PLAYBACK_SPEED
        self._draw_frame(min(elapsed, self.shot.duration))
        if elapsed >= self.shot.duration:
            self._finish_shot()

    def _draw_frame(self, elapsed):
        count = np.searchsorted(self.shot.times, elapsed, side="right")
        x, y = self.shot.position_at(elapsed)
        self.trail.set_data(np.append(self.shot.x[:count], x), np.append(self.shot.y[:count], y))
        self.projectile.set_data([x], [y])
        self.time_label.set_text(f"t = {elapsed:.2f} s")
        self._update_round_clock()
        self._update_environment_label(elapsed)
        self._set_camera(x, y, follow=True)
        self.flight_renderer.draw()

    def _refresh_terrain(self):
        self._invalidate_controls()
        pixels, colour_table = terrain_texture(self.game.terrain, self.theme, self.dither)
        self.terrain_image.set_data(pixels)
        self.terrain_image.set_cmap(ListedColormap(colour_table))
        self.terrain_image.set_clim(0, len(colour_table)-1)
        self.terrain_outline.set_segments(self.game.terrain.outline_segments())

    def _finish_shot(self):
        if not self.game.finish_shot(self.shot):
            if self.game.state == "ended":
                self._show_results()
            return
        self.is_flying = False
        self.flight_renderer.stop()
        self._invalidate_controls()
        if self.shot.removed_cells:
            self._refresh_terrain()
        self._refresh_targets()
        area = self.shot.area
        if area is not None:
            style = dict(fill=False, edgecolor=self.colours["effect"], linewidth=1.3,
                         antialiased=False, zorder=6)
            self.effect = Polygon(area.outline_points(), closed=True, **style)
            self.ax.add_patch(self.effect)
            trigger = "AIRBURST" if self.shot.reason == "fuse" else "IMPACT"
            self.status.set_text(f"{area.shell} {trigger} | HIT {len(self.shot.hit_target_ids)}"
                                 f" (+{self.shot.points_earned}) | {self.shot.removed_cells} cells removed.")
        else:
            self.status.set_text("SHOT ENDED - " + self.shot.reason.replace("_", " ") + ".")
        self._sync_controls(redraw=False)
        self.fig.canvas.draw_idle()
        if area is not None:
            self._play_sound("hit" if self.shot.hit_target_ids else "explosion")

    def _return_to_cannon(self, event=None):
        if (self.closed or self.page != "game" or self.is_flying
                or self.game.state != "playing"):
            return
        self._set_camera()
        self.control_renderer.draw(axes=(self.ax,))

    def clear_shot(self, event=None):
        """Cancel playback or clear its picture, retaining all terrain changes."""
        if self.audio is not None and self.is_flying:
            self.audio.stop()
        self._cancel_aim()
        self._invalidate_controls()
        self.timer.stop()
        self.flight_renderer.stop()
        self.game.cancel_shot()
        self.is_flying = False
        self.shot = None
        self.trail.set_data([], [])
        self.projectile.set_data([], [])
        self._remove_effect()
        self.status.set_text("Shot cleared. Terrain and current loading retained.")
        self.time_label.set_text("t = 0.00 s")
        self._set_camera()
        self._sync_controls()
        if self.page == "game" and self.game.state == "playing" and not self.closed:
            self.timer.start()

    def _start_game(self, gravity_mode, timed):
        if self.audio is not None:
            self.audio.stop()
        self.timer.stop()
        self.flight_renderer.stop()
        self.game.new_map(gravity_mode, timed=timed)
        self._reset_loading()
        self.shot = None
        self.is_flying = False
        self.trail.set_data([], [])
        self.projectile.set_data([], [])
        self._remove_effect()
        self._set_camera()
        self._refresh_terrain()
        self._refresh_targets()
        self._refresh_environment()
        self.status.set_text("New map. SELECT SHELL + CHARGES -> LOAD -> AIM -> FIRE.")
        self.time_label.set_text("t = 0.00 s")
        self._set_page("game")

    def _set_camera(self, projectile_x=None, projectile_y=None, follow=False):
        terrain = self.game.terrain
        width, height = min(data.VIEW_WIDTH, terrain.width), min(data.VIEW_HEIGHT, terrain.height)
        if follow:
            # Shift just enough to keep the shell on the safe box's edge;
            # movement within it reuses the cached landscape unchanged.
            left = min(max(self.ax.get_xlim()[0], projectile_x - data.CAMERA_SAFE_X[1]*width),
                       projectile_x - data.CAMERA_SAFE_X[0]*width)
            lower = min(max(self.ax.get_ylim()[0], projectile_y - data.CAMERA_SAFE_Y[1]*height),
                        projectile_y - data.CAMERA_SAFE_Y[0]*height)
        else:
            focus_x = self.game.cannon[0] if projectile_x is None else projectile_x
            left = focus_x - 0.5 * width
            lower = 0.0 if projectile_y is None else projectile_y - 0.75 * height
        left = max(0.0, min(terrain.width - width, left))
        lower = max(0.0, min(terrain.height - height, lower))
        if self.ax.get_xlim() != (left, left + width):
            self.ax.set_xlim(left, left + width)
        if self.ax.get_ylim() != (lower, lower + height):
            self.ax.set_ylim(lower, lower + height)
        field = self.game.gravity_field
        for index, label in self.gravity_labels:
            region_left = field.width * index / len(field.values)
            region_right = field.width * (index + 1) / len(field.values)
            start, end = max(left, region_left), min(left + width, region_right)
            position = ((start + end) / 2, lower + height - 1.5)
            if label.get_visible() != (end > start):
                label.set_visible(end > start)
            if label.get_position() != position:
                label.set_position(position)

    def _update_round_clock(self):
        if self.game.timed:
            seconds = math.ceil(self.game.remaining_seconds)
            label = f"{seconds // 60:02}:{seconds % 60:02}"
        else:
            label = "UNLIMITED"
        changed = self.round_label.get_text() != label
        self.round_label.set_text(label)
        return changed

    def _refresh_page_background(self):
        colour = (self.colours.get("menu_background", self.colours["background"])
                  if self.page == "menu" else self.colours["background"])
        self.fig.set_facecolor(colour)
        if hasattr(self.fig.canvas, "get_tk_widget"):
            self.fig.canvas.get_tk_widget().configure(background=LETTERBOX_COLOUR)

    def _set_page(self, page):
        self._cancel_aim()
        self._invalidate_controls()
        self.timer.stop()
        self.flight_renderer.stop()
        for button in self.page_buttons.values():
            button.disconnect_events()
            button.ax.remove()
        self.page_buttons = {}
        for artist in self.page_text:
            artist.remove()
        self.page_text = []
        for axis in self.page_axes:
            axis.remove()
        self.page_axes = []
        self.theme_preview = None
        self.page = page
        self._refresh_page_background()
        visible = page == "game"
        self.ax.set_visible(visible)
        self.angle_slider.ax.set_visible(visible)
        self.fuse_box.ax.set_visible(visible)
        for button in self.buttons.values():
            button.ax.set_visible(visible)
        for artist in (self.environment, self.status, self.time_label, self.summary,
                       self.fuse_hint, *self.control_text):
            artist.set_visible(visible)
        self.round_label.set_visible(page in ("game", "shop"))
        self._sync_controls()
        if page in ("game", "shop") and self.game.state == "playing":
            self.timer.start()

    def _text(self, x, y, text, size=12, colour="text", **kwargs):
        if self.page == "menu" and colour in ("text", "muted") and "menu_text" in self.colours:
            colour = "menu_text"
        elif colour in ("text", "muted") and f"ui_{colour}" in self.colours:
            colour = f"ui_{colour}"
        # Readouts on light chrome need different ink from the yellow projectile.
        if colour == "projectile" and "readout" in self.colours:
            colour = "readout"
        artist = self.fig.text(x, y, text, fontsize=size * self._layout_scale * self.font_scale,
                               color=self.colours[colour], fontfamily=self.font_family, **kwargs)
        self._font_sizes[artist] = size
        self.page_text.append(artist)
        return artist

    def _show_shop(self, event=None, message=""):
        if self.page not in ("game", "shop") or self.is_flying or self.closed:
            return
        if not self.game.tick():
            self._show_results()
            return
        self._set_page("shop")
        self.caption.set_text("SHOP")
        self._text(0.5, 0.78, "SHOP / SPEND YOUR SCORE", ha="center", size=18)
        self._text(0.5, 0.69, f"AVAILABLE POINTS: {self.game.score}", ha="center",
                   size=15, colour="projectile")
        values = " / ".join(f"{value:+.1f}" for value in self.game.gravity_field.values)
        self._text(0.5, 0.62, f"{data.GRAVITY_MODES[self.game.gravity_mode]} | g: {values}",
                   ha="center", size=11)
        for index, (item_id, item) in enumerate(data.SHOP_ITEMS.items(), 1):
            y = 0.51 - (index - 1) * 0.13
            self._text(0.12, y + 0.025, f"{index}. {item['name']}  |  {item['price']} points", size=12)
            self._add_button(item_id, f"BUY #{index}", [0.76, y, 0.13, 0.065],
                             lambda event, selected=item_id: self._buy_item(selected), page=True)
        self._text(0.12, 0.335, "Gravity reroll: MIXED mode only. Terrain and wind stay in place.",
                   size=10, colour="muted")
        self._text(0.12, 0.305, "Map reset: new terrain, targets and environment; keeps score and time.",
                   size=10, colour="muted")
        self._text(0.5, 0.27, f"Minimum balance: {data.MIN_SCORE} points.", ha="center",
                   size=10, colour="projectile")
        self._text(0.5, 0.225, textwrap.fill(message, width=84), ha="center", va="top", size=10)
        self._text(0.5, 0.16, "The round clock continues while shopping.", ha="center",
                   size=10, colour="muted")
        self._add_button("back", "RETURN TO GAME", [0.32, 0.07, 0.36, 0.07],
                         self._close_shop, page=True)
        self.fig.canvas.draw_idle()

    def _buy_item(self, item_id):
        if self.page != "shop" or self.closed:
            return
        success, message = self.game.purchase(item_id)
        if self.game.state != "playing":
            self._show_results()
            return
        if success:
            if data.SHOP_ITEMS[item_id]["effect"] == "reset_map":
                self.shot = None
                self.trail.set_data([], [])
                self.projectile.set_data([], [])
                self._remove_effect()
                self.time_label.set_text("t = 0.00 s")
                self._refresh_terrain()
                self._refresh_targets()
            self._refresh_environment()
            self.status.set_text(message)
        self._show_shop(message=message)

    def _close_shop(self, event=None):
        if self.page != "shop" or self.closed:
            return
        if not self.game.tick():
            self._show_results()
            return
        self._set_page("game")

    def _show_menu(self, event=None):
        self._set_page("menu")
        self.caption.set_text("MAIN MENU")
        # Eras Demi carries its own weight; keep fallback titles bold.
        weight = "normal" if self.menu_title_font_family == data.MENU_TITLE_FONT_FAMILY else "bold"
        title = self._text(0.5, 0.76, "Ballistic Lab 98", ha="center", size=data.MENU_TITLE_FONT_SIZE,
                           fontweight=weight)
        title.set_fontfamily(self.menu_title_font_family)
        if weight == "bold" and findfont(title.get_fontproperties()) == findfont(
                FontProperties(family=self.menu_title_font_family)):
            # Microsoft Sans Serif has no bold face; retain a heavier fallback title.
            title.set_path_effects([withStroke(linewidth=0.55, foreground=title.get_color())])
        credit = self._text(0.5, 0.71, "Inspired by Iron Nest", ha="center", size=12,
                            colour="muted", fontstyle="italic")
        credit.set_fontfamily(self.menu_credit_font_family)
        if self.settings_warning:
            self._text(0.5, 0.605, textwrap.shorten(self.settings_warning, width=90),
                       ha="center", size=8, colour="muted")
        self._add_button("start", "START", [0.35, 0.50, 0.30, 0.08], self._show_gravity, page=True)
        self._add_button("leaderboard", "LEADERBOARD", [0.35, 0.38, 0.30, 0.08],
                         self._show_leaderboard, page=True)
        self._add_button("help", "HOW TO PLAY", [0.35, 0.26, 0.30, 0.08], self._show_help, page=True)
        self._add_button("exit", "EXIT", [0.35, 0.14, 0.30, 0.08], self._quit, page=True)
        # Shift the four main buttons down one framebuffer pixel, even after resizing.
        for name in ("start", "leaderboard", "help", "exit"):
            axis = self.page_buttons[name].ax
            axis.set_axes_locator(lambda ax, renderer, base=axis.get_position().frozen():
                                  base.translated(0, -1 / ax.figure.bbox.height))
        self._add_button("theme", "THEME", [0.81, 0.055, 0.14, 0.045],
                         self._show_theme, page=True, size=9)
        self._text(0.025, 0.025, "V0.8", size=8, colour="muted", ha="left", va="bottom")
        self.fig.canvas.draw_idle()

    @staticmethod
    def _duration_description():
        seconds = data.ROUND_DURATION_SECONDS
        return f"{seconds / 60:g} MIN" if seconds % 60 == 0 else f"{seconds:g} S"

    def _show_help(self, event=None):
        if self.closed or self.page not in ("menu", "help"):
            return
        self._set_page("help")
        self.caption.set_text("FIELD MANUAL")
        self._text(0.5, 0.82, "HOW TO PLAY", ha="center", size=20)
        self._text(0.07, 0.72, "1 / LOAD & FIRE", size=12)
        steps = (f"Choose a shell, then packs 1 to {data.CHARGE_MAX} in order.\n"
                 "Press LOAD to commit the shell and packs.\n"
                 "Choose IMPACT or TIMED where available.\n"
                 f"TIMED: enter 0 < t <= {data.MAX_SHOT_TIME:g}s and press Enter.\n"
                 "Aim with ANGLE, choose LEFT/RIGHT, then FIRE.\n"
                 "Each shot consumes its load. Load again to fire.\n"
                 "Hint: Try angles above 45 degrees for a different effect.")
        self._text(0.07, 0.67, steps, size=10, va="top", linespacing=1.5)
        self._text(0.07, 0.43, "2 / ROUND & SCORE", size=12)
        rounds = (f"Each target is worth {data.POINTS_PER_TARGET} points.\n"
                  f"TIMED: {self._duration_description()}; the clock also runs in SHOP.\n"
                  "UNLIMITED scores are not saved to the leaderboard.\n"
                  "CLEAR SHOT cancels a shot or clears its trail.\n"
                  "TO CANNON returns the view between shots.\n"
                  "Negative g favors air; positive g favors ground.\n"
                  "F11: fullscreen. THEME: display and sound.")
        self._text(0.07, 0.38, rounds, size=10, va="top", linespacing=1.5)
        self._text(0.54, 0.72, "SHELLS", size=12)
        descriptions = []
        for name, shell in data.SHELLS.items():
            if shell["shape"] == "rectangle":
                shape = f"forward {shell['length']:g}x{shell['width']:g}m"
            elif shell["shape"] == "sector":
                shape = f"{shell['angle_degrees']:g}deg fan, r={shell['radius']:g}m"
            else:
                shape = f"circle, r={shell['radius']:g}m"
            descriptions.append(f"{name} {shell['mass']:g}kg: {shape}.")
        digging = "/".join(name for name, shell in data.SHELLS.items() if shell.get("destroys_terrain", True))
        preserving = "/".join(name for name, shell in data.SHELLS.items() if not shell.get("destroys_terrain", True))
        timed_only = "/".join(name for name, shell in data.SHELLS.items() if shell.get("timed_only", False))
        descriptions.append(f"{digging} dig terrain; {preserving} leave it intact.")
        if timed_only:
            descriptions.append(f"{timed_only}: TIMED ONLY; early contact = no burst.")
        self._text(0.54, 0.67, "\n".join(descriptions), size=10, va="top", linespacing=1.5)
        self._text(0.54, 0.43, "SHOP", size=12)
        shop = (f"RESET MAP: {data.SHOP_ITEMS['map_reset']['price']} points.\n"
                f"REROLL GRAVITY: {data.SHOP_ITEMS['gravity_reroll']['price']} points, MIXED only.\n"
                f"You can borrow down to {data.MIN_SCORE} points.\n"
                "Purchases keep the current round running.")
        self._text(0.54, 0.38, shop, size=10, va="top", linespacing=1.5)
        self._add_button("back", "BACK", [0.35, 0.055, 0.30, 0.06], self._show_menu, page=True)
        self.fig.canvas.draw_idle()

    def _show_theme(self, event=None):
        if self.closed or self.page not in ("menu", "theme"):
            return
        self._set_page("theme")
        self.caption.set_text("DISPLAY & SOUND")
        self._text(0.5, 0.80, "DISPLAY / SOUND", size=18, ha="center")
        gap = 0.04
        width = (0.72 - gap * (len(THEMES) - 1)) / len(THEMES)
        for index, (key, theme) in enumerate(THEMES.items()):
            button = self._add_button(f"palette_{key}", theme["label"],
                                     [0.14 + index*(width + gap), 0.66, width, 0.07],
                                     lambda event, selected=key: self._select_theme(selected), page=True)
            if key == self.theme_id:
                button.color = self.colours["selected"]
                button.hovercolor = self.colours["selected_hover"]
                button.ax.set_facecolor(button.color)
                button.label.set_color(self.colours["selected_text"])
                self._bevel(button.ax, sunken=True)
        self._text(0.5, 0.61, f"PALETTE: {self.theme['label']}", size=11, ha="center")
        self._add_button("dither", f"DITHER: {'ON' if self.dither else 'OFF'}",
                         [0.14, 0.52, 0.22, 0.06], self._toggle_dither, page=True)
        self._add_button("scanlines", f"SCANLINES: {'ON' if self.scanlines else 'OFF'}",
                         [0.39, 0.52, 0.22, 0.06], self._toggle_scanlines, page=True)
        self._add_button("sound", f"SOUND: {'ON' if self.sound_enabled else 'OFF'}",
                         [0.64, 0.52, 0.22, 0.06], self._toggle_sound, page=True)
        self._text(0.5, 0.485, "MAP PREVIEW", size=9, ha="center", colour="muted")
        preview = self.fig.add_axes([0.18, 0.235, 0.64, 0.235])
        preview.imshow(self.terrain_image.get_array(), origin="lower", aspect="auto",
                       cmap=self.terrain_image.get_cmap(), norm=self.terrain_image.norm,
                       interpolation="nearest")
        self.theme_preview = preview
        swatches = self.fig.add_axes([0.18, 0.175, 0.64, 0.035])
        swatches.imshow(np.arange(len(self.theme["swatches"]))[None, :], aspect="auto",
                        cmap=ListedColormap(self.theme["swatches"]),
                        vmin=0, vmax=len(self.theme["swatches"])-1, interpolation="nearest")
        for axis in (preview, swatches):
            axis.set_xticks([])
            axis.set_yticks([])
            axis.set_navigate(False)
            for spine in axis.spines.values():
                spine.set_edgecolor(self.colours["border"])
            self.page_axes.append(axis)
        hint = "Sound effects are supported on Windows only."
        self._text(0.5, 0.13, textwrap.shorten(self.settings_warning, width=90) if self.settings_warning else hint,
                   ha="center", size=9, colour="muted")
        self._add_button("back", "BACK", [0.35, 0.045, 0.30, 0.06], self._show_menu, page=True)
        self.fig.canvas.draw_idle()

    def _select_theme(self, theme_id):
        if self.closed or self.page != "theme" or theme_id not in THEMES:
            return
        self.theme_id = theme_id
        self.theme = THEMES[theme_id]
        self.colours = self.theme["colours"]
        self._restyle()
        self._save_display_settings()
        self._show_theme()

    def _toggle_dither(self, event=None):
        if self.closed or self.page != "theme":
            return
        self.dither = not self.dither
        self._refresh_terrain()
        self._save_display_settings()
        self._show_theme()

    def _toggle_scanlines(self, event=None):
        if self.closed or self.page != "theme":
            return
        self.scanlines = not self.scanlines
        display_filter = getattr(self.fig.canvas, "scanline_filter", None)
        if display_filter is not None:
            display_filter.enabled = self.scanlines
        self._save_display_settings()
        self._show_theme()

    def _save_display_settings(self):
        self.display_settings.update(theme=self.theme_id, dither=self.dither,
                                     scanlines=self.scanlines, sound=self.sound_enabled)
        if self.settings_store is not None:
            _, self.settings_warning = self.settings_store.save(self.display_settings)

    def _toggle_sound(self, event=None):
        if self.closed or self.page != "theme":
            return
        self.sound_enabled = not self.sound_enabled
        if self.audio is not None:
            self.audio.set_enabled(self.sound_enabled)
        self._save_display_settings()
        self._show_theme()
        if self.sound_enabled:
            self._play_sound("click")

    def _restyle(self):
        """Recolour existing game artists without replacing widgets or callbacks."""
        c = self.colours
        self._invalidate_controls()
        self._refresh_page_background()
        self.header_ax.set_facecolor(self.theme["header"])
        self.ax.set_facecolor(c.get("plot_background", c["background"]))
        self.ax.tick_params(colors=self._ui_colour())
        for artist in (self.ax.xaxis.label, self.ax.yaxis.label, self.status, *self.control_text):
            artist.set_color(self._ui_colour())
        for artist in (self.caption, self.environment):
            artist.set_color(c.get("header_text", c["text"]))
        for spine in self.ax.spines.values():
            spine.set_edgecolor(c["border"])
        self.summary.set_color(self._ui_colour("muted"))
        self.fuse_hint.set_color(self._ui_colour("muted"))
        self.time_label.set_color(c.get("readout", c["projectile"]))
        self.round_label.set_color(c.get("header_text", c["projectile"]))
        self.pending_legend.set_text(self.theme["legend"])
        self.loaded_legend.set_text(self.theme["loaded_legend"])
        self.trail.set_color(c["trajectory"])
        self.projectile.set_color(c["projectile"])
        self.projectile.set_markeredgecolor(c.get("projectile_edge", c["projectile"]))
        if self.effect is not None:
            self.effect.set_edgecolor(c["effect"])
        self.cannon_icon.recolour(c)
        self.terrain_outline.set_color(c["terrain_edge"])
        self._refresh_terrain()
        self._displayed_targets = None
        self._refresh_targets()
        self._refresh_environment()
        self.angle_slider.ax.set_facecolor(c["panel"])
        self.angle_slider.poly.set_facecolor(c["selected"])
        self.angle_slider.track.set_facecolor(c["panel"])
        self.angle_slider._handle.set_markerfacecolor(c["panel"])
        self.angle_slider._handle.set_markeredgecolor(c["bevel_dark"])
        self.angle_slider.vline.set_color(c["border"])
        for label in (self.angle_slider.label, self.angle_slider.valtext):
            label.set_color(self._ui_colour())
        self.fuse_box.color = self.fuse_box.hovercolor = c["input_background"]
        self.fuse_box.ax.set_facecolor(c["input_background"])
        for artist in (self.fuse_box.label, self.fuse_box.text_disp, self.fuse_box.cursor):
            artist.set_color(c["input_text"])
        self._bevel(self.fuse_box.ax, sunken=True)

    def _show_gravity(self, event=None):
        self._set_page("gravity")
        self.caption.set_text("CHOOSE GRAVITY")
        self._text(0.5, 0.78, "1 / GRAVITY MODE", ha="center", size=16)
        low, high = data.RANDOM_GRAVITY_RANGE
        descriptions = (f"Uniform g = {data.GRAVITY:g}", f"One random g in [{low:g}, {high:g}]",
                        f"{self.game.mixed_gravity_regions} regions; g in [{low:g}, {high:g}]")
        for index, (mode, label) in enumerate(data.GRAVITY_MODES.items()):
            y = 0.60 - index * 0.14
            self._add_button(mode, label, [0.18, y, 0.23, 0.08],
                             lambda event, selected=mode: self._select_gravity(selected), page=True)
            self._text(0.46, y + 0.03, descriptions[index], size=11)
        self._add_button("back", "BACK", [0.07, 0.09, 0.15, 0.06], self._show_menu, page=True)

    def _select_gravity(self, mode):
        self.selected_gravity = mode
        self._set_page("time_mode")
        self.caption.set_text("CHOOSE ROUND")
        self._text(0.5, 0.76, "2 / ROUND TYPE", ha="center", size=16)
        self._text(0.5, 0.66, data.GRAVITY_MODES[mode], ha="center", colour="muted")
        self._add_button("timed", f"TIMED / {self._duration_description()}", [0.29, 0.46, 0.42, 0.09],
                         lambda event: self._start_game(mode, True), page=True)
        self._add_button("unlimited", "UNLIMITED", [0.29, 0.31, 0.42, 0.09],
                         lambda event: self._start_game(mode, False), page=True)
        self._add_button("back", "BACK", [0.07, 0.09, 0.15, 0.06], self._show_gravity, page=True)

    def _end_game(self, event=None, reason="finished"):
        self.game.end_round(reason)
        self._show_results()

    def _return_menu(self, event=None):
        if self.audio is not None and self.is_flying:
            self.audio.stop()
        self.game.end_round("menu")
        if self.game.timed and not self.game.score_saved:
            self._show_results()
        else:
            self.is_flying = False
            self._show_menu()

    def _show_results(self):
        if self.page != "results":
            self._play_sound("round_end")
        self.is_flying = False
        self._set_page("results")
        self.caption.set_text("ROUND OVER")
        self._text(0.5, 0.76, f"SCORE  {self.game.score}", ha="center", size=26, colour="projectile")
        mode = data.GRAVITY_MODES[self.game.gravity_mode]
        self._text(0.5, 0.65, f"{mode} / {'TIMED' if self.game.timed else 'UNLIMITED'}"
                   f"  |  WIND: {self.game.wind_label}", ha="center")
        self._text(0.5, 0.56, f"Hits: {self.game.targets_hit}  Shots: {self.game.shots_fired}"
                   f"  End: {self.game.end_reason.replace('_', ' ')}", ha="center", size=11)
        self._text(0.5, 0.44, textwrap.fill(self.game.result_message, width=78),
                   ha="center", va="top", size=10, colour="muted")
        self._add_button("again", "PLAY AGAIN", [0.22, 0.21, 0.24, 0.08],
                         lambda event: self._start_game(self.game.gravity_mode, self.game.timed), page=True)
        self._add_button("menu", "MAIN MENU", [0.54, 0.21, 0.24, 0.08], self._show_menu, page=True)

    def _show_leaderboard(self, event=None):
        self._set_page("leaderboard")
        self.caption.set_text("LEADERBOARD")
        mode = self.leaderboard_mode
        records, warning = self.game.score_store.leaderboard(mode)
        self._text(0.5, 0.81, "TIMED SCORES / TOP 10", ha="center", size=16)
        self._add_button("filter", f"MODE: {data.GRAVITY_MODES[mode]}", [0.31, 0.69, 0.38, 0.065],
                         self._next_leaderboard_mode, page=True)
        lines = ["RANK    SCORE    WIND       DATE (LOCAL)"]
        for index, record in enumerate(records, 1):
            direction, level = record["wind_direction"], record["wind_level"]
            wind = "NONE" if level == 0 else f"{'L' if direction < 0 else 'R'}{level}"
            date = datetime.fromisoformat(record["played_at"]).astimezone().strftime("%m-%d %H:%M")
            lines.append(f"{index:>4}    {record['score']:>5}    {wind:<5}      {date}")
        if not records:
            lines.append("\nNo timed scores for this mode yet.")
        self._text(0.24, 0.63, "\n".join(lines), va="top", size=11, linespacing=1.6)
        if warning:
            self._text(0.5, 0.17, textwrap.fill(warning, width=88), ha="center", size=9, colour="muted")
        self._add_button("back", "BACK", [0.07, 0.07, 0.15, 0.06], self._show_menu, page=True)

    def _next_leaderboard_mode(self, event=None):
        modes = tuple(data.GRAVITY_MODES)
        self.leaderboard_mode = modes[(modes.index(self.leaderboard_mode) + 1) % len(modes)]
        self._show_leaderboard()

    def _quit(self, event=None):
        self._on_close(event)
        plt.close(self.fig)

    def _on_close(self, event):
        if self.closed:
            return
        if self.audio is not None:
            self.audio.close()
        self._cancel_aim()
        self.timer.stop()
        self.flight_renderer.close()
        self.control_renderer.close()
        self.game.end_round("closed")
        if self.game.timed and self.game.score_save_attempted and not self.game.score_saved:
            print(self.game.result_message)
        self.closed = True
        self.is_flying = False

    def show(self):
        plt.show()
