# SPDX-License-Identifier: GPL-3.0-or-later
"""
Wind Preview: the tree moves in the viewport as UNIGINE moves it.

A Geometry Nodes modifier reads the wind colours and offsets the vertices
with the formula of UNIGINE's mesh_base material, leaves mode "geometry
vertex color based" (data/core/materials/base/objects/mesh/shaders/common/
vertex.h), with the same parameters as that material's Animation group:

- stem: scale = max(z * Stem Offset, 0); offset.xy = (sin 0.9a cos 0.3a,
  cos 0.9a sin 0.3a) * scale^2 with a = Stem Noise * (object x + y) + Stem
  Speed * t; offset.z = dot(offset.xy, centre - vertex) * Stem Radius; plus
  the global wind vector * scale^2;
- branch: B * Branch Offset * 0.3 * noise(Branch Speed * 2 * t + G * 100)
  per axis;
- leaves: R * Leaves Offset * 0.2 * noise(Leaves Speed * 8 * t + Leaves
  Noise * 10 * (x + y + z) + G * 100) per axis;
  (the 0.3, 2, 0.2, 8 and 10 are the engine's own scaling of the sliders);
- noise(t) = 0.5 * (cos(v1 t + v2) + sin(v3 t + v4)), three sets of v for
  x, y and z.

The engine reads the colour bytes / 255; Blender gives Geometry Nodes the
linear value, so the colour goes back to sRGB first. Positions are the
mesh's own (object space), as in the shader. The object's rotation and
scale are left out of the stem's z term and the wind (approximate there).
"""

import bpy

from .colors import wind_attribute
from .translations import iface_

GROUP = "TWP Wind Preview"
MODIFIER = "TWP_WindPreview"
GROUP_VERSION = 4   # bump when the node tree below changes: old groups get rebuilt

# What the engine multiplies the material's sliders by before the shader
# (source/engine/render/Material.cpp, set_shader_animation_parameters).
# The stem sliders go through as they are.
LEAF_NOISE, LEAF_OFFSET, LEAF_SPEED = 10.0, 0.2, 8.0
BRANCH_OFFSET, BRANCH_SPEED = 0.3, 2.0

# (name, default, min, max, description): UNIGINE mesh_base defaults
# (name, default, min, max, description); defaults as the user's tree materials
PARAMS = (
    ("Stem Offset", 0.1, 0.0, 10.0, "Animation offset amplitude scale for vegetation stems"),
    ("Stem Radius", 0.01, 0.0, 10.0, "Animation rotation amplitude scale for vegetation stems"),
    ("Stem Speed", 1.0, 0.0, 10.0, "Animation time scale for vegetation stems"),
    ("Stem Noise", 1.0, 0.0, 10.0, "Spatial noise that varies the direction stems move in"),
    ("Branch Offset", 0.5, 0.0, 10.0, "Branch movement amplitude (blue channel)"),
    ("Branch Speed", 2.0, 0.0, 10.0, "Branch animation time scale"),
    ("Leaves Offset", 0.5, 0.0, 10.0, "Leaf movement amplitude (red channel)"),
    ("Leaves Speed", 1.0, 0.0, 100.0, "Leaf animation time scale"),
    ("Leaves Noise", 10.0, 0.0, 100.0, "Spatial noise that varies the direction leaves move in"),
)
NOISE = ((1.14, 1.05, 0.83, -9.22), (0.88, 4.55, 1.20, 1.43), (-0.9, 2.34, 0.96, 5.13))


class _Builder:
    """Small helper to wire math nodes: sockets or numbers in, socket out."""

    def __init__(self, tree):
        self.tree = tree
        self.x = 0

    def node(self, kind, **props):
        n = self.tree.nodes.new(kind)
        for key, value in props.items():
            setattr(n, key, value)
        n.location = (self.x, 0)
        self.x += 20
        return n

    def feed(self, sock, value):
        if isinstance(value, bpy.types.NodeSocket):
            self.tree.links.new(value, sock)
        else:
            sock.default_value = value

    def math(self, op, a, b=0.0, c=0.0):
        n = self.node("ShaderNodeMath", operation=op)
        self.feed(n.inputs[0], a)
        self.feed(n.inputs[1], b)
        if len(n.inputs) > 2:
            self.feed(n.inputs[2], c)
        return n.outputs[0]

    def add(self, *terms):
        out = terms[0]
        for t in terms[1:]:
            out = self.math('ADD', out, t)
        return out

    def mul(self, *terms):
        out = terms[0]
        for t in terms[1:]:
            out = self.math('MULTIPLY', out, t)
        return out

    def noise(self, t, v):
        """0.5 * (cos(v1 t + v2) + sin(v3 t + v4))"""
        v1, v2, v3, v4 = v
        c = self.math('COSINE', self.math('MULTIPLY_ADD', t, v1, v2))
        s = self.math('SINE', self.math('MULTIPLY_ADD', t, v3, v4))
        return self.mul(self.add(c, s), 0.5)

    def to_srgb(self, c):
        """Linear -> sRGB (the bytes the engine reads)."""
        low = self.mul(c, 12.92)
        high = self.math('SUBTRACT', self.mul(self.math('POWER', self.math('MAXIMUM', c, 0.0),
                                                        1.0 / 2.4), 1.055), 0.055)
        is_high = self.math('GREATER_THAN', c, 0.0031308)
        return self.add(low, self.mul(self.math('SUBTRACT', high, low), is_high))

    def combine(self, x, y, z):
        n = self.node("ShaderNodeCombineXYZ")
        self.feed(n.inputs[0], x)
        self.feed(n.inputs[1], y)
        self.feed(n.inputs[2], z)
        return n.outputs[0]


def _build(tree):
    tree.nodes.clear()
    iface = tree.interface
    iface.clear()
    iface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    iface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    attr_sock = iface.new_socket("Attribute", in_out='INPUT', socket_type='NodeSocketString')
    attr_sock.default_value = "WindColor"
    for name, default, lo, hi, desc in PARAMS:
        s = iface.new_socket(name, in_out='INPUT', socket_type='NodeSocketFloat')
        s.default_value, s.min_value, s.max_value, s.description = default, lo, hi, desc
    wind = iface.new_socket("Wind", in_out='INPUT', socket_type='NodeSocketVector')
    wind.description = "Global wind direction (render_animation_wind), times the stem scale squared"

    b = _Builder(tree)
    gin = b.node("NodeGroupInput")
    gout = b.node("NodeGroupOutput")
    p = {name: gin.outputs[name] for name, *_rest in PARAMS}

    named = b.node("GeometryNodeInputNamedAttribute", data_type='FLOAT_COLOR')
    b.feed(named.inputs["Name"], gin.outputs["Attribute"])
    sep_c = b.node("FunctionNodeSeparateColor")
    b.feed(sep_c.inputs[0], named.outputs["Attribute"])
    r = b.to_srgb(sep_c.outputs[0])
    g = b.to_srgb(sep_c.outputs[1])
    bl = b.to_srgb(sep_c.outputs[2])

    pos = b.node("GeometryNodeInputPosition").outputs[0]
    sep_p = b.node("ShaderNodeSeparateXYZ")
    b.feed(sep_p.inputs[0], pos)
    x, y, z = sep_p.outputs[0], sep_p.outputs[1], sep_p.outputs[2]
    t = b.node("GeometryNodeInputSceneTime").outputs["Seconds"]

    selfob = b.node("GeometryNodeSelfObject")
    info = b.node("GeometryNodeObjectInfo")
    b.feed(info.inputs["Object"], selfob.outputs[0])
    sep_o = b.node("ShaderNodeSeparateXYZ")
    b.feed(sep_o.inputs[0], info.outputs["Location"])

    # stem
    scale = b.math('MAXIMUM', b.mul(z, p["Stem Offset"]), 0.0)
    s2 = b.mul(scale, scale)
    angle = b.math('MULTIPLY_ADD', b.add(sep_o.outputs[0], sep_o.outputs[1]), p["Stem Noise"],
                   b.mul(p["Stem Speed"], t))
    a03, a09 = b.mul(angle, 0.3), b.mul(angle, 0.9)
    sx = b.mul(b.math('SINE', a09), b.math('COSINE', a03), s2)
    sy = b.mul(b.math('COSINE', a09), b.math('SINE', a03), s2)
    # dot(offset, centre - vertex): the centre is the origin of the mesh's own space
    sz = b.mul(b.add(b.mul(sx, x), b.mul(sy, y)), -1.0, p["Stem Radius"])
    stem = b.combine(sx, sy, sz)
    wind_off = b.node("ShaderNodeVectorMath", operation='SCALE')
    b.feed(wind_off.inputs[0], gin.outputs["Wind"])
    b.feed(wind_off.inputs["Scale"], s2)

    # branch and leaves, delayed per branch by G; the material's sliders reach
    # the shader scaled (Material::set_shader_animation_parameters)
    delay = b.mul(g, 100.0)
    t_branch = b.math('MULTIPLY_ADD', b.mul(p["Branch Speed"], BRANCH_SPEED), t, delay)
    amp_branch = b.mul(bl, p["Branch Offset"], BRANCH_OFFSET)
    branch = b.combine(*(b.mul(amp_branch, b.noise(t_branch, v)) for v in NOISE))
    t_leaf = b.add(b.mul(p["Leaves Speed"], LEAF_SPEED, t),
                   b.mul(p["Leaves Noise"], LEAF_NOISE, b.add(x, y, z)), delay)
    amp_leaf = b.mul(r, p["Leaves Offset"], LEAF_OFFSET)
    leaves = b.combine(*(b.mul(amp_leaf, b.noise(t_leaf, v)) for v in NOISE))

    total = stem
    for part in (wind_off.outputs[0], branch, leaves):
        n = b.node("ShaderNodeVectorMath", operation='ADD')
        b.feed(n.inputs[0], total)
        b.feed(n.inputs[1], part)
        total = n.outputs[0]

    setpos = b.node("GeometryNodeSetPosition")
    b.feed(setpos.inputs["Geometry"], gin.outputs[0])
    b.feed(setpos.inputs["Offset"], total)
    tree.links.new(setpos.outputs[0], gout.inputs[0])
    tree["twp_version"] = GROUP_VERSION


def node_group():
    tree = bpy.data.node_groups.get(GROUP)
    if tree is None or tree.bl_idname != 'GeometryNodeTree':
        tree = bpy.data.node_groups.new(GROUP, 'GeometryNodeTree')
    if tree.get("twp_version") != GROUP_VERSION:
        _build(tree)
    return tree


def modifier(ob):
    """The preview modifier of this object, if it has one."""
    return ob.modifiers.get(MODIFIER) if ob is not None else None


def input_ids(mod):
    """Modifier keys of the group's inputs, by name."""
    return {item.name: item.identifier for item in mod.node_group.interface.items_tree
            if item.item_type == 'SOCKET' and item.in_out == 'INPUT'}


# Blender 5.2 keeps a node modifier's input values in mod.properties.inputs
# (one struct per socket, with .value); before that they were ID properties
# of the modifier (mod["Socket_2"]).

def _socket_struct(mod, name):
    props = getattr(mod, "properties", None)
    inputs = getattr(props, "inputs", None) if props is not None else None
    if inputs is None:
        return None
    return getattr(inputs, input_ids(mod)[name], None)


def get_input(mod, name):
    sock = _socket_struct(mod, name)
    if sock is not None:
        return sock.value
    return mod[input_ids(mod)[name]]


def set_input(ob, mod, name, value):
    sock = _socket_struct(mod, name)
    if sock is not None:
        sock.value = value
    else:
        mod[input_ids(mod)[name]] = value
    # an ID property set from Python does not update the evaluated copy by itself
    ob.update_tag()


def draw_input(layout, mod, name, **kw):
    sock = _socket_struct(mod, name)
    if sock is not None:
        layout.prop(sock, "value", **kw)
    else:
        layout.prop(mod, '["%s"]' % input_ids(mod)[name], **kw)


def suspended(ob):
    """Context manager: the preview off while the real geometry is needed
    (the AO bake, its cache key)."""
    return _Suspend(modifier(ob))


class _Suspend:
    def __init__(self, mod):
        self.mod = mod

    def __enter__(self):
        if self.mod is not None:
            self.saved = (self.mod.show_viewport, self.mod.show_render)
            self.mod.show_viewport = self.mod.show_render = False
        return self

    def __exit__(self, *exc):
        if self.mod is not None:
            self.mod.show_viewport, self.mod.show_render = self.saved
        return False


VALUES_KEY = "twp_wind_preview_2"   # changed sliders, kept on the object (v2: only the ones off the defaults)
SLIDERS = [name for name, *_rest in PARAMS] + ["Wind"]


def _start(ob, attr_name):
    mod = ob.modifiers.new(MODIFIER, 'NODES')
    mod.node_group = node_group()
    mod.show_in_editmode = False
    mod.show_on_cage = False
    set_input(ob, mod, "Attribute", attr_name)
    stored = ob.get(VALUES_KEY)
    if stored is not None:
        for name in SLIDERS:
            if name in stored:
                value = stored[name]
                set_input(ob, mod, name, tuple(value) if name == "Wind" else float(value))
    return mod


def _remove(ob):
    """Keep the sliders on the object and take the modifier off."""
    mod = modifier(ob)
    if mod is None:
        return
    # only what differs from the defaults: new defaults then reach old trees
    defaults = {name: default for name, default, *_rest in PARAMS}
    values = {}
    for name in SLIDERS:
        value = get_input(mod, name)
        if name == "Wind":
            if any(abs(v) > 1e-6 for v in value):
                values[name] = list(value)
        elif abs(float(value) - defaults[name]) > 1e-6:
            values[name] = float(value)
    ob[VALUES_KEY] = values
    ob.modifiers.remove(mod)


def _object_at(ptr):
    if not ptr:
        return None
    return next((o for o in bpy.data.objects if o.as_pointer() == ptr), None)


def remove_all():
    """Take every preview off (on unregister: the tree must not keep moving)."""
    for ob in bpy.data.objects:
        if ob.type == 'MESH' and modifier(ob) is not None:
            _remove(ob)


class TREEWIND_OT_wind_preview(bpy.types.Operator):
    """Run from the panel: the preview plays in a small window of its
    sliders, and a click anywhere outside that window stops it (playback
    stops, the frame goes back, the modifier goes away). From a script:
    toggles the modifier."""
    bl_idname = "tree_wind.wind_preview"
    bl_label = "Wind Preview"
    bl_description = ("Play the tree's wind in the viewport as UNIGINE moves it, from its wind "
                      "colours. A click outside the preview window stops it")
    bl_options = set()

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'MESH'

    def _begin(self, context):
        ob = context.active_object
        attr = wind_attribute(ob.data)
        if attr is None:
            self.report({'WARNING'}, iface_("No wind colours yet: run Auto Paint"))
            return None
        # by address, not name: the object may be renamed while the preview runs
        self._ob_ptr = ob.as_pointer()
        return _start(ob, attr.name)

    def invoke(self, context, event):
        ob = context.active_object
        if modifier(ob) is not None:   # left over: just take it off
            _remove(ob)
            return {'FINISHED'}
        if self._begin(context) is None:
            return {'CANCELLED'}
        screen = context.screen
        self._played = not screen.is_animation_playing
        if self._played:
            bpy.ops.screen.animation_play()
        return context.window_manager.invoke_props_dialog(
            self, width=320, title=iface_("Wind Preview"), confirm_text=iface_("Stop"))

    def draw(self, context):
        ob = _object_at(getattr(self, "_ob_ptr", 0))
        mod = modifier(ob)
        if mod is None or mod.node_group is None:
            return
        col = self.layout.column(align=True)
        col.use_property_split = True
        col.use_property_decorate = False
        # named as in the UNIGINE material editor (English there), so values carry over
        groups = (("Stem Offset", "Stem Radius", "Stem Speed", "Stem Noise"),
                  ("Branch Offset", "Branch Speed"),
                  ("Leaves Offset", "Leaves Speed", "Leaves Noise"))
        for group in groups:
            for name in group:
                draw_input(col, mod, name, text=name, translate=False)
            col.separator()
        draw_input(col, mod, "Wind", text="Wind")
        hint = self.layout.row()
        hint.active = False
        hint.label(text="Click outside this window to stop", icon='INFO')

    def _stop(self, context):
        ob = _object_at(getattr(self, "_ob_ptr", 0))
        if ob is not None:
            _remove(ob)
        else:
            # an undo step remade the objects: only one preview runs at a time
            remove_all()
        if getattr(self, "_played", False) and context.screen is not None                 and context.screen.is_animation_playing:
            bpy.ops.screen.animation_cancel(restore_frame=True)

    def execute(self, context):
        if hasattr(self, "_ob_ptr"):   # Stop in the window
            self._stop(context)
            return {'FINISHED'}
        ob = context.active_object
        if modifier(ob) is not None:
            _remove(ob)
        elif self._begin(context) is None:
            return {'CANCELLED'}
        return {'FINISHED'}

    def cancel(self, context):
        self._stop(context)


CLASSES = (TREEWIND_OT_wind_preview,)
