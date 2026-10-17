# SPDX-License-Identifier: GPL-2.0-or-later
"""Auto paint: wind colours computed from the tree's structure."""

import time

import bpy
import numpy as np

from . import analysis, bake_ao
from .colors import (BRANCHES_ATTR, ObjectMode, isolated, preview, remember_wind_attribute,
                     set_active, show_colors, wind_attribute, write_channels)
from .translations import iface_

# Structure analysis is the slow part; repainting with other curve settings
# reuses it while the mesh, the material roles and the structure settings
# stay the same.
_cache = {}


def slot_roles(ob):
    roles, names = [], []
    for slot in ob.material_slots:
        mat = slot.material
        roles.append(mat.tree_wind_role if mat else 'AUTO')
        names.append(mat.name if mat else "")
    return roles, names


def tree_for(ob, md, settings):
    roles, names = slot_roles(ob)
    resolved = analysis.resolve_roles(md, roles, names)
    face_role = analysis.face_roles(md, resolved)
    key = (ob.data.as_pointer(), md.checksum(), tuple(resolved),
           round(settings.fork_ratio, 4), round(settings.min_branch, 4),
           round(settings.fork_angle, 4))
    tree = _cache.get(ob.name)
    if tree is None or tree[0] != key:
        tree = (key, analysis.analyze(md, face_role, settings.fork_ratio, settings.min_branch,
                                      settings.fork_angle))
        _cache.clear()
        _cache[ob.name] = tree
    return tree[1], face_role, resolved


class TREEWIND_OT_auto_paint(bpy.types.Operator):
    bl_idname = "tree_wind.auto_paint"
    bl_label = "Auto Paint"
    bl_description = ("Paint wind colours from the tree's structure: B bends branches toward "
                      "their tips, G gives each big branch its own time offset, R makes leaf "
                      "tips flutter")
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        ob = context.active_object
        return ob is not None and ob.type == 'MESH'

    def execute(self, context):
        ob = context.active_object
        settings = context.scene.tree_wind
        channels = settings.channels()
        if not channels and not settings.paint_a:
            self.report({'WARNING'}, iface_("No channels selected"))
            return {'CANCELLED'}
        if isolated(ob.data):
            self.report({'ERROR'}, iface_("Apply or cancel the channel being painted first"))
            return {'CANCELLED'}
        t0 = time.perf_counter()
        ao_error = None
        with ObjectMode(ob):
            me = ob.data
            md = analysis.MeshData(me)
            try:
                tree, face_role, _roles = tree_for(ob, md, settings)
            except analysis.TreeError as ex:
                self.report({'ERROR'}, iface_(str(ex)))
                return {'CANCELLED'}
            rgb, mask = analysis.compute_colors(
                tree, md, face_role, settings.paint_params(), analysis.read_uv(me))
            attr = wind_attribute(me, create=True)
            name = attr.name
            if channels:
                write_channels(me, attr, rgb, channels, mask)
            if settings.paint_a:
                zmin = float(md.co[tree.chain >= 0, 2].min())
                try:
                    ao = bake_ao.ambient_occlusion(context, ob, md, tree.height,
                                                   settings.ao_distance, tree, face_role,
                                                   leaves=settings.ao_on_leaves)
                except RuntimeError as ex:
                    # R G B are written already: finish, so the change stays one undo step
                    ao_error = str(ex)
                else:
                    alpha = ao * bake_ao.ground_gradient(md, settings.ground_height, zmin, tree.height)
                    if not settings.ao_on_leaves:
                        alpha[face_role[md.loop_poly] == analysis.LEAF] = 1.0
                    # the bake added and removed an attribute: look ours up again
                    write_channels(me, me.color_attributes[name], alpha, ['A'], mask)
                    channels = channels + ['A']
            set_active(me, name)
        show_colors(context)
        preview(context)
        info = analysis.summary(tree)
        self.report({'INFO'}, iface_("Painted {:s}: {:d} branches ({:d} limbs), {:d} leaves, {:.2f} s").format(
            "".join(channels), info["chains"], info["limbs"], info["leaves"],
            time.perf_counter() - t0))
        if ao_error is not None:
            self.report({'WARNING'}, iface_("AO bake failed: {:s}").format(ao_error))
        return {'FINISHED'}


class TREEWIND_OT_show_structure(bpy.types.Operator):
    bl_idname = "tree_wind.show_structure"
    bl_label = "Show Branches"
    bl_description = ("Paint each found branch and the leaves hanging on it in its own colour "
                      "into a separate attribute, to check how the tree was understood")
    bl_options = {'REGISTER', 'UNDO'}

    poll = TREEWIND_OT_auto_paint.poll

    def execute(self, context):
        ob = context.active_object
        settings = context.scene.tree_wind
        with ObjectMode(ob):
            me = ob.data
            md = analysis.MeshData(me)
            try:
                tree, face_role, _roles = tree_for(ob, md, settings)
            except analysis.TreeError as ex:
                self.report({'ERROR'}, iface_(str(ex)))
                return {'CANCELLED'}
            nv = md.nv
            chain = tree.chain.copy()
            leaves = np.where(tree.leaf_island >= 0)[0]
            leaf_chain = np.full(nv, -1, np.int64)
            leaf_chain[leaves] = tree.chain[tree.leaf_host[tree.leaf_island[leaves]]]
            loop_role = face_role[md.loop_poly]
            lc = np.where(loop_role == analysis.LEAF, leaf_chain[md.loop_vert], chain[md.loop_vert])
            rng = np.random.default_rng(7)
            pal = rng.uniform(0.15, 1.0, (max(len(tree.tip_d), 1), 3))
            pal[tree.root] = (0.35, 0.2, 0.1)
            rgba = np.ones((md.nl, 4), np.float32)
            ok = lc >= 0
            rgba[ok, :3] = pal[lc[ok]]
            rgba[~ok, :3] = 0.0
            remember_wind_attribute(me)  # before the helper turns active
            attrs = me.color_attributes
            attr = attrs.get(BRANCHES_ATTR) or attrs.new(BRANCHES_ATTR, 'BYTE_COLOR', 'CORNER')
            attr.data.foreach_set("color_srgb", rgba.ravel())
            me.update()
            set_active(me, BRANCHES_ATTR)
        show_colors(context)
        info = analysis.summary(tree)
        self.report({'INFO'}, iface_("{:d} branches ({:d} limbs, {:d} levels), {:d} leaves; "
                              "shown in attribute TWP_Branches").format(
                                  info["chains"], info["limbs"], info["levels"], info["leaves"]))
        return {'FINISHED'}


CLASSES = (TREEWIND_OT_auto_paint, TREEWIND_OT_show_structure)
