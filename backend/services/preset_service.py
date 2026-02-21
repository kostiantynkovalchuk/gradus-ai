"""Preset Answer Service - Instant responses for common questions"""

import json
import os
from typing import Optional, Dict, List
from fuzzywuzzy import fuzz
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class PresetService:
    def __init__(self):
        self.presets: List[Dict[str, str]] = []
        self.load_presets()
        
        self.preset_hits = 0
        self.api_calls_saved = 0
        self.estimated_savings = 0.0
        self.hit_counts: Dict[str, int] = {}
        self.start_time = datetime.now()
    
    def load_presets(self):
        """Load preset answers from JSON file"""
        preset_file = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "data",
            "preset_answers.json"
        )
        
        try:
            with open(preset_file, 'r', encoding='utf-8') as f:
                self.presets = json.load(f)
            
            logger.info(f"Loaded {len(self.presets)} preset answers")
        except FileNotFoundError:
            logger.warning(f"Preset file not found: {preset_file}")
            self.presets = []
        except Exception as e:
            logger.error(f"Error loading presets: {e}")
            self.presets = []
    
    def get_preset_answer(self, question: str) -> Optional[str]:
        """
        Try to match question to a preset answer
        
        Returns:
            - Preset answer if found
            - None if no match (fallback to Claude API)
        """
        if not self.presets:
            return None
        
        question_normalized = question.strip().lower()
        
        for preset in self.presets:
            preset_q = preset.get('question', '')
            if preset_q.lower() == question_normalized:
                self._track_usage(preset_q)
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
            logger.info(f"[PRESET] Fuzzy match ({best_score}%): {best_match[:50]}...")
            return best_preset.get('answer')
        
        keywords_map = {
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
        
        for keywords, preset_q in keywords_map.items():
            if all(word in question_normalized for word in keywords):
                for preset in self.presets:
                    if preset.get('question') == preset_q:
                        self._track_usage(preset_q)
                        logger.info(f"[PRESET] Keyword match: {keywords}")
                        return preset.get('answer')
        
        logger.info(f"[API] No preset match, using Claude: {question[:50]}...")
        return None
    
    def _track_usage(self, question: str):
        """Track preset usage and estimated savings"""
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
        """Get usage statistics"""
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
        """Reload presets from file (hot reload)"""
        self.load_presets()
        return {"status": "reloaded", "count": len(self.presets)}


preset_service = PresetService()
