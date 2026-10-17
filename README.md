# Tree Wind Paint

A Blender add-on that paints wind vertex colours on a tree mesh from the tree's own structure, then lets you correct them by hand, channel by channel or by UV.

It reads the mesh as a tree: it finds the trunk, the branches and what grows on what, hangs every leaf card on the branch it belongs to, and paints the channels a wind shader reads. Where a twig or a leaf meets its parent, its colour is exactly the parent's colour there, so the animation does not tear at the joints.

## Channels

| Channel | Meaning | How it is painted |
|---|---|---|
| **R** | Leaf flutter | 0 at the leaf's stem, rising to the tip. Leaf cards that share UVs get the same values. |
| **G** | Phase (time offset) | One value per branch, so a branch moves as a whole. Twigs and leaves take their branch's value. |
| **B** | Branch bend | 0 on the trunk, growing along each limb to its tips. Twigs and leaves continue the value of the point they grow from. |
| **A** | Ambient occlusion | Baked with Cycles, darker towards the ground. Optional. |

The trunk itself stays at B = 0: the wind shader is expected to sway the trunk on its own (by height). This is the convention of the UNIGINE vegetation shaders and is close to the CryEngine / SpeedTree layout.

## Requirements

- Blender 4.2 or newer (tested on 4.2, 4.5, 5.0 and 5.2)
- Cycles turned on, for the AO channel

## Installation

1. Download the `.zip` from the releases (or build it, see below).
2. In Blender: **Edit > Preferences > Get Extensions**, menu **⌄ > Install from Disk…**, pick the zip.

The panels are in the 3D View sidebar (**N**), tab **Tree Wind**. The tab name can be changed in the add-on's preferences.

## Usage

### Auto Paint

1. Select the tree mesh.
2. Check the material roles in the panel. Each material is **Bark**, **Leaves**, **Bare Branches** (dead or leafless wood, nothing hangs on it and it does not bend), **Skip** or **Auto**. Auto guesses by the material name (leaf, needle, bark, trunk, dead, dry…), otherwise by shape, and shows its guess under the drop-down.
3. Pick the channels to paint with the **R G B A** toggles.
4. Press **Auto Paint**.

The toggles also choose what the viewport shows: a single channel is shown as grey, several channels in colour. This works in Object Mode only. Turn all of R, G and B back on before exporting, otherwise a helper attribute stays on the mesh.

**Show Branches** paints every branch found in its own colour, to check how the tree was understood. **Show Wind Colors** goes back to the wind colours and removes the helper attributes.

### Settings

- **Bend Curve**: how steeply B grows along a limb.
- **Leafless Branches Don't Bend**: a branch with no leaves on it keeps the B of the point it grows from.
- **Flutter Curve**: how R grows from a leaf's stem to its tip.
- **Phase Seed**: reshuffles the G values.
- **AO Range**, **Ground Gradient**, **AO on Leaves**: the alpha channel.

**Tree Structure** (fork ratio, fork angle, minimal branch length) controls where the trunk splits into limbs. The defaults work for most trees.

### Manual Paint by Channel

Press a channel button to paint that channel alone. It is copied as grey into a temporary attribute, and every Vertex Paint brush and tool works on it. **Apply** writes it back into its channel, **Cancel** drops the changes.

While a channel is being painted:

- the two brush values, with **X** to swap them and **Ctrl+X** to fill;
- **Blend**: Replace, Add or Multiply, shared with the brush;
- **Linear** gradient: drag along a branch. The ends stick to the surface, and only a cylinder around the line is painted (mouse wheel while dragging sets its radius);
- **Radial** gradient: a circle on the screen or a sphere in 3D;
- **Randomize Parts**: one random value per loose part of the mesh;
- **Levels**: input black and white points, gamma, output range.

Selection masking (faces or vertices) limits all of them.

### Paint by UV

Leaf cards are usually copies of a few card types that share their UVs.

- **Copy to Same UV**: paint one leaf, select it (Edit Mode, or Vertex Paint with face masking) and copy its colour to every copy of the same card.
- In the **UV Editor** sidebar, a linear or radial gradient dragged across a card in UV space paints that card on every leaf that shares it. **X** swaps the values, **Ctrl+X** fills the shown faces.

## Notes

- AO is baked with Cycles. Other objects are hidden while it bakes, and the scene settings are restored afterwards.
- A branch modelled as a separate piece stuck into the trunk gets the trunk's AO where it goes in, so the joint shows no seam. Short stubs and knots take the trunk's AO all over.
- Helper attributes are named `TWP_*`. Remove them, or press Show Wind Colors, before exporting.
- The UI is in English and Russian.

## Building

```
blender --factory-startup --command extension build --source-dir tree_wind_paint --output-dir dist
blender --factory-startup --command extension validate dist/tree_wind_paint-<version>.zip
```

## License

GPL-2.0-or-later.

## Author

zloy_pingvin, Telegram: https://t.me/zloytux
