import logging

logger = logging.getLogger(__name__)


def validate_counts(vision_data: dict) -> list[str]:
    """Flag suspicious count patterns that may indicate detection errors."""
    warnings = []

    v = vision_data.get("vodka", {})
    gd = v.get("greenday_facings") or 0
    ua = v.get("ukrainka_facings") or 0
    hel = v.get("helsinki_facings") or 0
    total_vodka = v.get("total_vodka_facings") or 0
    our_vodka = gd + ua + hel

    if gd >= 6 and ua == 0 and hel == 0:
        warnings.append(
            f"⚠️ GreenDay знайдено ({gd}шт), але Ukrainka та Helsinki = 0. "
            "Можливо, не всі наші бренди розпізнано."
        )

    if total_vodka > 0 and our_vodka > 0 and (our_vodka / total_vodka) > 0.8 and ua == 0 and hel == 0:
        warnings.append(
            "⚠️ Частка горілки >80% тільки за рахунок GreenDay — "
            "перевірте фото на наявність Ukrainka/Helsinki."
        )

    c = vision_data.get("cognac", {})
    total_cognac = c.get("total_cognac_facings") or 0
    if total_cognac == 0 and vision_data.get("shelf_scan"):
        for row in vision_data["shelf_scan"]:
            cat_lower = (row.get("category") or "").lower()
            if "cognac" in cat_lower or "коньяк" in cat_lower or "brandy" in cat_lower:
                warnings.append(
                    "⚠️ Виявлено коньячну полицю в рядковому скануванні, "
                    "але підрахунок = 0. Можливо, бренди не розпізнано."
                )
                break

    return warnings


def _safe_int(val) -> int:
    if val is None:
        return 0
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def calculate_score(vision_data: dict) -> dict:
    score = 100
    errors = []
    info = []
    auto_fail = False

    warnings = validate_counts(vision_data)

    v = vision_data.get("vodka", {})
    v_confidence = v.get("confidence", "high")

    if v_confidence != "low":
        gd = _safe_int(v.get("greenday_facings"))
        ua = _safe_int(v.get("ukrainka_facings"))
        hel = _safe_int(v.get("helsinki_facings"))
        other_v = _safe_int(v.get("other_avtd_vodka_facings"))
        our_vodka = gd + ua + hel + other_v
        total_vodka = _safe_int(v.get("total_vodka_facings"))
        vodka_share = round(our_vodka / total_vodka * 100) if total_vodka > 0 else 0
        vodka_passed = vodka_share >= 25

        if total_vodka > 0 and not vodka_passed:
            auto_fail = True
            score -= 15
            errors.append({
                "code": "1_108608",
                "description": f"Частка полиці горілки {vodka_share}% < 25% — провал звіту",
                "brand": "AVTD Горілка",
                "severity": "auto_fail",
            })
    else:
        gd = ua = hel = other_v = our_vodka = total_vodka = 0
        vodka_share = None
        vodka_passed = None
        info.append("Горілка: не вдалося точно оцінити (фото занадто далеке або нечітке)")

    if not vision_data.get("has_general_overview", True):
        completeness = vision_data.get("photo_completeness", "complete")
        deduct = 10 if completeness in ("partial", "close_up") else 20
        score -= deduct
        errors.append({
            "code": "NP59_200009734",
            "description": "Відсутній загальний огляд всіх полиць",
            "brand": "",
            "severity": "standard",
        })

    pos = vision_data.get("pos_materials", {})
    if pos.get("competitor_branded_pos_present") and not pos.get("avtd_shelf_strip_present"):
        score -= 10
        errors.append({
            "code": "1_108106",
            "description": "Відсутній шелфстрипер AVTD при наявності конкурентських POS",
            "brand": "GREENDAY",
            "severity": "standard",
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
                "severity": sev,
            })

    ps = vision_data.get("premium_shelf", {})
    if ps.get("top_shelf_visible", False):
        gd_on_top = any([
            ps.get("gd_evolution_present"),
            ps.get("gd_planet_present"),
            ps.get("gd_discovery_present"),
        ])
        if not gd_on_top:
            score -= 10
            errors.append({
                "code": "ELITE_SHELF",
                "description": "GreenDay Evolution/Planet/Discovery відсутні на елітній полиці",
                "brand": "GREENDAY",
                "severity": "standard",
            })
    else:
        score -= 5
        info.append("Верхня полиця не видна на фото")

    c = vision_data.get("cognac", {})
    c_confidence = c.get("confidence", "high")
    if c_confidence != "low":
        our_cognac = (
            _safe_int(c.get("adjari_facings"))
            + _safe_int(c.get("dovbush_facings"))
            + _safe_int(c.get("klinkov_facings"))
            + _safe_int(c.get("jean_jack_facings"))
            + _safe_int(c.get("other_avtd_cognac_facings"))
        )
        total_cognac = _safe_int(c.get("total_cognac_facings"))
        cognac_share = round(our_cognac / total_cognac * 100) if total_cognac > 0 else 0
    else:
        our_cognac = total_cognac = cognac_share = None
        info.append("Коньяк: не вдалося точно оцінити (фото занадто далеке або нечітке)")

    w = vision_data.get("wine", {})
    w_confidence = w.get("confidence", "high")
    if w_confidence != "low":
        our_wine = (
            _safe_int(w.get("villa_ua_facings"))
            + _safe_int(w.get("didi_lari_facings"))
            + _safe_int(w.get("kristi_valley_facings"))
            + _safe_int(w.get("kosher_facings"))
            + _safe_int(w.get("other_avtd_wine_facings"))
        )
        total_wine = _safe_int(w.get("total_wine_facings"))
        wine_share = round(our_wine / total_wine * 100) if total_wine > 0 else 0
    else:
        our_wine = total_wine = wine_share = None
        info.append("Вино: не вдалося точно оцінити (фото занадто далеке або нечітке)")

    sp = vision_data.get("sparkling", {})
    s_confidence = sp.get("confidence", "high")
    if s_confidence != "low":
        our_sparkling = _safe_int(sp.get("villa_ua_sparkling_facings"))
        total_sparkling = _safe_int(sp.get("total_sparkling_facings"))
        sparkling_share = round(our_sparkling / total_sparkling * 100) if total_sparkling > 0 else 0
    else:
        our_sparkling = total_sparkling = sparkling_share = None
        info.append("Ігристе: не вдалося точно оцінити (фото занадто далеке або нечітке)")

    standard_errors_count = sum(1 for e in errors if e.get("severity") not in ("auto_fail",))

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
            "photo_completeness": vision_data.get("photo_completeness", "complete"),
        },
        "errors": errors,
        "info": info,
        "warnings": warnings,
        "shelf_share": {
            "vodka": {
                "our_facings": our_vodka,
                "total_facings": total_vodka,
                "percent": vodka_share,
                "threshold": 25,
                "passed": vodka_passed,
                "confidence": v_confidence,
                "breakdown": {"greenday": gd, "ukrainka": ua, "helsinki": hel},
            },
            "cognac": {
                "our_facings": our_cognac,
                "total_facings": total_cognac,
                "percent": cognac_share,
                "threshold": 33,
                "passed": (cognac_share >= 33) if cognac_share is not None else None,
                "confidence": c_confidence,
            },
            "wine": {
                "our_facings": our_wine,
                "total_facings": total_wine,
                "percent": wine_share,
                "threshold": 40,
                "passed": (wine_share >= 40) if wine_share is not None else None,
                "confidence": w_confidence,
            },
            "sparkling": {
                "our_facings": our_sparkling,
                "total_facings": total_sparkling,
                "percent": sparkling_share,
                "threshold": 20,
                "passed": (sparkling_share >= 20) if sparkling_share is not None else None,
                "confidence": s_confidence,
            },
        },
        "elite_shelf_check": {
            "elite_section_exists": ps.get("top_shelf_visible", False),
            "gd_evolution_on_top": any([
                ps.get("gd_evolution_present"),
                ps.get("gd_planet_present"),
                ps.get("gd_discovery_present"),
            ]),
            "imports_visible": ps.get("imported_brands_visible", []),
        },
        "pos_materials": pos,
        "brands_found": vision_data.get("brands_found", {}),
        "notes": vision_data.get("notes", ""),
        "retried_categories": vision_data.get("retried_categories", []),
        "phase": 1,
        "scored_categories": ["vodka"],
        "info_only_categories": ["wine", "cognac", "sparkling"],
    }
