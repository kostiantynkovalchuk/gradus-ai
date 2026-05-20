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
}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FEW-SHOT EXAMPLES — VERIFIED BY EXPERT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

These are verified examples showing correct JSON output for reference shelf photos.
Use them to calibrate your counting and share calculation.

EXAMPLE 1 — shelf_ref_02.jpg (ADJARI closeup, verified)
This photo shows one shelf row with ADJARI cognac lineup.
Expert verified: cognac AVTD share = 100%.
Correct output for cognac section:
{
  "confidence": "high",
  "adjari_facings": 11,
  "adjari_skus": ["Cherry", "Orange", "3★", "5★ tubus", "5★"],
  "dovbush_facings": 0,
  "jean_jack_facings": 0,
  "klinkov_facings": 0,
  "competitor_facings": 1,
  "competitor_brands": ["Ukrainian Soul"],
  "total_cognac_facings": 12
}
Key lesson: When you can clearly read ADJARI label — count confidently.
Partial photo = "medium" confidence but still count what is visible.

EXAMPLE 2 — shelf_ref_21.jpg (full store overview, verified)
This photo shows a complete alcohol section, both edges visible.
Expert verified: vodka AVTD share = 97%, cognac AVTD share = 98%.
This means nearly ALL bottles on this shelf are AVTD brands.

CRITICAL LESSON FROM THIS EXAMPLE:
When a shelf has strong AVTD signage and predominantly AVTD-shaped bottles,
do NOT default unclear bottles to "competitor". Instead:
- If bottle shape/color matches known AVTD brand → count as AVTD
- If bottle is truly unidentifiable → add to notes, do NOT inflate competitor_facings
- "other vodka x6" on an AVTD-dominant shelf is likely AVTD, not competitor

Correct approach for share calculation:
- Count confirmed AVTD facings
- Count confirmed competitor facings (only if brand is clearly identifiable as non-AVTD)
- Unidentified bottles on AVTD-dominant shelf → add to relevant AVTD category, not competitor
- Result: vodka share should reflect ~97% AVTD on this shelf

GENERAL RULE FROM BOTH EXAMPLES:
1. Closeup photo + readable label = count precisely, high confidence
2. Wide shot + AVTD-dominant shelf = assume AVTD for unreadable bottles,
   note uncertainty in "notes" field
3. Never inflate competitor_facings with unidentified bottles
4. If unsure about a specific bottle — add it to the AVTD category it most likely
   belongs to based on shelf context, and note it

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

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


_CATEGORY_RETRY_PROMPTS = {
    "cognac": """You are re-analyzing a shelf photo. The first analysis found a cognac/brandy shelf row but MISSED AVTD cognac brands.

Your ONLY task: find AVTD cognac brands on these shelves. Ignore vodka and wine.

ADJARI (Аджарі) — what to look for:
- Dark amber ROUNDED bottles with DIAMOND MESH/NET texture
- Gold cap, mountain landscape label, eagle emblem, text "ADJARI"
- Variants: 3★, 4★ Квартелі, 5★ (in tube), 7★ Мудрий (black label), Cherry, Orange
- MOST COMMON cognac brand on Ukrainian shelves

DOVBUSH (Довбуш) — what to look for:
- SQUARE bottles (NOT rounded like ADJARI!), WOODEN CORK cap
- Portrait of Cossack warrior, text "ДОВБУШ" or "DOVBUSH"
- Variants: 3★, 4★ Big Four (green label), Honey/Медовий (orange label)

JEAN JACK (Жан-Жак) — what to look for:
- Flat/square bottles with horseman medallion
- Text "ЖАН-ЖАК" or "JEAN JACK"
- Variants: Classic 3★, France 4★, Reserve 5★, Amaretto, Honey, Orange

Count ALL AVTD cognac facings. Also count competitor cognac (Aznauri, Tavria, etc.).
Do NOT include imported whisky (Jameson, Jack Daniel's) — only cognac/brandy.

Return ONLY this JSON:
{
  "adjari_facings": 0,
  "dovbush_facings": 0,
  "jean_jack_facings": 0,
  "klinkov_facings": 0,
  "competitor_facings": 0,
  "total_cognac_facings": 0,
  "search_notes": ""
}""",

    "wine": """You are re-analyzing a shelf photo. The first analysis found a wine shelf row but MISSED AVTD wine brands.

Your ONLY task: find AVTD wine brands on these shelves. Ignore vodka and cognac.

VILLA UA — what to look for:
- KEY IDENTIFIER: MEDALLION/COIN on every label
- Standard 750ml wine bottles (taller and thinner than vodka)
- Collections: Classic (most common), Art, Avtorskaya, Fruit Wine
- Colors: pale green (white wine), dark (red wine), pink (rosé)
- WARNING: Villa Krim is NOT Villa UA — it is a COMPETITOR!

KRISTI VALLEY — text "KRISTI VALLEY" on label, French-style names
KOSHER — kosher certification symbols, Star of David

Count ALL AVTD wine facings. Also count competitor wines.

Return ONLY this JSON:
{
  "villa_ua_facings": 0,
  "kristi_valley_facings": 0,
  "kosher_facings": 0,
  "competitor_facings": 0,
  "total_wine_facings": 0,
  "search_notes": ""
}""",

    "sparkling": """You are re-analyzing a shelf photo. The first analysis found a sparkling wine shelf row but MISSED AVTD sparkling brands.

Your ONLY task: find AVTD sparkling wine. Ignore still wine, vodka, cognac.

VILLA UA SPARKLING — what to look for:
- Dark CHAMPAGNE-SHAPED bottles with FOIL on neck
- Same MEDALLION/COIN as still Villa UA wine, but on champagne bottle
- Variants: Bellini, Brut, Grand Cuvee, Muscat, Pina Colada, Rosé, Salute Asti, Semisweet
- Usually on SEPARATE shelf from still wine
- Do NOT confuse with still Villa UA wine — sparkling has champagne bottle shape!

VILLA UA FRIZZANTE — slim bottles, Light Rosé and Light White

Count ALL AVTD sparkling facings. Also count competitor sparkling (Odesa, Oreanda, Artemivske).

Return ONLY this JSON:
{
  "villa_ua_sparkling_facings": 0,
  "villa_ua_frizzante_facings": 0,
  "competitor_facings": 0,
  "total_sparkling_facings": 0,
  "search_notes": ""
}""",
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


def _retry_ukrainka_helsinki(client: anthropic.Anthropic, photo_b64_list: list[str]) -> dict | None:
    """Focused second pass specifically looking for Ukrainka and Helsinki.

    Triggered when GreenDay is found but Ukrainka + Helsinki = 0,
    which is wrong 70% of the time based on expert corrections.
    Only Ukrainka/Helsinki reference images are sent to keep the model focused.
    """
    RETRY_PROMPT = """You are re-analyzing a shelf photo. The first analysis found GreenDay vodka but MISSED Ukrainka and Helsinki.

Your ONLY task: find Ukrainka and Helsinki bottles on these shelves. Ignore everything else.

UKRAINKA (Українка) — what to look for:
- TRANSPARENT/CLEAR glass bottles (not green like GreenDay)
- Wide WHITE label with large Cyrillic text "УКРАЇНКА"
- Diamond/geometric pattern carved into the glass on some variants
- Silver/grey metal cap
- Variants that ALL count as Ukrainka:
  * Traditional — white label, clear bottle
  * Crystal — silver/diamond label, clear bottle with geometric pattern
  * Tinctures (настоянки) — colored liquid (red=berry, green=herb, dark=black currant) but SAME bottle shape and "УКРАЇНКА" text
- Usually stands in groups of 3-6 bottles
- Often positioned NEAR GreenDay on the same shelf row

HELSINKI (Хельсінкі) — what to look for:
- TRANSPARENT/CLEAR glass bottles (similar to Ukrainka but different label)
- Winter/mountain landscape scene on label
- Text "HELSINKI" in Latin letters
- 5 different label colors: light blue (Ice Palace), grey (Winter Capital), dark blue (Ultramarin), orange (Frosty Citrus), brown (Salted Caramel)
- Often stands NEXT TO GreenDay
- Do NOT confuse with Klinkov dark boxes — Helsinki is always a transparent BOTTLE

Scan EVERY shelf row carefully. Count each facing.

Return ONLY this JSON:
{
  "ukrainka_facings": 0,
  "ukrainka_variants": [],
  "helsinki_facings": 0,
  "helsinki_variants": [],
  "search_notes": "describe where you looked and what you found"
}"""

    content = []

    # Only Ukrainka and Helsinki reference images — keeps model focused
    ua_hel_refs = [
        r for r in BRAND_REFERENCES
        if any(k in r.get("name", "") for k in ("ukrainka", "helsinki"))
    ]
    if ua_hel_refs:
        content.append({
            "type": "text",
            "text": "REFERENCE — look carefully at these AVTD vodka brands you must find:",
        })
        for ref in ua_hel_refs:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": ref["media_type"], "data": ref["b64"]},
            })
            content.append({"type": "text", "text": f"↑ {ref['label']}"})

    content.append({
        "type": "text",
        "text": "Now look at these shelf photos and find Ukrainka and Helsinki:",
    })
    for b64 in photo_b64_list[:5]:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })
    content.append({"type": "text", "text": RETRY_PROMPT})

    try:
        raw = _call_claude_vision(
            client=client,
            content=content,
            system="You are a shelf photo analyzer. Return only valid JSON.",
            max_tokens=1024,
            model=VISION,
        )
        result = json.loads(raw)
        logger.info(
            f"[PhotoReport] UA/HEL retry: UA={result.get('ukrainka_facings')}, "
            f"HEL={result.get('helsinki_facings')}, "
            f"notes={result.get('search_notes', '')[:120]}"
        )
        return result
    except Exception as e:
        logger.error(f"[PhotoReport] UA/HEL retry failed: {e}")
        return None


def _retry_category(client: anthropic.Anthropic, photo_b64_list: list[str], category: str) -> dict | None:
    """Focused second pass for a specific category.

    Sends only category-relevant reference images + a focused prompt.
    Triggered when shelf_scan mentions the category but all AVTD facings = 0.
    """
    prompt = _CATEGORY_RETRY_PROMPTS.get(category)
    if not prompt:
        return None

    category_ref_keywords = {
        "cognac": ["adjari", "dovbush", "jeanjack"],
        "wine": ["villaua_classic", "villaua_art", "villaua_avtor", "villaua_fruit", "kosher", "kristivalley"],
        "sparkling": ["villaua_sparkling", "villaua_fruit_frizzante"],
    }
    keywords = category_ref_keywords.get(category, [])

    content = []

    refs_added = 0
    for ref in BRAND_REFERENCES:
        name = ref.get("name", "")
        if any(kw in name for kw in keywords):
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": ref["media_type"], "data": ref["b64"]},
            })
            content.append({"type": "text", "text": f"REFERENCE: {ref['label']}"})
            refs_added += 1

    logger.info(f"[PhotoReport] {category} retry: {refs_added} reference images")

    content.append({
        "type": "text",
        "text": f"Now look at these shelf photos and find AVTD {category} brands:",
    })
    for b64 in photo_b64_list[:5]:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg", "data": b64},
        })
    content.append({"type": "text", "text": prompt})

    try:
        raw = _call_claude_vision(
            client=client,
            content=content,
            system="You are a shelf photo analyzer. Return only valid JSON.",
            max_tokens=1024,
            model=VISION,
        )
        result = json.loads(raw)
        logger.info(f"[PhotoReport] {category} retry result: {json.dumps(result, default=str)[:200]}")
        return result
    except Exception as e:
        logger.error(f"[PhotoReport] {category} retry failed: {e}")
        return None


def _merge_cognac_retry(result: dict, retry: dict) -> None:
    """Merge cognac retry findings into original result."""
    cognac = result.get("cognac", {})
    adjari = retry.get("adjari_facings") or 0
    dovbush = retry.get("dovbush_facings") or 0
    jeanjack = retry.get("jean_jack_facings") or 0
    klinkov = retry.get("klinkov_facings") or 0

    if adjari + dovbush + jeanjack + klinkov > 0:
        logger.info(f"[PhotoReport] Cognac retry found: ADJARI={adjari}, DOVBUSH={dovbush}, JJ={jeanjack}")
        cognac["adjari_facings"] = adjari
        cognac["dovbush_facings"] = dovbush
        cognac["jean_jack_facings"] = jeanjack
        cognac["klinkov_facings"] = klinkov
        cognac["competitor_facings"] = retry.get("competitor_facings") or cognac.get("competitor_facings") or 0
        cognac["total_cognac_facings"] = retry.get("total_cognac_facings") or 0
        cognac["other_avtd_cognac_facings"] = 0
        result["cognac"] = cognac
        notes = result.get("notes", "") or ""
        result["notes"] = (notes + " [Cognac retry: found AVTD cognac after initial scan missed them]").strip()
    else:
        logger.info("[PhotoReport] Cognac retry confirmed 0 AVTD cognac — keeping original")


def _merge_wine_retry(result: dict, retry: dict) -> None:
    """Merge wine retry findings into original result."""
    wine = result.get("wine", {})
    villaua = retry.get("villa_ua_facings") or 0
    kristivalley = retry.get("kristi_valley_facings") or 0
    kosher = retry.get("kosher_facings") or 0

    if villaua + kristivalley + kosher > 0:
        logger.info(f"[PhotoReport] Wine retry found: VillaUA={villaua}, KV={kristivalley}, Kosher={kosher}")
        wine["villa_ua_facings"] = villaua
        wine["kristi_valley_facings"] = kristivalley
        wine["kosher_facings"] = kosher
        wine["competitor_facings"] = retry.get("competitor_facings") or wine.get("competitor_facings") or 0
        wine["total_wine_facings"] = retry.get("total_wine_facings") or 0
        wine["didi_lari_facings"] = 0
        wine["other_avtd_wine_facings"] = 0
        result["wine"] = wine
        notes = result.get("notes", "") or ""
        result["notes"] = (notes + " [Wine retry: found AVTD wine after initial scan missed them]").strip()
    else:
        logger.info("[PhotoReport] Wine retry confirmed 0 AVTD wine — keeping original")


def _merge_sparkling_retry(result: dict, retry: dict) -> None:
    """Merge sparkling retry findings into original result."""
    sparkling = result.get("sparkling", {})
    villaua_spark = retry.get("villa_ua_sparkling_facings") or 0
    frizzante = retry.get("villa_ua_frizzante_facings") or 0

    if villaua_spark + frizzante > 0:
        logger.info(f"[PhotoReport] Sparkling retry found: VillaUA={villaua_spark}, Frizzante={frizzante}")
        sparkling["villa_ua_sparkling_facings"] = villaua_spark + frizzante
        sparkling["competitor_facings"] = retry.get("competitor_facings") or sparkling.get("competitor_facings") or 0
        sparkling["total_sparkling_facings"] = retry.get("total_sparkling_facings") or 0
        result["sparkling"] = sparkling
        notes = result.get("notes", "") or ""
        result["notes"] = (notes + " [Sparkling retry: found Villa UA sparkling after initial scan missed them]").strip()
    else:
        logger.info("[PhotoReport] Sparkling retry confirmed 0 AVTD sparkling — keeping original")


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

    # ── Vodka-specific retry: GD found but UA + HEL = 0 ──────────────────────
    # This pattern is wrong 70% of the time per expert correction data.
    vodka = vision_result.get("vodka", {})
    gd  = vodka.get("greenday_facings") or 0
    ua  = vodka.get("ukrainka_facings") or 0
    hel = vodka.get("helsinki_facings") or 0

    if gd > 0 and ua == 0 and hel == 0:
        logger.info(f"[PhotoReport] Vodka retry triggered: GD={gd} but UA+HEL=0")
        retry_result = _retry_ukrainka_helsinki(client, photo_b64_list)

        if retry_result:
            retry_ua  = retry_result.get("ukrainka_facings") or 0
            retry_hel = retry_result.get("helsinki_facings") or 0

            if retry_ua > 0 or retry_hel > 0:
                logger.info(f"[PhotoReport] Vodka retry found: UA={retry_ua}, HEL={retry_hel}")
                vodka["ukrainka_facings"] = retry_ua
                vodka["helsinki_facings"] = retry_hel

                # Recalculate our_facings and total — retry may have found bottles missed in pass 1
                other_avtd   = vodka.get("other_avtd_vodka_facings") or 0
                new_our      = gd + retry_ua + retry_hel + other_avtd
                prev_our     = vodka.get("our_facings") or (gd + other_avtd)
                total        = vodka.get("total_vodka_facings") or 0
                if new_our > prev_our:
                    vodka["total_vodka_facings"] = total + (new_our - prev_our)
                vodka["our_facings"] = new_our

                vision_result["vodka"] = vodka
                notes = vision_result.get("notes", "") or ""
                vision_result["notes"] = (
                    notes + " [Vodka retry: found additional Ukrainka/Helsinki after initial scan missed them]"
                ).strip()
            else:
                logger.info("[PhotoReport] Vodka retry confirmed UA=0 HEL=0 — keeping original result")

    # ── Cognac retry: shelf_scan mentions cognac row but all AVTD cognac = 0 ──
    # ~30% outlier rate per expert correction data
    cognac = vision_result.get("cognac", {})
    adjari   = cognac.get("adjari_facings") or 0
    dovbush  = cognac.get("dovbush_facings") or 0
    klinkov  = cognac.get("klinkov_facings") or 0
    jeanjack = cognac.get("jean_jack_facings") or 0
    total_avtd_cognac = adjari + dovbush + klinkov + jeanjack

    shelf_scan = vision_result.get("shelf_scan", [])
    has_cognac_row = any(
        "cognac" in (row.get("category", "") or "").lower() or
        "brandy" in (row.get("category", "") or "").lower() or
        any(
            "adjari" in b.lower() or "dovbush" in b.lower() or "cognac" in b.lower()
            for b in row.get("brands", [])
        )
        for row in shelf_scan
    )

    if has_cognac_row and total_avtd_cognac == 0:
        logger.info("[PhotoReport] Cognac retry triggered: shelf_scan has cognac row but AVTD cognac=0")
        retry_result = _retry_category(client, photo_b64_list, "cognac")
        if retry_result:
            _merge_cognac_retry(vision_result, retry_result)

    # ── Wine retry: shelf_scan mentions wine row but all AVTD wine = 0 ──
    # ~52% outlier rate per expert correction data
    wine = vision_result.get("wine", {})
    villaua      = wine.get("villa_ua_facings") or 0
    didilari     = wine.get("didi_lari_facings") or 0
    kristivalley = wine.get("kristi_valley_facings") or 0
    kosher       = wine.get("kosher_facings") or 0
    total_avtd_wine = villaua + didilari + kristivalley + kosher

    has_wine_row = any(
        "wine" in (row.get("category", "") or "").lower() or
        any(
            "villa" in b.lower() or "wine" in b.lower() or "didi" in b.lower()
            for b in row.get("brands", [])
        )
        for row in shelf_scan
    )

    if has_wine_row and total_avtd_wine == 0:
        logger.info("[PhotoReport] Wine retry triggered: shelf_scan has wine row but AVTD wine=0")
        retry_result = _retry_category(client, photo_b64_list, "wine")
        if retry_result:
            _merge_wine_retry(vision_result, retry_result)

    # ── Sparkling retry: shelf_scan mentions sparkling row but Villa UA sparkling = 0 ──
    # ~76% outlier rate per expert correction data
    sparkling     = vision_result.get("sparkling", {})
    villaua_spark = sparkling.get("villa_ua_sparkling_facings") or 0

    has_sparkling_row = any(
        "sparkling" in (row.get("category", "") or "").lower() or
        "asti" in (row.get("category", "") or "").lower() or
        any(
            "sparkling" in b.lower() or "asti" in b.lower() or
            "prosecco" in b.lower() or "champagne" in b.lower()
            for b in row.get("brands", [])
        )
        for row in shelf_scan
    )

    if has_sparkling_row and villaua_spark == 0:
        logger.info("[PhotoReport] Sparkling retry triggered: shelf_scan has sparkling row but Villa UA sparkling=0")
        retry_result = _retry_category(client, photo_b64_list, "sparkling")
        if retry_result:
            _merge_sparkling_retry(vision_result, retry_result)

    # ── Vodka low-share retry: AVTD share < 30% but total > 5 and confidence != low ──
    # Catches cases where AI found some AVTD vodka but massively under-counted —
    # e.g. report 118 returned 61% when expert verified 97%.
    _vodka = vision_result.get("vodka", {})
    _vodka_avtd = (
        (_vodka.get("greenday_facings") or 0) +
        (_vodka.get("ukrainka_facings") or 0) +
        (_vodka.get("helsinki_facings") or 0) +
        (_vodka.get("other_avtd_vodka_facings") or 0)
    )
    _vodka_total = _vodka.get("total_vodka_facings") or 0
    _vodka_share = (_vodka_avtd / _vodka_total * 100) if _vodka_total > 5 else None

    if (
        _vodka_share is not None
        and _vodka_share < 30
        and _vodka.get("confidence") != "low"
    ):
        logger.info(
            f"[PhotoReport] Vodka low-share retry: "
            f"{_vodka_avtd}/{_vodka_total} = {_vodka_share:.0f}%"
        )
        _retry = _analyze_focused_sync(client, photo_b64_list, "vodka")
        if _retry and _retry.get("confidence") in ("high", "medium"):
            _retry_avtd = (
                (_retry.get("greenday_facings") or 0) +
                (_retry.get("ukrainka_facings") or 0) +
                (_retry.get("helsinki_facings") or 0) +
                (_retry.get("other_avtd_vodka_facings") or 0)
            )
            if _retry_avtd > _vodka_avtd:
                _retry_total = _retry.get("total_vodka_facings") or _vodka_total
                _new_share = (_retry_avtd / _retry_total * 100) if _retry_total else 0
                logger.info(
                    f"[PhotoReport] Vodka low-share retry improved: "
                    f"{_vodka_share:.0f}% → {_new_share:.0f}%"
                )
                vision_result["vodka"] = _retry
                notes = vision_result.get("notes", "") or ""
                vision_result["notes"] = (
                    notes + f" [Vodka low-share retry: {_vodka_share:.0f}% → {_new_share:.0f}%]"
                ).strip()
            else:
                logger.info(
                    f"[PhotoReport] Vodka low-share retry did not improve: "
                    f"retry={_retry_avtd} vs original={_vodka_avtd}"
                )

    # ── Cognac low-share retry: AVTD share < 30% but total > 5 and confidence != low ──
    _cognac = vision_result.get("cognac", {})
    _cognac_avtd = (
        (_cognac.get("adjari_facings") or 0) +
        (_cognac.get("dovbush_facings") or 0) +
        (_cognac.get("jean_jack_facings") or 0) +
        (_cognac.get("klinkov_facings") or 0) +
        (_cognac.get("other_avtd_cognac_facings") or 0)
    )
    _cognac_total = _cognac.get("total_cognac_facings") or 0
    _cognac_share = (_cognac_avtd / _cognac_total * 100) if _cognac_total > 5 else None

    if (
        _cognac_share is not None
        and _cognac_share < 30
        and _cognac.get("confidence") != "low"
    ):
        logger.info(
            f"[PhotoReport] Cognac low-share retry: "
            f"{_cognac_avtd}/{_cognac_total} = {_cognac_share:.0f}%"
        )
        _retry_result = _retry_category(client, photo_b64_list, "cognac")
        if _retry_result:
            _retry_avtd_c = (
                (_retry_result.get("adjari_facings") or 0) +
                (_retry_result.get("dovbush_facings") or 0) +
                (_retry_result.get("jean_jack_facings") or 0) +
                (_retry_result.get("klinkov_facings") or 0)
            )
            if _retry_avtd_c > _cognac_avtd:
                _retry_total_c = _retry_result.get("total_cognac_facings") or _cognac_total
                _new_share_c = (_retry_avtd_c / _retry_total_c * 100) if _retry_total_c else 0
                logger.info(
                    f"[PhotoReport] Cognac low-share retry improved: "
                    f"{_cognac_share:.0f}% → {_new_share_c:.0f}%"
                )
                vision_result["cognac"].update({
                    "adjari_facings":         _retry_result.get("adjari_facings") or 0,
                    "adjari_skus":            _retry_result.get("adjari_skus") or _cognac.get("adjari_skus") or [],
                    "dovbush_facings":        _retry_result.get("dovbush_facings") or 0,
                    "jean_jack_facings":      _retry_result.get("jean_jack_facings") or 0,
                    "klinkov_facings":        _retry_result.get("klinkov_facings") or 0,
                    "other_avtd_cognac_facings": 0,
                    "competitor_facings":     _retry_result.get("competitor_facings") or _cognac.get("competitor_facings") or 0,
                    "total_cognac_facings":   _retry_total_c,
                })
                notes = vision_result.get("notes", "") or ""
                vision_result["notes"] = (
                    notes + f" [Cognac low-share retry: {_cognac_share:.0f}% → {_new_share_c:.0f}%]"
                ).strip()
            else:
                logger.info(
                    f"[PhotoReport] Cognac low-share retry did not improve: "
                    f"retry={_retry_avtd_c} vs original={_cognac_avtd}"
                )

    # ── Wine low-share retry: AVTD share < 20% but total > 5 and confidence != low ──
    _wine = vision_result.get("wine", {})
    _wine_avtd = (
        (_wine.get("villa_ua_facings") or 0) +
        (_wine.get("didi_lari_facings") or 0) +
        (_wine.get("kristi_valley_facings") or 0) +
        (_wine.get("kosher_facings") or 0) +
        (_wine.get("other_avtd_wine_facings") or 0)
    )
    _wine_total = _wine.get("total_wine_facings") or 0
    _wine_share = (_wine_avtd / _wine_total * 100) if _wine_total > 5 else None

    if (
        _wine_share is not None
        and _wine_share < 20
        and _wine.get("confidence") != "low"
    ):
        logger.info(
            f"[PhotoReport] Wine low-share retry: "
            f"{_wine_avtd}/{_wine_total} = {_wine_share:.0f}%"
        )
        _retry_result = _retry_category(client, photo_b64_list, "wine")
        if _retry_result:
            _retry_avtd_w = (
                (_retry_result.get("villa_ua_facings") or 0) +
                (_retry_result.get("kristi_valley_facings") or 0) +
                (_retry_result.get("kosher_facings") or 0)
            )
            if _retry_avtd_w > _wine_avtd:
                _retry_total_w = _retry_result.get("total_wine_facings") or _wine_total
                _new_share_w = (_retry_avtd_w / _retry_total_w * 100) if _retry_total_w else 0
                logger.info(
                    f"[PhotoReport] Wine low-share retry improved: "
                    f"{_wine_share:.0f}% → {_new_share_w:.0f}%"
                )
                vision_result["wine"].update({
                    "villa_ua_facings":         _retry_result.get("villa_ua_facings") or 0,
                    "didi_lari_facings":         _retry_result.get("didi_lari_facings") or 0,
                    "kristi_valley_facings":     _retry_result.get("kristi_valley_facings") or 0,
                    "kosher_facings":            _retry_result.get("kosher_facings") or 0,
                    "other_avtd_wine_facings":   0,
                    "competitor_facings":        _retry_result.get("competitor_facings") or _wine.get("competitor_facings") or 0,
                    "total_wine_facings":        _retry_total_w,
                })
                notes = vision_result.get("notes", "") or ""
                vision_result["notes"] = (
                    notes + f" [Wine low-share retry: {_wine_share:.0f}% → {_new_share_w:.0f}%]"
                ).strip()
            else:
                logger.info(
                    f"[PhotoReport] Wine low-share retry did not improve: "
                    f"retry={_retry_avtd_w} vs original={_wine_avtd}"
                )

    return vision_result
