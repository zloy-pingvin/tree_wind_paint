# SPDX-License-Identifier: GPL-3.0-or-later
"""
Painting through UVs.

Leaf cards (and often twigs) of a tree are copies of a few pieces from one
atlas, so every copy has its corners at the same UV points. Copy to Same UV
spreads the colour of the selected (painted) faces to all faces of the same
material at those UV points; UV Gradient is dragged in the UV editor across
one card and lands on every copy of it.

While a channel is being painted on its own (ops_channel), both tools work
on that grey copy, so the result shows up right away and Apply keeps it.
"""

import math

import bpy
import numpy as np
from bpy.props import EnumProperty, FloatProperty, FloatVectorProperty

from . import analysis
from .colors import (CHANNEL_INDEX, ICON, TEMP_ATTR, ObjectMode, blend_values, isolated,
                     paint_mask, preview, read_corners, write_channels, write_corners,
                     wind_attribute)
from .ops_gradient import _circle, add_handler, draw_guides, remove_handler, window_region
from .ops_autopaint import slot_roles
from .props import GRADIENT_SCOPE_ITEMS, brush_grey
from .translations import iface_


def _target(me, channels):
    """(attribute, channels to write); the grey copy while a channel is isolated."""
    iso = isolated(me)
    if iso:
        return me.color_attributes[TEMP_ATTR], ['R', 'G', 'B']
    return wind_attribute(me, create=True), channels


def _hidden(me):
    hide = np.zeros(len(me.polygons), bool)
    me.polygons.foreach_get("hide", hide)
    return hide


class TREEWIND_OT_uv_copy(bpy.types.Operator):
    bl_idname = "tree_wind.uv_copy"
    bl_label = "Copy to Same UV"
    bl_description = ("Copy the colour of the selected faces to every face of the same material "
                      "whose corners sit at the same UV points, i.e. to all copies of the same "
                      "piece (a leaf card, a twig...). Select the painted copy in Edit Mode or "
                      "with face selection masking")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'MESH'

    def execute(self, context):
        ob = context.active_object
        me = ob.data
        mode = ob.mode
        channels = context.scene.tree_wind.uv_channels()
        if not channels and not isolated(me):
            self.report({'WARNING'}, iface_("No channels selected"))
            return {'CANCELLED'}
        if mode not in {'EDIT', 'VERTEX_PAINT'} or (mode == 'VERTEX_PAINT' and not me.use_paint_mask):
            self.report({'ERROR'}, iface_("Select the painted leaf: Edit Mode, or Vertex Paint with "
                                   "face selection masking"))
            return {'CANCELLED'}
        with ObjectMode(ob):
            uv = analysis.read_uv(me)
            if uv is None:
                self.report({'ERROR'}, iface_("The mesh has no UV map"))
                return {'CANCELLED'}
            md = analysis.MeshData(me)
            visible = ~_hidden(me)
            sel = md.poly_select & visible
            if not sel.any():
                self.report({'ERROR'}, iface_("Nothing selected: select the painted leaf"))
                return {'CANCELLED'}
            attr, channels = _target(me, channels)
            rgba = read_corners(me, attr)
            # a copy is the same UV point in the same material: two cards of
            # different materials may share UVs and must not mix
            pairs = np.stack([md.poly_mat[md.loop_poly], analysis.uv_keys(uv)], axis=1)
            _u, group = np.unique(pairs, axis=0, return_inverse=True)
            group = group.ravel()
            src = sel[md.loop_poly]
            ngroup = len(_u)
            cnt = np.bincount(group[src], minlength=ngroup)
            mean = np.stack([np.bincount(group[src], weights=rgba[src, k], minlength=ngroup)
                             / np.maximum(cnt, 1) for k in range(3)], axis=1)
            # only shown faces
            hit = ~src & visible[md.loop_poly] & (cnt[group] > 0)
            if not hit.any():
                self.report({'WARNING'}, iface_("No other faces share these UV points"))
                return {'CANCELLED'}
            values = np.zeros((md.nl, 3))
            values[hit] = mean[group[hit]]
            write_channels(me, attr, values, channels, hit)
            faces = np.unique(md.loop_poly[hit])
        self.report({'INFO'}, iface_("Copied {:s} to {:d} faces").format("".join(channels), len(faces)))
        preview(context)
        return {'FINISHED'}


def _faces_under(uv, md, faces, point):
    """Faces (of the given ones) whose UV polygon contains point.

    Even-odd rule over the polygon's edges, so concave faces work too (a fan
    of triangles from one corner covers space outside a concave outline).
    """
    loops = np.where(np.isin(md.loop_poly, faces))[0]
    a = uv[loops]
    b = uv[md.loop_next[loops]]
    px, py = float(point[0]), float(point[1])
    # edges that straddle the horizontal line through the point...
    straddle = (a[:, 1] > py) != (b[:, 1] > py)
    dy = np.where(straddle, b[:, 1] - a[:, 1], 1.0)
    # ...and cross it to the right of the point
    x = a[:, 0] + (py - a[:, 1]) * (b[:, 0] - a[:, 0]) / dy
    crossing = straddle & (x > px)
    count = np.bincount(md.loop_poly[loops][crossing], minlength=md.npoly)
    hit = np.zeros(md.npoly, bool)
    hit[faces] = (count[faces] % 2) == 1
    return np.where(hit)[0]


# The UV gradient that is waiting for or doing a drag: the panel shows its
# button pressed. A new start makes the running one stop (by token).
UV_RUNNING = {"mode": None, "token": 0}


def stop_all():
    """Forget the running UV gradient (on unregister; its drawing goes with
    ops_gradient.stop_all)."""
    UV_RUNNING["mode"] = None
    UV_RUNNING["token"] += 1


def apply_uv_gradient(context, ob, start, end, mode, channel, power, v_from, v_to, blend, scope):
    """Returns (faces painted, error message or None)."""
    me = ob.data
    ob_mode = ob.mode
    sync = context.scene.tool_settings.use_uv_select_sync
    with ObjectMode(ob):
        uv = analysis.read_uv(me)
        if uv is None:
            return 0, "The mesh has no UV map"
        md = analysis.MeshData(me)
        visible = ~_hidden(me)
        roles, names = slot_roles(ob)
        fr = analysis.face_roles(md, analysis.resolve_roles(md, roles, names))
        if ob_mode == 'EDIT' and not sync:
            shown = md.poly_select & visible
        elif ob_mode == 'EDIT':
            shown = visible
        else:
            shown = visible & (fr == analysis.LEAF)
        faces = np.where(shown)[0]
        if not len(faces):
            return 0, "No faces in the UV editor: select leaves in Edit Mode"
        if scope == 'CARD':
            under = _faces_under(uv, md, faces, start)
            if not len(under):
                loops = np.where(shown[md.loop_poly])[0]
                near = loops[np.argmin(((uv[loops] - np.asarray(start)) ** 2).sum(1))]
                under = np.array([md.loop_poly[near]])
            # Bark and leaves share UV space: where they overlap the leaf
            # wins, and the card only grows within that face's material.
            leafy = under[fr[under] == analysis.LEAF]
            pick = leafy[0] if len(leafy) else under[0]
            shown = shown & (md.poly_mat == md.poly_mat[pick])
            under = under[md.poly_mat[under] == md.poly_mat[pick]]
            # UV islands where copies of a card merge: faces are linked
            # through the UV points their corners share.
            loops = np.where(shown[md.loop_poly])[0]
            _k, kinv = np.unique(analysis.uv_keys(uv[loops]), return_inverse=True)
            lab = analysis.components(md.npoly + len(_k), md.loop_poly[loops], md.npoly + kinv.ravel())
            labels = np.unique(lab[under])
            chosen = shown & np.isin(lab[:md.npoly], labels)
        else:
            chosen = shown
        mask = chosen[md.loop_poly]
        if ob_mode == 'VERTEX_PAINT':
            # as a brush there: selection masking and hidden faces
            mask &= paint_mask(me, md.nl)[1]
        s = np.asarray(start, np.float64)
        e = np.asarray(end, np.float64)
        dvec = e - s
        if mode == 'RADIAL':
            # out from the start point; outside the circle nothing changes
            radius = max(float(np.linalg.norm(dvec)), 1e-12)
            dist = np.linalg.norm(uv - s, axis=1)
            mask &= dist <= radius
            t = np.clip(dist / radius, 0.0, 1.0) ** power
        else:
            t = np.clip(((uv - s) @ dvec) / max(float(dvec @ dvec), 1e-12), 0.0, 1.0) ** power
        values = v_from + (v_to - v_from) * t
        # While a channel is being painted everything goes into its grey copy,
        # whatever channel the UV editor shows: Cancel must drop it all.
        if isolated(me):
            attr = me.color_attributes[TEMP_ATTR]
            rgba = read_corners(me, attr).copy()
            new = np.clip(blend_values(rgba[:, :3].mean(axis=1), values, blend), 0.0, 1.0)
            rgba[mask, :3] = new[mask, None]
            write_corners(me, attr, rgba, mask)
        else:
            attr = wind_attribute(me, create=True)
            old = read_corners(me, attr)[:, CHANNEL_INDEX[channel]]
            write_channels(me, attr, np.clip(blend_values(old, values, blend), 0.0, 1.0), [channel], mask)
        return len(np.unique(md.loop_poly[mask])), None


class TREEWIND_OT_uv_gradient(bpy.types.Operator):
    bl_idname = "tree_wind.uv_gradient"
    bl_label = "UV Gradient"
    bl_description = ("Drag across a card in the UV editor: the channel goes from the brush value "
                      "at the start to the second value at the end, on every copy of that card")
    bl_options = {'REGISTER', 'UNDO'}

    start: FloatVectorProperty(name="Start", size=2, subtype='XYZ')
    end: FloatVectorProperty(name="End", size=2, default=(0.0, 1.0), subtype='XYZ')
    mode: EnumProperty(
        name="Mode",
        items=(('LINEAR', "Linear", "Along the line", 0),
               ('RADIAL', "Radial", "Out from the start point, inside a circle", 1)))
    channel: EnumProperty(
        name="Channel", default='R',
        items=(('R', "R", "Leaf flutter", ICON['R'], 0),
               ('G', "G", "Time offset", ICON['G'], 1),
               ('B', "B", "Branch bend", ICON['B'], 2)))
    power: FloatProperty(name="Curve", default=1.0, min=0.2, max=16.0)
    value_from: FloatProperty(name="Start Value", default=0.0, min=0.0, max=1.0, subtype='FACTOR')
    value_to: FloatProperty(name="End Value", default=1.0, min=0.0, max=1.0, subtype='FACTOR')
    blend: EnumProperty(
        name="Blend",
        items=(('REPLACE', "Replace", "", 0), ('ADD', "Add", "", 1), ('MULTIPLY', "Multiply", "", 2)))
    scope: EnumProperty(name="Scope", items=GRADIENT_SCOPE_ITEMS, default='CARD')

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'MESH'

    def invoke(self, context, event):
        area = context.area
        region = window_region(area) if area and area.type == 'IMAGE_EDITOR' else None
        if region is None:
            self.report({'ERROR'}, iface_("Run it from the UV editor"))
            return {'CANCELLED'}
        self._take_settings(context)
        self._area = area
        self._region = region
        self._a = self._b = None
        UV_RUNNING["token"] += 1
        UV_RUNNING["mode"] = self.mode
        self._token = UV_RUNNING["token"]
        add_handler(bpy.types.SpaceImageEditor, self._token, self._draw)
        context.window_manager.modal_handler_add(self)
        self._status(context)
        area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _take_settings(self, context):
        # again at the start of the drag: X / Ctrl+X still work while the tool waits
        s = context.scene.tree_wind
        self.channel = s.gradient_channel
        self.power = s.gradient_power
        self.value_from = brush_grey("color")
        self.value_to = brush_grey("secondary_color")
        self.blend = s.gradient_blend
        self.scope = s.gradient_scope

    def _status(self, context):
        iso = isolated(context.active_object.data)
        context.workspace.status_text_set(
            iface_("Drag across a card: {:s} goes {:.2f} → {:.2f}. Esc / right click cancels").format(
                iso[1] if iso else self.channel, self.value_from, self.value_to))

    def _draw(self):
        # the handler runs for every image editor: draw only in the one dragged in
        if self._a is None or bpy.context.area != self._area:
            return
        c0 = (self.value_from,) * 3 + (1.0,)
        c1 = (self.value_to,) * 3 + (1.0,)
        segs = [([self._a, self._b], [c0, c1])]
        if self.mode == 'RADIAL':
            r = math.hypot(self._b[0] - self._a[0], self._b[1] - self._a[1])
            strips = [(_circle(self._a, 4.0), c0), (_circle(self._a, r), c1)]
        else:
            strips = [(_circle(self._a, 4.0), c0), (_circle(self._b, 4.0), c1)]
        draw_guides(segs, strips)

    def _cleanup(self, context):
        remove_handler(bpy.types.SpaceImageEditor, self._token)
        if UV_RUNNING["token"] == self._token:
            UV_RUNNING["mode"] = None
            context.workspace.status_text_set(None)
        self._area.tag_redraw()

    def modal(self, context, event):
        region = self._region
        x = event.mouse_x - region.x
        y = event.mouse_y - region.y
        dragging = self._a is not None
        if UV_RUNNING["token"] != self._token or not self.poll(context):
            self._cleanup(context)
            return {'CANCELLED'}
        inside = 0 <= x < region.width and 0 <= y < region.height
        if event.value == 'PRESS' and (event.type == 'ESC' or (event.type == 'RIGHTMOUSE' and inside)):
            self._cleanup(context)
            return {'CANCELLED'}
        if not dragging:
            # waiting: everything but a press in the editor goes on to Blender (keys, panel...)
            if event.type == 'LEFTMOUSE' and event.value == 'PRESS' and inside:
                self._take_settings(context)
                self._status(context)
                self._a = self._b = (x, y)
                self._area.tag_redraw()
                return {'RUNNING_MODAL'}
            return {'PASS_THROUGH'}
        if event.type == 'MOUSEMOVE':
            self._b = (x, y)
        elif event.type == 'LEFTMOUSE' and event.value == 'RELEASE':
            a, b = self._a, self._b
            self._cleanup(context)
            if abs(a[0] - b[0]) + abs(a[1] - b[1]) < 4:
                self.report({'WARNING'}, iface_("Drag a line, not a click"))
                return {'CANCELLED'}
            self.start = region.view2d.region_to_view(*a)
            self.end = region.view2d.region_to_view(*b)
            return self.execute(context)
        elif event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN',
                            'TRACKPADZOOM', 'NDOF_MOTION'}:
            return {'PASS_THROUGH'}
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def execute(self, context):
        count, error = apply_uv_gradient(
            context, context.active_object, tuple(self.start), tuple(self.end), self.mode,
            self.channel, self.power, self.value_from, self.value_to, self.blend, self.scope)
        if error:
            self.report({'ERROR'}, iface_(error))
            return {'CANCELLED'}
        self.report({'INFO'}, iface_("Gradient on {:d} faces").format(count))
        preview(context)
        return {'FINISHED'}


class TREEWIND_OT_uv_fill(bpy.types.Operator):
    bl_idname = "tree_wind.uv_fill"
    bl_label = "Fill"
    bl_description = ("Fill the faces shown in the UV editor with the brush value, in the picked "
                      "channel and blend (Ctrl+X)")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'MESH'

    def execute(self, context):
        s = context.scene.tree_wind
        value = brush_grey("color")
        count, error = apply_uv_gradient(
            context, context.active_object, (0.0, 0.0), (1.0, 0.0), 'LINEAR', s.gradient_channel,
            1.0, value, value, s.gradient_blend, 'ALL')
        if error:
            self.report({'ERROR'}, iface_(error))
            return {'CANCELLED'}
        self.report({'INFO'}, iface_("Filled {:d} faces").format(count))
        preview(context)
        return {'FINISHED'}


CLASSES = (TREEWIND_OT_uv_copy, TREEWIND_OT_uv_gradient, TREEWIND_OT_uv_fill)
