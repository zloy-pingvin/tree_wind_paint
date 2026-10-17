# SPDX-License-Identifier: GPL-2.0-or-later
"""
Paint one channel on its own.

The channel is copied as grey into a temporary attribute and made active, so
every vertex paint tool (brushes, gradient, Set Color with face masking,
Adjust > Levels / Invert...) works on it as on a normal colour. Apply copies
the grey back into that channel only; the other channels never change.
"""

import bpy
import numpy as np
from bpy.props import EnumProperty, FloatProperty, IntProperty

from .colors import (BRANCHES_ATTR, CHANNEL_INDEX, ISO_CH_KEY, ISO_SRC_KEY, PREVIEW_ATTR, TEMP_ATTR,
                     ObjectMode, blend_values, drop_helper, isolated, paint_mask, preview,
                     read_corners, set_active, show_colors, wind_attribute, write_channels,
                     write_corners)
from .translations import iface_

CHANNEL_ITEMS = (
    ('R', "R", "Red: leaf flutter", 0),
    ('G', "G", "Green: time offset", 1),
    ('B', "B", "Blue: branch bend", 2),
    ('A', "A", "Alpha: ambient occlusion", 3),
)


def _mesh_poll(context):
    ob = context.active_object
    return ob is not None and ob.type == 'MESH'


def _drop_temp(me):
    src = me.get(ISO_SRC_KEY)
    tmp = me.color_attributes.get(TEMP_ATTR)
    if tmp is not None:
        me.color_attributes.remove(tmp)
    for key in (ISO_SRC_KEY, ISO_CH_KEY):
        if key in me:
            del me[key]
    if src and src in me.color_attributes:
        set_active(me, src)


class TREEWIND_OT_channel_edit(bpy.types.Operator):
    bl_idname = "tree_wind.channel_edit"
    bl_label = "Paint Channel"
    bl_description = ("Paint this channel alone as greyscale in Vertex Paint; "
                      "Apply writes it back without touching the other channels")
    bl_options = {'REGISTER', 'UNDO'}

    channel: EnumProperty(name="Channel", items=CHANNEL_ITEMS)

    @classmethod
    def poll(cls, context):
        return _mesh_poll(context)

    def execute(self, context):
        ob = context.active_object
        me = ob.data
        iso = isolated(me)
        if iso:
            if iso[1] == self.channel:
                return {'CANCELLED'}
            self.report({'ERROR'}, iface_("Apply or cancel the channel being painted first"))
            return {'CANCELLED'}
        with ObjectMode(ob):
            attr = wind_attribute(me, create=True)
            grey = read_corners(me, attr)[:, CHANNEL_INDEX[self.channel]]
            rgba = np.ones((len(grey), 4), np.float32)
            rgba[:, :3] = grey[:, None]
            drop_helper(me, TEMP_ATTR)
            drop_helper(me, PREVIEW_ATTR)
            tmp = me.color_attributes.new(TEMP_ATTR, 'BYTE_COLOR', 'CORNER')
            tmp.data.foreach_set("color_srgb", rgba.ravel())
            me[ISO_SRC_KEY] = attr.name
            me[ISO_CH_KEY] = self.channel
            set_active(me, TEMP_ATTR)
        if ob.mode != 'VERTEX_PAINT':
            bpy.ops.object.mode_set(mode='VERTEX_PAINT')
        show_colors(context)
        return {'FINISHED'}


class TREEWIND_OT_channel_apply(bpy.types.Operator):
    bl_idname = "tree_wind.channel_apply"
    bl_label = "Apply Channel"
    bl_description = "Write the painted grey back into its channel and remove the temporary attribute"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _mesh_poll(context) and isolated(context.active_object.data) is not None

    def execute(self, context):
        ob = context.active_object
        me = ob.data
        src_name, channel = isolated(me)
        with ObjectMode(ob):
            src = me.color_attributes.get(src_name)
            if src is None:
                _drop_temp(me)
                self.report({'ERROR'}, iface_("Attribute \"{:s}\" is gone").format(src_name))
                return {'CANCELLED'}
            grey = read_corners(me, me.color_attributes[TEMP_ATTR])[:, :3].mean(axis=1)
            write_channels(me, src, grey, [channel])
            _drop_temp(me)
        show_colors(context)
        preview(context)
        return {'FINISHED'}


class TREEWIND_OT_channel_cancel(bpy.types.Operator):
    bl_idname = "tree_wind.channel_cancel"
    bl_label = "Cancel"
    bl_description = "Drop the painted grey; the channel keeps its old values"
    bl_options = {'REGISTER', 'UNDO'}

    poll = TREEWIND_OT_channel_apply.poll

    def execute(self, context):
        ob = context.active_object
        with ObjectMode(ob):
            _drop_temp(ob.data)
        preview(context)
        return {'FINISHED'}


def _painting_poll(context):
    """A channel is being painted, in Vertex Paint."""
    ob = context.active_object
    return (ob is not None and ob.type == 'MESH' and ob.mode == 'VERTEX_PAINT'
            and isolated(ob.data) is not None)


class TREEWIND_OT_randomize_parts(bpy.types.Operator):
    bl_idname = "tree_wind.randomize_parts"
    bl_label = "Randomize Parts"
    bl_description = ("Give every loose part of the mesh its own random value between the brush "
                      "value and the second value (only the selected parts with selection masking)")
    bl_options = {'REGISTER', 'UNDO'}

    seed: IntProperty(name="Seed", default=0, min=0)

    @classmethod
    def poll(cls, context):
        return _painting_poll(context)

    def execute(self, context):
        from . import analysis
        from .props import brush_grey
        settings = context.scene.tree_wind
        v0 = brush_grey("color")
        v1 = brush_grey("secondary_color")
        ob = context.active_object
        me = ob.data
        with ObjectMode(ob):
            nl = len(me.loops)
            lv, mask = paint_mask(me, nl)
            nxt = np.arange(nl) + 1
            start = np.empty(len(me.polygons), np.int32)
            total = np.empty(len(me.polygons), np.int32)
            me.polygons.foreach_get("loop_start", start)
            me.polygons.foreach_get("loop_total", total)
            nxt[start + total - 1] = start
            lab = analysis.components(len(me.vertices), lv.astype(np.int64), lv[nxt].astype(np.int64))
            parts, part = np.unique(lab, return_inverse=True)
            rng = np.random.default_rng(self.seed)
            value = (v0 + (v1 - v0) * rng.random(len(parts)))[part.ravel()]
            tmp = me.color_attributes[TEMP_ATTR]
            rgba = read_corners(me, tmp).copy()
            new = np.clip(blend_values(rgba[:, :3].mean(axis=1), value[lv], settings.gradient_blend), 0.0, 1.0)
            rgba[mask, :3] = new[mask, None]
            write_corners(me, tmp, rgba, mask)
            count = len(np.unique(part.ravel()[lv[mask]]))
        self.report({'INFO'}, iface_("Random values on {:d} parts").format(count))
        return {'FINISHED'}


class TREEWIND_OT_levels(bpy.types.Operator):
    """Photoshop-style levels, as in Vertex Color Master: values between the
    input black and white points are stretched to 0..1, bent by gamma and
    put into the output range."""
    bl_idname = "tree_wind.levels"
    bl_label = "Levels"
    bl_description = ("Levels of the channel being painted: input black and white points, gamma, "
                      "output range (only the selection with selection masking)")
    bl_options = {'REGISTER', 'UNDO'}

    in_black: FloatProperty(name="Input Black", default=0.0, min=0.0, max=1.0,
                            description="This value and lower become the output black")
    in_white: FloatProperty(name="Input White", default=1.0, min=0.0, max=1.0,
                            description="This value and higher become the output white")
    gamma: FloatProperty(name="Gamma", default=1.0, min=0.1, max=9.99, soft_min=0.5, soft_max=2.0,
                         precision=3, step=1,
                         description="Midtones: above 1 brighter, below 1 darker")
    out_black: FloatProperty(name="Output Black", default=0.0, min=0.0, max=1.0, precision=3,
                             description="Value the input black becomes")
    out_white: FloatProperty(name="Output White", default=1.0, min=0.0, max=1.0, precision=3,
                             description="Value the input white becomes")

    @classmethod
    def poll(cls, context):
        return _painting_poll(context)

    def invoke(self, context, event):
        # live: every slider change undoes the last run and runs again
        return context.window_manager.invoke_props_popup(self, event)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="Input")
        col.prop(self, "in_black")
        col.prop(self, "in_white")
        col.prop(self, "gamma")
        col.separator()
        col.label(text="Output")
        col.prop(self, "out_black")
        col.prop(self, "out_white")

    def execute(self, context):
        ob = context.active_object
        me = ob.data
        with ObjectMode(ob):
            lv, mask = paint_mask(me, len(me.loops))
            tmp = me.color_attributes[TEMP_ATTR]
            rgba = read_corners(me, tmp).copy()
            v = rgba[:, :3].mean(axis=1)
            t = np.clip((v - self.in_black) / max(self.in_white - self.in_black, 1e-6), 0.0, 1.0)
            t = t ** (1.0 / self.gamma)
            new = np.clip(self.out_black + t * (self.out_white - self.out_black), 0.0, 1.0)
            rgba[mask, :3] = new[mask, None]
            write_corners(me, tmp, rgba, mask)
        return {'FINISHED'}


class TREEWIND_OT_swap_values(bpy.types.Operator):
    bl_idname = "tree_wind.swap_values"
    bl_label = "Swap Values"
    bl_description = "Swap the brush value and the second value (X in Vertex Paint)"

    def execute(self, context):
        s = context.scene.tree_wind
        first = s.brush_value
        s.brush_value = s.brush_value_2
        s.brush_value_2 = first
        return {'FINISHED'}


class TREEWIND_OT_show_wind(bpy.types.Operator):
    bl_idname = "tree_wind.show_wind"
    bl_label = "Show Wind Colors"
    bl_description = ("Show the wind colours themselves in the viewport and remove the helper "
                      "attributes of Show Branches and of the channel view, ready for export")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _mesh_poll(context) and isolated(context.active_object.data) is None

    def execute(self, context):
        ob = context.active_object
        me = ob.data
        attr = wind_attribute(me)
        if attr is None:
            self.report({'WARNING'}, iface_("No wind colours yet: run Auto Paint"))
            return {'CANCELLED'}
        name = attr.name
        with ObjectMode(ob):
            drop_helper(me, BRANCHES_ATTR)
            # all channels, whatever the toggles show: helpers must not reach an export
            drop_helper(me, PREVIEW_ATTR)
            set_active(me, name)
        show_colors(context)
        return {'FINISHED'}


CLASSES = (
    TREEWIND_OT_channel_edit,
    TREEWIND_OT_channel_apply,
    TREEWIND_OT_channel_cancel,
    TREEWIND_OT_show_wind,
    TREEWIND_OT_swap_values,
    TREEWIND_OT_randomize_parts,
    TREEWIND_OT_levels,
)
