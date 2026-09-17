# Pixel dashboard visual QA

## 2026-09-16 one-click / fixed metrics / action-frame revision

final result: passed

Source visual remains the user's reference below. Latest implementation:
`ui-preview/pixel-dashboard-live.png`, 1496x1106 native capture including OS title/toolbar;
logical canvas width 1488, source 1488x1058. Native Tk, CSS/DPR not applicable.
Both images opened in the same comparison input. Live state intentionally differs:
one running upernet model, eight physical GPUs rather than the reference's four mock runs.

Findings and fixes:
- P1 fixed: right chart alternated between Loss and mIoU. Both charts now have fixed named
  series, no cross-metric fallback, and validation epoch annotation. Screenshot shows
  training epoch 139 with validation epoch 138, Loss 0.2384 and mIoU 79.86 concurrently.
- P2 fixed: forced empty table rows consumed space. Table now fits actual task count.
- P2 fixed: duplicated GPU hardware section and oversized cards hid GPU 4–7.
  Telemetry merged into compact station cards; recaptured view includes all eight cards.
- P2 fixed: static mentor. Eight transparent generated action frames now change arms,
  rod, herbs and potion. Aspect ratio preserved, training cycles stirring and pouring.
  Native smoke confirms multiple distinct frames rendered, plus stopped/offline states.

Typography: existing bitmap headings and Consolas values retained. Spacing: two charts
and mentor room retain the reference's approximate 2:1 split, condensed GPU grid below.
Colors: existing navy/cyan/yellow/green tokens retained. Images: source-derived mentor,
transparent alpha and nearest-neighbor sampling; body not stretched. Copy: fixed Loss/mIoU,
TOTAL separated from within-epoch step progress. Source and generated mentor likeness
are visually close; generated faces are not claimed pixel-identical.
Focused inspection covered chart titles, validation epoch, face, and all eight telemetry rows;
these were legible in the full-resolution comparison, so separate crops were unnecessary.

Verification: 40 pytest tests passed. Native smoke verified selection, 0/1/8/32 GPU layouts,
offline/stopped handling and action frame cycling. Actual start-monitor.cmd launched the live
window, automatically found the training log and all 8 GPUs, and loaded training history.
Previous API, watcher and tunnel were stopped before final capture; new direct SSH mode
continued updating independently. No new remote installation or remote files required.
Large-cauldron action revision: V5 replaces the small handheld bowl with a waist-high floor cauldron;
frames visibly show staff stirring, raising/pouring potion and adding herbs. Transparent extraction
was checked at all four corners and the runtime uses aspect-preserving nearest-neighbor fitting.
Remaining scope: auto-discovery targets supported OpenMMLab training entrypoints/logs;
custom training frameworks need an adapter or explicit compatible log root.

## Earlier review (historical, superseded where changed above)

final result: passed

Source: C:/Users/87836/AppData/Local/Temp/codex-clipboard-36986718-4b55-4042-bbe4-0325bfa13d2a.png

Implementation: ui-preview/pixel-dashboard-qa.png (native Tk window captured with Win32 PrintWindow).
Source dimensions: 1488 x 1058. Implementation capture: native window including title bar and demo toolbar;
client geometry 1488 x 1058, logical dashboard 1488 x 1070, scaled uniformly to client canvas.
Comparison excludes Windows title bar / demo controls. CSS/deviceScaleFactor: not applicable (native Tk).
State: four GPUs, first model selected; training/validating/saving/idle. Demo clearly labeled.

## Comparison history

1. Full-view source and native capture opened together. P2: assistant scenes compressed vertically,
   bottom telemetry partially below viewport, headings used a smooth font.
2. Scene crops now focus on the lower 64% containing the complete apprentice and cauldron;
   scale is uniform, dashboard fits height, and Windows Terminal bitmap headings are used.
3. Re-captured and opened with source in the same comparison input. P2: bitmap font jumped
   to a smaller strike under fractional scaling. Quantized heading size to 8-pixel increments.
4. Final capture re-opened with source: complete telemetry visible, stable title/numeric typography,
   task table, paired charts, mentor room, four apprentice cards and four hardware cards present.

## Required surfaces

- Typography: bitmap heading/numeric hierarchy, Consolas data labels. Minor glyph/weight differences
  from the reference remain P3. Chinese falls back to the installed system font.
- Spacing/layout: same major four bands and roughly 2:1 charts/room split. Four assistants rather
  than reference's three plus summary is intentional: user requested one assistant per GPU.
- Colors: near-black navy, thin cyan outlines, yellow training/purple validation/blue saving,
  green metrics and gray idle states retained.
- Imagery: generated dark pixel room/apprentice atlas, nearest-neighbor display. Approved mentor
  bitmap composited with a background mask, never regenerated. Different mentor body proportions
  are intentional because the user explicitly locked this character. No icon stand-ins used.
- Copy: actual task IDs, metrics, epochs, hardware. Demo label is persistent. Live mode uses API
  data and displays missing values; no fabricated live histories. Reference clock/data are examples.

Focused review: the same full-resolution capture was inspected at title/numeric typography,
mentor face/background edges, apprentice silhouettes and bottom telemetry; these regions were
readable in the full-resolution comparison, so separate crop files were not necessary.

## Functional evidence and limits

- 35 automated tests passed, including API step/loss propagation, shared GPU and DDP mapping.
- Native smoke exercised selection and 0/1/8/32 GPU layouts, stopped and offline states.
- Wheel contains pixel_window.py, pixel_assets.py and both runtime images.
- No live remote GPU server connected for this review; screenshot data is demo data.
- Remote smoke after this review connected through a temporary SSH tunnel to a private training server:
  `pixel-dashboard-live.png` showed 8 real RTX 4090 D devices, five API tasks, and the DDP task on GPUs 4/5.
- Remote smoke used a temporary `/tmp/training-monitor-proxy-test-20260916-1200` directory and state file;
  the API process, tunnel, local window, and temporary directory were stopped/removed after capture.
- No browser console: native Tk. Native smoke completed without callback exceptions.
- Character animation is currently slight scene motion and state swaps, not articulated hands.

## P3 follow-up

Tune chart stroke weight and small-font density; add face-preserving articulated animation.
Pixel fonts on non-Windows platforms may need a bundled replacement.
