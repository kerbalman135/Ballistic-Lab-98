"""Small vector icons using the existing palette and Matplotlib.

Enemy silhouettes keep a readable screen size. A separate aiming circle marks
the centre; the larger contact region is independent of the decorative icon.
The cannon barrel uses world coordinates and ends at the actual barrel tip.
"""

import numpy as np
from matplotlib.offsetbox import AnnotationBbox, DrawingArea
from matplotlib.patches import PathPatch, Polygon, Rectangle
from matplotlib.path import Path
from matplotlib.transforms import Affine2D

from .physics import calculate_velocity_components
from . import game_data as data


class _CannonPatch(PathPatch):
    """Notify cached redraws when Matplotlib replaces a patch's geometry."""

    def set_path(self, path):
        super().set_path(path)
        self.stale = True


class CannonIcon:
    def __init__(self, axes, colours):
        self.axes = axes
        self._mount_state = None
        # Compound paths batch the two legs, feet and central pedestal.
        self.mount = self._patch(4)
        self.post_shadow = self._patch(4.05, outlined=False)
        self.post_bands = self._patch(4.1, filled=False, linewidth=0.6)
        self.beam = self._patch(4.2)
        self.barrel = self._patch(5)
        self.barrel_highlight = self._patch(5.1, outlined=False)
        self.muzzle_band = self._patch(5.2)
        self.chassis = self._patch(6)
        self.roof_highlight = self._patch(6.1, filled=False, linewidth=1.4)
        self.recolour(colours)

    def _patch(self, zorder, filled=True, outlined=True, linewidth=0.8):
        patch = _CannonPatch(Path(np.zeros((1, 2))), fill=filled, linewidth=linewidth,
                          antialiased=False, joinstyle="miter", capstyle="butt", zorder=zorder)
        patch._cannon_outlined = outlined
        self.axes.add_patch(patch)
        return patch

    @staticmethod
    def _compound(parts, closed=True):
        paths = []
        for points in parts:
            points = np.asarray(points)
            if closed:
                # Matching winding keeps overlapping filled pieces solid.
                area = np.sum(points[:, 0] * np.roll(points[:, 1], -1)
                              - points[:, 1] * np.roll(points[:, 0], -1))
                if area < 0:
                    points = points[::-1]
            paths.append(Path(np.vstack((points, points[:1])), closed=True)
                         if closed else Path(points))
        return Path.make_compound_path(*paths)

    def recolour(self, colours):
        self.colours = colours
        outline = colours.get("cannon_outline", colours["text"])
        for patch, role in ((self.mount, "panel"), (self.post_shadow, "disabled_text"),
                            (self.beam, "terrain"), (self.barrel, "disabled_text"),
                            (self.barrel_highlight, "panel"), (self.muzzle_band, "panel"),
                            (self.chassis, "terrain")):
            patch.set_facecolor(colours[role])
            patch.set_edgecolor(outline if patch._cannon_outlined else "none")
        self.post_bands.set_edgecolor(outline)
        self.roof_highlight.set_edgecolor(colours.get(
            "cannon_highlight", colours.get("cannon_outline", colours["terrain_edge"])))

    def update(self, position, angle, direction):
        x, y = position
        scale = data.CANNON_ICON_SCALE
        turret_scale = scale * data.CANNON_TURRET_SCALE

        def mounted(points):
            return np.asarray(points) * (direction, 1) + (x, y)

        mount_state = (position, direction, turret_scale, data.CANNON_PIVOT_HEIGHT)
        if mount_state != self._mount_state:
            centre = -.956 * turret_scale
            post_left, post_right = centre - .29*turret_scale, centre + .29*turret_scale
            post_top, post_bottom = -.4*turret_scale, -.535*turret_scale
            pedestal = ((post_left, post_bottom), (post_right, post_bottom),
                        (post_right, post_top), (post_left, post_top))
            parts = [mounted(pedestal)]
            foot_top = -data.CANNON_PIVOT_HEIGHT + .12*turret_scale
            leg_top = -.645*turret_scale
            drop = leg_top - foot_top
            half_width = .05*turret_scale / np.sqrt(2)
            for anchor, outward in ((-1.896, -1), (-.016, 1)):
                top = np.array((anchor * turret_scale, leg_top))
                bottom = top + (outward * drop, -drop)
                offset = np.array((half_width, outward * half_width))
                parts.append(mounted((top-offset, top+offset,
                                      bottom+(2*half_width, 0), bottom-(2*half_width, 0))))
                left, right = bottom[0]-.30*turret_scale, bottom[0]+.30*turret_scale
                parts.append(mounted(((left, -data.CANNON_PIVOT_HEIGHT),
                                      (right, -data.CANNON_PIVOT_HEIGHT),
                                      (right, foot_top), (left, foot_top))))
            self.mount.set_path(self._compound(parts))
            self.post_shadow.set_path(self._compound([mounted(
                ((post_left, post_bottom), (post_left+.12*turret_scale, post_bottom),
                 (post_left+.12*turret_scale, post_top), (post_left, post_top)))]))
            self.post_bands.set_path(self._compound([
                mounted(((post_left, post_bottom + fraction*(post_top-post_bottom)),
                         (post_right, post_bottom + fraction*(post_top-post_bottom))))
                for fraction in (.2, .8)], closed=False))
            beam_left, beam_right = centre-turret_scale, centre+turret_scale
            self.beam.set_path(self._compound([mounted(
                ((beam_left, -.655*turret_scale), (beam_right, -.655*turret_scale),
                 (beam_right-.07*turret_scale, -.535*turret_scale),
                 (beam_left+.07*turret_scale, -.535*turret_scale)))]))
            hull = np.array(((-2.072, .35), (-1.752, .53), (-.53, .53),
                             (.16, -.16), (.16, -.40), (-2.072, -.40))) * turret_scale
            self.chassis.set_path(self._compound([mounted(hull)]))
            self.roof_highlight.set_path(self._compound([mounted(hull[:3])], closed=False))
            self._mount_state = mount_state

        ux, uy = calculate_velocity_components(1, angle, direction)
        def world(points):
            return [(x + ux * along - uy * across, y + uy * along + ux * across)
                    for along, across in points]

        length = data.BARREL_LENGTH
        half_barrel = .13 * scale
        # Geometry starts at the pivot; the hull also covers the inboard root.
        self.barrel.set_path(self._compound([world(
            ((0, -half_barrel), (length, -half_barrel),
             (length, half_barrel), (0, half_barrel)))]))
        self.barrel_highlight.set_path(self._compound([world(
            ((0, .06*half_barrel), (length, .06*half_barrel),
             (length, .65*half_barrel), (0, .65*half_barrel)))]))
        self.muzzle_band.set_path(self._compound([world(
            ((length-.18*scale, -1.28*half_barrel), (length, -1.28*half_barrel),
             (length, 1.28*half_barrel), (length-.18*scale, 1.28*half_barrel)))]))


def enemy_icon(axes, target, colours, scale=1):
    """A tank or flying saucer badge centred on the hidden collision region."""
    ground = target.kind == "ground"
    ink = colours["enemy_ground" if ground else "enemy_air"]
    outline = colours.get("projectile_edge", colours.get("plot_background", colours["background"]))
    canvas = DrawingArea(22 * scale, 18 * scale, clip=True)

    def polygon(points, fill=ink, edge=outline):
        patch = Polygon(points, closed=True, facecolor=fill, edgecolor=edge,
                        linewidth=0.6, antialiased=False)
        canvas.add_artist(patch)

    if ground:
        # Faceted red armour and bright details echo the saucer's cockpit/lights.
        polygon(((2, 1), (19, 1), (21, 3), (19, 5), (2, 5), (0, 3)),
                colours["disabled_text"])
        polygon(((3, 2), (18, 2), (19, 3), (18, 4), (3, 4), (2, 3)), outline)
        for left in (4, 9, 14):
            canvas.add_artist(Rectangle((left, 2), 3, 2,
                                        facecolor=colours["panel"], edgecolor=outline,
                                        linewidth=0.4, antialiased=False))
        polygon(((2, 5), (4, 9), (16, 9), (21, 6), (19, 5)))
        polygon(((4, 8), (16, 8), (17.5, 7), (3.5, 7)),
                colours["input_background"], "none")
        polygon(((7, 9), (8, 13), (13, 13), (16, 9)))
        canvas.add_artist(Rectangle((14, 10), 7, 2, facecolor=ink, edgecolor=outline,
                                    linewidth=0.4, antialiased=False))
        canvas.add_artist(Rectangle((20, 10), 1, 2, facecolor=outline, edgecolor="none",
                                    linewidth=0, antialiased=False))
        canvas.add_artist(Rectangle((9, 10), 3, 1.5,
                                    facecolor=colours["input_background"], edgecolor=outline,
                                    linewidth=0.4, antialiased=False))
        canvas.add_artist(Rectangle((17, 5.5), 2, 1.5,
                                    facecolor=colours["projectile"], edgecolor=outline,
                                    linewidth=0.4, antialiased=False))
        alignment = (0.5, 0.25)
    else:
        # Faceted cockpit, wide saucer rim, lower hull and three landing lights.
        polygon(((6, 10), (7, 13), (9, 15), (13, 15), (15, 13), (16, 10)),
                colours["input_background"], outline)
        polygon(((1, 8), (4, 11), (18, 11), (21, 8), (18, 5), (4, 5)), ink, outline)
        polygon(((4, 7), (18, 7), (15, 4), (7, 4)), colours["panel"], outline)
        for left in (5, 10, 15):
            canvas.add_artist(Rectangle((left, 8), 2, 1.5,
                                       facecolor=colours["projectile"], edgecolor="none",
                                       linewidth=0, antialiased=False))
        alignment = (0.5, 0.5)
    for artist in canvas.get_children():
        artist.set_transform(Affine2D().scale(scale) + canvas.get_transform())
        artist.set_linewidth(artist.get_linewidth() * scale)
    badge = AnnotationBbox(canvas, target.position, frameon=False, pad=0,
                           box_alignment=alignment, annotation_clip=True, zorder=4)
    axes.add_artist(badge)
    return badge
