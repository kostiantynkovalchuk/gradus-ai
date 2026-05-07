"""
Brand reference image loader for Alex Photo Report.

Loads AVTD brand reference photos from the references/ directory and
exposes them as base64-encoded images to be injected into every
Claude Vision API call, giving the model visual anchors for each brand.

Reference images are loaded ONCE at module import and cached in memory.
If the directory is empty or PIL is unavailable, falls back gracefully
with a warning — analysis still works, just without reference images.

Expected files in this directory:

  Vodka lineups (3):
    greenday_lineup.jpg      — Full GreenDay lineup (Classic, Air, Crystal, ...)
    helsinki_lineup.jpg      — Full Helsinki lineup (Ice Palace, Ultramarin, ...)
    ukrainka_lineup.jpg      — Full Ukrainka lineup (Traditional, Strong, Platinum)

  Cognac/brandy lineups (3):
    adjari_lineup.jpg        — ADJARI 3★ flagship + 5★ tube + 7★ premium
    dovbush_lineup.jpg       — DOVBUSH 3★ Карпатський + 4★ Big Four + 4★ round + Honey
    jeanjack_lineup.jpg      — JEAN JACK full 6-SKU lineup (3 classic + 3 flavored)

  Wine lineups (up to 8, added progressively):
    villaua_classic_white.jpg  — Villa UA Classic white wines (8 SKU) [PENDING]
    villaua_classic_red.jpg    — Villa UA Classic red/rosé wines (9 SKU) [PENDING]
    villaua_art.jpg            — Villa UA Art Collection (6 SKU)
    villaua_avtorskaya.jpg     — Villa UA Avtorskaya blends (5 SKU) [PENDING]
    villaua_fruit_frizzante.jpg — Villa UA Fruit + Frizzante Light (5 SKU, 2 loaded)
    villaua_sparkling.jpg      — Villa UA Sparkling champagne-bottle (8 SKU) [PENDING]
    kosher_lineup.jpg          — Kosher Collection (5 SKU)
    kristivalley_lineup.jpg    — Kristi Valley French wines (5 SKU)

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
    # ── Vodka lineups ─────────────────────────────────────────────────────────
    "greenday_lineup": (
        "GreenDay full lineup: Classic, Air, Crystal, Original Life, Ultra Soft. "
        "All have green labels and the 'GD' logo. Recognizable by bright green color."
    ),
    "helsinki_lineup": (
        "Helsinki FULL LINEUP — 5 SKUs: Ice Palace (light blue label), Winter Capital (grey), "
        "Ultramarin (dark blue), Frosty Citrus (orange), Salted Caramel (brown). "
        "ALL are TRANSPARENT bottles with mountain/winter scene on label. "
        "CRITICAL: Do NOT confuse with Klinkov (dark boxes) or Nemiroff."
    ),
    "ukrainka_lineup": (
        "Ukrainka full lineup: Traditional, Strong, Platinum. All have diamond-pattern glass "
        "and wide white labels. Often grouped in 3–6 bottles. Mixed with GreenDay on same shelf."
    ),
    # ── Cognac/brandy lineups ─────────────────────────────────────────────────
    "adjari_lineup": (
        "ADJARI (Аджарі) FULL LINEUP — 3 key SKUs of AVTD cognac/brandy. "
        "Left to right: ADJARI 3★ (golden label, MOST COMMON on shelves, rounded amber bottle, "
        "eagle emblem, mountain landscape), ADJARI 5★ in CYLINDRICAL TUBE packaging (dark brown "
        "tube — do NOT confuse with Klinkov RECTANGULAR boxes), ADJARI 7★ 'Мудрий Аджарелія' "
        "(BLACK label with portrait of man in traditional hat, premium). "
        "ALL have 'ADJARI' text, mountain landscape, eagle emblem. ALL are AVTD brands."
    ),
    "dovbush_lineup": (
        "DOVBUSH (Довбуш) FULL LINEUP — 4 SKUs of AVTD cognac/brandy. "
        "All have SQUARE bottle shape (NOT rounded like ADJARI!) with WOODEN CORK cap. "
        "Left to right: 3★ Карпатський (brown label, Cyrillic 'ДОВБУШ', Cossack warrior portrait), "
        "4★ 'Big Four' (GREEN label, LATIN text 'DOVBUSH the Carpathian BIG FOUR'), "
        "4★ alternative (round stamp/seal design on label), "
        "Honey/Медовий (bright ORANGE/YELLOW honeycomb label, bee icon, 37.5% ABV — tincture, "
        "not cognac, but still AVTD — count as Dovbush facing). "
        "Usually stands NEXT TO ADJARI on cognac shelf. ALL are AVTD brands."
    ),
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
    # ── Wine lineups ──────────────────────────────────────────────────────────
    "villaua_classic_white": (
        "VILLA UA CLASSIC — WHITE WINES (8 SKU). AVTD flagship wine brand. "
        "KEY IDENTIFIER: MEDALLION/COIN emblem on every label (castle/building icon). "
        "Standard 750ml bottles, pale green/straw color. "
        "Includes: Riesling, Blanc de Blanc, Chardonnay, Muscat Berbarro, Muscat Marbel, "
        "Muscat Riviera, Piccolo, Traminer Blanc. "
        "WARNING: Villa Krim is NOT Villa UA — it is a competitor brand!"
    ),
    "villaua_classic_red": (
        "VILLA UA CLASSIC — RED and ROSÉ WINES (9 SKU). Same AVTD brand, same medallion/coin emblem. "
        "Dark bottles (red wines) and pink bottles (rosé). "
        "Includes: Bastardo, Cabernet, Merlot, Negro del Mare, Pinot Noir, Saperavi, "
        "Shato Baron, Shato Le Grand, Shevalie Rouge. "
        "Same 750ml bottle shape as Classic White. AVTD brand."
    ),
    "villaua_art": (
        "VILLA UA ART COLLECTION — 6 wine SKUs. Premium line with distinctive slim bottle shape "
        "and artistic label design. KEY IDENTIFIER: large embossed MEDALLION on upper bottle neck "
        "(above label). Label has cursive 'Art Collection' text + 'VILLA UA' + wine variety name. "
        "Red wines have BLACK label with copper/red accents (Bosconelli, Sangiovese). "
        "White wines have WHITE label with teal/green accents (Muscat, Pinot Grigio, Portofino, Chateau Orlando). "
        "Includes: Bosconelli, Muscat, Pinot Grigio, Portofino, Sangiovese, Chateau Orlando. "
        "AVTD brand."
    ),
    "villaua_avtorskaya": (
        "VILLA UA AVTORSKAYA (Authors) COLLECTION — 5 blend wines. "
        "Each bottle combines two grape varieties. "
        "Includes: Cabernet Pinot Noir, Chardonnay Sauvignon, Muscat Traminer, "
        "Piano Rosé, Pinot Noir Merlot. "
        "Same Villa UA medallion. AVTD brand."
    ),
    "villaua_fruit_frizzante": (
        "VILLA UA FRUIT WINE + FRIZZANTE LIGHT — up to 5 SKUs. "
        "Frizzante Light: slim 700ml bottles with bold geometric label design (overlapping oval shapes), "
        "text 'VILLA UA Frizzante Light'. "
        "Frizzante Rosé has PINK cap + pink/gold ovals. "
        "Frizzante White has YELLOW cap + yellow/gold ovals. "
        "Fruit wines (Cherry/Mango/Peach) have fruit-themed labels. "
        "ALL are AVTD brands. Different shelf section from still wine."
    ),
    "villaua_sparkling": (
        "VILLA UA SPARKLING — 8 SKUs. Dark CHAMPAGNE-SHAPED bottles with FOIL on neck. "
        "Same Villa UA medallion/coin emblem on champagne bottle. "
        "Includes: Bellini, Brut, Grand Cuvee, Muscat, Pina Colada, Rose, Salute Asti, Semisweet. "
        "On SEPARATE shelf from still wine. "
        "Do NOT confuse with still Villa UA — sparkling has champagne bottle shape and foil neck! "
        "AVTD brand."
    ),
    "kosher_lineup": (
        "KOSHER COLLECTION — 5 wine SKUs. AVTD kosher wine brand. "
        "KEY IDENTIFIER: 'KOSHER COLLECTION' text + Star of David menorah logo at top, "
        "ornate mandala-style pattern on label, 'Est. 2010', kosher certification seal. "
        "Dark bottles. Includes: Agada (red), Cabernet (red), Chardonnay (white/clear), "
        "Emet (red), Saperavi (red). "
        "The only kosher wines in AVTD portfolio. AVTD brand."
    ),
    "kristivalley_lineup": (
        "KRISTI VALLEY — 5 wine SKUs. AVTD wine brand with French-style positioning. "
        "KEY IDENTIFIER: 'KRISTI VALLEY' text in large font, running horse made of particles on label, "
        "'Mis en bouteille en France', 'Vin de la Communauté Européenne'. "
        "Label colors: cream/beige background (white wines), orange/red background (red wines), "
        "cream with pink tones (rosé). "
        "Includes: Châtelain Clemont (white, cream label), Belle Mélanie (red, orange label), "
        "Saint Thouri (rosé, cream+pink), Charon Blanc (white, cream label), Vivien Rouge (red, orange label). "
        "AVTD brand."
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
        f"({sum(1 for r in refs if not r['is_shelf_ref'])} product lineups, "
        f"{sum(1 for r in refs if r['is_shelf_ref'])} shelf)"
    )
    return refs


BRAND_REFERENCES: list[dict] = load_references()
