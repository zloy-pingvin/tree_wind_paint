# SPDX-License-Identifier: GPL-3.0-or-later
"""
Tree Wind Paint: vertex colours for engine wind animation of trees.

Channels: B bends branches (0 at a branch base, 1 at its tip), G is a time
offset shared by a big branch and everything on it, R makes leaves flutter
(0 at the stem, 1 at the tip). Auto Paint computes them from the mesh;
Manual Paint by Channel and the UV tools correct them by hand.

Metadata lives in blender_manifest.toml; extensions carry no bl_info.
"""

import bpy

from . import (ops_autopaint, ops_channel, ops_gradient, ops_uv, preferences, props, translations,
               ui, wind_preview)

CLASSES = (props.CLASSES + ops_autopaint.CLASSES + ops_channel.CLASSES + ops_gradient.CLASSES
           + ops_uv.CLASSES + wind_preview.CLASSES + ui.CLASSES + preferences.CLASSES)


# X swaps the two brush values and Ctrl+X fills, as in Vertex Paint. The UV
# editor has nothing on these keys (only Texture Paint uses them).
_keymaps = []


def _register_keymaps():
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc is None:  # background mode
        return
    km = kc.keymaps.new(name="UV Editor", space_type='EMPTY')
    _keymaps.append((km, km.keymap_items.new("tree_wind.swap_values", 'X', 'PRESS')))
    _keymaps.append((km, km.keymap_items.new("tree_wind.uv_fill", 'X', 'PRESS', ctrl=True)))


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    props.register()
    translations.register()
    _register_keymaps()
    preferences.apply_saved_category()


def unregister():
    # running gradient tools: their drawing would outlive the add-on
    ops_gradient.stop_all()
    ops_uv.stop_all()
    try:
        wind_preview.remove_all()
    except AttributeError:
        pass   # bpy.data not reachable in this context: nothing to clean
    for km, kmi in _keymaps:
        km.keymap_items.remove(kmi)
    _keymaps.clear()
    translations.unregister()
    props.unregister()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
