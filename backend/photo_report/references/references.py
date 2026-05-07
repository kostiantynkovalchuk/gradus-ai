"""
Brand reference image loader for Alex Photo Report.

Loads AVTD brand reference photos from the references/ directory and
exposes them as base64-encoded images to be injected into every
Claude Vision API call, giving the model visual anchors for each brand.

Reference images are loaded ONCE at module import and cached in memory.
If the directory is empty or PIL is unavailable, falls back gracefully
with a warning — analysis still works, just without reference images.

Expected files in this directory (23 total):

  Vodka product photos (6):
    greenday_classic_500.jpg     — GreenDay Classic 500ml (production photo)
    helsinki_ice_palace_500.jpg  — Helsinki Ice Palace 500ml
    ukrainka_traditional_500.jpg — Ukrainka Traditional 500ml
    greenday_lineup.jpg          — Full GreenDay lineup (Classic, Air, Crystal, ...)
    helsinki_lineup.jpg          — Full Helsinki lineup (Ice Palace, Ultramarin, ...)
    ukrainka_lineup.jpg          — Full Ukrainka lineup (Traditional, Strong, Platinum)

  Cognac/brandy product photos (7):
    adjari_3star_500.jpg   — ADJARI 3★ 500ml flagship (rounded amber bottle, golden label)
    adjari_5star_tubus.jpg — ADJARI 5★ in cylindrical tube packaging
    adjari_7star_500.jpg   — ADJARI 7★ "Мудрий Аджарелія" premium (black label, portrait)
    dovbush_3star_500.jpg  — DOVBUSH 3★ "Карпатський" (square bottle, wooden cork, Cyrillic)
    dovbush_4star_500.jpg  — DOVBUSH 4★ "Big Four" LIMITED (green label, Latin text)
    dovbush_4star_round.jpg — DOVBUSH 4★ alternative round-stamp design
    dovbush_honey_500.jpg  — DOVBUSH "Медовий" HONEY tincture (orange/yellow honeycomb label)

  Ideal shelf reference photos (10):
    shelf_ref_02.jpg — ADJARI cognac close-up + Helsinki + Ukrainka
    shelf_ref_05.jpg — Villa UA wine + GreenDay + Ukrainka
    shelf_ref_07.jpg — Villa UA Sparkling + ADJARI + GreenDay + Dovbush + Funju
    shelf_ref_12.jpg — "Горілка" section: Ukrainka top row + GreenDay bottom row
    shelf_ref_13.jpg — Full AVTD portfolio on 6 shelves
    shelf_ref_16.jpg — Klinkov boxes + ADJARI varieties + GreenDay + Helsinki
    shelf_ref_17.jpg — ALL brand shelf-strips visible
    shelf_ref_19.jpg — Competitor POS vs Ukrainka + Villa UA
    shelf_ref_21.jpg — Helsinki transparent bottles next to GreenDay; Klinkov boxes on top (NOT Helsinki)
    shelf_ref_22.jpg — 6 Helsinki SKUs on top shelf + full AVTD shelf-strips
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
        "Helsinki FULL LINEUP — 5 SKUs: Ice Palace (light blue label), Winter Capital (grey), "
        "Ultramarin (dark blue), Frosty Citrus (orange), Salted Caramel (brown). "
        "ALL are TRANSPARENT bottles with mountain/winter scene on label. "
        "CRITICAL: Do NOT confuse with Klinkov (dark boxes) or Nemiroff."
    ),
    "shelf_ref_21": (
        "IDEAL SHELF: Helsinki TRANSPARENT bottles (NO BOXES) on 4th shelf from ground, "
        "positioned NEXT TO GreenDay on the vodka shelf. "
        "Top shelf has Klinkov BOXES (dark blue+gold) — these are NOT Helsinki, Klinkov is cognac. "
        "ADJARI cognac on middle shelves. Key learning: Helsinki = transparent vodka bottles; "
        "Klinkov = dark premium cognac boxes."
    ),
    "shelf_ref_22": (
        "IDEAL SHELF: 6 Helsinki SKUs on top shelf RIGHT SIDE — transparent bottles, no boxes. "
        "'HELSINKI' shelf-strip clearly visible. "
        "All AVTD brands present with shelf-strips: KLINKOV, HELSINKI, ЖАН-ЖАК, УКРАINKA, "
        "ДОВБУШ, GREENDAY, ADJARI, VILLA UA. "
        "Best reference for identifying Helsinki transparent bottles and AVTD POS shelf-strips."
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
    # ── ADJARI cognac references ──────────────────────────────────────────────
    "adjari_3star_500": (
        "ADJARI 3★ 500ml — FLAGSHIP cognac/brandy. Dark amber ROUNDED bottle, golden mountain "
        "landscape label, eagle emblem at bottom, gold cap, text 'ADJARI', three stars ★★★, "
        "number '3'. MOST COMMON ADJARI SKU on shelves. Other variants (4★ Квартелі, 5★) look "
        "similar with different star count. ALL are AVTD brands."
    ),
    "adjari_5star_tubus": (
        "ADJARI 5★ in TUBE packaging — dark brown CYLINDRICAL tube next to the bottle. On shelves "
        "you may see ONLY the tube (bottle hidden inside). Tube has 'ADJARI' text, mountain "
        "landscape, eagle, five stars ★★★★★. Do NOT confuse ADJARI tubes with Klinkov boxes — "
        "Klinkov boxes are RECTANGULAR, ADJARI tubes are CYLINDRICAL."
    ),
    "adjari_7star_500": (
        "ADJARI 7★ 'Мудрий Аджарелія' 500ml — PREMIUM cognac/brandy. Same bottle shape as 3★ "
        "but with BLACK label, portrait of a man in traditional hat, text 'МУДРИЙ АДЖАРЕЛІЯ', "
        "number '7'. Premium variant with distinctive dark design. AVTD brand."
    ),
    # ── DOVBUSH cognac references ─────────────────────────────────────────────
    "dovbush_3star_500": (
        "DOVBUSH (Довбуш) 3★ 'Карпатський' 500ml — FLAGSHIP cognac/brandy. SQUARE bottle "
        "(NOT rounded like ADJARI!), WOODEN CORK cap, Cossack warrior portrait, CYRILLIC text "
        "'ДОВБУШ Карпатський', three stars ★★★, number '3'. Usually stands NEXT TO ADJARI on "
        "cognac shelf. AVTD brand."
    ),
    "dovbush_4star_500": (
        "DOVBUSH 4★ 'Big Four' LIMITED 500ml — Same SQUARE bottle as 3★ but with GREEN label "
        "and LATIN text 'DOVBUSH the Carpathian BIG FOUR', wooden cork, number '4'. IMPORTANT: "
        "This looks VERY DIFFERENT from Dovbush 3★ (green vs brown, Latin vs Cyrillic) but it "
        "IS the same brand. AVTD brand."
    ),
    "dovbush_4star_round": (
        "DOVBUSH 4★ alternative design with ROUND STAMP/SEAL on label. Same square bottle shape "
        "as other Dovbush variants. Different label layout from 'Big Four' version. AVTD brand — "
        "count as Dovbush facing."
    ),
    "dovbush_honey_500": (
        "DOVBUSH 'Медовий' HONEY tincture 500ml — Same SQUARE bottle shape as Dovbush cognac "
        "but with bright ORANGE/YELLOW HONEYCOMB label, bee icon, text 'HONEY Медовий', 37.5% "
        "ABV. This is a TINCTURE not cognac, but it IS a Dovbush/AVTD product. Count as Dovbush "
        "facing in the cognac section."
    ),
    # ── JEAN JACK (Жан-Жак) cognac references ────────────────────────────────
    "jeanjack_lineup": (
        "JEAN JACK (Жан-Жак) FULL LINEUP — 6 SKUs of AVTD cognac/brandy. "
        "All share the same FLAT/SQUARE bottle shape with 'ЖАН-ЖАК' / 'JEAN JACK' text "
        "and the iconic HORSEMAN (rider on horse) medallion on label. "
        "CLASSIC VARIANTS (differ by ribbon color and star count): "
        "Classic 3★ (red ribbon, cream label), "
        "Франс/France 4★ (brown/copper ribbon, cream label), "
        "Резерв/Reserve 5★ (blue ribbon, cream label with blue accents). "
        "FLAVORED VARIANTS (same bottle shape, flavor-specific label colors): "
        "Amaretto (dark brown/black label with leaf pattern, 30% ABV), "
        "Honey/Медовий (bright yellow/gold honeycomb label, yellow cap, 37.5% ABV), "
        "Orange/Апельсин (bright orange label with citrus pattern, 30% ABV). "
        "ALL are AVTD brands. Usually stands NEXT TO ADJARI and DOVBUSH in the cognac section. "
        "KEY IDENTIFIER: flat square bottle + horseman medallion + 'Jean Jack' text."
    ),
    # ── Shelf references ──────────────────────────────────────────────────────
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
