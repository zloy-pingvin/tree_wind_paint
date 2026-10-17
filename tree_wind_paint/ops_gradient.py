# SPDX-License-Identifier: GPL-2.0-or-later
"""
Gradient tools for painting a channel by hand (see ops_channel).

The value goes from the brush value at the start of the drag to the second
brush value at its end, on the grey copy of the channel being painted.

- Linear: the ends of the line stick to the surface under the cursor, so a
  gradient can run along a branch even when it goes into depth. Only the
  inside of a cylinder around the line is painted; the mouse wheel sets its
  radius while dragging.
- Radial, circle: everything inside a circle on the screen, as seen.
- Radial, sphere: everything within a 3D distance of the point on the
  surface where the drag starts.

Outside the cylinder, circle or sphere nothing changes. Blend modes:
replace, add, multiply. Vertex paint selection masking is respected.
"""

import math

import bpy
import gpu
import numpy as np
from bpy.props import EnumProperty
from bpy_extras import view3d_utils
from gpu_extras.batch import batch_for_shader
from mathutils import Vector, geometry
from mathutils.bvhtree import BVHTree

from .colors import (TEMP_ATTR, ObjectMode, blend_values, isolated, paint_mask, read_corners,
                     write_corners)
from .props import brush_grey
from .translations import iface_

CIRCLE_SEGMENTS = 48
WHEEL_STEP = 1.15

# The gradient tool that is waiting for or doing a drag: the panel shows its
# button pressed. A new start makes the running one stop (by token).
RUNNING = {"mode": None, "token": 0}


def window_region(area):
    for region in area.regions:
        if region.type == 'WINDOW':
            return region
    return None


def draw_guides(segs, strips):
    """Draw drag guides in their gradient colours over a dark outline.

    segs: [(positions, colours)] drawn as LINES; strips: [(positions, colour)]
    drawn as LINE_STRIP. Grey on a grey viewport needs the outline.
    """
    shader = gpu.shader.from_builtin('SMOOTH_COLOR')
    gpu.state.blend_set('ALPHA')
    dark = (0.0, 0.0, 0.0, 0.7)
    for width, outline in ((4.0, True), (2.0, False)):
        try:
            gpu.state.line_width_set(width)
        except Exception:
            pass
        for pos, cols in segs:
            cols = [dark] * len(pos) if outline else cols
            batch_for_shader(shader, 'LINES', {"pos": pos, "color": cols}).draw(shader)
        for pos, col in strips:
            col = dark if outline else col
            batch_for_shader(shader, 'LINE_STRIP', {"pos": pos, "color": [col] * len(pos)}).draw(shader)
    try:
        gpu.state.line_width_set(1.0)
    except Exception:
        pass
    gpu.state.blend_set('NONE')


def _circle(center, radius):
    cx, cy = center
    return [(cx + radius * math.cos(2 * math.pi * i / CIRCLE_SEGMENTS),
             cy + radius * math.sin(2 * math.pi * i / CIRCLE_SEGMENTS))
            for i in range(CIRCLE_SEGMENTS + 1)]


class TREEWIND_OT_gradient(bpy.types.Operator):
    bl_idname = "tree_wind.gradient"
    bl_label = "Gradient"
    bl_description = ("Drag in the viewport: the channel goes from the brush value at the start "
                      "to the second value at the end")
    # no REGISTER: the drag cannot be redone from a panel
    bl_options = {'UNDO'}

    mode: EnumProperty(
        name="Mode",
        items=(('LINEAR', "Linear", "Along a line, inside a cylinder around it", 0),
               ('RADIAL', "Radial", "Out from a point, inside a circle or a sphere", 1)))

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'MESH' and isolated(ob.data) is not None

    # --- setup ----------------------------------------------------------------

    def invoke(self, context, event):
        area = context.area
        region = window_region(area) if area and area.type == 'VIEW_3D' else None
        if region is None or region.data is None:
            self.report({'ERROR'}, iface_("Run it from the 3D viewport"))
            return {'CANCELLED'}
        ob = context.active_object
        me = ob.data
        nv = len(me.vertices)
        co = np.empty(nv * 3, np.float32)
        me.vertices.foreach_get("co", co)
        co = co.reshape(nv, 3).astype(np.float64)
        mw = np.array(ob.matrix_world)
        self._co = co @ mw[:3, :3].T + mw[:3, 3]
        me.calc_loop_triangles()
        tris = np.empty(len(me.loop_triangles) * 3, np.int32)
        me.loop_triangles.foreach_get("vertices", tris)
        self._bvh = BVHTree.FromPolygons(self._co.tolist(), tris.reshape(-1, 3).tolist(),
                                         all_triangles=True)
        # the drag paints this mesh as it is now; anything else when it ends cancels it
        self._ob_ptr = ob.as_pointer()
        self._ob_mode = ob.mode
        self._center = Vector(self._co.mean(axis=0))
        self._area = area
        self._region = region
        self._rv3d = region.data
        self._a = self._b = None
        self._a3 = self._b3 = None
        RUNNING["token"] += 1
        RUNNING["mode"] = self.mode
        self._token = RUNNING["token"]
        self._handle = bpy.types.SpaceView3D.draw_handler_add(self._draw, (), 'WINDOW', 'POST_PIXEL')
        context.window_manager.modal_handler_add(self)
        self._status(context)
        area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _same_mesh(self, context):
        """Still the object, mode and channel copy the tool started on.

        While the tool waits, clicks and keys reach Blender: the channel may be
        applied, the object changed, an undo step taken.
        """
        if not self.poll(context):
            return False
        ob = context.active_object
        return (ob.as_pointer() == self._ob_ptr and ob.mode == self._ob_mode
                and len(ob.data.vertices) == len(self._co)
                and TEMP_ATTR in ob.data.color_attributes)

    def _status(self, context):
        if self.mode == 'LINEAR':
            text = iface_("Drag a line · wheel while dragging: cylinder radius · Esc / right click: cancel")
        else:
            text = iface_("Drag from the centre · Esc / right click: cancel")
        context.workspace.status_text_set(text)

    def _cleanup(self, context):
        bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
        if RUNNING["token"] == self._token:
            RUNNING["mode"] = None
            context.workspace.status_text_set(None)
        self._area.tag_redraw()

    # --- 3D points under the cursor ---------------------------------------------

    def _ray(self, px):
        origin = view3d_utils.region_2d_to_origin_3d(self._region, self._rv3d, px)
        direction = view3d_utils.region_2d_to_vector_3d(self._region, self._rv3d, px)
        return origin, direction

    def _view_dir(self):
        return self._rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))

    def _on_plane(self, px, through):
        origin, direction = self._ray(px)
        hit = geometry.intersect_line_plane(origin, origin + direction, through, self._view_dir())
        return hit if hit is not None else through.copy()

    def _surface_or_plane(self, px, through):
        origin, direction = self._ray(px)
        loc, _n, _i, _d = self._bvh.ray_cast(origin, direction)
        return loc if loc is not None else self._on_plane(px, through)

    def _px_radius(self, at, radius):
        """Screen size in pixels of a world distance at a point."""
        right = self._rv3d.view_rotation @ Vector((1.0, 0.0, 0.0))
        p0 = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, at)
        p1 = view3d_utils.location_3d_to_region_2d(self._region, self._rv3d, at + right * radius)
        if p0 is None or p1 is None:
            return 0.0
        return (p1 - p0).length

    def _ends(self):
        """World start and end points of the drag."""
        settings = bpy.context.scene.tree_wind
        a3 = self._a3
        if self.mode == 'RADIAL' and settings.radial_shape == 'SPHERE':
            b3 = self._on_plane(self._b, a3)
        else:
            b3 = self._surface_or_plane(self._b, a3)
        return a3, b3

    # --- drawing ----------------------------------------------------------------

    def _draw(self):
        if self._a is None:
            return
        settings = bpy.context.scene.tree_wind
        v0 = brush_grey("color")
        v1 = brush_grey("secondary_color")
        c0 = (v0, v0, v0, 1.0)
        c1 = (v1, v1, v1, 1.0)
        segs = []    # (pos, colours) for 'LINES'
        strips = []  # (pos, colour) for 'LINE_STRIP'
        a = Vector(self._a)
        b = Vector(self._b)
        segs.append(([self._a, self._b], [c0, c1]))
        if self.mode == 'LINEAR':
            a3, b3 = self._ends()
            ra = self._px_radius(a3, settings.gradient_radius)
            rb = self._px_radius(b3, settings.gradient_radius)
            strips.append((_circle(self._a, ra), c0))
            strips.append((_circle(self._b, rb), c1))
            side = b - a
            if side.length > 1e-6:
                n = Vector((-side.y, side.x)).normalized()
                for sign in (1, -1):
                    segs.append(([tuple(a + n * ra * sign), tuple(b + n * rb * sign)], [c0, c1]))
        else:
            if settings.radial_shape == 'SPHERE':
                a3, b3 = self._ends()
                r = self._px_radius(a3, (b3 - a3).length)
            else:
                r = (b - a).length
            strips.append((_circle(self._a, 4.0), c0))
            strips.append((_circle(self._a, r), c1))
        draw_guides(segs, strips)

    # --- events -----------------------------------------------------------------

    def modal(self, context, event):
        region = self._region
        x = event.mouse_x - region.x
        y = event.mouse_y - region.y
        settings = context.scene.tree_wind
        dragging = self._a is not None
        if RUNNING["token"] != self._token or not self._same_mesh(context):
            self._cleanup(context)
            return {'CANCELLED'}
        inside = 0 <= x < region.width and 0 <= y < region.height
        if event.value == 'PRESS' and (event.type == 'ESC' or (event.type == 'RIGHTMOUSE' and inside)):
            self._cleanup(context)
            return {'CANCELLED'}
        if not dragging:
            # waiting: everything but a press in the viewport goes on to Blender (keys, panel...)
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and inside:
                self._a = self._b = (x, y)
                origin, direction = self._ray(self._a)
                loc, _n, _i, _d = self._bvh.ray_cast(origin, direction)
                self._a3 = loc if loc is not None else self._on_plane(self._a, self._center)
                self._area.tag_redraw()
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}
        if event.type == 'MOUSEMOVE':
            self._b = (x, y)
        elif event.type in {'WHEELUPMOUSE', 'WHEELDOWNMOUSE'} and self.mode == 'LINEAR':
            step = WHEEL_STEP if event.type == 'WHEELUPMOUSE' else 1.0 / WHEEL_STEP
            settings.gradient_radius = max(settings.gradient_radius * step, 1e-4)
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            a, b = self._a, self._b
            ends = self._ends()
            self._cleanup(context)
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) < 4:
                self.report({'WARNING'}, iface_("Drag a line, not a click"))
                return {'CANCELLED'}
            count = self._apply(context, a, b, ends)
            self.report({'INFO'}, iface_("Gradient on {:d} vertices").format(count))
            return {'FINISHED'}
        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN',
                            'TRACKPADZOOM', 'NDOF_MOTION'}:
            return {'PASS_THROUGH'}
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def execute(self, context):
        # Only interactive: it needs the drag in the viewport.
        return {'CANCELLED'}

    # --- painting ---------------------------------------------------------------

    def _weights(self, settings, a, b, ends):
        """(inside mask, gradient position 0..1) per vertex."""
        p = self._co
        a3, b3 = (np.array(v, np.float64) for v in ends)
        if self.mode == 'LINEAR':
            d = b3 - a3
            length2 = max(float(d @ d), 1e-12)
            t = ((p - a3) @ d) / length2
            radial = np.linalg.norm(p - (a3 + t[:, None] * d), axis=1)
            inside = (t >= 0.0) & (t <= 1.0) & (radial <= settings.gradient_radius)
            return inside, np.clip(t, 0.0, 1.0)
        if settings.radial_shape == 'SPHERE':
            radius = max(float(np.linalg.norm(b3 - a3)), 1e-9)
            dist = np.linalg.norm(p - a3, axis=1)
            return dist <= radius, np.clip(dist / radius, 0.0, 1.0)
        # circle on the screen
        m = np.array(self._rv3d.perspective_matrix)
        clip = np.c_[p, np.ones(len(p))] @ m.T
        w = clip[:, 3]
        front = w > 1e-9
        ndc = clip[:, :2] / np.where(front, w, 1.0)[:, None]
        px = (ndc * 0.5 + 0.5) * np.array([self._region.width, self._region.height])
        radius = max(math.hypot(b[0] - a[0], b[1] - a[1]), 1e-9)
        dist = np.linalg.norm(px - np.array(a, np.float64), axis=1)
        return front & (dist <= radius), np.clip(dist / radius, 0.0, 1.0)

    def _apply(self, context, a, b, ends):
        settings = context.scene.tree_wind
        v_start = brush_grey("color")
        v_end = brush_grey("secondary_color")
        inside, t = self._weights(settings, a, b, ends)
        value = v_start + (v_end - v_start) * t
        ob = context.active_object
        me = ob.data
        with ObjectMode(ob):
            lv, mask = paint_mask(me, len(me.loops))
            mask &= inside[lv]
            tmp = me.color_attributes[TEMP_ATTR]
            rgba = read_corners(me, tmp).copy()
            new = blend_values(rgba[:, :3].mean(axis=1), value[lv], settings.gradient_blend)
            rgba[mask, :3] = np.clip(new[mask], 0.0, 1.0)[:, None]
            write_corners(me, tmp, rgba, mask)
        return len(np.unique(lv[mask]))


CLASSES = (TREEWIND_OT_gradient,)
