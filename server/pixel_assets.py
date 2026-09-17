"""Fast, local pixel-asset cleanup for the mentor sprite assets.

This optional utility is deliberately deterministic: it removes a baked
checkerboard background, optionally narrows the mentor head in each grid cell,
and can add subtle focused/stopped expression accents to the legacy sheet. It
does not call an image-generation service and never overwrites the input file.
"""

from __future__ import annotations

import argparse
from collections import deque
from pathlib import Path
from typing import Iterable, List, Tuple

from PIL import Image, ImageDraw


RGB = Tuple[int, int, int]
Box = Tuple[int, int, int, int]


# Relative to a 384x512 cell. The boxes cover hair, glasses, ears and face,
# while stopping before the nearby cauldron, scroll, crystal or control panel.
HEAD_BOXES: List[Box] = [
    (72, 20, 306, 226),
    (62, 20, 300, 224),
    (62, 18, 300, 222),
    (58, 20, 302, 228),
    (62, 18, 306, 230),
    (58, 24, 298, 230),
    (62, 20, 302, 226),
    (62, 18, 306, 226),
]
CELL_WIDTH = 384
CELL_HEIGHT = 512


def background_candidate(pixel: RGB) -> bool:
    low, high = min(pixel), max(pixel)
    return low >= 185 and high - low <= 24


def border_background_mask(image: Image.Image) -> bytearray:
    """Find checkerboard pixels connected to the image border."""

    rgb = image.convert("RGB")
    width, height = rgb.size
    pixels = rgb.load()
    visited = bytearray(width * height)
    queue = deque()

    def enqueue(x: int, y: int) -> None:
        index = y * width + x
        if visited[index] or not background_candidate(pixels[x, y]):
            return
        visited[index] = 1
        queue.append((x, y))

    for x in range(width):
        enqueue(x, 0)
        enqueue(x, height - 1)
    for y in range(height):
        enqueue(0, y)
        enqueue(width - 1, y)

    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < width and 0 <= ny < height:
                enqueue(nx, ny)
    return visited


def remove_checkerboard(image: Image.Image) -> Image.Image:
    rgba = image.convert("RGBA")
    mask = border_background_mask(image)
    alpha = rgba.getchannel("A")
    alpha_pixels = alpha.load()
    width, height = rgba.size
    for index, connected in enumerate(mask):
        if connected:
            alpha_pixels[index % width, index // width] = 0
    rgba.putalpha(alpha)
    return rgba


def normalize_transparent_rgb(image: Image.Image) -> Image.Image:
    """Use a stable RGB value for fully transparent pixels."""

    rgba = image.convert("RGBA")
    pixels = rgba.load()
    for y in range(rgba.height):
        for x in range(rgba.width):
            r, g, b, alpha = pixels[x, y]
            if alpha == 0:
                pixels[x, y] = (255, 255, 255, 0)
    return rgba


def absolute_box(cell_index: int, box: Box) -> Box:
    column = cell_index % 4
    row = cell_index // 4
    x1, y1, x2, y2 = box
    return (
        column * CELL_WIDTH + x1,
        row * CELL_HEIGHT + y1,
        column * CELL_WIDTH + x2,
        row * CELL_HEIGHT + y2,
    )


def narrow_head(image: Image.Image, box: Box, factor: float = 0.82) -> None:
    x1, y1, x2, y2 = box
    crop = image.crop(box)
    new_width = max(1, int(crop.width * factor))
    crop = crop.resize((new_width, crop.height), Image.Resampling.NEAREST)
    transparent = Image.new("RGBA", (x2 - x1, y2 - y1), (0, 0, 0, 0))
    image.paste(transparent, box[:2])
    target_x = x1 + (x2 - x1 - new_width) // 2
    image.alpha_composite(crop, (target_x, y1))


def add_expression(image: Image.Image, box: Box, stopped: bool) -> None:
    """Add tiny pixel accents without changing the mentor's identity."""

    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1
    center = x1 + width // 2
    brow_y = y1 + int(height * 0.50)
    mouth_y = y1 + int(height * 0.73)
    ink = (43, 29, 30, 235)
    draw = ImageDraw.Draw(image)
    if stopped:
        draw.line((center - 31, brow_y + 2, center - 10, brow_y - 2), fill=ink, width=3)
        draw.line((center + 10, brow_y - 2, center + 31, brow_y + 2), fill=ink, width=3)
        draw.line((center - 12, mouth_y, center + 14, mouth_y), fill=ink, width=3)
    else:
        draw.line((center - 30, brow_y - 2, center - 10, brow_y), fill=ink, width=2)
        draw.line((center + 10, brow_y, center + 30, brow_y - 2), fill=ink, width=2)
        draw.line((center - 11, mouth_y, center + 13, mouth_y - 2), fill=ink, width=2)


def prepare_mentor_sheet(input_path: Path, output_path: Path) -> None:
    image = remove_checkerboard(Image.open(input_path))
    for index, relative_box in enumerate(HEAD_BOXES):
        box = absolute_box(index, relative_box)
        narrow_head(image, box)
        if index == 6:
            add_expression(image, box, stopped=False)
        elif index == 7:
            add_expression(image, box, stopped=True)
    image = normalize_transparent_rgb(image)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG", optimize=True)


def prepare_identity_anchor(input_path: Path, output_path: Path) -> None:
    """Clean a generated mentor image without changing its geometry or pixels."""

    image = normalize_transparent_rgb(remove_checkerboard(Image.open(input_path)))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG", optimize=True)


def prepare_state_sheet(input_path: Path, output_path: Path) -> None:
    """Clean the current 2x2 mentor state sheet without changing its frames."""

    prepare_identity_anchor(input_path, output_path)


def remove_small_top_components(image: Image.Image, max_y: int = 10, max_area: int = 800) -> Image.Image:
    """Remove tiny isolated generator/grid fragments above the main sprite."""

    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    pixels = alpha.load()
    width, height = rgba.size
    visited = bytearray(width * height)
    for start_y in range(height):
        for start_x in range(width):
            start = start_y * width + start_x
            if visited[start] or pixels[start_x, start_y] == 0:
                continue
            stack = [(start_x, start_y)]
            visited[start] = 1
            component = []
            top = start_y
            while stack:
                x, y = stack.pop()
                component.append((x, y))
                top = min(top, y)
                for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                    if 0 <= nx < width and 0 <= ny < height:
                        index = ny * width + nx
                        if not visited[index] and pixels[nx, ny] > 0:
                            visited[index] = 1
                            stack.append((nx, ny))
            if top <= max_y and len(component) <= max_area:
                for x, y in component:
                    pixels[x, y] = 0
    rgba.putalpha(alpha)
    return rgba


def prepare_coherent_action_sheet(input_path: Path, output_path: Path) -> None:
    """Clean and normalize a generated 4x4 action sheet to portrait cells.

    Image generators commonly return a wide canvas even when the requested
    grid is square.  The generated cells are trimmed to their opaque artwork,
    scaled into the established 384x512 mentor cell, and bottom-aligned so the
    runtime sees a stable baseline and a consistent character size.
    """

    source = remove_checkerboard(Image.open(input_path))
    columns, rows = 4, 4
    frame_width = source.width // columns
    frame_height = source.height // rows
    sheet = Image.new("RGBA", (columns * CELL_WIDTH, rows * CELL_HEIGHT), (0, 0, 0, 0))
    for index in range(columns * rows):
        column = index % columns
        row = index // columns
        cell = source.crop((
            column * frame_width,
            row * frame_height,
            (column + 1) * frame_width,
            (row + 1) * frame_height,
        ))
        # A few generated cells contain tiny dark grid fragments on their top
        # edge. They are not part of the mentor artwork and would otherwise be
        # included in the bounding box as floating dashes.
        cell_pixels = cell.load()
        for y in range(min(6, cell.height)):
            for x in range(cell.width):
                red, green, blue, alpha = cell_pixels[x, y]
                if alpha and max(red, green, blue) < 120:
                    cell_pixels[x, y] = (red, green, blue, 0)
        cell = remove_small_top_components(cell)
        bbox = cell.getchannel("A").getbbox()
        if bbox is None:
            continue
        padding = 4
        x1 = max(0, bbox[0] - padding)
        y1 = max(0, bbox[1] - padding)
        x2 = min(cell.width, bbox[2] + padding)
        y2 = min(cell.height, bbox[3] + padding)
        artwork = cell.crop((x1, y1, x2, y2))
        max_width = CELL_WIDTH - 24
        max_height = CELL_HEIGHT - 16
        scale = min(max_width / artwork.width, max_height / artwork.height)
        artwork = artwork.resize(
            (max(1, round(artwork.width * scale)), max(1, round(artwork.height * scale))),
            Image.Resampling.NEAREST,
        )
        target = Image.new("RGBA", (CELL_WIDTH, CELL_HEIGHT), (0, 0, 0, 0))
        target.alpha_composite(
            artwork,
            ((CELL_WIDTH - artwork.width) // 2, CELL_HEIGHT - artwork.height - 4),
        )
        sheet.alpha_composite(target, (column * CELL_WIDTH, row * CELL_HEIGHT))
    image = normalize_transparent_rgb(sheet)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "PNG", optimize=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="clean mentor pixel assets locally")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kind", choices=("sheet", "state-sheet", "anchor", "coherent-sheet"), default="sheet")
    args = parser.parse_args()
    if not args.input.is_file():
        raise SystemExit(f"input file not found: {args.input}")
    if args.input.resolve() == args.output.resolve():
        raise SystemExit("refusing to overwrite the input sprite sheet")
    if args.kind in {"anchor", "state-sheet"}:
        prepare_identity_anchor(args.input, args.output)
    elif args.kind == "coherent-sheet":
        prepare_coherent_action_sheet(args.input, args.output)
    else:
        prepare_mentor_sheet(args.input, args.output)
    print(f"wrote: {args.output}")


if __name__ == "__main__":
    main()
