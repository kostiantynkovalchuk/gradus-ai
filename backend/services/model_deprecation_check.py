"""
Monthly Claude model-deprecation check.

Fetches Anthropic's deprecation docs page, scans for active model identifiers
from ai_models.py, and alerts admin via notification_service ONLY when the
set of flagged models changes.  Results are persisted in the single-row
model_deprecation_state table (migration 044) for content-based deduplication.

Scheduler: 1st of every month at 09:05 UTC
Manual trigger: POST /admin/check-model-deprecations
"""

import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

import requests

from services import ai_models
from services.notification_service import notification_service

logger = logging.getLogger(__name__)

DEPRECATION_URL = "https://docs.claude.com/en/docs/about-claude/model-deprecations"
RETIREMENT_KEYWORDS = ["deprecat", "retire", "sunset", "end of life", "end-of-life"]
CONTEXT_WINDOW = 250
FETCH_TIMEOUT = 20


def _active_models() -> dict[str, str]:
    """Return {constant_name: model_id} for all identifiers in ai_models.py."""
    return {
        "SONNET": ai_models.SONNET,
        "HAIKU":  ai_models.HAIKU,
        "OPUS":   ai_models.OPUS,
    }


def _fetch_page(url: str) -> Optional[str]:
    try:
        r = requests.get(url, timeout=FETCH_TIMEOUT, headers={"User-Agent": "GradusAI-DeprecationCheck/1.0"})
        r.raise_for_status()
        return r.text.lower()
    except Exception as exc:
        logger.error("[DeprecationCheck] Failed to fetch deprecation page: %s", exc)
        return None


def _scan_page(page: str, models: dict[str, str]) -> set[str]:
    """Return set of constant names whose model IDs appear near retirement language."""
    flagged = set()
    for name, model_id in models.items():
        needle = model_id.lower()
        for match in re.finditer(re.escape(needle), page):
            start = max(0, match.start() - CONTEXT_WINDOW)
            end = min(len(page), match.end() + CONTEXT_WINDOW)
            window = page[start:end]
            if any(kw in window for kw in RETIREMENT_KEYWORDS):
                flagged.add(name)
                break
    return flagged


def _read_state() -> dict:
    try:
        from solomon_contracts.db import fetchone
        row = fetchone("SELECT * FROM model_deprecation_state WHERE id = 1")
        if row:
            return dict(row)
    except Exception as exc:
        logger.warning("[DeprecationCheck] Could not read state: %s", exc)
    return {}


def _write_state(last_status: str, flagged_names: list[str], alert_sent: bool) -> None:
    now = datetime.now(timezone.utc)
    alert_col = ", last_alert_sent_at = NOW()" if alert_sent else ""
    sql = f"""
        UPDATE model_deprecation_state
        SET last_check_at = NOW(),
            last_status = %(status)s,
            last_flagged_models = %(flagged)s
            {alert_col}
        WHERE id = 1
    """
    try:
        from solomon_contracts.db import execute
        execute(sql, {"status": last_status, "flagged": json.dumps(flagged_names)})
    except Exception as exc:
        logger.error("[DeprecationCheck] Could not persist state: %s", exc)


def _touch_check_at() -> None:
    try:
        from solomon_contracts.db import execute
        execute("UPDATE model_deprecation_state SET last_check_at = NOW() WHERE id = 1")
    except Exception as exc:
        logger.warning("[DeprecationCheck] Could not update last_check_at: %s", exc)


def _build_alert(flagged_names: set[str], models: dict[str, str], kind: str) -> str:
    if kind == "recovery":
        return (
            "✅ Claude model deprecation check\n\n"
            "All previously-flagged models are clear on Anthropic's deprecation page.\n\n"
            f"Review: {DEPRECATION_URL}"
        )
    label = "Additional models newly flagged" if kind == "addition" else "Models newly flagged"
    lines = "\n".join(f"• {name} = {models[name]}" for name in sorted(flagged_names))
    return (
        f"⚠️ Claude model deprecation check\n\n"
        f"Active models flagged on Anthropic's deprecation page:\n"
        f"{lines}\n\n"
        f"Review: {DEPRECATION_URL}\n"
        f"Update backend/services/ai_models.py to migrate."
    )


def check_model_deprecations() -> dict:
    """
    Fetch the Anthropic deprecation page, diff against stored state, and alert
    via notification_service if the flagged-model set has changed.

    Returns a result dict describing what happened (useful for the manual trigger
    endpoint and for unit tests).
    """
    models = _active_models()
    state = _read_state()
    prev_flagged: set[str] = set(state.get("last_flagged_models") or [])
    prev_status: str = state.get("last_status") or "ok"

    page = _fetch_page(DEPRECATION_URL)
    if page is None:
        _touch_check_at()
        logger.warning("[DeprecationCheck] Fetch failed — previous state preserved")
        return {"status": "fetch_failed", "flagged": list(prev_flagged), "alert_sent": False}

    current_flagged = _scan_page(page, models)
    new_additions = current_flagged - prev_flagged
    recoveries = prev_flagged - current_flagged
    status = "flagged" if current_flagged else "ok"

    alert_sent = False
    alert_kind: Optional[str] = None

    if current_flagged and not prev_flagged:
        alert_kind = "new"
    elif current_flagged and new_additions:
        alert_kind = "addition"
    elif not current_flagged and prev_flagged:
        alert_kind = "recovery"

    if alert_kind:
        notify_set = new_additions if alert_kind == "addition" else current_flagged
        message = _build_alert(notify_set if alert_kind != "recovery" else set(), models, alert_kind)
        sent = notification_service.send_custom_notification(message)
        alert_sent = sent
        if sent:
            logger.info("[DeprecationCheck] Alert sent (%s): %s", alert_kind, sorted(notify_set if alert_kind != "recovery" else prev_flagged))
        else:
            logger.error("[DeprecationCheck] Alert build failed for kind=%s", alert_kind)
    else:
        if current_flagged:
            logger.info("[DeprecationCheck] Flagged set unchanged (%s) — no alert", sorted(current_flagged))
        else:
            logger.info("[DeprecationCheck] All models clear — no alert")

    _write_state(status, sorted(current_flagged), alert_sent)

    return {
        "status": status,
        "flagged": sorted(current_flagged),
        "prev_flagged": sorted(prev_flagged),
        "new_additions": sorted(new_additions),
        "recoveries": sorted(recoveries),
        "alert_sent": alert_sent,
        "alert_kind": alert_kind,
    }
