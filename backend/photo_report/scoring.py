import logging

logger = logging.getLogger(__name__)


def calculate_score(vision_data: dict) -> dict:
    score = 100
    errors = []
    info = []
    auto_fail = False

    v = vision_data.get("vodka", {})
    gd = v.get("greenday_facings", 0)
    ua = v.get("ukrainka_facings", 0)
    hel = v.get("helsinki_facings", 0)
    other_v = v.get("other_avtd_vodka_facings", 0)
    our_vodka = gd + ua + hel + other_v
    total_vodka = v.get("total_vodka_facings", 0)
    vodka_share = round(our_vodka / total_vodka * 100) if total_vodka > 0 else 0
    vodka_passed = vodka_share >= 25

    if total_vodka > 0 and not vodka_passed:
        auto_fail = True
        score -= 15
        errors.append({
            "code": "1_108608",
            "description": f"Частка полиці горілки {vodka_share}% < 25% — провал звіту",
            "brand": "AVTD Горілка",
            "severity": "auto_fail"
        })

    if not vision_data.get("has_general_overview", True):
        score -= 20
        errors.append({
            "code": "NP59_200009734",
            "description": "Відсутній загальний огляд всіх полиць",
            "brand": "",
            "severity": "standard"
        })

    pos = vision_data.get("pos_materials", {})
    if pos.get("competitor_branded_pos_present") and not pos.get("avtd_shelf_strip_present"):
        score -= 10
        errors.append({
            "code": "1_108106",
            "description": "Відсутній шелфстрипер AVTD при наявності конкурентських POS",
            "brand": "GREENDAY",
            "severity": "standard"
        })

    skipped_codes = {"1_108106", "1_108608", "NP59_200009734"}
    for mv in vision_data.get("merchandise_violations", []):
        if mv.get("code", "") not in skipped_codes:
            sev = mv.get("severity", "standard")
            score -= 25 if sev == "auto_fail" else 10
            if sev == "auto_fail":
                auto_fail = True
            errors.append({
                "code": mv.get("code", ""),
                "description": mv.get("description", ""),
                "brand": mv.get("brand", ""),
                "severity": sev
            })

    ps = vision_data.get("premium_shelf", {})
    if ps.get("top_shelf_visible", False):
        gd_on_top = any([
            ps.get("gd_evolution_present"),
            ps.get("gd_planet_present"),
            ps.get("gd_discovery_present")
        ])
        if not gd_on_top:
            score -= 10
            errors.append({
                "code": "ELITE_SHELF",
                "description": "GreenDay Evolution/Planet/Discovery відсутні на елітній полиці",
                "brand": "GREENDAY",
                "severity": "standard"
            })
    else:
        score -= 5
        info.append("Верхня полиця не видна на фото")

    c = vision_data.get("cognac", {})
    our_cognac = (
        c.get("adjari_facings", 0)
        + c.get("dovbush_facings", 0)
        + c.get("klinkov_facings", 0)
        + c.get("jean_jack_facings", 0)
        + c.get("other_avtd_cognac_facings", 0)
    )
    total_cognac = c.get("total_cognac_facings", 0)
    cognac_share = round(our_cognac / total_cognac * 100) if total_cognac > 0 else 0

    w = vision_data.get("wine", {})
    our_wine = (
        w.get("villa_ua_facings", 0)
        + w.get("didi_lari_facings", 0)
        + w.get("kristi_valley_facings", 0)
        + w.get("kosher_facings", 0)
        + w.get("other_avtd_wine_facings", 0)
    )
    total_wine = w.get("total_wine_facings", 0)
    wine_share = round(our_wine / total_wine * 100) if total_wine > 0 else 0

    sp = vision_data.get("sparkling", {})
    our_sparkling = sp.get("villa_ua_sparkling_facings", 0)
    total_sparkling = sp.get("total_sparkling_facings", 0)
    sparkling_share = round(our_sparkling / total_sparkling * 100) if total_sparkling > 0 else 0

    standard_errors_count = sum(1 for e in errors if e.get("severity") != "auto_fail")

    if auto_fail:
        score = min(score, 55)
        passed = False
    elif standard_errors_count > 2 or score < 70:
        passed = False
    else:
        passed = True

    score = max(0, score)

    return {
        "score": score,
        "passed": passed,
        "trade_point_type": vision_data.get("trade_point_type", "retail"),
        "photo_quality": {
            "has_overview": vision_data.get("has_general_overview", False),
            "overview_note": vision_data.get("overview_note", ""),
            "photos_analyzed": vision_data.get("photos_analyzed", 1),
        },
        "errors": errors,
        "info": info,
        "shelf_share": {
            "vodka": {
                "our_facings": our_vodka,
                "total_facings": total_vodka,
                "percent": vodka_share,
                "threshold": 25,
                "passed": vodka_passed,
                "breakdown": {"greenday": gd, "ukrainka": ua, "helsinki": hel}
            },
            "cognac": {
                "our_facings": our_cognac,
                "total_facings": total_cognac,
                "percent": cognac_share,
                "threshold": 33,
                "passed": cognac_share >= 33
            },
            "wine": {
                "our_facings": our_wine,
                "total_facings": total_wine,
                "percent": wine_share,
                "threshold": 40,
                "passed": wine_share >= 40
            },
            "sparkling": {
                "our_facings": our_sparkling,
                "total_facings": total_sparkling,
                "percent": sparkling_share,
                "threshold": 20,
                "passed": sparkling_share >= 20
            }
        },
        "elite_shelf_check": {
            "elite_section_exists": ps.get("top_shelf_visible", False),
            "gd_evolution_on_top": any([
                ps.get("gd_evolution_present"),
                ps.get("gd_planet_present"),
                ps.get("gd_discovery_present")
            ]),
            "imports_visible": ps.get("imported_brands_visible", [])
        },
        "pos_materials": pos,
        "brands_found": vision_data.get("brands_found", {}),
        "notes": vision_data.get("notes", ""),
        "phase": 1,
        "scored_categories": ["vodka"],
        "info_only_categories": ["wine", "cognac", "sparkling"]
    }
