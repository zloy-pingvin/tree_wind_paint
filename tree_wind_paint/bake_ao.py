# SPDX-License-Identifier: GPL-3.0-or-later
"""
Ambient occlusion for the alpha channel (the Crysis convention: A = AO).

Cycles bakes AO straight into a temporary colour attribute. Every other
object is hidden from the render while it bakes (a file often keeps the
LODs and an impostor at the same spot, and they would shade the tree), and
render settings are put back afterwards. The result is multiplied by a
gradient from the ground: darker at the foot of the tree, fading out at a
share of its height.
"""

import hashlib
import os

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc

from . import analysis
from .colors import set_active
from .translations import iface_

TMP = "TWP_AO"
BAKE_SAMPLES = 64
GROUND_DARK = 0.5   # alpha factor at ground level
SMOOTH_STEPS = 2    # passes of averaging with neighbour vertices
JOINT_BLEND = 0.02  # share of the tree height over which a branch fades from its parent's AO
JOINT_PIECE_SHARE = 0.25  # ... but at most this share of the branch piece's own length
STUB_SIZE = 0.015   # share of the tree height: a smaller piece takes its parent's AO all over
BURIED_REACH = 4.0  # how deep (in JOINT_BLEND) a buried branch base is still looked for
CLEAN_STEPS = 20    # passes filling in the AO of bark vertices other pieces touch
CLEAN_REACH = 0.01  # share of the tree height: farthest a touching piece's shade is removed

# AO only depends on the geometry and the distance: keep it per mesh.
_cache = {}


def _bake(context, ob, distance, plain=False):
    """AO per corner, 0 (occluded) .. 1 (open).

    With plain, every surface bakes as a plain opaque material: AO is baked
    at the corners, and a leaf card's corners lie where its alpha texture is
    clear, so through the real material leaves come out black. Without it
    the clear parts of leaf cards let the AO rays through, which is what the
    bark wants.
    """
    scene = context.scene
    if not hasattr(scene, "cycles"):
        # the Cycles add-on is turned off: no engine to bake with
        raise RuntimeError(iface_("Cycles is turned off in Preferences > Add-ons"))
    me = ob.data
    saved = {
        "engine": scene.render.engine,
        "world": scene.world,
        "active": context.view_layer.objects.active,
        "selected": [o for o in context.view_layer.objects if o.select_get()],
        "hidden": {o.name: o.hide_render for o in scene.objects},
        "color": me.color_attributes.active_color_name,
    }
    world = scene.world
    temp_world = None
    if world is None:
        temp_world = bpy.data.worlds.new("TWP_AO_World")
        scene.world = world = temp_world
    saved_distance = world.light_settings.distance
    saved_samples = scene.cycles.samples
    view_layer = context.view_layer
    saved_override = view_layer.material_override
    override = bpy.data.materials.new("TWP_AO_Plain") if plain else None
    # its real name: Blender adds .001 when the name is taken
    tmp_name = me.color_attributes.new(TMP, 'FLOAT_COLOR', 'CORNER').name
    try:
        scene.render.engine = 'CYCLES'
        scene.cycles.samples = BAKE_SAMPLES
        world.light_settings.distance = distance
        # plain: our opaque material; otherwise the tree's own, not one the
        # user overrides the view layer with
        view_layer.material_override = override
        for o in scene.objects:
            o.hide_render = o is not ob
        for o in saved["selected"]:
            o.select_set(False)
        ob.select_set(True)
        context.view_layer.objects.active = ob
        set_active(me, tmp_name)
        # every bake setting that matters is given: the scene's own (Selected
        # to Active, a cage...) are for the user's bakes, not this one
        bpy.ops.object.bake(type='AO', target='VERTEX_COLORS', use_clear=True,
                            use_selected_to_active=False, use_cage=False)
        # linear: AO is a fraction of open sky, not a colour to display
        attr = me.color_attributes[tmp_name]
        buf = np.empty(len(attr.data) * 4, np.float32)
        attr.data.foreach_get("color", buf)
        ao = buf.reshape(-1, 4)[:, 0].copy()
    finally:
        tmp = me.color_attributes.get(tmp_name)
        if tmp is not None:
            me.color_attributes.remove(tmp)
        if saved["color"] in me.color_attributes:
            set_active(me, saved["color"])
        world.light_settings.distance = saved_distance
        scene.cycles.samples = saved_samples
        view_layer.material_override = saved_override
        if override is not None:
            bpy.data.materials.remove(override)
        scene.render.engine = saved["engine"]
        scene.world = saved["world"]
        if temp_world is not None:
            bpy.data.worlds.remove(temp_world)
        for o in scene.objects:
            if o.name in saved["hidden"]:
                o.hide_render = saved["hidden"][o.name]
        ob.select_set(False)
        for o in saved["selected"]:
            o.select_set(True)
        context.view_layer.objects.active = saved["active"]
    return np.clip(ao, 0.0, 1.0)


def _per_vertex(md, ao):
    """Per corner -> per vertex: the bake gives every face corner its own
    value, so the faces around one vertex disagree and a low-poly trunk
    looks chopped into facets."""
    lv = md.loop_vert
    cnt = np.maximum(np.bincount(lv, minlength=md.nv), 1)
    return np.bincount(lv, weights=ao, minlength=md.nv) / cnt


def _smooth(md, v):
    """A few passes of averaging with neighbour vertices."""
    lv = md.loop_vert
    a, b = lv, lv[md.loop_next]
    deg = np.maximum(np.bincount(a, minlength=md.nv) + np.bincount(b, minlength=md.nv), 1)
    for _ in range(SMOOTH_STEPS):
        nb = (np.bincount(a, weights=v[b], minlength=md.nv)
              + np.bincount(b, weights=v[a], minlength=md.nv)) / deg
        v = 0.5 * v + 0.5 * nb
    return v


class _Parts:
    """Bark split into parts joined by edges, and how the parts hang together.

    Loose bark pieces are parts, and so is a piece welded to another by a
    vertex or two only (vertices merged by accident: a knot, a limb). Such a
    welded part is a separate surface going into its neighbour like any
    loose branch. A vertex shared by parts belongs to the biggest of them,
    on whose surface it lies.

    face: part per face (-1 not bark); vert: part per vertex (-1 not bark);
    joints: (parent part, child part, entry vertex), from the trunk out;
    island_face: bark island per face (-1 not bark).
    """

    def __init__(self, md, tree, face_role):
        wood_f = np.isin(face_role, analysis.WOOD)
        lp, lv = md.loop_poly, md.loop_vert
        a, b = lv, lv[md.loop_next]
        # faces linked through the bark edges they share
        key = np.minimum(a, b).astype(np.int64) * md.nv + np.maximum(a, b)
        keep = wood_f[lp]
        key, kp = key[keep], lp[keep]
        order = np.argsort(key, kind='stable')
        key, kp = key[order], kp[order]
        same = key[1:] == key[:-1]
        lab = analysis.components(md.npoly, kp[:-1][same], kp[1:][same])
        self.face = np.where(wood_f, lab, -1)
        self.island_face = np.where(wood_f, tree.island[lv[md.poly_start]], -1)
        size = np.bincount(lab[wood_f], minlength=md.npoly)
        # every vertex goes to the biggest part among its faces
        wl = wood_f[lp]
        cv, cp = lv[wl], self.face[lp[wl]]
        o = np.lexsort((size[cp], cv))[::-1]
        uv, first = np.unique(cv[o], return_index=True)
        self.vert = np.full(md.nv, -1, np.int64)
        self.vert[uv] = cp[o][first]

        island = tree.island
        joints = {}
        # loose pieces: their biggest part hangs where the analysis attached them
        best = {}
        ps, first_face = np.unique(self.face, return_index=True)
        for p, f in zip(ps.tolist(), first_face.tolist()):
            if p < 0:
                continue
            i = int(island[lv[md.poly_start[f]]])
            if i not in best or size[p] > size[best[i]]:
                best[i] = p
        main = set(best.values())
        pairs = tree.bridge_pairs if tree.bridge_pairs is not None else np.zeros((0, 2), np.int64)
        for u, m in pairs.tolist():
            child = best.get(int(island[m]))
            if child is not None and self.vert[u] >= 0:
                joints[child] = (int(self.vert[u]), child, m)
        # welded parts: they hang on the biggest part they share a vertex with
        pv = np.unique(np.stack([cv, cp], axis=1), axis=0)
        multi = np.bincount(pv[:, 0], minlength=md.nv) > 1
        d = np.nan_to_num(tree.d, nan=np.inf)
        for v, p in pv[multi[pv[:, 0]]].tolist():
            owner = int(self.vert[v])
            if p == owner or p in main:
                continue
            if p not in joints or d[v] < d[joints[p][2]]:
                joints[p] = (owner, p, v)
        self.joints = sorted(joints.values(), key=lambda j: d[j[2]])
        self.welded = sum(1 for p in joints if p not in main)


def clean_contacts(md, tree, parts, ao, reach):
    """Per vertex AO without the shade loose bark pieces cast where they touch.

    A bark vertex within the AO distance of another piece's surface (a
    trunk vertex next to where a branch goes in) is darkened by that piece,
    and on a low-poly trunk the colour of one vertex spreads over faces a
    metre long: a dark streak. Such vertices get their AO from the untouched
    vertices of their own piece instead (filled in from the edge inwards,
    then evened out). Pieces here are whole bark islands: a limb welded to
    the trunk by a vertex keeps the shade of its fork.
    """
    part = tree.island
    bark = np.where(part >= 0)[0]
    co = md.co
    wood = np.where(parts.island_face >= 0)[0]
    starts = md.poly_start[wood].tolist()
    totals = md.poly_total[wood].tolist()
    lv_list = md.loop_vert.tolist()
    polys = [lv_list[s:s + t] for s, t in zip(starts, totals)]
    co_list = co.tolist()
    bvh = BVHTree.FromPolygons(co_list, polys, all_triangles=False)
    face_part = parts.island_face[wood].tolist()
    vp = part.tolist()
    touched = np.zeros(md.nv, bool)
    for v in bark.tolist():
        for _loc, _nrm, idx, _dist in bvh.find_nearest_range(co_list[v], reach):
            if face_part[idx] != vp[v]:
                touched[v] = True
                break
    if not touched.any():
        return ao
    a, b = md.loop_vert, md.loop_vert[md.loop_next]
    same = (part[a] == part[b]) & (part[a] >= 0)
    a, b = np.concatenate([a[same], b[same]]), np.concatenate([b[same], a[same]])
    ao = ao.copy()
    have = ~touched
    for _ in range(CLEAN_STEPS):
        pending = touched & ~have
        if not pending.any():
            break
        total = np.bincount(a, weights=ao[b] * have[b], minlength=md.nv)
        count = np.bincount(a, weights=have[b].astype(float), minlength=md.nv)
        new = pending & (count > 0)
        if not new.any():
            break  # a piece touched all over keeps its own AO
        ao[new] = total[new] / count[new]
        have |= new
    filled = touched & have
    count = np.bincount(a, minlength=md.nv)
    for _ in range(CLEAN_STEPS):
        total = np.bincount(a, weights=ao[b], minlength=md.nv)
        ao[filled] = total[filled] / np.maximum(count[filled], 1)
    return ao


def match_joints(md, tree, parts, ao):
    """Per vertex AO where every bark part meets its parent as the parent.

    A branch stuck into the trunk has its own vertices, rarely where the
    trunk has them, and its base is buried in the trunk where the bake sees
    no sky. So near the joint it takes the parent's AO at the nearest point
    of the parent's surface (inside it fully; a part that only touches the
    parent counts from its closest vertices), fading back to its own over
    JOINT_BLEND of the tree height, or JOINT_PIECE_SHARE of the part's
    length if that is shorter; a stub smaller than STUB_SIZE of the tree
    height takes the parent's AO all over. Every edge that goes through the parent's
    surface takes the parent's AO at that point on both ends, so the seam
    matches exactly. Parts go from the trunk out, so a twig on a branch
    meets the branch's corrected AO.
    """
    if not parts.joints:
        return ao
    ao = ao.copy()
    part = parts.vert
    radius = max(JOINT_BLEND * tree.height, 1e-6)
    wood = np.where(parts.face >= 0)[0]
    wood_part = parts.face[wood]
    co_list = md.co.tolist()
    lv_list = md.loop_vert.tolist()
    wood_polys = [lv_list[s:s + t] for s, t in zip(md.poly_start[wood].tolist(),
                                                   md.poly_total[wood].tolist())]
    # vertices and edges grouped by part, to slice per part
    v_order = np.argsort(part, kind='stable')
    v_part = part[v_order]
    ea, eb = md.loop_vert, md.loop_vert[md.loop_next]
    inner = (part[ea] == part[eb]) & (part[ea] >= 0)
    ea, eb = ea[inner], eb[inner]
    e_order = np.argsort(part[ea], kind='stable')
    ea, eb = ea[e_order], eb[e_order]
    e_part = part[ea]
    bvhs = {}
    for parent, child, m in parts.joints:
        if parent not in bvhs:
            polys = [wood_polys[i] for i in np.where(wood_part == parent)[0].tolist()]
            bvhs[parent] = (BVHTree.FromPolygons(co_list, polys, all_triangles=False), polys)
        bvh, polys = bvhs[parent]
        lo, hi = np.searchsorted(v_part, [child, child + 1])
        verts = v_order[lo:hi]
        if not len(verts):
            continue
        # a short twig keeps most of its own AO: fade over a share of its length;
        # a stub (a knot, a sawn-off twig) is coloured like its parent all over
        stub = float(np.ptp(md.co[verts], axis=0).max()) < STUB_SIZE * tree.height
        span = float(np.nanmax(tree.d[verts]) - np.nanmin(tree.d[verts]))
        reach = min(radius, max(JOINT_PIECE_SHARE * span, 1e-6))
        found = {}    # vertex -> (signed gap, parent face, nearest point)
        for v in verts.tolist():
            p = Vector(co_list[v])
            loc, nrm, idx, dist = bvh.find_nearest(p, BURIED_REACH * radius)
            if loc is not None:
                found[v] = (dist if (p - loc).dot(nrm) >= 0.0 else -dist, idx, loc)
        if not found:
            continue
        # a part that only touches the parent: its closest vertices count as the joint
        touch = max(min(g for g, _i, _l in found.values()), 0.0)
        target = {}
        for v, (gap, idx, loc) in found.items():
            t = 0.0 if stub else min(max(gap - touch, 0.0) / reach, 1.0)
            w = 1.0 - t * t * (3.0 - 2.0 * t)
            if w > 0.0:
                target[v] = (_sample(ao, co_list, polys[idx], loc), w)
        # The seam lies on the edges that go through the parent's surface, and
        # its colour mixes both ends of such an edge: both ends take the
        # parent's AO at the point where the edge goes through it (averaged
        # over the edges). Only edges at the joint can: an end inside the
        # parent or within the fade.
        joint = set(target)
        lo, hi = np.searchsorted(e_part, [child, child + 1])
        pairs_ab = set()
        for a, b in zip(ea[lo:hi].tolist(), eb[lo:hi].tolist()):
            if a in joint or b in joint:
                pairs_ab.add((a, b) if a < b else (b, a))
        acc = {}
        for a, b in pairs_ab:
            pa, pb = Vector(co_list[a]), Vector(co_list[b])
            d = pb - pa
            hit = bvh.ray_cast(pa, d.normalized(), d.length) if d.length > 1e-9 else (None,) * 4
            if hit[0] is None:
                hit = bvh.ray_cast(pb, -d.normalized(), d.length) if d.length > 1e-9 else hit
            if hit[0] is None:
                continue
            value = _sample(ao, co_list, polys[hit[2]], hit[0])
            for v in (a, b):
                total, count = acc.get(v, (0.0, 0))
                acc[v] = (total + value, count + 1)
        for v, (total, count) in acc.items():
            target[v] = (total / count, 1.0)
        for v, (value, w) in target.items():
            ao[v] += (value - ao[v]) * w
    return ao


def _sample(ao, co, corners, point):
    """Per vertex AO interpolated at a point on a face."""
    weights = poly_3d_calc([Vector(co[x]) for x in corners], point)
    return float(sum(wt * ao[x] for wt, x in zip(weights, corners)))


def _socket_value(sock):
    value = getattr(sock, "default_value", None)
    try:
        return tuple(value)
    except TypeError:
        return value


_UI_PROPS = {'location', 'width', 'height', 'select', 'hide', 'show_options', 'show_preview',
             'show_texture', 'use_custom_color', 'color', 'show_expanded', 'show_in_editmode',
             'show_on_cage', 'is_active', 'show_pin'}


def _simple_props(struct, items):
    """The plain settings of a data block or node (numbers, flags, choices)."""
    for prop in struct.bl_rna.properties:
        if prop.type in {'ENUM', 'BOOLEAN', 'INT', 'FLOAT', 'STRING'} and not prop.is_readonly \
                and prop.identifier not in _UI_PROPS:
            value = getattr(struct, prop.identifier, None)
            try:
                value = tuple(value)
            except TypeError:
                pass
            items.append((prop.identifier, value))


def _image_items(image, items):
    """An image by what it holds: a painted texture keeps its name and path."""
    # Not the size, nor whether it is loaded: the bake itself loads it.
    items.append((image.name, image.filepath, image.source, image.alpha_mode,
                  image.colorspace_settings.name))
    if image.is_dirty or image.source == 'GENERATED':
        # painted and not saved (or made in Blender): only the pixels tell
        pixels = np.empty(len(image.pixels), np.float32)
        image.pixels.foreach_get(pixels)
        items.append(hashlib.blake2b(pixels.tobytes(), digest_size=16).hexdigest())
    elif image.packed_file is not None:
        items.append(image.packed_file.size)
    else:
        path = bpy.path.abspath(image.filepath, library=image.library)
        try:
            items.append(os.path.getmtime(path))
        except OSError:
            pass


def _node_tree_items(tree, items, seen):
    """Everything in a node tree that can change what it renders, node groups
    included (once each)."""
    if tree is None or tree.name in seen:
        return
    seen.add(tree.name)
    for node in tree.nodes:
        items.append((node.name, node.bl_idname, node.mute))
        image = getattr(node, "image", None)
        if image is not None:
            _image_items(image, items)
        # node settings that are not sockets (blend types, interpolation...)
        _simple_props(node, items)
        ramp = getattr(node, "color_ramp", None)
        if ramp is not None:
            items.append((ramp.interpolation, ramp.color_mode,
                          [(e.position, tuple(e.color)) for e in ramp.elements]))
        mapping = getattr(node, "mapping", None)
        if mapping is not None and hasattr(mapping, "curves"):
            items.append([[(tuple(p.location), p.handle_type) for p in c.points]
                          for c in mapping.curves])
        # RGB, Value and the like keep their value on the output
        for sock in list(node.inputs) + list(node.outputs):
            items.append((sock.identifier, _socket_value(sock)))
        _node_tree_items(getattr(node, "node_tree", None), items, seen)
    for link in tree.links:
        items.append((link.from_node.name, link.from_socket.identifier,
                      link.to_node.name, link.to_socket.identifier, link.is_muted))


def _bake_key(context, ob, md, distance_share):
    """Something that changes whenever the bake could come out different: the
    geometry as rendered (modifiers, shape keys), the UVs (where a leaf card
    is clear), the transform, the materials and the distance."""
    me = ob.data
    h = hashlib.blake2b(digest_size=16)
    h.update(md.checksum().encode())
    for layer in me.uv_layers:
        h.update(layer.name.encode())
        uv = np.empty(len(layer.data) * 2, np.float32)
        layer.data.foreach_get("uv", uv)
        h.update(uv.tobytes())
    # the map textures read when a node names none
    render_uv = next((layer.name for layer in me.uv_layers if layer.active_render), None)
    h.update(repr(render_uv).encode())
    items = []
    if len(ob.modifiers) or me.shape_keys is not None:
        evaluated = ob.evaluated_get(context.evaluated_depsgraph_get()).data
        co = np.empty(len(evaluated.vertices) * 3, np.float32)
        evaluated.vertices.foreach_get("co", co)
        h.update(co.tobytes())
        h.update(np.int64(len(evaluated.polygons)).tobytes())
        # the bake renders: the modifiers' render settings (show_render, render
        # levels...) count, which the viewport geometry above does not show
        for mod in ob.modifiers:
            items.append((mod.name, mod.type))
            _simple_props(mod, items)
    h.update(np.round(np.array(ob.matrix_world)[:3, :3], 6).tobytes())
    seen = set()
    for slot in ob.material_slots:
        mat = slot.material
        items.append(mat.name if mat else None)
        if mat is not None:
            _node_tree_items(mat.node_tree, items, seen)
    h.update(repr(items).encode())
    h.update(repr(round(distance_share, 6)).encode())
    return (ob.data.as_pointer(), h.hexdigest())


def _see_through(ob, md, face_role):
    """Whether a leaf material can be transparent (then the leaves need the
    plain bake): an alpha input linked or below 1, a transparent shader, or
    a node group, which could hold anything."""
    slots = np.unique(md.poly_mat[face_role == analysis.LEAF]).tolist()
    for i in slots:
        mat = ob.material_slots[i].material if i < len(ob.material_slots) else None
        if mat is None or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if node.type in {'BSDF_TRANSPARENT', 'GROUP'}:
                return True
            alpha = node.inputs.get("Alpha")
            if alpha is not None and (alpha.is_linked or getattr(alpha, "default_value", 1.0) < 1.0):
                return True
    return False


def ambient_occlusion(context, ob, md, height, distance_share, tree=None, face_role=None,
                      leaves=False):
    """Baked AO per corner, cached while nothing the bake depends on changes
    (see _bake_key).

    height is in mesh units; Cycles bakes in world units, so the object's
    scale goes in (a tree imported at 0.01 would otherwise get 100 times the
    distance). With the tree, the shade loose bark pieces cast where they
    touch goes (clean_contacts), and bark parts match their parent where
    they meet it (match_joints); parts are loose pieces and pieces welded
    by vertices only (_Parts). With leaves (and face_role), the leaves take
    their AO from a second bake with plain materials (see _bake).
    """
    scale = abs(float(np.linalg.det(np.array(ob.matrix_world)[:3, :3]))) ** (1.0 / 3.0)
    key = _bake_key(context, ob, md, distance_share)
    distance = max(distance_share * height * scale, 1e-4)
    hit = _cache.get(ob.name)
    if hit is None or hit["key"] != key:
        ao = _bake(context, ob, distance)
        hit = {"key": key, "raw": _per_vertex(md, ao), "leaf_raw": None,
               "fixed_for": None, "fixed": None}
        _cache.clear()
        _cache[ob.name] = hit
    ao = hit["raw"]
    leaf_v = None
    if leaves and face_role is not None:
        leaf_f = face_role[md.loop_poly] == analysis.LEAF
        if leaf_f.any() and _see_through(ob, md, face_role):
            if hit["leaf_raw"] is None:
                hit["leaf_raw"] = _per_vertex(md, _bake(context, ob, distance, plain=True))
            leaf_v = np.zeros(md.nv, bool)
            leaf_v[md.loop_vert[leaf_f]] = True
            ao = np.where(leaf_v, hit["leaf_raw"], ao)
    if tree is None:
        return _smooth(md, ao)[md.loop_vert]
    # the joints depend on the tree too: repainting with the same structure is free
    done = hit["fixed_for"]
    if done is None or done[0] is not tree or done[1] != (leaf_v is not None):
        # before smoothing, which would spread the shade of a touching piece around
        # only the contact shade: with a long AO range a piece's shade is a broad
        # gradient anyway, and searching that far would take minutes
        reach = min(distance_share, CLEAN_REACH) * height
        parts = _Parts(md, tree, face_role)
        ao = clean_contacts(md, tree, parts, ao, max(reach, 1e-6))
        hit["fixed"] = match_joints(md, tree, parts, _smooth(md, ao))
        hit["fixed_for"] = (tree, leaf_v is not None)
    return hit["fixed"][md.loop_vert]


def ground_gradient(md, height_share, zmin, height):
    """Per corner: GROUND_DARK at the foot of the tree up to 1 at height_share."""
    if height_share <= 0:
        return np.ones(md.nl)
    z = md.co[md.loop_vert, 2]
    t = np.clip((z - zmin) / max(height_share * height, 1e-6), 0.0, 1.0)
    t = t * t * (3.0 - 2.0 * t)
    return GROUND_DARK + (1.0 - GROUND_DARK) * t
