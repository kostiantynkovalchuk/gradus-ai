"""
Brand reference metadata for AVTD photo report analysis.

This module provides visual anchors and reference data used to improve
Claude AI's brand recognition in shelf photos. The data is embedded
into focused prompts to guide the model toward correct brand identification.
"""

BRAND_VISUAL_ANCHORS: dict = {
    "greenday": {
        "ua_name": "GreenDay",
        "category": "vodka",
        "label_colors": ["green", "black", "white", "silver"],
        "logo_description": "Bold 'GreenDay' wordmark in green on white or black background",
        "bottle_shapes": ["standard 0.5L", "0.7L sleek"],
        "skus": [
            "GreenDay Classic — green label, white text",
            "GreenDay Ice — light-blue accent, snowflake motif",
            "GreenDay Evolution — dark premium label, metallic silver",
            "GreenDay Planet — globe motif, eco-green design",
            "GreenDay Discovery — explorer motif, gold accents",
        ],
        "common_confusions": ["Nemiroff (similar green tones)", "Хортиця green line"],
        "placement_notes": "Typically eye-level and top shelf; premium SKUs on highest shelf",
    },
    "ukrainka": {
        "ua_name": "Українка",
        "category": "vodka",
        "label_colors": ["blue", "yellow", "white"],
        "logo_description": "Ukrainian flag colors — blue and yellow, with 'Українка' Cyrillic text",
        "bottle_shapes": ["standard 0.5L"],
        "skus": [
            "Українка Classic — blue/yellow label",
            "Українка Пшенична — wheat motif, golden tones",
        ],
        "common_confusions": ["Хортиця (blue label)", "Козацька Рада"],
        "placement_notes": "Usually adjacent to GreenDay on AVTD-facing shelf block",
    },
    "helsinki": {
        "ua_name": "Helsinki",
        "category": "vodka",
        "label_colors": ["white", "blue", "grey"],
        "logo_description": "Nordic-style label, 'Helsinki' in serif or clean sans-serif font",
        "bottle_shapes": ["standard 0.5L", "premium 0.7L"],
        "skus": [
            "Helsinki Original — white/blue clean label",
            "Helsinki Silver — silver metallic label",
        ],
        "common_confusions": ["Finlandia (similar Nordic style)", "Absolut"],
        "placement_notes": "Often placed below or beside GreenDay",
    },
    "adjari": {
        "ua_name": "Аджарі",
        "category": "cognac",
        "label_colors": ["gold", "brown", "cream", "dark-green"],
        "logo_description": "Georgian-style label with 'Adjari' in Latin and/or Cyrillic, gold accents",
        "bottle_shapes": ["cognac 0.5L", "cognac 0.75L"],
        "skus": [
            "Adjari 3★ — three stars, cream/gold label",
            "Adjari 5★ — five stars, darker premium label",
            "Adjari VSOP — black/gold premium packaging",
        ],
        "common_confusions": ["Грузинський коньяк (similar label style)", "Метаксa"],
        "placement_notes": "Cognac section, typically center shelf",
    },
    "dovbush": {
        "ua_name": "Довбуш",
        "category": "cognac",
        "label_colors": ["dark-brown", "green", "gold"],
        "logo_description": "Ukrainian heritage label with Carpathian motifs, 'Довбуш' Cyrillic",
        "bottle_shapes": ["cognac 0.5L"],
        "skus": [
            "Довбуш 3★",
            "Довбуш 5★",
        ],
        "common_confusions": ["Zakarpattia regional brands"],
        "placement_notes": "Usually grouped with Adjari in cognac block",
    },
    "klinkov": {
        "ua_name": "Клінков",
        "category": "cognac",
        "label_colors": ["red", "gold", "dark"],
        "logo_description": "Red label with crossed swords motif, 'Klinkov' or 'Клінков' text",
        "bottle_shapes": ["cognac 0.5L"],
        "skus": ["Klinkov 3★", "Klinkov 5★"],
        "common_confusions": ["Armenian brandy labels"],
        "placement_notes": "Positioned in AVTD cognac block",
    },
    "jean_jack": {
        "ua_name": "Jean Jack",
        "category": "cognac",
        "label_colors": ["cream", "gold", "dark-blue"],
        "logo_description": "French-style label, 'Jean Jack' in elegant script",
        "bottle_shapes": ["cognac 0.5L", "0.7L"],
        "skus": ["Jean Jack VS", "Jean Jack VSOP"],
        "common_confusions": ["Courvoisier (similar style)", "Hennessy"],
        "placement_notes": "Premium cognac shelf placement",
    },
    "villa_ua": {
        "ua_name": "Villa UA",
        "category": "wine",
        "label_colors": ["white", "green", "red", "gold"],
        "logo_description": "Elegant villa/estate motif, 'Villa UA' in serif font",
        "bottle_shapes": ["750ml standard wine"],
        "skus": [
            "Villa UA Chardonnay",
            "Villa UA Sauvignon Blanc",
            "Villa UA Cabernet Sauvignon",
            "Villa UA Merlot",
        ],
        "common_confusions": ["Villa Krim (similar name)", "Inkerman estate wines"],
        "placement_notes": "Wine section, center to upper shelf",
    },
    "didi_lari": {
        "ua_name": "Діді Ларі",
        "category": "wine",
        "label_colors": ["red", "terracotta", "gold"],
        "logo_description": "Georgian-style label with 'Didi Lari' text, cultural motifs",
        "bottle_shapes": ["750ml standard wine"],
        "skus": ["Didi Lari Red", "Didi Lari White", "Didi Lari Semi-Sweet"],
        "common_confusions": ["Other Georgian wine imports"],
        "placement_notes": "Grouped with imported wines or AVTD wine block",
    },
    "kristi_valley": {
        "ua_name": "Kristі Valley",
        "category": "wine",
        "label_colors": ["purple", "white", "gold"],
        "logo_description": "Valley/landscape motif, 'Kristi Valley' text",
        "bottle_shapes": ["750ml standard wine"],
        "skus": ["Kristi Valley Red", "Kristi Valley White"],
        "common_confusions": ["Similar domestic wine labels"],
        "placement_notes": "AVTD wine block",
    },
    "villa_ua_sparkling": {
        "ua_name": "Villa UA (ігристе)",
        "category": "sparkling",
        "label_colors": ["white", "gold", "silver"],
        "logo_description": "Same villa motif as Villa UA wine but with bubbles/sparkle elements",
        "bottle_shapes": ["750ml sparkling/champagne"],
        "skus": [
            "Villa UA Brut",
            "Villa UA Semi-Dry",
            "Villa UA Rosé",
        ],
        "common_confusions": ["Артемівське", "Ігристе Кримське", "Freixenet (similar gold foil)"],
        "placement_notes": "Sparkling wine section or holiday display",
    },
}


AVTD_SHELF_STRIP_DESCRIPTION = (
    "AVTD shelf strip (шелфстрипер): a horizontal price-channel insert with the AVTD or "
    "brand logo (GreenDay / AVTD group), typically placed at the bottom edge of a shelf "
    "facing. Usually 6–8cm tall, spanning the full shelf width. Color: green or white with "
    "green accent."
)

POS_MATERIAL_TYPES = {
    "shelf_strip": "Horizontal strip attached to shelf edge with brand branding",
    "wobbler": "Small dangling card attached to shelf, protruding into aisle",
    "price_holder": "Plastic holder containing a price card with brand logo",
    "stopper": "Rigid divider between brand blocks on shelf",
    "poster": "Printed poster on shelf back panel or wall behind shelf",
}

COMPETITOR_VODKA_BRANDS = [
    "Nemiroff",
    "Хортиця / Khortytsa",
    "Козацька Рада",
    "Первак",
    "Parlamenta",
    "Morosha",
    "Finlandia",
    "Absolut",
    "Smirnoff",
    "Stuffed",
    "Medoff",
    "Shabo (vodka line)",
]

COMPETITOR_COGNAC_BRANDS = [
    "Закарпатський",
    "Метаксa / Metaxa",
    "Courvoisier",
    "Hennessy",
    "Remy Martin",
    "Ararat",
    "Aznauri",
    "Kizlyar",
    "Таврія (cognac)",
]


def get_brand_anchor_text(category: str) -> str:
    """
    Return a human-readable visual anchor summary for a given category
    to be injected into Claude prompts for improved brand recognition.
    """
    brands = [b for b in BRAND_VISUAL_ANCHORS.values() if b["category"] == category]
    if not brands:
        return ""

    lines = [f"BRAND VISUAL REFERENCE — {category.upper()}:"]
    for brand in brands:
        lines.append(f"\n• {brand['ua_name']}:")
        lines.append(f"  Label colors: {', '.join(brand['label_colors'])}")
        lines.append(f"  Description: {brand['logo_description']}")
        if brand.get("common_confusions"):
            lines.append(f"  Common confusions to avoid: {', '.join(brand['common_confusions'])}")
        if brand.get("skus"):
            lines.append(f"  SKUs: {'; '.join(brand['skus'][:3])}")

    if category == "vodka":
        lines.append(f"\nKnown competitor brands to count separately: {', '.join(COMPETITOR_VODKA_BRANDS[:6])}")
    elif category == "cognac":
        lines.append(f"\nKnown competitor brands: {', '.join(COMPETITOR_COGNAC_BRANDS[:5])}")

    return "\n".join(lines)


def get_all_avtd_brand_names() -> list[str]:
    """Return flat list of all AVTD brand Ukrainian names for quick lookup."""
    return [b["ua_name"] for b in BRAND_VISUAL_ANCHORS.values()]
