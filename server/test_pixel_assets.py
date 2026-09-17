from pathlib import Path

from PIL import Image

from pixel_assets import prepare_identity_anchor, prepare_mentor_sheet, prepare_state_sheet


def test_pixel_asset_cleanup_creates_transparent_sheet(tmp_path: Path) -> None:
    source = Path(__file__).parent.parent / "assets" / "pixel" / "mentor-actions-sprite-sheet-original-draft.png"
    target = tmp_path / "mentor-v2.png"

    prepare_mentor_sheet(source, target)

    image = Image.open(target)
    assert image.mode == "RGBA"
    assert image.size == (1536, 1024)
    assert image.getchannel("A").getbbox() is not None
    assert image.getpixel((0, 0))[3] == 0


def test_identity_anchor_cleanup_preserves_size_and_adds_alpha(tmp_path: Path) -> None:
    source = Path(__file__).parent.parent / "assets" / "pixel" / "mentor-main-anchor.png"
    target = tmp_path / "mentor-anchor.png"

    prepare_identity_anchor(source, target)

    image = Image.open(target)
    assert image.mode == "RGBA"
    assert image.size == (1024, 1536)
    assert image.getpixel((0, 0))[3] == 0


def test_state_sheet_cleanup_preserves_generated_2x2_layout(tmp_path: Path) -> None:
    source = Path(__file__).parent.parent / "assets" / "pixel" / "mentor-state-sprite-sheet-raw.png"
    target = tmp_path / "mentor-state-sheet.png"

    prepare_state_sheet(source, target)

    image = Image.open(target)
    assert image.mode == "RGBA"
    assert image.size == (1024, 1536)
    assert image.getpixel((0, 0))[3] == 0
    assert image.getpixel((512, 768))[3] == 0
