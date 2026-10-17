# SPDX-License-Identifier: GPL-3.0-or-later
"""Sidebar panels: 3D View > Tree Wind and UV Editor > Tree Wind."""

import bpy

from . import analysis, ops_gradient, ops_uv
from .colors import ICON, PREVIEW_ATTR, isolated, wind_attribute
from .translations import iface_

ROLE_NAMES = {analysis.LEAF: "Leaves", analysis.BARK: "Bark", analysis.BARE: "Bare Branches"}


def _read_version():
    """Add-on version from blender_manifest.toml next to this file."""
    import os
    import tomllib
    try:
        with open(os.path.join(os.path.dirname(__file__), "blender_manifest.toml"), "rb") as f:
            return tomllib.load(f).get("version", "")
    except (OSError, ValueError):
        return ""


VERSION = _read_version()

DEFAULT_CATEGORY = "Tree Wind"


def _mesh(context):
    ob = context.active_object
    return ob if ob is not None and ob.type == 'MESH' else None


def channel_toggles(layout, s, names, chans="RGB"):
    """Channel toggle buttons, each with its channel's icon."""
    grid = layout.grid_flow(row_major=True, columns=len(chans), even_columns=True, align=True)
    for ch, name in zip(chans, names):
        grid.prop(s, name, toggle=True, icon=ICON[ch], text="")


def brush_values(layout, s):
    """The two brush values with the swap button between them."""
    row = layout.row(align=True)
    row.prop(s, "brush_value", text="")
    row.operator("tree_wind.swap_values", text="", icon='ARROW_LEFTRIGHT')
    row.prop(s, "brush_value_2", text="")


def channel_prop(layout, s, name, ch):
    """A setting marked with the icon of the channel it acts on."""
    row = layout.row()
    row.label(text="", icon=ICON[ch])
    row.prop(s, name)


class TREEWIND_PT_main(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tree Wind"
    bl_label = "Tree Wind"

    def draw_header(self, context):
        self.layout.label(text="", icon='OUTLINER_OB_FORCE_FIELD')

    def draw_header_preset(self, context):
        if VERSION:
            row = self.layout.row()
            row.active = False
            row.label(text="v" + VERSION, translate=False)

    def draw(self, context):
        layout = self.layout
        ob = _mesh(context)
        if ob is None:
            layout.label(text="Select a tree mesh", icon='INFO')
            return
        s = context.scene.tree_wind
        me = ob.data

        box = layout.box()
        box.label(text="Materials", icon='MATERIAL')
        if not ob.material_slots:
            box.label(text="No materials: roles are guessed by shape")
        for slot in ob.material_slots:
            mat = slot.material
            if mat is None:
                continue
            split = box.split(factor=0.5, align=True)
            split.label(text=mat.name, translate=False)
            split.prop(mat, "tree_wind_role", text="")
            if mat.tree_wind_role == 'AUTO':
                # what Auto picked, under the drop-down so it is not cut off
                guess = analysis.guess_role_by_name(mat.name)
                hint = box.split(factor=0.5)
                hint.label(text="")
                hint.active = False
                hint.label(text="→ " + (iface_(ROLE_NAMES[guess]) if guess is not None
                                        else iface_("by shape")), translate=False)

        attr = wind_attribute(me)
        col = layout.column()
        col.label(text=iface_("Attribute: ") + (attr.name if attr else iface_("WindColor (new)")),
                  icon='GROUP_VCOL', translate=False)
        channel_toggles(col, s, ("paint_r", "paint_g", "paint_b", "paint_a"), "RGBA")
        if ob.mode != 'OBJECT':
            # the preview writes mesh data, which only object mode allows safely
            note = col.row()
            note.alert = True
            note.label(text="Channel view: Object Mode only", icon='ERROR')
        elif PREVIEW_ATTR in me.color_attributes:
            note = col.row()
            note.active = False
            note.label(text="Preview: turn on RGB for export", icon='INFO')
        big = col.row()
        big.scale_y = 1.4
        big.operator("tree_wind.auto_paint", icon='BRUSH_DATA')
        row = col.row(align=True)
        row.operator("tree_wind.show_wind", icon='OUTLINER_OB_FORCE_FIELD')
        row.operator("tree_wind.show_structure", icon='OUTLINER_OB_EMPTY')


def _mesh_poll(cls, context):
    return _mesh(context) is not None


class TREEWIND_PT_settings(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tree Wind"
    bl_parent_id = "TREEWIND_PT_main"
    bl_label = "Settings"
    bl_options = {'DEFAULT_CLOSED'}

    poll = classmethod(_mesh_poll)

    def draw(self, context):
        s = context.scene.tree_wind
        col = self.layout.column(align=True)
        channel_prop(col, s, "flutter_power", 'R')
        channel_prop(col, s, "group_seed", 'G')
        channel_prop(col, s, "bend_power", 'B')
        channel_prop(col, s, "rigid_leafless", 'B')
        channel_prop(col, s, "ao_distance", 'A')
        channel_prop(col, s, "ground_height", 'A')
        channel_prop(col, s, "ao_on_leaves", 'A')


class TREEWIND_PT_structure(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tree Wind"
    bl_parent_id = "TREEWIND_PT_main"
    bl_label = "Tree Structure"
    bl_options = {'DEFAULT_CLOSED'}

    poll = classmethod(_mesh_poll)

    def draw(self, context):
        s = context.scene.tree_wind
        col = self.layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(s, "fork_ratio")
        col.prop(s, "fork_angle")
        col.prop(s, "min_branch")


class TREEWIND_PT_channels(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tree Wind"
    bl_label = "Manual Paint by Channel"

    poll = classmethod(_mesh_poll)

    def draw(self, context):
        layout = self.layout
        me = context.active_object.data
        iso = isolated(me)
        if iso:
            src, channel = iso
            layout.label(text=iface_("Painting {:s} of {:s}").format(channel, src),
                         icon=ICON.get(channel, 'BRUSH_DATA'), translate=False)
            s = context.scene.tree_wind
            brush_values(layout, s)
            layout.row().prop(s, "gradient_blend", expand=True)
            hint = layout.row()
            hint.active = False
            hint.label(text="X: swap · Ctrl+X: fill")
            box = layout.box()
            row = box.row(align=True)
            running = ops_gradient.RUNNING["mode"]
            row.operator("tree_wind.gradient", text="Linear", icon='IPO_LINEAR',
                         depress=running == 'LINEAR').mode = 'LINEAR'
            row.operator("tree_wind.gradient", text="Radial", icon='SPHERECURVE',
                         depress=running == 'RADIAL').mode = 'RADIAL'
            box.prop(s, "gradient_radius")
            box.row().prop(s, "radial_shape", expand=True)
            row = layout.row(align=True)
            row.operator("tree_wind.randomize_parts", icon='MOD_NOISE')
            row.operator("tree_wind.levels", icon='SEQ_HISTOGRAM')
            layout.separator(factor=1.0)
            row = layout.row(align=True)
            row.scale_y = 1.3
            row.operator("tree_wind.channel_apply", text="Apply", icon='CHECKMARK', depress=True)
            cancel = row.row(align=True)
            cancel.alert = True
            cancel.operator("tree_wind.channel_cancel", icon='X')
        else:
            grid = layout.grid_flow(row_major=True, columns=4, even_columns=True, align=True)
            grid.scale_y = 1.3
            for ch in ('R', 'G', 'B', 'A'):
                grid.operator("tree_wind.channel_edit", text="", icon=ICON[ch]).channel = ch


class TREEWIND_PT_uv(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tree Wind"
    bl_label = "Paint by UV"

    poll = classmethod(_mesh_poll)

    def draw(self, context):
        layout = self.layout
        s = context.scene.tree_wind
        me = context.active_object.data
        sub = layout.column()
        sub.enabled = isolated(me) is None
        channel_toggles(sub, s, ("uv_r", "uv_g", "uv_b"))
        layout.operator("tree_wind.uv_copy", icon='UV_SYNC_SELECT')


# short lines: the sidebar is narrow and labels do not wrap
UV_HELP = (
    "1. Paint one copy",
    "   (Manual Paint by Channel)",
    "2. Select it: Edit Mode, or",
    "   Vertex Paint with face mask",
    "3. Copy to Same UV: every",
    "   face at the same UV points",
    "   gets its values",
    "UV Gradient: UV Editor >",
    "   Sidebar > Tree Wind",
)


class TREEWIND_PT_uv_help(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Tree Wind"
    bl_parent_id = "TREEWIND_PT_uv"
    bl_label = "How to Use"
    bl_options = {'DEFAULT_CLOSED'}

    poll = classmethod(_mesh_poll)

    def draw_header(self, context):
        self.layout.label(text="", icon='QUESTION')

    def draw(self, context):
        col = self.layout.column(align=True)
        col.active = False
        for line in UV_HELP:
            col.label(text=line)


class TREEWIND_PT_uv_editor(bpy.types.Panel):
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Tree Wind"
    bl_label = "Tree Wind"

    @classmethod
    def poll(cls, context):
        return _mesh(context) is not None

    def draw_header(self, context):
        self.layout.label(text="", icon='OUTLINER_OB_FORCE_FIELD')

    def draw(self, context):
        layout = self.layout
        s = context.scene.tree_wind
        me = context.active_object.data
        iso = isolated(me)
        if iso:
            layout.label(text=iface_("Painting {:s} of {:s}").format(iso[1], iso[0]),
                         icon='BRUSH_DATA', translate=False)
        grid = layout.grid_flow(row_major=True, columns=3, even_columns=True, align=True)
        # while a channel is being painted the UV tools paint that channel
        grid.enabled = iso is None
        for ch in ('R', 'G', 'B'):
            grid.prop_enum(s, "gradient_channel", ch, text="", icon=ICON[ch])
        brush_values(layout, s)
        layout.row().prop(s, "gradient_blend", expand=True)
        hint = layout.row()
        hint.active = False
        hint.label(text="X: swap · Ctrl+X: fill")
        running = ops_uv.UV_RUNNING["mode"]
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator("tree_wind.uv_gradient", text="Linear", icon='IPO_LINEAR',
                     depress=running == 'LINEAR').mode = 'LINEAR'
        row.operator("tree_wind.uv_gradient", text="Radial", icon='SPHERECURVE',
                     depress=running == 'RADIAL').mode = 'RADIAL'
        col = layout.column()
        col.use_property_split = True
        col.use_property_decorate = False
        col.prop(s, "gradient_power")
        col.prop(s, "gradient_scope")
        layout.separator()
        sub = layout.column()
        sub.enabled = iso is None
        channel_toggles(sub, s, ("uv_r", "uv_g", "uv_b"))
        layout.operator("tree_wind.uv_copy", icon='UV_SYNC_SELECT')



UV_EDITOR_HELP = (
    "1. Edit Mode: select the leaves",
    "   (the UV editor shows them)",
    "2. Pick the channel and values",
    "3. Linear or Radial, then drag",
    "   across a card: stem to tip",
    "Card Under Cursor: that card",
    "   and every copy of it",
    "All Faces: all selected faces",
    "   at once (select a group)",
    "Esc / right click: cancel",
)


class TREEWIND_PT_uv_editor_help(bpy.types.Panel):
    bl_space_type = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Tree Wind"
    bl_parent_id = "TREEWIND_PT_uv_editor"
    bl_label = "How to Use"
    bl_options = {'DEFAULT_CLOSED'}

    poll = classmethod(_mesh_poll)

    def draw_header(self, context):
        self.layout.label(text="", icon='QUESTION')

    def draw(self, context):
        col = self.layout.column(align=True)
        col.active = False
        for line in UV_EDITOR_HELP:
            col.label(text=line)


def set_category(name):
    """Move every panel to the sidebar tab with this name."""
    name = name.strip() or DEFAULT_CATEGORY
    if all(cls.bl_category == name for cls in CLASSES):
        return
    for cls in reversed(CLASSES):
        if cls.is_registered:
            bpy.utils.unregister_class(cls)
    for cls in CLASSES:
        cls.bl_category = name
        bpy.utils.register_class(cls)


CLASSES = (
    TREEWIND_PT_main,
    TREEWIND_PT_settings,
    TREEWIND_PT_structure,
    TREEWIND_PT_channels,
    TREEWIND_PT_uv,
    TREEWIND_PT_uv_help,
    TREEWIND_PT_uv_editor,
    TREEWIND_PT_uv_editor_help,
)
