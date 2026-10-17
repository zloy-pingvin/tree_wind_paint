# SPDX-License-Identifier: GPL-2.0-or-later
"""Scene settings and the per-material role."""

import math

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty

from .colors import ICON, preview


def _show_picked(_self, context):
    preview(context)

# Enum values are saved in .blend files as numbers: every item has a fixed
# number that must never change, new items get new numbers.
ROLE_ITEMS = (
    ('AUTO', "Auto", "By the name (leaf, needle... are leaves; dead, dry... are bare "
                     "branches; bark, trunk, branch... are bark), otherwise by shape: small "
                     "loose islands are leaves", 0),
    ('BARK', "Bark", "Trunk and branches", 1),
    ('BARE', "Bare Branches", "Dead or leafless branches: no leaf hangs on them and they do "
                              "not bend", 4),
    ('LEAF', "Leaves", "Leaf cards", 2),
    ('SKIP', "Skip", "Leave these faces unpainted", 3),
)

def _brush_colors():
    """Where vertex paint keeps the brush colours: unified settings or the brush."""
    ts = bpy.context.tool_settings
    vp = ts.vertex_paint if ts else None
    if vp is None:
        return None
    # per paint mode since 4.3 or so, one for the whole scene before
    ups = getattr(vp, "unified_paint_settings", None) or ts.unified_paint_settings
    if ups.use_unified_color or vp.brush is None:
        return ups
    return vp.brush


def _to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_srgb(c):
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1.0 / 2.4) - 0.055


_BLEND_TO_BRUSH = {0: 'MIX', 1: 'ADD', 2: 'MUL'}
_BRUSH_TO_BLEND = {v: k for k, v in _BLEND_TO_BRUSH.items()}


def _vertex_brush():
    ts = bpy.context.tool_settings
    vp = ts.vertex_paint if ts else None
    return vp.brush if vp is not None else None


def _get_blend(settings):
    brush = _vertex_brush()
    if brush is not None and brush.blend in _BRUSH_TO_BLEND:
        return _BRUSH_TO_BLEND[brush.blend]
    return settings.get("gradient_blend_store", 0)


def _set_blend(settings, value):
    settings["gradient_blend_store"] = value
    brush = _vertex_brush()
    if brush is not None:
        brush.blend = _BLEND_TO_BRUSH[value]


def brush_grey(attr):
    """Brush colour as the grey it writes (brush colours are linear)."""
    target = _brush_colors()
    if target is None:
        return 0.0
    rgb = getattr(target, attr)
    return min(max(sum(_to_srgb(max(c, 0.0)) for c in rgb) / 3.0, 0.0), 1.0)


def set_brush_grey(attr, value):
    target = _brush_colors()
    if target is not None:
        lin = _to_linear(value)
        setattr(target, attr, (lin, lin, lin))


GRADIENT_SCOPE_ITEMS = (
    ('CARD', "Card Under Cursor", "Only the UV island the drag starts on, on every leaf that "
                                  "shares its UVs", 0),
    ('ALL', "All Faces", "Every face shown in the UV editor", 1),
)


class TreeWindSettings(bpy.types.PropertyGroup):
    # The channel toggles also pick what the viewport shows (colors.preview).
    paint_r: BoolProperty(name="R", default=True, update=_show_picked,
                          description="Write and show the red channel (leaf flutter)")
    paint_g: BoolProperty(name="G", default=True, update=_show_picked,
                          description="Write and show the green channel (time offset)")
    paint_b: BoolProperty(name="B", default=True, update=_show_picked,
                          description="Write and show the blue channel (branch bend)")
    paint_a: BoolProperty(
        name="A", default=True, update=_show_picked,
        description="Write the alpha channel: ambient occlusion baked with Cycles, darker toward "
                    "the ground (the Crysis convention: A = AO)")
    ao_distance: FloatProperty(
        name="AO Range", default=0.005, min=0.001, max=1.0, subtype='FACTOR',
        description="How far occluders count, as a share of tree height")
    ground_height: FloatProperty(
        name="Ground Gradient", default=0.3, min=0.0, max=1.0, subtype='FACTOR',
        description="Up to this share of tree height the alpha darkens toward the ground "
                    "(0: no ground gradient)")
    ao_on_leaves: BoolProperty(
        name="AO on Leaves", default=True,
        description="Write the shading into leaves too; off: leaves get alpha 1 (no shading)")

    # Grey values of the vertex paint brush colours, in the stored (sRGB)
    # scale: what lands in the channel. Not stored here, they read and
    # write Blender's own brush colours, so its X (swap) and Ctrl+X (fill)
    # keep working with them.
    brush_value: FloatProperty(
        name="Brush Value", min=0.0, max=1.0, subtype='FACTOR',
        get=lambda self: brush_grey("color"),
        set=lambda self, value: set_brush_grey("color", value),
        description="Value the brush paints into the channel (X swaps it with the second value)")
    brush_value_2: FloatProperty(
        name="Second Value", min=0.0, max=1.0, subtype='FACTOR',
        get=lambda self: brush_grey("secondary_color"),
        set=lambda self, value: set_brush_grey("secondary_color", value),
        description="The second brush value (X swaps the two)")

    bend_power: FloatProperty(
        name="Bend Curve", default=2.0, min=0.2, max=16.0,
        description="Steepness of the blue gradient: 1 is linear, "
                    "higher keeps the bend near the tips")
    rigid_leafless: BoolProperty(
        name="Leafless Branches Don't Bend", default=True,
        description="Branches with no leaves on them or on anything they carry get no blue "
                    "gradient: they keep the blue of the point they grow from (0 on the trunk)")
    group_seed: IntProperty(
        name="Phase Seed", default=0, min=0,
        description="Shuffles the green values")
    flutter_power: FloatProperty(
        name="Flutter Curve", default=3.0, min=0.2, max=16.0,
        description="Steepness of the red gradient from the leaf stem to its tip")
    fork_ratio: FloatProperty(
        name="Fork Ratio", default=0.5, min=0.0, max=1.0, subtype='FACTOR',
        description="The trunk ends at the first branch at least this long compared to "
                    "the rest of the trunk; 0 keeps the whole longest path as trunk")
    fork_angle: FloatProperty(
        name="Fork Max Angle", default=math.radians(40.0), min=0.0, max=math.radians(90.0),
        subtype='ANGLE',
        description="Only a branch growing upward within this angle of vertical can split "
                    "the trunk; a long branch going sideways (pines, firs) is just a branch")
    min_branch: FloatProperty(
        name="Min Branch", default=0.01, min=0.0, max=0.2, subtype='FACTOR',
        description="Shorter tips (share of tree height) are bark bumps, not branches")

    uv_r: BoolProperty(name="R", default=True, description="Copy the red channel")
    uv_g: BoolProperty(name="G", default=False, description="Copy the green channel")
    uv_b: BoolProperty(name="B", default=False, description="Copy the blue channel")

    gradient_channel: EnumProperty(
        name="Channel", default='R',
        items=(('R', "R", "Leaf flutter", ICON['R'], 0),
               ('G', "G", "Time offset", ICON['G'], 1),
               ('B', "B", "Branch bend", ICON['B'], 2)))
    gradient_power: FloatProperty(
        name="Curve", default=1.0, min=0.2, max=16.0,
        description="1 is linear, higher keeps the gradient low until near its end")
    gradient_scope: EnumProperty(name="Scope", items=GRADIENT_SCOPE_ITEMS, default='CARD')

    # gradient tools in the 3D viewport (ops_gradient)
    # One blend for the brush and the gradients: it reads and writes the vertex
    # paint brush's own blend (Mix / Add / Multiply), which works on the stored
    # values just like the gradients do.
    gradient_blend: EnumProperty(
        name="Blend",
        items=(('REPLACE', "Replace", "The new value replaces the old one", 0),
               ('ADD', "Add", "The new value is added to the old one", 1),
               ('MULTIPLY', "Multiply", "The old value is multiplied by the new one", 2)),
        get=lambda self: _get_blend(self), set=lambda self, value: _set_blend(self, value),
        description="How the brush and the gradients combine with the channel "
                    "(the same as the brush blend in the header)")
    radial_shape: EnumProperty(
        name="Shape", default='CIRCLE',
        items=(('CIRCLE', "Circle", "A circle on the screen: everything inside it as seen", 0),
               ('SPHERE', "Sphere", "A sphere in 3D around the point on the surface where the "
                                    "drag starts", 1)))
    gradient_radius: FloatProperty(
        name="Cylinder Radius", default=0.3, min=0.0001, soft_max=10.0, subtype='DISTANCE',
        description="Radius of the cylinder the linear gradient paints in "
                    "(mouse wheel while dragging)")

    def paint_params(self):
        from .analysis import PaintParams
        p = PaintParams()
        for name in ("bend_power", "rigid_leafless", "group_seed", "flutter_power"):
            setattr(p, name, getattr(self, name))
        return p

    def channels(self):
        return [c for c, on in (('R', self.paint_r), ('G', self.paint_g), ('B', self.paint_b)) if on]

    def uv_channels(self):
        return [c for c, on in (('R', self.uv_r), ('G', self.uv_g), ('B', self.uv_b)) if on]


CLASSES = (TreeWindSettings,)


def register():
    bpy.types.Scene.tree_wind = PointerProperty(type=TreeWindSettings)
    bpy.types.Material.tree_wind_role = EnumProperty(
        name="Wind Role", items=ROLE_ITEMS, default='AUTO',
        description="What these faces are for wind painting")


def unregister():
    del bpy.types.Material.tree_wind_role
    del bpy.types.Scene.tree_wind
