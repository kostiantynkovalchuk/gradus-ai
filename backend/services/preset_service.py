"""Preset Answer Service - Database-backed instant responses for common questions"""

import logging
from typing import Optional, Dict, List
from fuzzywuzzy import fuzz
from datetime import datetime
from sqlalchemy import text

logger = logging.getLogger(__name__)


class PresetService:
    def __init__(self):
        self.presets: List[Dict] = []
        self.preset_hits = 0
        self.api_calls_saved = 0
        self.estimated_savings = 0.0
        self.hit_counts: Dict[str, int] = {}
        self.start_time = datetime.now()
        self._keywords_map = {
            ("коктейлі", "тренд"): "Які коктейлі тренд цього сезону?",
            ("постачальник", "алкогол"): "Порекомендуй постачальників алкоголю",
            ("постачальники", "преміум"): "Кращі постачальники преміум алкоголю?",
            ("постачальники", "алкогол"): "Порекомендуй постачальників алкоголю",
            ("порекомендуй", "постачальник"): "Порекомендуй постачальників алкоголю",
            ("де", "закупити", "алкоголь"): "Порекомендуй постачальників алкоголю",
            ("кращі", "постачальник"): "Порекомендуй постачальників алкоголю",
            ("постачальник", "бар"): "Порекомендуй постачальників алкоголю",
            ("постачальник", "ресторан"): "Порекомендуй постачальників алкоголю",
            ("де", "купити", "алкоголь", "оптом"): "Порекомендуй постачальників алкоголю",
            ("знизити", "витрати", "бар"): "Як знизити витрати на бар на 20%?",
            ("скоротити", "витрати"): "Як знизити витрати на бар на 20%?",
            ("ліцензія", "алкоголь"): "Що потрібно для ліцензії на алкоголь?",
            ("ліцензію", "алкоголь"): "Що потрібно для ліцензії на алкоголь?",
            ("ліцензування",): "Що потрібно для ліцензії на алкоголь?",
            ("зимов", "меню"): "Ідеї для зимового коктейльного меню?",
            ("зимов", "коктейл"): "Ідеї для зимового коктейльного меню?",
            ("craft", "spirits"): "Топ-5 українських craft spirits?",
            ("крафт", "спіритс"): "Топ-5 українських craft spirits?",
            ("українськ", "горілк"): "Топ-5 українських craft spirits?",
        }
        self.load_presets()

    def _get_db_session(self):
        import models
        if models.SessionLocal is None:
            models.init_db()
        return models.SessionLocal()

    def load_presets(self):
        """Load preset answers from database"""
        try:
            db = self._get_db_session()
            try:
                result = db.execute(text(
                    "SELECT id, question_pattern, answer_text, category, priority "
                    "FROM alex_preset_answers WHERE is_active = TRUE ORDER BY priority DESC"
                ))
                self.presets = []
                for row in result:
                    self.presets.append({
                        'id': row[0],
                        'question': row[1],
                        'answer': row[2],
                        'category': row[3],
                        'priority': row[4],
                    })
                logger.info(f"Loaded {len(self.presets)} preset answers from database")
            finally:
                db.close()
        except Exception as e:
            logger.warning(f"Error loading presets from DB, will retry on next call: {e}")
            self.presets = []

    def _update_usage_in_db(self, preset_id: int):
        """Update usage_count and last_used_at in database"""
        try:
            db = self._get_db_session()
            try:
                db.execute(text(
                    "UPDATE alex_preset_answers SET usage_count = usage_count + 1, "
                    "last_used_at = NOW(), updated_at = NOW() WHERE id = :id"
                ), {'id': preset_id})
                db.commit()
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Error updating preset usage: {e}")

    def get_preset_answer(self, question: str) -> Optional[str]:
        if not self.presets:
            self.load_presets()
            if not self.presets:
                return None

        question_normalized = question.strip().lower()

        for preset in self.presets:
            preset_q = preset.get('question', '')
            if preset_q.lower() == question_normalized:
                self._track_usage(preset_q)
                self._update_usage_in_db(preset['id'])
                logger.info(f"[PRESET] Exact match: {preset_q[:50]}...")
                return preset.get('answer')

        best_match = None
        best_score = 0
        best_preset = None

        for preset in self.presets:
            preset_q = preset.get('question', '')
            score = fuzz.ratio(question_normalized, preset_q.lower())
            if score > best_score:
                best_score = score
                best_match = preset_q
                best_preset = preset

        if best_score >= 85:
            self._track_usage(best_match)
            self._update_usage_in_db(best_preset['id'])
            logger.info(f"[PRESET] Fuzzy match ({best_score}%): {best_match[:50]}...")
            return best_preset.get('answer')

        for keywords, preset_q in self._keywords_map.items():
            if all(word in question_normalized for word in keywords):
                for preset in self.presets:
                    if preset.get('question') == preset_q:
                        self._track_usage(preset_q)
                        self._update_usage_in_db(preset['id'])
                        logger.info(f"[PRESET] Keyword match: {keywords}")
                        return preset.get('answer')

        logger.info(f"[API] No preset match, using Claude: {question[:50]}...")
        return None

    def _track_usage(self, question: str):
        self.preset_hits += 1
        self.api_calls_saved += 1
        self.estimated_savings += 0.015
        self.hit_counts[question] = self.hit_counts.get(question, 0) + 1
        if self.preset_hits % 10 == 0:
            logger.info(
                f"Preset savings: {self.api_calls_saved} API calls, "
                f"~${self.estimated_savings:.2f} saved"
            )

    def get_stats(self) -> Dict:
        top_presets = sorted(
            [{"question": q, "hits": h} for q, h in self.hit_counts.items()],
            key=lambda x: x["hits"],
            reverse=True
        )[:6]
        uptime = (datetime.now() - self.start_time).total_seconds() / 3600
        return {
            "preset_hits": self.preset_hits,
            "api_calls_saved": self.api_calls_saved,
            "estimated_savings_usd": round(self.estimated_savings, 2),
            "presets_loaded": len(self.presets),
            "top_presets": top_presets,
            "uptime_hours": round(uptime, 2)
        }

    def reload_presets(self):
        self.load_presets()
        return {"status": "reloaded", "count": len(self.presets)}


preset_service = PresetService()
