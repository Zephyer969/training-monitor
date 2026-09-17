# Pixel alchemist assets

## Current approved identity (supersedes the historical notes below)

Use `mentor-photo-redesign-v3.png`. The desktop application bundles a byte-identical
copy at `server/alchemy_assets/mentor-approved.png`. Its source prompt is saved in
`mentor-photo-redesign-v3.prompt.txt`. The face is never regenerated or deformed;
the runtime applies only a border-connected background transparency mask and nearest-neighbor display scaling.
The runtime now includes 16 arm/tool animation frames while keeping the identity anchor unchanged.
The bundled source remains unchanged.
`server/alchemy_assets/alchemy-rooms.png` contains a measured 2x2 atlas: empty mentor room,
purple active apprentice, blue saving apprentice, and green resting apprentice.
The native dashboard composites the approved mentor over the empty room.

`server/alchemy_assets/apprentices-v1-unique.png` is the GPU apprentice atlas:
16 transparent cells arranged as 8 identity pairs. Each pair has two nearby
animation frames, while the eight pairs use different outfits, tools and
alchemy materials. The desktop dashboard assigns them by GPU card, offsets
their animation phases so they do not move in sync, and mirrors/color-varies
overflow cards after the first eight GPUs.

`mentor-state-sprite-sheet.png` was rejected for identity drift and must not be used
at runtime. `mentor-alchemist.png` is also historical. The metadata marks these
previous frames and phase mappings as legacy.

The current runtime action set is `mentor-actions-v7-coherent-no-fan.png`, a 4x4
portrait atlas with a 12-frame runtime sequence: four stir frames, four potion
frames, and four herb frames. Two visibly smaller generated transition cells are
skipped, and the fourth sample action is not reachable. Each displayed cell uses
the same 384x512 canvas and bottom baseline; the runtime holds each frame for
four update ticks so the actions do not rush. The fan action is retired and is
not loaded by the desktop runtime. The older v5 and v6 sheets remain only as
historical source material.

The main training loop uses the supplemental `mentor-stir-main-v1.png` strip:
four equal left-center-right-center stirring frames with a common artwork box
and bottom baseline. It is normalized to a common visible height at runtime and takes priority over the
older atlas while the mentor is in `training` or `preparing`.

## Historical notes (obsolete)

`mentor-alchemist.png` is the current main identity anchor regenerated directly
from the mentor reference photo. It is the preferred source for future action
frames and keeps the mentor's face separate from the GPU/task layout.

`mentor-state-sprite-sheet.png` is the current 2x2 state/action sheet generated
from the approved identity anchor. Its four frames cover stirring, adding
herbs, reading the validation scroll, and a mildly strict stopped state. The
raw generated source is preserved as
`mentor-state-sprite-sheet-raw.png`.

`mentor-actions-sprite-sheet.png` is a legacy 4x2 local-corrected action-sheet
prototype kept for comparison and future expansion.
The previous round is preserved as
`mentor-actions-sprite-sheet-original-draft.png`. The local correction removes
the baked checkerboard, narrows each head with nearest-neighbour scaling, and
adds focused/stopped facial accents to the final frames. The metadata still
marks this legacy asset as a prototype.

`mentor-actions.json` defines the stable frame contract used by the future GUI.
The mentor is one permanent main character. GPU count and model run count must
never duplicate him; they only change the number of surrounding task slots.

The terminal client includes a small text fallback so the monitor remains usable
without loading PNG files. The future GUI should use `mentor-alchemist.png` as
the identity source and `mentor-state-sprite-sheet.png` as the current phase
animation contract. GPU count and model run count must never duplicate the
mentor; they only change the surrounding task stations.

To repeat the deterministic correction locally:

```bash
python server/pixel_assets.py \
  --input assets/pixel/mentor-actions-sprite-sheet-original-draft.png \
  --output assets/pixel/mentor-actions-sprite-sheet.png
```

To clean a newly generated identity anchor without changing the character:

```bash
python server/pixel_assets.py --kind anchor \
  --input assets/pixel/mentor-main-anchor.png \
  --output assets/pixel/mentor-alchemist.png
```

To clean a newly generated state sheet while preserving its layout:

```bash
python server/pixel_assets.py --kind state-sheet \
  --input assets/pixel/mentor-state-sprite-sheet-raw.png \
  --output assets/pixel/mentor-state-sprite-sheet.png
```
