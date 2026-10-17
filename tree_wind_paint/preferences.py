# SPDX-License-Identifier: GPL-3.0-or-later
"""Add-on preferences: version and links, the sidebar tab, the UV editor hotkeys."""

import bpy
import rna_keymap_ui
from bpy.props import StringProperty

from . import ui

URL_GITHUB = "https://github.com/zloy-pingvin/tree_wind_paint"
URL_TELEGRAM = "https://t.me/zloytux"

# operators with a UV editor hotkey (registered in __init__)
HOTKEY_OPERATORS = ("tree_wind.swap_values", "tree_wind.uv_fill")


def _category_changed(self, _context):
    ui.set_category(self.category)


class TREEWIND_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    category: StringProperty(
        name="Sidebar Tab", default=ui.DEFAULT_CATEGORY, update=_category_changed,
        description="Tab of the 3D View and UV editor sidebars the panels sit in")

    def draw(self, context):
        layout = self.layout

        row = layout.row()
        row.label(text="Tree Wind Paint " + ui.VERSION, icon='OUTLINER_OB_FORCE_FIELD',
                  translate=False)
        links = layout.row(align=True)
        links.scale_y = 1.2
        links.operator("wm.url_open", text="GitHub", icon='URL').url = URL_GITHUB
        links.operator("wm.url_open", text="Telegram", icon='COMMUNITY').url = URL_TELEGRAM

        layout.separator()
        box = layout.box()
        box.label(text="Interface", icon='WINDOW')
        box.prop(self, "category")

        layout.separator()
        box = layout.box()
        box.label(text="Hotkeys: UV Editor", icon='KEYINGSET')
        kc = context.window_manager.keyconfigs.user
        km = kc.keymaps.get("UV Editor") if kc else None
        shown = False
        if km is not None:
            for kmi in km.keymap_items:
                if kmi.idname in HOTKEY_OPERATORS:
                    rna_keymap_ui.draw_kmi([], kc, km, kmi, box, 0)
                    shown = True
        if not shown:
            box.label(text="Hotkeys are not available in this session", icon='INFO')
        hint = box.row()
        hint.active = False
        hint.label(text="In Vertex Paint, X and Ctrl+X are Blender's own keys", icon='INFO')

        layout.separator()
        box = layout.box()
        box.label(text="Notes", icon='INFO')
        col = box.column(align=True)
        col.active = False
        col.label(text="The AO bake uses Cycles; other objects are hidden while it bakes")
        col.label(text="TWP_* colour attributes are helpers: turn on R G B (or Show Wind "
                       "Colors) before export")


CLASSES = (TREEWIND_AddonPreferences,)


def apply_saved_category():
    """Use the tab saved in the preferences (they exist only once enabled)."""
    addon = bpy.context.preferences.addons.get(__package__)
    if addon is not None and addon.preferences is not None:
        ui.set_category(addon.preferences.category)
