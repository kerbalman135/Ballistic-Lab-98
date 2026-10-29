"""A small Agg framebuffer displayed at integer zoom in a resizable Tk window.

Only the presentation is scaled: physics, world coordinates and mouse hit
testing keep their original precision. Tkinter belongs to the standard library.
"""

import math
from types import SimpleNamespace

import matplotlib
import matplotlib.pyplot as plt
import numpy as np

from . import game_data as data

LETTERBOX_COLOUR = "#000000"


class ScanlineFilter:
    """Darken screen-anchored rows in a reusable display copy, never the Agg cache."""

    def __init__(self, enabled=True, strength=0.12, period=2):
        self.enabled = enabled
        self.period = max(2, int(period))
        strength = min(1.0, max(0.0, float(strength)))
        self.factor = np.float32(1.0 - strength)
        self.output = None

    def apply(self, rgba, bounds=None):
        rgba = np.asarray(rgba)
        if not self.enabled:
            return rgba
        height, width = rgba.shape[:2]
        if self.output is None or self.output.shape != rgba.shape:
            self.output = np.empty_like(rgba)
            bounds = None
        x0, y0, x1, y1 = (0, 0, width, height) if bounds is None else bounds
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(width, x1), min(height, y1)
        if x1 <= x0 or y1 <= y0:
            return self.output
        self.output[y0:y1, x0:x1] = rgba[y0:y1, x0:x1]
        # Keep the stripe phase fixed at the top of the complete framebuffer,
        # even when a dirty rectangle begins partway through a dark row.
        first = y0 + (self.period - 1 - y0) % self.period
        dark = np.s_[first:y1:self.period, x0:x1]
        # Contiguous RGBA rows are much faster than strided RGB indexing.
        # Restore alpha afterwards: this is a brightness effect, not transparency.
        np.multiply(rgba[dark], self.factor, out=self.output[dark], casting="unsafe")
        self.output[first:y1:self.period, x0:x1, 3] = rgba[first:y1:self.period, x0:x1, 3]
        return self.output


def render_geometry(width, height, render_width=None, render_height=None, lock_aspect=None):
    """Return framebuffer size and integer zoom, optionally fitting the chosen ratio."""
    width, height = max(1, int(width)), max(1, int(height))
    cap_width = max(1, data.RENDER_WIDTH if render_width is None else render_width)
    cap_height = max(1, data.RENDER_HEIGHT if render_height is None else render_height)
    lock_aspect = data.LOCK_RENDER_ASPECT if lock_aspect is None else lock_aspect
    if lock_aspect:
        ratio = cap_width / cap_height
        width, height = min(width, height * ratio), min(height, width / ratio)
    zoom = max(1, math.ceil(width / cap_width), math.ceil(height / cap_height))
    width, height = int(width), int(height)
    return max(1, width // zoom), max(1, height // zoom), zoom


def create_game_figure(title, facecolor, display_settings=None):
    preferences = display_settings or {}
    initial_width, initial_height = 1280, 720
    if preferences.get("lock_render_aspect", data.LOCK_RENDER_ASPECT):
        ratio = (preferences.get("render_width", data.RENDER_WIDTH)
                 / preferences.get("render_height", data.RENDER_HEIGHT))
        initial_width = min(initial_width, initial_height * ratio)
        initial_height = initial_width / ratio
    initial_size = initial_width / data.RENDER_DPI, initial_height / data.RENDER_DPI
    # Keep notebooks' other figures and backend selection intact.
    if "tk" not in matplotlib.get_backend().lower():
        return plt.figure(num=title, figsize=initial_size, dpi=data.RENDER_DPI,
                          facecolor=facecolor)

    import tkinter as tk
    from matplotlib import _pylab_helpers
    from matplotlib.backend_bases import ResizeEvent
    from matplotlib.backends import _backend_tk
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure

    class ScaledToolbar(_backend_tk.NavigationToolbar2Tk):
        def draw_rubberband(self, event, x0, y0, x1, y1):
            self.remove_rubberband()
            canvas = self.canvas
            zoom = canvas.pixel_zoom
            ox, oy = canvas.display_offset
            height = canvas.figure.bbox.height
            coordinates = (ox + x0*zoom, oy + (height-y0)*zoom,
                           ox + x1*zoom, oy + (height-y1)*zoom)
            canvas._rubberband_rect_black = canvas._tkcanvas.create_rectangle(*coordinates)
            canvas._rubberband_rect_white = canvas._tkcanvas.create_rectangle(
                *coordinates, outline="white", dash=(3, 3))

    class ScaledManager(_backend_tk.FigureManagerTk):
        _toolbar2_class = ScaledToolbar

    class ScaledCanvas(FigureCanvasTkAgg):
        manager_class = ScaledManager

        def __init__(self, figure, master=None):
            super().__init__(figure, master=master)
            self._tkcanvas.configure(background=LETTERBOX_COLOUR)
            self._render_photo = tk.PhotoImage(master=self._tkcanvas)
            preferences = display_settings or {}
            self.scanline_filter = ScanlineFilter(preferences.get("scanlines", data.DEFAULT_SCANLINES),
                                                  preferences.get("scanline_strength", data.SCANLINE_STRENGTH),
                                                  preferences.get("scanline_period", data.SCANLINE_PERIOD))
            self.display_size = self.get_width_height(physical=True)
            self.pixel_zoom = 1
            self.display_offset = (0, 0)
            self.resize(SimpleNamespace(width=self.display_size[0], height=self.display_size[1]))

        def _update_device_pixel_ratio(self, event=None):
            # OS scaling applies to the native window/toolbar, not the framebuffer.
            self._set_device_pixel_ratio(1)

        def resize(self, event):
            if not hasattr(self, "_render_photo"):
                return
            width, height = max(1, event.width), max(1, event.height)
            preferences = display_settings or {}
            rw, rh, self.pixel_zoom = render_geometry(width, height,
                preferences.get("render_width"), preferences.get("render_height"),
                preferences.get("lock_render_aspect"))
            self.display_size = (width, height)
            self.display_offset = ((width - rw * self.pixel_zoom) // 2,
                                   (height - rh * self.pixel_zoom) // 2)
            # Round upward by one float step: Agg truncates sizes to integers.
            self.figure.set_size_inches(math.nextafter(rw / data.RENDER_DPI, math.inf),
                                        math.nextafter(rh / data.RENDER_DPI, math.inf),
                                        forward=False)
            self._render_photo.configure(width=rw, height=rh)
            self._tkphoto.configure(width=width, height=height)
            self._tkphoto.put(LETTERBOX_COLOUR, to=(0, 0, width, height))
            self._tkcanvas.coords(self._tkcanvas_image_region, width / 2, height / 2)
            ResizeEvent("resize_event", self)._process()
            self.draw_idle()

        def _event_mpl_coords(self, event):
            ox, oy = self.display_offset
            return ((self._tkcanvas.canvasx(event.x) - ox) / self.pixel_zoom,
                    self.figure.bbox.height -
                    (self._tkcanvas.canvasy(event.y) - oy) / self.pixel_zoom)

        def blit(self, bbox=None):
            rw, rh = self.get_width_height(physical=True)
            if bbox is None:
                x0, y0, x1, y1 = 0, 0, rw, rh
            else:
                x0 = max(0, math.floor(bbox.x0))
                x1 = min(rw, math.ceil(bbox.x1))
                y0 = max(0, rh - math.ceil(bbox.y1))
                y1 = min(rh, rh - math.floor(bbox.y0))
            if x1 <= x0 or y1 <= y0:
                return
            pixels = self.scanline_filter.apply(self.renderer.buffer_rgba(), (x0, y0, x1, y1))
            _backend_tk.blit(self._render_photo, pixels, (0, 1, 2, 3), bbox=bbox)
            zoom = self.pixel_zoom
            ox, oy = self.display_offset
            self._tkphoto.tk.call(str(self._tkphoto), "copy", str(self._render_photo),
                                  "-from", x0, y0, x1, y1,
                                  "-to", ox + x0 * zoom, oy + y0 * zoom,
                                  "-zoom", zoom, zoom, "-compositingrule", "set")

    figure = Figure(figsize=initial_size, dpi=data.RENDER_DPI, facecolor=facecolor)
    figure.set_label(title)
    number = max(plt.get_fignums(), default=0) + 1
    manager = ScaledCanvas.new_manager(figure, number)
    _pylab_helpers.Gcf._set_new_active_manager(manager)
    # F11 keeps fullscreen available alongside normal resizing/maximizing.
    figure.canvas.mpl_connect("key_press_event",
                             lambda event: manager.full_screen_toggle() if event.key == "f11" else None)
    return figure
