# SPDX-License-Identifier: GPL-3.0-or-later
"""
Colour attribute access shared by the operators.

Values are read and written through ``color_srgb``: for a byte colour
attribute that is exactly the stored bytes / 255, i.e. what the engine gets.
"""

import bpy
import numpy as np

CHANNELS = ('R', 'G', 'B')
CHANNEL_INDEX = {'R': 0, 'G': 1, 'B': 2, 'A': 3}


def _channel_icons():
    """Icon per channel; RGB_* where this Blender has them, COLOR_* otherwise."""
    have = bpy.types.UILayout.bl_rna.functions["prop"].parameters["icon"].enum_items.keys()
    icons = {ch: ("RGB_" + name if "RGB_" + name in have else "COLOR_" + name)
             for ch, name in (('R', "RED"), ('G', "GREEN"), ('B', "BLUE"))}
    icons['A'] = 'IMAGE_ALPHA'
    return icons


ICON = _channel_icons()

# Helper attributes (never treated as the wind colours) start with this.
HELPER_PREFIX = "TWP_"
# Grey copy of one channel while it is being painted (see ops_channel).
TEMP_ATTR = "TWP_Channel"
BRANCHES_ATTR = "TWP_Branches"
# The wind colours with only the channels picked in the panel (see preview()).
PREVIEW_ATTR = "TWP_Preview"
ISO_SRC_KEY = "tree_wind_iso_src"
ISO_CH_KEY = "tree_wind_iso_channel"
# Name of the attribute last painted, so a helper being shown does not hide it.
WIND_ATTR_KEY = "tree_wind_attr"

DEFAULT_ATTR = "WindColor"


def isolated(me):
    """(source attribute name, channel) while a channel is being painted."""
    if TEMP_ATTR in me.color_attributes and ISO_SRC_KEY in me:
        return me[ISO_SRC_KEY], me.get(ISO_CH_KEY, 'R')
    return None


def _set_active(me, name):
    attrs = me.color_attributes
    for i, a in enumerate(attrs):
        if a.name == name:
            attrs.active_color_index = i
            return


def wind_attribute(me, create=False):
    """The colour attribute that holds the wind colours.

    The active colour attribute unless it is one of our helpers, then the one
    painted last, then any other. Read-only (safe in draw()) unless
    create=True: then a byte corner attribute is added when there is none,
    and the result is remembered on the mesh. Only operators may pass it.
    """
    attrs = me.color_attributes
    iso = isolated(me)
    if iso and iso[0] in attrs:
        return attrs[iso[0]]
    found = None
    name = attrs.active_color_name
    if name and not name.startswith(HELPER_PREFIX) and name in attrs:
        found = attrs[name]
    if found is None:
        stored = me.get(WIND_ATTR_KEY)
        if stored and stored in attrs:
            found = attrs[stored]
    if found is None:
        found = next((a for a in attrs if not a.name.startswith(HELPER_PREFIX)), None)
    if not create:
        return found
    if found is None:
        found = attrs.new(DEFAULT_ATTR, 'BYTE_COLOR', 'CORNER')
        buf = np.zeros((len(found.data), 4), np.float32)
        buf[:, 3] = 1.0
        found.data.foreach_set("color_srgb", buf.ravel())
        _set_active(me, found.name)
        attrs.render_color_index = attrs.active_color_index
    if me.get(WIND_ATTR_KEY) != found.name:
        me[WIND_ATTR_KEY] = found.name
    return found


def remember_wind_attribute(me):
    """Store the current wind attribute's name (operators only, not draw())."""
    found = wind_attribute(me)
    if found is not None and me.get(WIND_ATTR_KEY) != found.name:
        me[WIND_ATTR_KEY] = found.name


def loop_verts(me):
    lv = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get("vertex_index", lv)
    return lv


def read_corners(me, attr):
    """RGBA per corner (sRGB) whatever the attribute's domain."""
    n = len(attr.data)
    buf = np.empty(n * 4, np.float32)
    attr.data.foreach_get("color_srgb", buf)
    buf = buf.reshape(n, 4)
    if attr.domain == 'POINT':
        return buf[loop_verts(me)]
    return buf


def write_corners(me, attr, rgba, mask=None):
    """Write RGBA per corner (sRGB). Corners outside mask keep their colour.

    A point attribute holds one colour per vertex, shared by every face
    around it: a vertex changes only when the mask lets all its corners
    through (a masked-out face next to it keeps its colour), and it gets the
    mean of its corners.
    """
    if mask is None:
        mask = np.ones(len(rgba), bool)
    n = len(attr.data)
    cur = np.empty(n * 4, np.float32)
    attr.data.foreach_get("color_srgb", cur)
    cur = cur.reshape(n, 4)
    if attr.domain == 'POINT':
        lv = loop_verts(me)
        total = np.bincount(lv, minlength=n)
        inside = np.bincount(lv[mask], minlength=n)
        whole = (total > 0) & (inside == total)
        sums = np.stack([np.bincount(lv, weights=rgba[:, k], minlength=n) for k in range(4)], 1)
        cur[whole] = sums[whole] / total[whole, None]
    else:
        cur[mask] = rgba[mask]
    attr.data.foreach_set("color_srgb", cur.ravel())
    me.update()


def paint_mask(me, nl):
    """Corners a Vertex Paint tool may change: never hidden ones, and only the
    selection with selection masking on."""
    lv = loop_verts(me)
    total = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get("loop_total", total)
    fhide = np.zeros(len(me.polygons), bool)
    me.polygons.foreach_get("hide", fhide)
    vhide = np.zeros(len(me.vertices), bool)
    me.vertices.foreach_get("hide", vhide)
    mask = ~np.repeat(fhide, total) & ~vhide[lv]
    if me.use_paint_mask_vertex:
        vsel = np.zeros(len(me.vertices), bool)
        me.vertices.foreach_get("select", vsel)
        mask &= vsel[lv]
    if me.use_paint_mask:
        fsel = np.zeros(len(me.polygons), bool)
        me.polygons.foreach_get("select", fsel)
        mask &= np.repeat(fsel, total)
    return lv, mask


def blend_values(old, new, blend):
    """Blend modes of the manual tools, in the stored scale like Blender's brush."""
    if blend == 'ADD':
        return old + new
    if blend == 'MULTIPLY':
        return old * new
    return new


def write_channels(me, attr, values, channels, mask=None):
    """values: per corner (nl, 3) or (nl,) for a single channel."""
    rgba = read_corners(me, attr).copy()
    values = np.asarray(values, np.float32)
    for ch in channels:
        k = CHANNEL_INDEX[ch]
        rgba[:, k] = values if values.ndim == 1 else values[:, k]
    write_corners(me, attr, rgba, mask)


class ObjectMode:
    """Run a block in object mode and return to the previous mode after it.

    Mesh arrays are only current outside edit mode, and attribute layers
    should not be added or removed under a paint mode.
    """

    def __init__(self, ob):
        self.ob = ob
        self.mode = ob.mode

    def __enter__(self):
        if self.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        return self

    def __exit__(self, *exc):
        if self.mode != 'OBJECT' and self.ob.mode != self.mode:
            bpy.ops.object.mode_set(mode=self.mode)
        return False


def show_colors(context):
    """Make solid-mode 3D views show the active colour attribute."""
    screen = context.screen
    if screen is None:
        return
    for area in screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.shading.color_type = 'VERTEX'


def set_active(me, name):
    _set_active(me, name)


def drop_helper(me, name):
    attr = me.color_attributes.get(name)
    if attr is not None:
        me.color_attributes.remove(attr)


def viewed_channels(settings):
    """Channels the viewport shows, from the panel's channel toggles."""
    picked = [c for c, on in (('R', settings.paint_r), ('G', settings.paint_g),
                              ('B', settings.paint_b), ('A', settings.paint_a)) if on]
    rgb = [c for c in picked if c != 'A']
    if rgb:
        return rgb
    return ['A'] if 'A' in picked else []


def preview(context):
    """Show only the channels picked in the panel.

    One channel shows as grey, several as colour with the others off. With
    R, G and B all picked (or nothing) the wind colours themselves show and
    the helper attribute goes away, so it never ends up in an export by
    accident. Only in object mode: there the mesh arrays are current and
    nothing is being painted.
    """
    ob = context.active_object
    if ob is None or ob.type != 'MESH' or ob.mode != 'OBJECT':
        return
    me = ob.data
    if isolated(me):
        return
    attr = wind_attribute(me)
    if attr is None:
        return
    # the helper is about to be active: remember which layer the wind colours are in
    name = attr.name
    if me.get(WIND_ATTR_KEY) != name:
        me[WIND_ATTR_KEY] = name
    view = viewed_channels(context.scene.tree_wind)
    if not view or set(view) == {'R', 'G', 'B'}:
        drop_helper(me, PREVIEW_ATTR)
        set_active(me, name)
        show_colors(context)
        return
    src = read_corners(me, attr)
    out = np.zeros_like(src)
    out[:, 3] = 1.0
    if len(view) == 1:
        out[:, :3] = src[:, CHANNEL_INDEX[view[0]]][:, None]
    else:
        for ch in view:
            out[:, CHANNEL_INDEX[ch]] = src[:, CHANNEL_INDEX[ch]]
    prev = me.color_attributes.get(PREVIEW_ATTR)
    if prev is None:
        prev = me.color_attributes.new(PREVIEW_ATTR, 'BYTE_COLOR', 'CORNER')
    prev.data.foreach_set("color_srgb", out.ravel())
    me.update()
    set_active(me, PREVIEW_ATTR)
    show_colors(context)
