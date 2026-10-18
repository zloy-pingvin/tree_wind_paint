# SPDX-License-Identifier: GPL-3.0-or-later
"""
Russian translations of the add-on's labels, tooltips and reports.

Blender shows them when Preferences > Interface > Language is Russian and
Translation of Tooltips / Interface is enabled. Strings Blender itself
already translates ("Materials", "Channel", "From", "To", "Apply") are not
repeated here. Formatted labels and reports go through iface_().

Contexts: "*" is the default (property names, tooltips, labels), "Operator"
is used for operator labels (bl_label).
"""

import bpy

_OP = "Operator"


def iface_(text):
    return bpy.app.translations.pgettext_iface(text)


ru_RU = {
    # --- panels -------------------------------------------------------------
    ("*", "Tree Wind"): "Ветер дерева",
    ("*", "Tree Structure"): "Структура дерева",
    ("*", "Manual Paint by Channel"): "Ручное рисование по каналам",
    ("*", "Paint by UV"): "Красить по UV",
    ("*", "Select a tree mesh"): "Выберите меш дерева",
    ("*", "No materials: roles are guessed by shape"): "Нет материалов: роли угадываются по форме",
    ("*", "How to Use"): "Как пользоваться",
    ("*", "1. Edit Mode: select the leaves"): "1. Edit Mode: выдели листья",
    ("*", "   (the UV editor shows them)"): "   (их UV видны в редакторе)",
    ("*", "2. Pick the channel and values"): "2. Выбери канал и значения",
    (_OP, "Swap Values"): "Поменять значения",
    (_OP, "Randomize Parts"): "Рандом частей",
    ("*", "Give every loose part of the mesh its own random value between the brush "
          "value and the second value (only the selected parts with selection masking)"):
        "Каждой отдельной части меша — своё случайное значение между значением кисти и вторым "
        "значением (при маске выделения — только выделенным частям)",
    ("*", "Random values on {:d} parts"): "Случайные значения на {:d} частях",
    (_OP, "Levels"): "Уровни",
    ("*", "Levels of the channel being painted: input black and white points, gamma, "
          "output range (only the selection with selection masking)"):
        "Уровни канала, который красится: входные чёрная и белая точки, гамма, выходной "
        "диапазон (при маске выделения — только выделенное)",
    ("*", "Input Black"): "Вход: чёрная точка",
    ("*", "This value and lower become the output black"):
        "Это значение и ниже становятся выходным чёрным",
    ("*", "Input White"): "Вход: белая точка",
    ("*", "This value and higher become the output white"):
        "Это значение и выше становятся выходным белым",
    ("*", "Midtones: above 1 brighter, below 1 darker"): "Средние тона: больше 1 — светлее, меньше 1 — темнее",
    ("*", "Output Black"): "Выход: чёрный",
    ("*", "Value the input black becomes"): "Во что превращается входная чёрная точка",
    ("*", "Output White"): "Выход: белый",
    ("*", "Value the input white becomes"): "Во что превращается входная белая точка",
    ("*", "Input"): "Вход",
    ("*", "Output"): "Выход",
    (_OP, "Fill"): "Залить",
    ("*", "Fill the faces shown in the UV editor with the brush value, in the picked "
          "channel and blend (Ctrl+X)"):
        "Залить грани, видимые в UV-редакторе, значением кисти в выбранный канал и с выбранным "
        "наложением (Ctrl+X)",
    ("*", "Filled {:d} faces"): "Залито граней: {:d}",
    ("*", "Swap the brush value and the second value (X in Vertex Paint)"):
        "Поменять местами значение кисти и второе значение (X в Vertex Paint)",
    ("*", "Drag across a card in the UV editor: the channel goes from the brush value "
          "at the start to the second value at the end, on every copy of that card"):
        "Протяните через карточку в UV-редакторе: канал идёт от значения кисти в начале "
        "ко второму значению в конце, на всех копиях этой карточки",
    ("*", "Along the line"): "Вдоль линии",
    ("*", "Out from the start point, inside a circle"): "От начальной точки, внутри круга",
    ("*", "Start Value"): "Значение в начале",
    ("*", "End Value"): "Значение в конце",
    ("*", "Drag across a card: {:s} goes {:.2f} → {:.2f}. Esc / right click cancels"):
        "Протяните через карточку: {:s} от {:.2f} до {:.2f}. Esc / правый клик — отмена",
    ("*", "Start"): "Начало",
    ("*", "End"): "Конец",
    ("*", "3. Linear or Radial, then drag"): "3. «Линейный» или «Радиальный»,",
    ("*", "   across a card: stem to tip"): "   протяни: черенок → кончик",
    ("*", "Card Under Cursor: that card"): "«Карточка под курсором»: эта",
    ("*", "   and every copy of it"): "   карточка и все её копии",
    ("*", "All Faces: all selected faces"): "«Все грани»: все выделенные",
    ("*", "   at once (select a group)"): "   сразу (выдели группу)",
    ("*", "Esc / right click: cancel"): "Esc / правый клик — отмена",
    ("*", "1. Paint one copy"): "1. Покрась одну копию",
    ("*", "   (Manual Paint by Channel)"): "   («Ручное рисование»)",
    ("*", "2. Select it: Edit Mode, or"): "2. Выдели её: Edit Mode",
    ("*", "   Vertex Paint with face mask"): "   или Vertex Paint с маской граней",
    ("*", "3. Copy to Same UV: every"): "3. «Копировать на те же UV»:",
    ("*", "   face at the same UV points"): "   все грани в тех же UV-точках",
    ("*", "   gets its values"): "   получат её значения",
    ("*", "UV Gradient: UV Editor >"): "UV-градиент: UV-редактор >",
    ("*", "   Sidebar > Tree Wind"): "   боковая панель > Ветер дерева",
    ("*", "Attribute: "): "Атрибут: ",
    ("*", "WindColor (new)"): "WindColor (будет создан)",
    ("*", "Painting {:s} of {:s}"): "Красится {:s} из {:s}",

    # --- material roles -----------------------------------------------------
    ("*", "Wind Role"): "Роль для ветра",
    ("*", "What these faces are for wind painting"): "Чем считать эти грани при покраске под ветер",
    ("*", "Auto"): "Авто",
    ("*", "By the name (leaf, needle... are leaves; dead, dry... are bare "
          "branches; bark, trunk, branch... are bark), otherwise by shape: small "
          "loose islands are leaves"):
        "По имени (leaf, needle, лист... — листья; dead, dry, сух... — голые ветки; bark, "
        "trunk, branch, кора... — кора), иначе по форме: мелкие отдельные острова — листья",
    ("*", "Bark"): "Кора",
    ("*", "Bare Branches"): "Голые ветки",
    ("*", "by shape"): "по форме",
    ("*", "Alpha: ambient occlusion"): "Альфа: затенение (AO)",
    ("*", "Write the alpha channel: ambient occlusion baked with Cycles, darker toward "
          "the ground (the Crysis convention: A = AO)"):
        "Записывать альфа-канал: затенение (AO), запечённое в Cycles, темнее к земле "
        "(как в Crysis: A = AO)",
    ("*", "AO Range"): "Дистанция AO",
    ("*", "How far occluders count, as a share of tree height"):
        "На каком расстоянии учитываются затеняющие части, доля высоты дерева",
    ("*", "Ground Gradient"): "Градиент от земли",
    ("*", "Up to this share of tree height the alpha darkens toward the ground "
          "(0: no ground gradient)"):
        "До этой доли высоты дерева альфа темнеет к земле (0 — без градиента)",
    ("*", "AO bake failed: {:s}"): "Не удалось запечь AO: {:s}",
    ("*", "Preview: turn on RGB for export"): "Превью: для экспорта включи RGB",
    ("*", "Channel view: Object Mode only"): "Показ каналов: только Object Mode",
    (_OP, "Gradient"): "Градиент",
    ("*", "Drag in the viewport: the channel goes from the brush value at the start "
          "to the second value at the end"):
        "Протяните во вьюпорте: канал идёт от значения кисти в начале ко второму значению в конце",
    ("*", "Along a line, inside a cylinder around it"): "Вдоль линии, внутри цилиндра вокруг неё",
    ("*", "Out from a point, inside a circle or a sphere"): "От точки, внутри круга или сферы",
    ("*", "Linear"): "Линейный",
    ("*", "Radial"): "Радиальный",
    (_OP, "Linear"): "Линейный",
    (_OP, "Radial"): "Радиальный",
    ("*", "Blend"): "Наложение",
    ("*", "Replace"): "Замена",
    ("*", "The new value replaces the old one"): "Новое значение заменяет старое",
    ("*", "Add"): "Добавить",
    ("*", "The new value is added to the old one"): "Новое значение прибавляется к старому",
    ("*", "Multiply"): "Умножить",
    ("*", "The old value is multiplied by the new one"): "Старое значение умножается на новое",
    ("*", "How the brush and the gradients combine with the channel "
          "(the same as the brush blend in the header)"):
        "Как кисть и градиенты накладываются на канал (то же, что режим смешивания кисти в шапке)",
    ("*", "Shape"): "Форма",
    ("*", "Circle"): "Круг",
    ("*", "A circle on the screen: everything inside it as seen"):
        "Круг на экране: всё, что видно внутри него",
    ("*", "Sphere"): "Сфера",
    ("*", "A sphere in 3D around the point on the surface where the drag starts"):
        "Сфера в 3D вокруг точки на поверхности, где начат жест",
    ("*", "Cylinder Radius"): "Радиус цилиндра",
    ("*", "Radius of the cylinder the linear gradient paints in (mouse wheel while dragging)"):
        "Радиус цилиндра, внутри которого красит линейный градиент (колесо мыши во время жеста)",
    ("*", "Run it from the 3D viewport"): "Запускайте из 3D-вьюпорта",
    ("*", "Drag a line · wheel while dragging: cylinder radius · Esc / right click: cancel"):
        "Протяните линию · колесо во время жеста: радиус цилиндра · Esc / правый клик: отмена",
    ("*", "Drag from the centre · Esc / right click: cancel"):
        "Протяните от центра · Esc / правый клик: отмена",
    ("*", "Gradient on {:d} vertices"): "Градиент на {:d} вершинах",
    ("*", "Sidebar Tab"): "Вкладка боковой панели",
    ("*", "Tab of the 3D View and UV editor sidebars the panels sit in"):
        "Вкладка боковых панелей 3D-вида и UV-редактора, где стоят панели аддона",
    ("*", "Hotkeys: UV Editor"): "Горячие клавиши: UV-редактор",
    ("*", "Hotkeys are not available in this session"): "Горячие клавиши в этом сеансе недоступны",
    ("*", "In Vertex Paint, X and Ctrl+X are Blender's own keys"):
        "В Vertex Paint X и Ctrl+X — собственные клавиши Blender",
    ("*", "Notes"): "Заметки",
    ("*", "Remove the Wind Preview modifier before export"):
        "Перед экспортом убери модификатор предпросмотра ветра",
    ("*", "Wind Preview"): "Предпросмотр ветра",
    (_OP, "Wind Preview"): "Предпросмотр ветра",
    (_OP, "Remove Preview"): "Убрать предпросмотр",
    ("*", "Play the tree's wind in the viewport as UNIGINE moves it, from its wind "
          "colours. A click outside the preview window stops it"):
        "Проиграть ветер дерева во вьюпорте так, как его двигает UNIGINE, по цветам ветра. "
        "Клик вне окна предпросмотра его останавливает",
    ("*", "UNIGINE mesh_base formula"): "Формула UNIGINE mesh_base",
    ("*", "Click outside its window to stop"): "Клик вне его окна — стоп",
    ("*", "Click outside this window to stop"): "Клик вне этого окна — стоп",
    ("*", "Stop"): "Стоп",
    ("*", "Wind"): "Ветер",
    ("*", "The AO bake uses Cycles; other objects are hidden while it bakes"):
        "AO запекается через Cycles; остальные объекты на это время скрываются",
    ("*", "TWP_* colour attributes are helpers: turn on R G B (or Show Wind Colors) before export"):
        "Атрибуты TWP_* — вспомогательные: перед экспортом включи R G B (или «Показать цвета ветра»)",
    ("*", "AO on Leaves"): "AO на листьях",
    ("*", "Write the shading into leaves too; off: leaves get alpha 1 (no shading)"):
        "Записывать затенение и в листья; выключено — у листьев альфа 1 (без затенения)",
    ("*", "Brush Value"): "Значение кисти",
    ("*", "Value the brush paints into the channel (X swaps it with the second value)"):
        "Значение, которое кисть пишет в канал (X меняет его со вторым)",
    ("*", "Second Value"): "Второе значение",
    ("*", "The second brush value (X swaps the two)"): "Второе значение кисти (X меняет их местами)",
    ("*", "X: swap · Ctrl+X: fill"): "X — поменять · Ctrl+X — залить",
    (_OP, "Cancel"): "Отмена",
    ("*", "Dead or leafless branches: no leaf hangs on them and they do not bend"):
        "Сухие ветки и ветки без листьев: листья на них не вешаются, и они не гнутся",
    ("*", "Trunk and branches"): "Ствол и ветки",
    ("*", "Leaves"): "Листья",
    ("*", "Leaf cards"): "Карточки листьев",
    ("*", "Skip"): "Пропустить",
    ("*", "Leave these faces unpainted"): "Не красить эти грани",

    # --- auto paint settings ------------------------------------------------
    ("*", "Write and show the red channel (leaf flutter)"): "Записывать и показывать красный канал (дрожание листьев)",
    ("*", "Write and show the green channel (time offset)"): "Записывать и показывать зелёный канал (сдвиг по времени)",
    ("*", "Write and show the blue channel (branch bend)"): "Записывать и показывать синий канал (изгиб веток)",
    ("*", "Bend Curve"): "Кривая изгиба",
    ("*", "Steepness of the blue gradient: 1 is linear, higher keeps the bend near the tips"):
        "Крутизна синего градиента: 1 — линейно, больше — изгиб сосредоточен у кончиков",
    ("*", "Leafless Branches Don't Bend"): "Голые ветки не гнутся",
    ("*", "Branches with no leaves on them or on anything they carry get no blue "
          "gradient: they keep the blue of the point they grow from (0 on the trunk)"):
        "Ветки без листьев (ни на них, ни на том, что на них растёт) не получают синего "
        "градиента: у них синий точки, откуда они растут (на стволе — 0)",
    ("*", "Phase Seed"): "Сид фазы",
    ("*", "Shuffles the green values"): "Перемешивает значения зелёного",
    ("*", "Flutter Curve"): "Кривая дрожания",
    ("*", "Steepness of the red gradient from the leaf stem to its tip"):
        "Крутизна красного градиента от черенка листа к кончику",
    ("*", "Fork Ratio"): "Порог развилки",
    ("*", "The trunk ends at the first branch at least this long compared to "
          "the rest of the trunk; 0 keeps the whole longest path as trunk"):
        "Ствол заканчивается на первой ветке, длина которой не меньше этой доли от "
        "оставшегося ствола; 0 — стволом считается весь самый длинный путь",
    ("*", "Fork Max Angle"): "Макс. угол развилки",
    ("*", "Only a branch growing upward within this angle of vertical can split "
          "the trunk; a long branch going sideways (pines, firs) is just a branch"):
        "Разделить ствол может только ветка, растущая вверх не дальше этого угла от вертикали; "
        "длинная ветка вбок (сосна, ель) — просто ветка",
    ("*", "Min Branch"): "Мин. ветка",
    ("*", "Shorter tips (share of tree height) are bark bumps, not branches"):
        "Более короткие отростки (доля высоты дерева) — неровности коры, а не ветки",
    ("*", "Copy the red channel"): "Копировать красный канал",
    ("*", "Copy the green channel"): "Копировать зелёный канал",
    ("*", "Copy the blue channel"): "Копировать синий канал",
    ("*", "Leaf flutter"): "Дрожание листьев",
    ("*", "Branch bend"): "Изгиб веток",
    ("*", "Curve"): "Кривая",
    ("*", "1 is linear, higher keeps the gradient low until near its end"):
        "1 — линейно, больше — градиент остаётся низким почти до конца",
    ("*", "Scope"): "Область",
    ("*", "Card Under Cursor"): "Карточка под курсором",
    ("*", "Only the UV island the drag starts on, on every leaf that shares its UVs"):
        "Только UV-остров, с которого начат жест, на всех листьях с теми же UV",
    ("*", "All Faces"): "Все грани",
    ("*", "Every face shown in the UV editor"): "Все грани, видимые в UV-редакторе",

    # --- operators ----------------------------------------------------------
    (_OP, "Auto Paint"): "Автопокраска",
    ("*", "Paint wind colours from the tree's structure: B bends branches toward "
          "their tips, G gives each big branch its own time offset, R makes leaf "
          "tips flutter"):
        "Покрасить цвета ветра по структуре дерева: B изгибает ветки к кончикам, "
        "G даёт каждой крупной ветке свой сдвиг по времени, R заставляет кончики листьев дрожать",
    (_OP, "Show Branches"): "Показать ветки",
    ("*", "Paint each found branch and the leaves hanging on it in its own colour "
          "into a separate attribute, to check how the tree was understood"):
        "Покрасить каждую найденную ветку и её листья своим цветом в отдельный атрибут, "
        "чтобы проверить, как распознано дерево",
    (_OP, "Paint Channel"): "Красить канал",
    ("*", "Paint this channel alone as greyscale in Vertex Paint; "
          "Apply writes it back without touching the other channels"):
        "Красить только этот канал в оттенках серого в Vertex Paint; "
        "«Применить канал» запишет его обратно, не трогая другие каналы",
    (_OP, "Apply Channel"): "Применить канал",
    ("*", "Write the painted grey back into its channel and remove the temporary attribute"):
        "Записать покрашенный серый обратно в канал и удалить временный атрибут",
    ("*", "Drop the painted grey; the channel keeps its old values"):
        "Отбросить покрашенный серый; канал сохранит старые значения",
    (_OP, "Show Wind Colors"): "Показать цвета ветра",
    ("*", "Show the wind colours themselves in the viewport and remove the helper "
          "attributes of Show Branches and of the channel view, ready for export"):
        "Показать во вьюпорте сами цвета ветра и удалить вспомогательные атрибуты "
        "«Показать ветки» и показа каналов — готово к экспорту",
    ("*", "Cycles is turned off in Preferences > Add-ons"):
        "Cycles выключен в Настройки > Дополнения",
    (_OP, "Copy to Same UV"): "Копировать на те же UV",
    ("*", "Copy the colour of the selected faces to every face of the same material "
          "whose corners sit at the same UV points, i.e. to all copies of the same "
          "piece (a leaf card, a twig...). Select the painted copy in Edit Mode or "
          "with face selection masking"):
        "Скопировать цвет выделенных граней на все грани того же материала, углы которых "
        "лежат в тех же UV-точках, то есть на все копии того же куска (карточки листа, "
        "веточки...). Выделите покрашенную копию в Edit Mode или маской выделения граней",
    (_OP, "UV Gradient"): "UV-градиент",
    ("*", "Red: leaf flutter"): "Красный: дрожание листьев",
    ("*", "Green: time offset"): "Зелёный: сдвиг по времени",
    ("*", "Blue: branch bend"): "Синий: изгиб веток",

    # --- reports ------------------------------------------------------------
    ("*", "No channels selected"): "Не выбран ни один канал",
    ("*", "Apply or cancel the channel being painted first"):
        "Сначала примените или отмените покраску канала",
    ("*", "Painted {:s}: {:d} branches ({:d} limbs), {:d} leaves, {:.2f} s"):
        "Покрашено {:s}: веток {:d} (сучьев {:d}), листьев {:d}, {:.2f} с",
    ("*", "{:d} branches ({:d} limbs, {:d} levels), {:d} leaves; shown in attribute TWP_Branches"):
        "Веток {:d} (сучьев {:d}, уровней {:d}), листьев {:d}; показано в атрибуте TWP_Branches",
    ("*", "No bark faces: set the bark material role"):
        "Нет граней коры: укажите роль материала коры",
    ("*", "Attribute \"{:s}\" is gone: give the wind colours that name again, or Cancel"):
        "Атрибут «{:s}» пропал: верни цветам ветра это имя или нажми «Отмена»",
    ("*", "No wind colours yet: run Auto Paint"): "Цветов ветра ещё нет: запустите автопокраску",
    ("*", "Select the painted leaf: Edit Mode, or Vertex Paint with face selection masking"):
        "Выделите покрашенный лист: Edit Mode или Vertex Paint с маской выделения граней",
    ("*", "The mesh has no UV map"): "У меша нет UV-карты",
    ("*", "Nothing selected: select the painted leaf"): "Ничего не выделено: выделите покрашенный лист",
    ("*", "No other faces share these UV points"): "Других граней в этих UV-точках нет",
    ("*", "Copied {:s} to {:d} faces"): "{:s} скопировано на {:d} граней",
    ("*", "No faces in the UV editor: select leaves in Edit Mode"):
        "В UV-редакторе нет граней: выделите листья в Edit Mode",
    ("*", "Run it from the UV editor"): "Запускайте из UV-редактора",
    ("*", "Drag a line, not a click"): "Нужно протянуть линию, а не кликнуть",
    ("*", "Gradient on {:d} faces"): "Градиент на {:d} гранях",
}

translations_dict = {"ru_RU": ru_RU}


def register():
    bpy.app.translations.register(__package__, translations_dict)


def unregister():
    bpy.app.translations.unregister(__package__)
