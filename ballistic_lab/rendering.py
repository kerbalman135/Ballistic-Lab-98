"""Partial control updates and cached live-flight rendering.

Matplotlib blitting restores saved pixels instead of drawing every widget
on every frame. Camera movement invalidates only the landscape cache.
Normal draw events rebuild both caches, including after a resize or hover.
"""

import numpy as np
from matplotlib.backends.backend_agg import RendererAgg
from matplotlib.patches import Patch, Rectangle
from matplotlib.offsetbox import AnnotationBbox
from matplotlib.transforms import Bbox, IdentityTransform
from matplotlib.widgets import TextBox


class ResponsiveTextBox(TextBox):
    def stop_typing(self):
        # Matplotlib 3.8 redraws the whole figure even when this box is idle.
        if self.capturekeystrokes or self.cursor.get_visible():
            super().stop_typing()


class ControlRenderer:
    """Repaint changed controls/text without redrawing the static landscape."""

    def __init__(self, figure, landscape, flight_renderer):
        self.figure = figure
        self.canvas = figure.canvas
        self.landscape = landscape
        self.flight_renderer = flight_renderer
        self.invalidate()
        self.draw_connection = self.canvas.mpl_connect("draw_event", self._on_draw)
        self.resize_connection = self.canvas.mpl_connect("resize_event", self.invalidate)

    def invalidate(self, event=None):
        self.geometry = None
        self.view = None
        self.bounds = {}
        self.text_states = {}

    def _geometry(self):
        return (*self.figure.bbox.bounds, self.figure.dpi)

    def _view(self):
        return (*self.landscape.get_xlim(), *self.landscape.get_ylim(), *self.landscape.bbox.bounds)

    @staticmethod
    def _text_state(text):
        return (text.get_text(), text.get_color(), text.get_position(), text.get_visible())

    def _bounds(self, artist, renderer):
        if artist is self.landscape:
            bounds = self.flight_renderer.scene_bounds(renderer)
        elif artist in self.figure.axes:
            bounds = Bbox.union([artist.bbox, *(text.get_window_extent(renderer)
                                 for text in artist.texts if text.get_visible())])
            # Spines straddle the axes edge. At low resolution, a neighbouring
            # button's antialiased border can fall into a cleared pixel row.
            stroke = max((spine.get_linewidth() for spine in artist.spines.values()), default=0)
            bounds = bounds.padded(stroke * self.figure.dpi / 144 + 1)
        else:
            bounds = artist.get_window_extent(renderer)
        return bounds.frozen() if bounds is not None else None

    def _on_draw(self, event):
        self.invalidate()
        if self.canvas.is_saving():
            return
        self.geometry = self._geometry()
        self.view = self._view()
        for artist in (*self.figure.axes, *self.figure.texts):
            if artist.get_visible():
                self.bounds[artist] = self._bounds(artist, event.renderer)
        self.text_states = {text: self._text_state(text) for text in self.figure.texts}

    @staticmethod
    def _merge(regions):
        merged = []
        for region in regions:
            index = 0
            while index < len(merged):
                if region.overlaps(merged[index]):
                    region = Bbox.union((region, merged.pop(index)))
                    index = 0
                else:
                    index += 1
            merged.append(region)
        return merged

    def draw(self, axes=(), texts=()):
        if (not self.canvas.supports_blit or self.flight_renderer.active
                or self.geometry != self._geometry()):
            self.canvas.draw_idle()
            return
        renderer = self.canvas.get_renderer()
        self.flight_renderer.begin_update()
        changed_texts = [text for text in texts
                         if self.text_states.get(text) != self._text_state(text)]
        changed = set((*axes, *changed_texts))
        if not changed:
            self.figure.stale = False
            return
        artists = [artist for artist in (*self.figure.axes, *self.figure.texts)
                   if artist.get_visible()]
        view = self._view()
        current = {artist: (self.bounds[artist] if artist in self.bounds and artist not in changed
                            and (artist is not self.landscape or view == self.view)
                            else self._bounds(artist, renderer)) for artist in artists}
        regions = [bounds.padded(2) for artist in changed
                   for bounds in (self.bounds.get(artist), current.get(artist))
                   if bounds is not None]
        # A merged rectangle also clears the gaps between its original parts.
        # Include controls in those gaps before painting, and repeat on expansion.
        regions = self._merge(regions)
        while True:
            neighbours = {artist for artist, bounds in current.items()
                          if artist not in changed and bounds is not None
                          and any(bounds.overlaps(region) for region in regions)}
            if not neighbours:
                break
            changed.update(neighbours)
            regions = self._merge([*regions, *(current[artist].padded(2) for artist in neighbours)])
        regions = [clipped for region in regions
                   if (clipped := Bbox.intersection(region, self.figure.bbox)) is not None]
        for region in regions:
            Rectangle((region.x0, region.y0), region.width, region.height,
                      transform=IdentityTransform(), facecolor=self.figure.get_facecolor(),
                      edgecolor="none", linewidth=0, antialiased=False).draw(renderer)
        transfers = []
        for artist in sorted(artists, key=lambda artist: artist.get_zorder()):
            if artist in changed:
                if artist is self.landscape:
                    transfers.extend(self.flight_renderer.draw_idle_scene(renderer, force=view != self.view))
                    if view != self.view and self.bounds.get(artist) is not None:
                        transfers.append(self.bounds[artist].padded(2))
                else:
                    artist.draw(renderer)
                    transfers.extend(box.padded(2) for box in (self.bounds.get(artist), current.get(artist))
                                     if box is not None)
                self.bounds[artist] = self._bounds(artist, renderer)
        for artist in changed - set(artists):
            if self.bounds.get(artist) is not None:
                transfers.append(self.bounds[artist].padded(2))
        for text in changed_texts:
            self.text_states[text] = self._text_state(text)
        for region in self._merge(transfers):
            clipped = Bbox.intersection(region, self.figure.bbox)
            if clipped is not None:
                self.canvas.blit(clipped)
        self.bounds[self.landscape] = current.get(self.landscape)
        self.view = view
        self.figure.stale = False

    def close(self):
        self.canvas.mpl_disconnect(self.draw_connection)
        self.canvas.mpl_disconnect(self.resize_connection)
        self.invalidate()


class FlightRenderer:
    """Share a static scene between aiming and flight; transfer only dirty pixels."""

    def __init__(self, axes, labels, motion=()):
        self.axes = axes
        self.canvas = axes.figure.canvas
        self.labels = tuple(labels)
        self.motion = tuple(motion)
        self.active = False
        self.foreground = ()
        self.saved_flags = []
        self.invalidate()
        self.draw_connection = self.canvas.mpl_connect("draw_event", self._on_draw)
        self.resize_connection = self.canvas.mpl_connect("resize_event", self.invalidate)

    def invalidate(self, event=None):
        self.controls_background = None
        self.scene_background = None
        self.view = None
        self.transfer_bounds = []
        self.base_key = None
        self.base_bounds = None
        self.idle_background = None
        self.idle_box = None
        self.previous_view = None
        self.previous_bounds = {}
        self.previous_labels = {}
        self.previous_line = None
        self.current_bounds = {}

    def begin_update(self):
        self.current_bounds = {}

    def _collect_foreground(self):
        # Preserve layering: trails pass behind enemies and cannon parts.
        self.foreground = tuple(sorted(
            (artist for artist in self.axes.get_children() if artist.get_zorder() >= 3),
            key=lambda artist: artist.get_zorder()))

    def start(self):
        self.stop()  # Restore old animation flags before collecting a new scene.
        if not self.canvas.supports_blit:
            return
        self._collect_foreground()
        self.saved_flags = [(artist, artist.get_animated())
                            for artist in (self.axes, *self.foreground, *self.labels)]
        for artist, _ in self.saved_flags:
            artist.set_animated(True)
        self.active = True
        self.invalidate()

    def stop(self):
        self.active = False
        for artist, animated in self.saved_flags:
            artist.set_animated(animated)
        self.saved_flags = []
        self.invalidate()

    def close(self):
        self.stop()
        self.canvas.mpl_disconnect(self.draw_connection)
        self.canvas.mpl_disconnect(self.resize_connection)

    def _view(self):
        return (*self.axes.get_xlim(), *self.axes.get_ylim(),
                *self.axes.bbox.bounds, *self.axes.figure.bbox.bounds, self.axes.figure.dpi)

    def _clip(self, bounds):
        if bounds is None or not np.all(np.isfinite(bounds.extents)):
            return None
        clipped = Bbox.intersection(bounds, self.axes.figure.bbox)
        return clipped.frozen() if clipped is not None else None

    def _artist_bounds(self, artist, renderer):
        if not artist.get_visible() or (hasattr(artist, "get_text") and not artist.get_text()):
            return None
        if isinstance(artist, AnnotationBbox) and not artist._check_xy(renderer):
            return None
        if isinstance(artist, Patch):
            # Bézier control vertices conservatively bound the complete curve.
            # Patch.get_window_extent otherwise solves extrema for every circle.
            points = artist.get_transform().transform(artist.get_path().vertices)
            if not len(points) or not np.all(np.isfinite(points)):
                return None
            bounds = Bbox.from_extents(*points.min(axis=0), *points.max(axis=0))
        else:
            bounds = artist.get_window_extent(renderer)
        if not np.all(np.isfinite(bounds.extents)):
            return None
        bounds = bounds.padded(4)
        if artist.get_clip_on() and not isinstance(artist, AnnotationBbox):
            clip = artist.get_clip_box()
            if clip is not None:
                bounds = Bbox.intersection(bounds, clip.padded(2))
        return self._clip(bounds)

    def _foreground_bounds(self, artist, renderer):
        if artist not in self.current_bounds:
            if self.previous_view == self._view() and artist in self.previous_bounds and not artist.stale:
                self.current_bounds[artist] = self.previous_bounds[artist]
            else:
                self.current_bounds[artist] = self._artist_bounds(artist, renderer)
        return self.current_bounds[artist]

    def _base_scene_bounds(self, renderer, drawn=False):
        key = self._view()
        if key == self.base_key:
            return self.base_bounds
        if not drawn:
            bounds = self.axes.get_tightbbox(renderer, bbox_extra_artists=[])
        else:
            # Axes.draw already laid out ticks. Reading their actual extents avoids
            # get_tightbbox's repeated locator/font/layout work on moving frames.
            parts = [self.axes.bbox.padded(3)]
            for axis, limits in ((self.axes.xaxis, self.axes.get_xlim()),
                                 (self.axes.yaxis, self.axes.get_ylim())):
                low, high = sorted(limits)
                for text in (axis.label, axis.get_offset_text()):
                    box = self._artist_bounds(text, renderer)
                    if box is not None:
                        parts.append(box)
                for tick in (*axis.majorTicks, *axis.minorTicks):
                    if low - 1e-9 <= tick.get_loc() <= high + 1e-9:
                        for artist in (tick.label1, tick.label2, tick.tick1line, tick.tick2line):
                            box = self._artist_bounds(artist, renderer)
                            if box is not None:
                                parts.append(box)
            for title in (self.axes.title, self.axes._left_title, self.axes._right_title):
                box = self._artist_bounds(title, renderer)
                if box is not None:
                    parts.append(box)
            bounds = Bbox.union(parts)
        self.base_key = key
        self.base_bounds = self._clip(bounds.padded(2))
        return self.base_bounds

    def scene_bounds(self, renderer, drawn=False):
        parts = [self._base_scene_bounds(renderer, drawn)]
        parts.extend(self._foreground_bounds(artist, renderer) for artist in self.foreground)
        return self._clip(Bbox.union([part for part in parts if part is not None]))

    def _line_region(self, artist):
        current = np.asarray(artist.get_xydata())
        previous = self.previous_line
        if previous is None or len(previous) < 2 or len(current) < len(previous) - 1:
            return None
        if not np.array_equal(current[:len(previous)-1], previous[:-1]):
            return None
        # Include the old interpolated head, its join and every new segment.
        tail = np.vstack((previous[-2:], current[max(0, len(previous)-2):]))
        points = artist.get_transform().transform(tail)
        points = points[np.all(np.isfinite(points), axis=1)]
        if not len(points):
            return None
        box = Bbox.from_extents(*points.min(axis=0), *points.max(axis=0)).padded(4)
        return self._clip(Bbox.intersection(box, self.axes.bbox.padded(2)))

    def _dirty_foreground(self, renderer):
        regions = []
        for artist in self.foreground:
            if not artist.stale and artist in self.previous_bounds:
                continue
            if self.motion and artist is self.motion[0]:
                tail = self._line_region(artist)
                if tail is not None:
                    self._foreground_bounds(artist, renderer)
                    regions.append(tail)
                    continue
            regions.extend(box for box in (self.previous_bounds.get(artist),
                                           self._foreground_bounds(artist, renderer)) if box is not None)
        regions.extend(box for artist, box in self.previous_bounds.items()
                       if artist not in self.foreground and box is not None)
        return regions

    def _dirty_labels(self, renderer):
        regions = []
        for label in self.labels:
            old = self.previous_labels.get(label)
            state = ControlRenderer._text_state(label)
            if old is None or old[0] != state:
                regions.extend(box for box in (old[1] if old else None,
                                               self._artist_bounds(label, renderer)) if box is not None)
        return regions

    def _remember_scene(self, renderer):
        bounds = {artist: self._foreground_bounds(artist, renderer)
                                for artist in self.foreground}
        self.previous_view = self._view()
        self.previous_bounds = bounds
        self.previous_line = (np.asarray(self.motion[0].get_xydata()).copy() if self.motion else None)

    def _remember_labels(self, renderer):
        self.previous_labels = {label: (ControlRenderer._text_state(label),
                                       self._artist_bounds(label, renderer)) for label in self.labels}

    def draw_idle_scene(self, renderer, force=False):
        self._collect_foreground()
        view = self._view()
        regions = self._dirty_foreground(renderer)
        box = self.scene_bounds(renderer)
        if force or self.previous_view != view:
            regions.append(box)
        if (self.idle_background is None or self.view != view or self.idle_box is None
                or not self.idle_box.contains(*box.p0) or not self.idle_box.contains(*box.p1)):
            figure = self.axes.figure
            background = RendererAgg(int(figure.bbox.width), int(figure.bbox.height), figure.dpi)
            figure.patch.draw(background)
            flags = [(artist, artist.get_animated()) for artist in self.foreground]
            try:
                for artist, _ in flags:
                    artist.set_animated(True)
                self.axes.draw(background)
            finally:
                for artist, animated in flags:
                    artist.set_animated(animated)
            self.idle_box = box
            self.idle_background = background.copy_from_bbox(box)
            self.view = view
        self.canvas.restore_region(self.idle_background)
        for artist in self.foreground:
            artist.draw(renderer)
        self._remember_scene(renderer)
        return [box for region in regions if (box := self._clip(region)) is not None]

    def _draw_foreground(self, renderer):
        for artist in (*self.foreground, *self.labels):
            artist.draw(renderer)

    def _frame_bounds(self, renderer):
        return [self.scene_bounds(renderer, drawn=True),
                *(box for label in self.labels
                  if (box := self._artist_bounds(label, renderer)) is not None)]

    def _on_draw(self, event):
        self.begin_update()
        self.base_key = None
        self.previous_view = None
        if not self.active:
            self.invalidate()
            if self.axes.get_visible() and not self.canvas.is_saving():
                self._collect_foreground()
                self._base_scene_bounds(event.renderer, drawn=True)
                self._remember_scene(event.renderer)
                self._remember_labels(event.renderer)
            return
        if self.canvas.is_saving():
            # Axes.draw includes animated children when exporting a figure.
            self.axes.draw(event.renderer)
            for artist in self.labels:
                artist.draw(event.renderer)
            self.invalidate()
            return
        self.controls_background = self.canvas.copy_from_bbox(self.axes.figure.bbox)
        self.axes.draw(event.renderer)
        self.scene_background = self.canvas.copy_from_bbox(self.axes.figure.bbox)
        self.view = self._view()
        self._draw_foreground(event.renderer)
        self.transfer_bounds = self._frame_bounds(event.renderer)
        self._remember_scene(event.renderer)
        self._remember_labels(event.renderer)

    def draw(self):
        if not self.active:
            self.canvas.draw_idle()
            return
        if self.controls_background is None:
            # The draw-event handler captures backgrounds and paints this frame.
            self.canvas.draw()
            return
        self.begin_update()
        renderer = self.canvas.get_renderer()
        view = self._view()
        moving = view != self.view
        regions = self._dirty_labels(renderer)
        if not moving:
            regions.extend(self._dirty_foreground(renderer))
        if view != self.view:
            self.canvas.restore_region(self.controls_background)
            self.axes.draw(renderer)
            self.scene_background = self.canvas.copy_from_bbox(self.axes.figure.bbox)
            self.view = view
        else:
            self.canvas.restore_region(self.scene_background)
        self._draw_foreground(renderer)
        if moving:
            current = self._frame_bounds(renderer)
            regions.extend((self.transfer_bounds[0], current[0]))
            self.transfer_bounds = current
        for region in ControlRenderer._merge(regions):
            clipped = Bbox.intersection(region, self.axes.figure.bbox)
            if clipped is not None:
                self.canvas.blit(clipped)
        self._remember_scene(renderer)
        self._remember_labels(renderer)
