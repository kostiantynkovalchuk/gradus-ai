"""
Brand reference image loader for Alex Photo Report.

Loads AVTD brand reference photos from the references/ directory and
exposes them as base64-encoded images to be injected into every
Claude Vision API call, giving the model visual anchors for each brand.

Reference images are loaded ONCE at module import and cached in memory.
If the directory is empty or PIL is unavailable, falls back gracefully
with a warning — analysis still works, just without reference images.

Expected files in this directory:
  Flagship product photos (3):
    greenday_classic_500.jpg    — GreenDay Classic 500ml (production photo)
    helsinki_ice_palace_500.jpg — Helsinki Ice Palace 500ml
    ukrainka_traditional_500.jpg — Ukrainka Traditional 500ml

  Lineup photos from HoReCa presenter PDF (3):
    greenday_lineup.jpg         — Full GreenDay lineup (Classic, Air, Crystal, ...)
    helsinki_lineup.jpg         — Full Helsinki lineup (Ice Palace, Ultramarin, ...)
    ukrainka_lineup.jpg         — Full Ukrainka lineup (Traditional, Strong, Platinum)

  Ideal shelf reference photos from Gotz (8):
    shelf_ref_02.jpg — ADJARI cognac close-up + Helsinki + Ukrainka
    shelf_ref_05.jpg — Villa UA wine + GreenDay + Ukrainka
    shelf_ref_07.jpg — Villa UA Sparkling + ADJARI + GreenDay + Dovbush + Funju
    shelf_ref_12.jpg — "Горілка" section: Ukrainka top row + GreenDay bottom row
    shelf_ref_13.jpg — Full AVTD portfolio on 6 shelves
    shelf_ref_16.jpg — Klinkov boxes + ADJARI varieties + GreenDay + Helsinki
    shelf_ref_17.jpg — ALL brand shelf-strips visible
    shelf_ref_19.jpg — Competitor POS vs Ukrainka + Villa UA
"""

import base64
import logging
from io import BytesIO
from pathlib import Path

logger = logging.getLogger(__name__)

REFERENCES_DIR = Path(__file__).parent
MAX_SIZE = 1200
QUALITY = 85

REFERENCE_LABELS: dict[str, str] = {
    "greenday_classic_500": (
        "GreenDay Classic 500ml — flagship vodka. Green bottle, bold 'GD' logo, "
        "'CLASSIC' label. This is the most common AVTD vodka SKU."
    ),
    "greenday_lineup": (
        "GreenDay full lineup: Classic, Air, Crystal, Original Life, Ultra Soft. "
        "All have green labels and the 'GD' logo. Recognizable by bright green color."
    ),
    "helsinki_ice_palace_500": (
        "Helsinki Ice Palace 500ml — vodka. BLUE bottle or blue label. "
        "'HELSINKI' in large Latin letters. Winter landscape motif. "
        "KEY IDENTIFIER: blue/icy color — unique among AVTD vodkas."
    ),
    "helsinki_lineup": (
        "Helsinki full lineup: Ice Palace, Winter Capital, Ultramarin, Frosty Citrus, Salted Caramel. "
        "All have blue/icy color scheme. Usually 1–3 bottles on shelf, not large groups."
    ),
    "ukrainka_traditional_500": (
        "Ukrainka Traditional 500ml — vodka. Clear glass bottle with DIAMOND PATTERN texture. "
        "WIDE WHITE label with 'УКРАЇНКА' in large Cyrillic text. "
        "KEY IDENTIFIER: diamond-texture glass + large white label. FREQUENTLY MISSED — look carefully."
    ),
    "ukrainka_lineup": (
        "Ukrainka full lineup: Traditional, Strong, Platinum. All have diamond-pattern glass "
        "and wide white labels. Often grouped in 3–6 bottles. Mixed with GreenDay on same shelf."
    ),
    "shelf_ref_02": (
        "IDEAL SHELF — ADJARI cognac close-up: top shelf has Cherry, Orange, 3★, 5★, 8★ variants. "
        "Below: Helsinki + Ukrainka vodka. Shows what cognac section looks like with AVTD brands."
    ),
    "shelf_ref_05": (
        "IDEAL SHELF — Villa UA wine: Didi Lari, Chardonnay, Rosé, Merlot on wine shelf. "
        "GreenDay + Ukrainka vodka on upper shelves. "
        "KEY: Villa UA wine has MEDALLION/COIN emblem on tall 750ml bottles."
    ),
    "shelf_ref_07": (
        "IDEAL SHELF — Villa UA Sparkling (dark champagne-bottle shape with foil neck) on top. "
        "ADJARI with shelf-strip. GreenDay backlit. Dovbush + Jean Jack cognac. Funju soju (small green bottles). "
        "Shows sparkling wine + soju placement."
    ),
    "shelf_ref_12": (
        "IDEAL SHELF — 'Горілка' section: Ukrainka FULL TOP ROW (clear bottles, white labels). "
        "GreenDay FULL BOTTOM ROW (green bottles). "
        "This is how Ukrainka + GreenDay look together on a vodka shelf."
    ),
    "shelf_ref_13": (
        "IDEAL SHELF — Full AVTD portfolio on 6 shelves: "
        "Ukrainka + Helsinki (top), GreenDay (mid), ADJARI + Dovbush + Jean Jack (cognac), Villa UA (bottom). "
        "Reference for all categories in one display."
    ),
    "shelf_ref_16": (
        "IDEAL SHELF — Klinkov premium boxes (top). ADJARI varieties (mid). "
        "GreenDay + Helsinki bottom. Shows cognac + vodka arrangement in premium section."
    ),
    "shelf_ref_17": (
        "IDEAL SHELF — ALL brand shelf-strips visible: KLINKOV, HELSINKI, ЖАН-ЖАК, УКРАINKA, "
        "ДОВБУШ, GREENDAY, ADJARI, VILLA UA. "
        "Best reference for identifying AVTD POS materials vs competitor POS."
    ),
    "shelf_ref_19": (
        "REAL SHELF — Nemiroff competitor shelf-strips on left. "
        "Ukrainka FULL LINEUP in center. Villa UA wine on right. "
        "Shows contrast: Nemiroff POS (competitor) vs our Ukrainka display. "
        "Use to distinguish competitor POS from AVTD POS."
    ),
}


def _load_and_encode(path: Path) -> str | None:
    """Load image, resize if needed, return base64 JPEG string. Returns None on error."""
    try:
        from PIL import Image  # local import — PIL may not be installed in all envs

        img = Image.open(path)
        if max(img.size) > MAX_SIZE:
            ratio = MAX_SIZE / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)

        buf = BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=QUALITY)
        return base64.b64encode(buf.getvalue()).decode()

    except ImportError:
        logger.warning("[References] Pillow not installed — cannot load reference images")
        return None
    except Exception as e:
        logger.warning(f"[References] Failed to load {path.name}: {e}")
        return None


def load_references() -> list[dict]:
    """
    Load all .jpg reference images from the references/ directory.
    Returns list of dicts with: name, label, b64, media_type.
    Returns empty list if directory has no images.
    """
    refs: list[dict] = []

    jpg_files = sorted(REFERENCES_DIR.glob("*.jpg")) + sorted(REFERENCES_DIR.glob("*.jpeg"))
    if not jpg_files:
        logger.info(
            "[References] No reference images found in references/ directory. "
            "Analysis will proceed without visual anchors. "
            "Upload .jpg files to backend/photo_report/references/ to enable."
        )
        return refs

    for img_path in jpg_files:
        b64 = _load_and_encode(img_path)
        if b64 is None:
            continue
        name = img_path.stem
        label = REFERENCE_LABELS.get(name, name.replace("_", " ").title())
        refs.append({
            "name": name,
            "label": label,
            "b64": b64,
            "media_type": "image/jpeg",
            "is_shelf_ref": name.startswith("shelf_ref_"),
        })

    logger.info(
        f"[References] Loaded {len(refs)} reference images "
        f"({sum(1 for r in refs if not r['is_shelf_ref'])} product, "
        f"{sum(1 for r in refs if r['is_shelf_ref'])} shelf)"
    )
    return refs


BRAND_REFERENCES: list[dict] = load_references()
