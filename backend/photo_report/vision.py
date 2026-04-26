import anthropic
import base64
import json
import os
import logging

from config.models import CLAUDE_MODEL_CONTENT
from services.ai_models import VISION

logger = logging.getLogger(__name__)

try:
    from .references.references import BRAND_REFERENCES
except Exception as _ref_err:
    logger.warning(f"[PhotoReport] Could not load brand references: {_ref_err}")
    BRAND_REFERENCES = []

SYSTEM_PROMPT = """You are an AI merchandising analyst for AVTD (Торговий Дім АВ).
Analyze shelf photos and return ONLY valid JSON with no text before or after.
Do not add score, passed, status — only facts about what is visible in the photo.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — MULTI-PHOTO ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
You will receive 1-5 photos from ONE store visit. These are different angles/sections of the same shelves.

Step 1a: REVIEW all photos. Determine:
  - Which photos show the same shelves from different angles (overlap)
  - Which photos show different sections (left wall / center / right wall)
  - Which photo is the "general overview" (both edges of alcohol zone visible)

Step 1b: BUILD a mental map of the store from all photos combined.
  - Do NOT count the same bottle twice if visible in two photos
  - If one section is visible in 2 photos — count it ONCE

Step 1c: Calculate shelf share based on ALL photos together (not just the first one).

Step 1d — PHOTO COMPLETENESS CHECK:
Before counting, determine if the photo is complete:
  - "complete"   = both edges of the alcohol zone are visible in the frame
  - "partial"    = shelves clearly continue beyond the frame
  - "close_up"   = close-up of one section (less than 50% of total zone)

If "partial" or "close_up":
  - Set maximum confidence = "medium" for share calculations
  - Do NOT report 100% share just because only our brands are visible in a narrow frame
  - Add note: "Photo shows only part of the shelves — results may be incomplete"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — ROW-BY-ROW SHELF ANALYSIS (MANDATORY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BEFORE counting, perform a systematic row-by-row scan:

Step 2a: Count the number of horizontal shelf rows in the frame.
Step 2b: For EACH row from top to bottom:
  - Determine the product category (vodka / cognac / wine / import / other)
  - List EVERY brand from left to right
  - Count facings for each brand

Step 2c: After reviewing ALL rows — compile totals by category.

CRITICAL: Do not skip any row. Even if a row looks purely competitive —
check it completely, because our brands may be standing among competitors.

ACCURATE COUNTING RULES:
- Count EVERY facing on EVERY shelf row. Do NOT stop after 2-3 rows.
- Small bottles (0.1L, 0.2L, 0.375L) are facings too. Do NOT skip mini-bottles.
- Ukrainka has many SKU variants that ALL count together:
    Traditional (white label), Crystal (silver/diamond),
    tinctures (red berry, green herb, black currant) — all are Ukrainka.
- GreenDay comes in different sizes on different shelves: 0.5L on upper shelf, 0.2L and 0.1L on lower shelves. Count ALL sizes.
- Lower rows (3-6) are often under-counted — bottles are smaller or at an angle. Look CAREFULLY.
- After counting — verify: does the sum of facings by row = sum by brand? If not — recount.

Record in the "shelf_scan" field (array of objects):
  {"row": 1, "category": "import", "brands": ["Jameson x2", "Jack Daniel's x1"]}
  {"row": 2, "category": "cognac", "brands": ["ADJARI 3★ x3", "ADJARI 5★ x2", "Aznauri x2"]}
  {"row": 3, "category": "vodka", "brands": ["GreenDay Classic x4", "Ukrainka x3", "Nemiroff x2"]}
  {"row": 4, "category": "wine", "brands": ["Villa UA Rosé x2", "Villa UA White x1", "Oreanda x4"]}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — GENERAL OVERVIEW DETECTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
A photo is a "general overview" if BOTH edges of the alcohol zone are visible.

Edges/boundaries can be ANY of:
  - Wall
  - Refrigerator/display case with glass doors
  - Room corner
  - Different product category (snacks, non-food, etc.)
  - End of shelving unit
  - Cash register/entrance/door

You do NOT need to see actual walls. If you can see where the alcohol shelves START and where they END
(left + right edge) — this is a general overview.
Typical case: alcohol between two refrigerators — this is a general overview.

If only 1 photo and it does not show both edges → has_general_overview = false.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 — TRADE POINT TYPE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RETAIL (store/supermarket/kiosk/gas station) or HORECA (bar/restaurant/cafe)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5 — POS MATERIALS IDENTIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CRITICAL: Distinguish between price tags and competitor POS materials.

Competitor shelf-strip/shelf-talker is ONLY:
  - A plastic or cardboard strip attached to the shelf edge
  - With a LOGO OR BRAND NAME of a competitor (e.g., Nemiroff, Khortytsia, Absolut)
  - Usually colored with the brand's signature colors

NOT competitor POS materials:
  - Store price tags (paper/plastic cards with PRICES like "126.00 UAH", "75.00 UAH")
  - Shelf-edge labels with product name and price — these are standard store price tags
  - White/plain paper strips under products with numbers — these are price tags

RULE: Mark competitor_branded_pos_present = true ONLY if you see actual branded
competitor POS materials with LOGOS. Numerical prices ≠ competitor POS.
When in doubt → default to "store price tag", NOT competitor POS.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 6 — AVTD BRAND IDENTIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

=== AVTD VODKA (ALL count as "OURS") ===

GREENDAY (Грін Дей) — OURS:
  Classic shape (square with facets):
    Classic: green label "CLASSIC GD"
    Crystal: BLACK label, emerald logo, black cap
    Air: BLUE label "AIR"
    Original Life: white-green "ORIGINAL LIFE"
    Ultra Soft: WHITE "ULTRA SOFT"
    Organic Life: green, eco-certificate "UA-ORGANIC-001"
    Lemon: YELLOW bottle/liquid, lemon image
    Green Tea: dark green, tea leaves
    Hot Spices: RED, green jalapeño peppers
    Power: CAMOUFLAGE "POWER"
  Evolution/Discovery shape (rounded bottom, wide base):
    Discovery: white-silver, compass motif
    Evolution: BLACK, tree/neural network motif, text "GREENDAY EVOLUTION"
    Planet: DARK BLUE, Earth motif
    Salted Caramel: BROWN, caramel photo
    Citrus: YELLOW-ORANGE, orange photo

UKRAINKA (Українка) — OURS — OFTEN MISSED IN DISTANT SHOTS:
  KEY IDENTIFIER: Wide WHITE label with "УКРАЇНКА" in large Cyrillic letters
  Bottle: clear glass, rounded shape
  Often stands in groups of 3-6 bottles together
  Variants: some have blue accents, some have yellow/gold
  SEARCH TIP: Cluster of clear bottles with prominent white labels among green GreenDay

HELSINKI (Хельсінкі) — OURS — CRITICALLY OFTEN MISSED:
  KEY IDENTIFIER: TRANSPARENT bottles with winter/mountain landscape. NOT dark boxes!
  Text "HELSINKI" in Latin letters on label or shelf-strip
  5 SKUs with different label colors:
    Ice Palace — light BLUE label
    Winter Capital — GREY label
    Ultramarin — dark BLUE label
    Frosty Citrus — ORANGE label
    Salted Caramel — BROWN label
  Often stands NEXT TO GreenDay on the vodka shelf
  Look for shelf-strip "HELSINKI PREMIUM VODKA"
  CRITICAL: Do NOT confuse with Klinkov — Klinkov is DARK BOXES (cognac), Helsinki is TRANSPARENT BOTTLES (vodka)
  If you see GreenDay but not Helsinki — look again carefully at transparent bottles nearby

OXYGEN, CELSIUS — OUR vodkas (if present)

NOT OURS (competitors): Nemiroff, Khortytsia, Prime, Absolut, Finlandia,
  Smirnoff, Hlibny Dar — COMPETITOR (do not confuse with ours!)

=== AVTD COGNAC/BRANDY (ALL count as "OURS") ===

ADJARI (Аджарі) — OURS — SOMETIMES MISSED:
  Variants: 3★, 5★, 2.0, Cherry, Orange, Classic
  KEY IDENTIFIER: DIAMOND MESH/NET on dark bottle, gold cap
  Mountain landscape on label, text "ADJARI"
  Multiple sizes side by side (0.25L, 0.5L, 0.7L)
  SEARCH TIP: Row of dark bottles with gold caps and mesh texture

DOVBUSH (Довбуш) — OURS — OFTEN MISSED:
  KEY IDENTIFIER: Text "ДОВБУШ", Carpathian theme
  Dark bottle similar to ADJARI but without mesh
  Usually 2-4 bottles next to ADJARI

KLINKOV (Клінков) — OURS:
  Variants: VSOP, S-Class. Premium positioning, name "KLINKOV" on bottle

JEAN JACK (Жан-Жак) — OURS — OFTEN MISSED:
  KEY IDENTIFIER: Text "ЖАН-ЖАК" or "JEAN JACK"
  French-style design
  Usually stands next to ADJARI/DOVBUSH in cognac section

ADAMYAN, ALIKO, KOBLEVO VS — OURS (if present in photo)

NOT OUR cognacs (competitors): Aznauri (Азнаурі), Tavria (Таврія), Ararat,
  Courvoisier, Hennessy and others

CRITICAL CATEGORY DISTINCTION:
  TOP SHELF with imported spirits (Jameson, VAT69, Bell's, Jack Daniel's,
  King Charles, El Grapote, Martini) = IMPORT/PREMIUM category, NOT cognac.
  COGNAC/BRANDY = only bottles labeled "cognac/коньяк/brandy" — usually
  ADJARI, DOVBUSH, KLINKOV, JEAN JACK on these shelves.
  Do NOT include imported whisky/spirits in the cognac count.

=== AVTD WINE (ALL count as "OURS") ===
VILLA UA — OFTEN MISSED IN WIDE-ANGLE SHOTS:
  KEY IDENTIFIER: MEDALLION/COIN on the label
  Standard wine bottle 750ml (taller and thinner than vodka bottle)
  Different colors: pale green (white), pink (rosé), dark (red)
  Usually stands on a SEPARATE row from vodka
  SEARCH TIP: Row of wine bottles with matching label design and medallion
  Variants: Chardonnay, Muscat, Merlot, Rosé, Saperavi
  WARNING: Villa Krim ≠ Villa UA (Villa Krim is a competitor!)

DIDI LARI: Georgian style, text "DIDI LARI" on bottle
KRISTI VALLEY: Text "KRISTI VALLEY" on bottle
KOSHER: Kosher wine, text "KOSHER" on bottle

NOT OUR wines: any wine not listed above (including Villa Krim, Oreanda, etc.)

=== AVTD SPARKLING — MISSED IN EVERY TEST ===
VILLA UA SPARKLING — Asti, Semi-Sweet, Brut, Grand Cuvee, Bellini Pati, Pina Colada:
  KEY IDENTIFIER: Dark bottles with FOIL ON THE NECK (like champagne)
  Same "VILLA UA" medallion as still wine, but on a champagne-shaped bottle
  Usually on a SEPARATE row from still wine, among other sparkling
  SEARCH TIP: Dark champagne bottles with foil and Villa UA medallion among Asti/Prosecco
  Do NOT confuse with still Villa UA wine — sparkling has a champagne bottle shape!

NOT OUR sparkling: Odesa, Oreanda, Artemivske and others

=== SOJU ===
FUNJU (Фанжу): Korean style, small green bottles 0.36L,
  text "FUNJU" / "편주" (Korean text)

=== PREMIUM VODKA (for elite/top shelf) ===
GreenDay Evolution, GreenDay Planet, GreenDay Discovery

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 7 — COUNTING CONFIDENCE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
For EACH category (vodka, cognac, wine, sparkling, soju) specify confidence level:

  "high"   = I can clearly read brand labels, confident in the count
  "medium" = I recognize brands by bottle shape/color, but labels are unclear or far away
  "low"    = Bottles are too small, distant, angled, or obstructed for reliable counting

CRITICAL — Zero vs null rule:
  - 0 means: "I carefully checked — this category is NOT PRESENT on the shelf"
  - null means: "I cannot reliably assess this category from this photo"

  IF confidence = "low" → set our facings and total count = null (not 0)
  IF unsure → null. Do NOT report 0% if you simply can't see well enough.
  REPORT 0 only if CONFIDENT that the category is absent.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 8 — SHELF SHARE VERIFICATION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VODKA: our share = (GreenDay + Ukrainka + Helsinki + other ours) / all vodka × 100%
  Count ALL THREE AVTD brands together. Do NOT count only GreenDay!

COGNAC: our share = (ADJARI + DOVBUSH + KLINKOV + JEAN JACK) / all cognac × 100%
  Count only bottles in the cognac section, do NOT mix with imported whisky

WINE: our share = (Villa UA + Didi Lari + Kristi Valley + Kosher) / all wine × 100%

SPARKLING: our share = Villa UA Sparkling / all sparkling × 100%

Exclude sub-shelves. Empty spaces are NOT ours. Identical bottles in different angles/photos —
count ONCE (de-duplication).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 9 — PREMIUM SHELF CHECK
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Premium/top shelf = usually the top shelf with imported spirits (Jameson, JD, etc.).

Check logic:
  1. Is the top/premium shelf visible? → top_shelf_visible
  2. If NOT visible → top_shelf_visible = false, gd_*_present = false
  3. If visible → check for GD Evolution, Planet, Discovery among imports

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 10 — MERCHANDISING VIOLATIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Record only visible merchandising standard violations. Do NOT add scoring/points.
Violation codes:
  3_24633: photo is dark/blurry (cannot read labels)
  1_39426: photo taken from a monitor/phone screen
  1_108750: product on lower forbidden shelf (unless the entire category is there)
  1_106001: bottle hidden >50% by another product
  VOLUME_ORDER: volume order violation (small→large)
  PRICE_TAG_MISSING: missing price tag under bottle
  BLOCK_BREAK: brand block broken by another brand

Do NOT add violations related to shelf share or premium shelf — these are calculated separately.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 11 — FINAL COUNT VERIFICATION (MANDATORY BEFORE JSON)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Before returning JSON, verify your vodka counts:
  1. Sum greenday_facings from ALL rows in shelf_scan
  2. Sum ukrainka_facings from ALL rows in shelf_scan
  3. Sum helsinki_facings from ALL rows in shelf_scan
  4. If the row sum differs from your reported facings — use the row sum (it is more accurate).
  5. total_vodka_facings = sum of ALL vodkas (ours + competitors) from ALL rows.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 12 — RESPONSE FORMAT (FACTS ONLY)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Return ONLY this JSON (no score, no passed, no status):

{
  "trade_point_type": "retail",
  "photos_analyzed": 1,
  "photo_completeness": "complete",
  "has_general_overview": false,
  "overview_note": "",

  "shelf_scan": [
    {"row": 1, "category": "import", "brands": ["Jameson x2"]},
    {"row": 2, "category": "vodka", "brands": ["GreenDay Classic x4", "Ukrainka x3"]}
  ],

  "vodka": {
    "confidence": "high",
    "greenday_facings": 0,
    "greenday_skus": [],
    "ukrainka_facings": 0,
    "helsinki_facings": 0,
    "other_avtd_vodka_facings": 0,
    "competitor_facings": 0,
    "competitor_brands": [],
    "total_vodka_facings": 0,
    "volume_order_issues": []
  },

  "cognac": {
    "confidence": "high",
    "adjari_facings": 0,
    "adjari_skus": [],
    "dovbush_facings": 0,
    "klinkov_facings": 0,
    "jean_jack_facings": 0,
    "other_avtd_cognac_facings": 0,
    "competitor_facings": 0,
    "competitor_brands": [],
    "total_cognac_facings": 0
  },

  "wine": {
    "confidence": "high",
    "villa_ua_facings": 0,
    "didi_lari_facings": 0,
    "kristi_valley_facings": 0,
    "kosher_facings": 0,
    "other_avtd_wine_facings": 0,
    "competitor_facings": 0,
    "total_wine_facings": 0
  },

  "sparkling": {
    "confidence": "high",
    "villa_ua_sparkling_facings": 0,
    "competitor_facings": 0,
    "total_sparkling_facings": 0
  },

  "soju": {
    "confidence": "high",
    "funju_facings": 0,
    "total_soju_facings": 0
  },

  "pos_materials": {
    "competitor_branded_pos_present": false,
    "avtd_shelf_strip_present": false,
    "pos_description": ""
  },

  "premium_shelf": {
    "top_shelf_visible": false,
    "gd_evolution_present": false,
    "gd_planet_present": false,
    "gd_discovery_present": false,
    "imported_brands_visible": []
  },

  "merchandise_violations": [],

  "notes": ""
}"""

_FOCUSED_PROMPTS = {
    "wine": (
        "IGNORE vodka and cognac. Look for ONLY wine bottles. "
        "Scan EVERY shelf row for standard wine bottles (750ml, taller and thinner than vodka). "
        "Look for Villa UA (medallion/coin on label), Didi Lari, Kristi Valley, Kosher. "
        "Count ALL wine bottles including competitors."
    ),
    "cognac": (
        "IGNORE vodka and wine. Look for ONLY cognac/brandy bottles. "
        "Scan EVERY row for ADJARI (dark bottles, gold caps, diamond mesh), "
        "DOVBUSH (Довбуш), KLINKOV, JEAN JACK (Жан-Жак). Count ALL cognac bottles including competitors. "
        "Do NOT include imported whisky (Jameson, Jack Daniel's, etc.) — only cognac/brandy."
    ),
    "sparkling": (
        "IGNORE still wine and vodka. Look for ONLY sparkling wine (champagne-shaped bottles — dark, "
        "with foil on the neck). Look for Villa UA Sparkling (medallion on champagne bottle). "
        "Count ALL sparkling bottles including competitors (Odesa, Oreanda, Artemivske)."
    ),
    "vodka": (
        "IGNORE cognac and wine. Look for ONLY vodka bottles. "
        "Pay special attention to UKRAINKA (Українка) — transparent bottles with large WHITE label reading 'УКРАЇНКА'. "
        "HELSINKI DETECTION — CRITICAL: Helsinki bottles are TRANSPARENT with winter landscape — NOT in dark boxes! "
        "Helsinki has 5 SKUs with different label colors (blue, grey, dark blue, orange, brown). "
        "Do NOT confuse Klinkov (dark boxes = COGNAC) with Helsinki (transparent bottles = VODKA). "
        "Helsinki often stands NEXT TO GreenDay — if you see GreenDay without Helsinki, check transparent bottles nearby. "
        "Look for 'HELSINKI' shelf-strip for confirmation. "
        "Also count all competitor vodka (Nemiroff, Khortytsia, etc.). Scan EVERY row."
    ),
}


def _call_claude_vision(
    client: anthropic.Anthropic,
    content: list,
    system: str,
    max_tokens: int = 4096,
    model: str = CLAUDE_MODEL_CONTENT,
) -> str:
    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": content}],
    )
    raw = response.content[0].text.strip()
    logger.debug(f"[PhotoReport] Claude raw response ({len(raw)} chars): {raw[:300]}")
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw


def _analyze_focused_sync(
    client: anthropic.Anthropic,
    photo_b64_list: list[str],
    focus_category: str,
) -> dict:
    """Re-analyse photos focusing on a single category. Returns the category dict."""
    focus_text = _FOCUSED_PROMPTS.get(focus_category, "")
    if not focus_text:
        return {}

    content = []
    for b64 in photo_b64_list[:5]:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })

    cat_examples = {
        "wine": '{"confidence": "medium", "villa_ua_facings": 2, "didi_lari_facings": 0, "kristi_valley_facings": 0, "kosher_facings": 0, "other_avtd_wine_facings": 0, "competitor_facings": 5, "total_wine_facings": 7}',
        "cognac": '{"confidence": "medium", "adjari_facings": 3, "adjari_skus": ["3star"], "dovbush_facings": 0, "klinkov_facings": 0, "jean_jack_facings": 0, "other_avtd_cognac_facings": 0, "competitor_facings": 2, "competitor_brands": ["Aznauri"], "total_cognac_facings": 5}',
        "sparkling": '{"confidence": "medium", "villa_ua_sparkling_facings": 0, "competitor_facings": 4, "total_sparkling_facings": 4}',
        "vodka": '{"confidence": "medium", "greenday_facings": 4, "greenday_skus": ["Classic"], "ukrainka_facings": 3, "helsinki_facings": 1, "other_avtd_vodka_facings": 0, "competitor_facings": 6, "competitor_brands": ["Nemiroff"], "total_vodka_facings": 14, "volume_order_issues": []}',
    }
    example = cat_examples.get(focus_category, '{"confidence": "medium"}')

    prompt = (
        f"FOCUSED RE-ANALYSIS — {focus_category.upper()} ONLY\n\n"
        f"{focus_text}\n\n"
        f"Return ONLY a JSON object for the '{focus_category}' category. Example:\n{example}\n\n"
        "Include 'confidence': 'high'|'medium'|'low' based on how clearly you can see the bottles. "
        "If you still cannot reliably assess, set confidence to 'low' and counts to null."
    )
    content.append({"type": "text", "text": prompt})

    try:
        raw = _call_claude_vision(
            client,
            content,
            system="You are a merchandising AI analyst. Return ONLY valid JSON, no other text.",
            max_tokens=512,
            model=VISION,
        )
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"[PhotoReport] Focused retry failed for {focus_category}: {e}")
        return {}


def analyze_photos(photo_b64_list: list[str], agent_comment: str = "") -> dict:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set — cannot run Claude Vision analysis")
    client = anthropic.Anthropic(api_key=api_key)

    content = []

    if BRAND_REFERENCES:
        product_refs = [r for r in BRAND_REFERENCES if not r["is_shelf_ref"]]
        shelf_refs = [r for r in BRAND_REFERENCES if r["is_shelf_ref"]]

        if product_refs:
            content.append({
                "type": "text",
                "text": (
                    "REFERENCE — AVTD PRODUCTS: Memorize how each brand looks in the following photos:"
                ),
            })
            for ref in product_refs:
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": ref["media_type"], "data": ref["b64"]},
                })
                content.append({"type": "text", "text": f"↑ {ref['label']}"})

        if shelf_refs:
            content.append({
                "type": "text",
                "text": (
                    "REFERENCE — IDEAL SHELVES: Here is how AVTD products look on real store shelves "
                    "(reference photos from the sales manager):"
                ),
            })
            for ref in shelf_refs:
                content.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": ref["media_type"], "data": ref["b64"]},
                })
                content.append({"type": "text", "text": f"↑ {ref['label']}"})

        content.append({
            "type": "text",
            "text": (
                "---\nNow analyze the following photos from a real agent store visit. "
                "Find the AVTD brands you just learned about on the store shelves:"
            ),
        })

    for b64 in photo_b64_list[:5]:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })

    user_text = (
        f"Analyze {len(photo_b64_list[:5])} photos from one store visit "
        "according to AVTD merchandising standards. Combine data from all photos into one report."
    )
    if agent_comment:
        user_text += f"\nAgent comment: {agent_comment}"
    user_text += "\nReturn only JSON with facts."
    content.append({"type": "text", "text": user_text})

    raw = _call_claude_vision(client, content, SYSTEM_PROMPT)
    try:
        vision_result = json.loads(raw)
    except json.JSONDecodeError as parse_err:
        logger.error(
            f"[PhotoReport] JSON parse failed: {parse_err}\n"
            f"  stop_reason={getattr(raw, 'stop_reason', 'unknown')}\n"
            f"  raw ({len(raw)} chars): {raw[:500]}"
        )
        raise

    retried_categories: list[str] = []
    for category in ("vodka", "wine", "cognac", "sparkling"):
        cat_data = vision_result.get(category, {})
        if cat_data.get("confidence") == "low":
            logger.info(f"[PhotoReport] Low confidence on '{category}', running focused retry")
            retry = _analyze_focused_sync(client, photo_b64_list, category)
            if retry and retry.get("confidence") in ("high", "medium"):
                vision_result[category] = retry
                retried_categories.append(category)
                logger.info(f"[PhotoReport] Retry improved '{category}' to confidence={retry['confidence']}")
            else:
                logger.info(f"[PhotoReport] Retry did not improve '{category}', keeping low-confidence result")

    if retried_categories:
        vision_result["retried_categories"] = retried_categories

    return vision_result
