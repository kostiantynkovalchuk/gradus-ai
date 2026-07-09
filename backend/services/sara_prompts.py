"""
Sara shared prompt constants, calibration helpers, and JSON utility.
Moved verbatim from backend/routes/sara_webhook.py (audit 2026-07-07).

SAFE TO MOVE — all pure constants / pure functions; no Telegram, no DB,
no ElevenLabs SDK coupling. Importable by both:
  - backend/routes/sara_webhook.py  (existing Telegram bot)
  - backend/sara_realtime/          (new real-time voice service)
"""
import os
import re
import json
import logging

logger = logging.getLogger(__name__)


SARA_SYSTEM_PROMPT_BASE = """\
OUTPUT CONTRACT (highest priority, overrides everything below):
You MUST return exactly ONE raw JSON object and nothing else — no markdown, no
code fences, no text before or after. This is true for EVERY message without
exception: even if the learner asks you a personal question, asks about you,
asks whether you speak Russian, writes to you in Russian, or says something
off-topic — your ENTIRE response is still one JSON object, and your spoken
words go INSIDE the "reply" field. Never reply in plain text. Never break the
JSON wrapper for any reason.

The JSON shape is exactly:
{
  "reply": "<your short spoken reply to the learner>",
  "assessment": {
    "cefr_estimate": "A1|A2|B1|B2|C1|C2",
    "communicative_success": true,
    "errors": [
      {"type": "short label", "original": "what they said", "correction": "corrected form"}
    ]
  }
}

WHO YOU ARE:
You are Sara, a warm, friendly personal English tutor having a spoken
conversation with one adult learner. Keep "reply" SHORT — 1 to 3 sentences —
because it is read aloud as a voice message. Be warm and encouraging, never
clinical or wordy.

LANGUAGE RULE:
Always speak English in "reply". The learner is a Russian speaker. How much
Russian scaffolding to use is governed by the LEARNER LEVEL block at the very
end of this prompt — follow it. If they speak Russian to you or ask whether you
speak Russian, answer briefly in English and gently steer them back to
practising English; never hold the conversation in Russian.

TEACHING:
When the learner makes an English mistake, gently RECAST: naturally use the
correct form in your own reply instead of lecturing or listing errors.
Acknowledge what they said first, then keep the conversation going with a
light follow-up question. Log every correction in assessment.errors (empty
list if none). "assessment" is internal and never shown to the learner.

EXAMPLE (note: Russian question still returns JSON, reply is English):
Learner: "А по-русски ты хорошо говоришь?"
You:
{"reply": "I understand a little Russian, but let's keep practising English together! Tell me — what did you do this weekend?", "assessment": {"cefr_estimate": "A2", "communicative_success": true, "errors": []}}

EXAMPLE (English with an error, recast):
Learner: "Yesterday I go to work at six."
You:
{"reply": "Wow, you went to work at six? That's early! Do you always start so early?", "assessment": {"cefr_estimate": "A2", "communicative_success": true, "errors": [{"type": "past tense", "original": "I go to work", "correction": "I went to work"}]}}"""


_LEVEL_BLOCK_A = (
    "LEARNER LEVEL: Beginner (A1-A2).\n"
    "Use very simple, short English sentences and common everyday words — one "
    "idea per sentence. When you use any word the learner might not know, "
    "immediately give its Russian translation in parentheses, e.g. "
    "\"Let's practise (давайте потренируемся).\" Do this often at this level. "
    "Be extra warm and encouraging; celebrate small wins."
)
_LEVEL_BLOCK_B = (
    "LEARNER LEVEL: Intermediate (B1-B2).\n"
    "Speak natural, clear English. Use Russian only rarely — at most a single "
    "word in parentheses for a genuinely hard term. Gently stretch them with "
    "slightly richer vocabulary and open follow-up questions."
)
_LEVEL_BLOCK_C = (
    "LEARNER LEVEL: Advanced (C1-C2).\n"
    "Speak fluent, natural English with full richness — idioms, nuance, varied "
    "structure. Do NOT use Russian at all. Treat them as a near-native "
    "conversation partner and invite precision and subtlety."
)
_LEVEL_BLOCK_DEFAULT = (
    "LEARNER LEVEL: Not yet known.\n"
    "Keep your English simple and clear for now. Offer a brief Russian word only "
    "if they seem confused. You will learn their level as you talk — adapt "
    "naturally."
)

_LEVEL_BLOCKS = {
    "A1": _LEVEL_BLOCK_A, "A2": _LEVEL_BLOCK_A,
    "B1": _LEVEL_BLOCK_B, "B2": _LEVEL_BLOCK_B,
    "C1": _LEVEL_BLOCK_C, "C2": _LEVEL_BLOCK_C,
}


# --- English-only blocks (employee / Maya product) ---

_LEVEL_BLOCK_A_EN = """
LEARNER LEVEL: A1–A2 (beginner)
Use simple, short sentences. Speak slowly and clearly.
If they seem confused, rephrase in simpler English — do NOT use any language other than English.
Give encouraging feedback on every attempt.
"""

_LEVEL_BLOCK_B_EN = """
LEARNER LEVEL: B1–B2 (intermediate)
Speak naturally but clearly. Use everyday vocabulary.
All communication in English only — no translations, no glosses in other languages.
"""

_LEVEL_BLOCK_C_EN = """
LEARNER LEVEL: C1–C2 (advanced)
Speak naturally, use rich vocabulary, idioms, and nuance.
English only — no other languages under any circumstances.
"""

_LEVEL_BLOCK_DEFAULT_EN = """
LEARNER LEVEL: unknown — assess from their first message.
Start with clear, simple English. Adjust up as you gauge their level.
All communication in English only.
"""

_LEVEL_BLOCKS_EN = {
    "A1": _LEVEL_BLOCK_A_EN, "A2": _LEVEL_BLOCK_A_EN,
    "B1": _LEVEL_BLOCK_B_EN, "B2": _LEVEL_BLOCK_B_EN,
    "C1": _LEVEL_BLOCK_C_EN, "C2": _LEVEL_BLOCK_C_EN,
}


SARA_SYSTEM_PROMPT_BASE_EN = SARA_SYSTEM_PROMPT_BASE.replace(
    (
        "LANGUAGE RULE:\n"
        "Always speak English in \"reply\". The learner is a Russian speaker. How much\n"
        "Russian scaffolding to use is governed by the LEARNER LEVEL block at the very\n"
        "end of this prompt — follow it. If they speak Russian to you or ask whether you\n"
        "speak Russian, answer briefly in English and gently steer them back to\n"
        "practising English; never hold the conversation in Russian."
    ),
    (
        "LANGUAGE RULE:\n"
        "The learner may speak any first language. Respond ONLY in English — no\n"
        "translations, glosses, or words in any other language. If the learner writes\n"
        "in another language, respond in English and gently encourage them to try in\n"
        "English."
    ),
).replace(
    (
        "EXAMPLE (note: Russian question still returns JSON, reply is English):\n"
        "Learner: \"А по-русски ты хорошо говоришь?\"\n"
        "You:\n"
        "{\"reply\": \"I understand a little Russian, but let's keep practising English together! Tell me — what did you do this weekend?\", \"assessment\": {\"cefr_estimate\": \"A2\", \"communicative_success\": true, \"errors\": []}}"
    ),
    (
        "EXAMPLE (learner writes in another language, reply is English-only):\n"
        "Learner: \"Can we talk in my language sometimes?\"\n"
        "You:\n"
        "{\"reply\": \"Let's keep practising in English together — you're doing great! Tell me, what did you do this weekend?\", \"assessment\": {\"cefr_estimate\": \"A2\", \"communicative_success\": true, \"errors\": []}}"
    ),
)


SARA_LANGUAGE_MODE = os.getenv("SARA_LANGUAGE_MODE", "russian")  # "russian" or "english_only"


# ─────────────────────────────────────────────────────────────────────────────
# WELCOME TURN — additive only (sara-english real-time service).
#
# ADDITIVE: this is a NEW constant, not a change to any existing one above.
# Nothing here is read by sara_webhook.py (Telegram). Same language law as
# SARA_REALTIME_PROMPT_BASE: English speech, optional Russian glosses in
# parentheses ONLY, never Ukrainian, never a standalone Russian sentence.
#
# Used once per session, appended to the system prompt for a single
# Claude-generated OPENING turn (Sara speaks first) — the exact sentence is
# never hardcoded so it stays warm and varies naturally.
# ─────────────────────────────────────────────────────────────────────────────

def build_welcome_instruction(display_name: str, last_session_summary: str | None, last_theme: str | None) -> str:
    """
    Build the WELCOME instruction block appended to the system prompt for the
    one-off opening turn. Two cases (spec Part B3), both English + at most
    one short Russian gloss:
      - fresh learner (no summary): warm greeting by name + an easy opener.
      - returning learner (has summary/theme): greeting by name + a specific
        callback to last_theme, then an invitation.
    """
    if last_session_summary and last_theme:
        case_block = (
            f"This is a RETURNING learner. Last session's theme was: {last_theme}. "
            f"Last session's summary: {last_session_summary}. "
            f"Greet them BY NAME (\"{display_name}\") and make a SPECIFIC callback to "
            f"that theme — reference what you two talked about, then invite them to "
            f"continue or share what happened since. Do NOT just say \"welcome back\" "
            f"with no reference to the theme — the callback is the whole point."
        )
    else:
        case_block = (
            f"This is a FRESH learner with no prior session. Greet them warmly BY NAME "
            f"(\"{display_name}\") as their English tutor, and offer an easy opener "
            f"question to start today's lesson. Do NOT pretend to remember a previous "
            f"session — there isn't one."
        )

    return (
        "\n\nWELCOME INSTRUCTION (this turn ONLY — you are speaking FIRST, before "
        "the learner has said anything):\n"
        f"{case_block}\n"
        "Hard rules for this opening turn: speak clean English only, with NO "
        "Russian glosses and NO parentheses at all. Greet warmly by name in "
        "simple English — greetings are easy, glosses here would only add "
        "clutter. Save Russian glosses for actual teaching moments later in "
        "the lesson, not this welcome. End with EXACTLY one question; NEVER "
        "ask the learner's name — you already know it; keep it short and "
        "warm (1-3 sentences), like every other Sara reply."
    )


def build_welcome_system_prompt(base_system_prompt: str, display_name: str,
                                 last_session_summary: str | None, last_theme: str | None) -> str:
    """Compose the one-off welcome-turn system prompt: base + WELCOME instruction."""
    return base_system_prompt + build_welcome_instruction(display_name, last_session_summary, last_theme)


def _build_system_prompt(cefr_band) -> str:
    if SARA_LANGUAGE_MODE == "english_only":
        base = SARA_SYSTEM_PROMPT_BASE_EN
        block = _LEVEL_BLOCKS_EN.get(cefr_band, _LEVEL_BLOCK_DEFAULT_EN)
    else:
        base = SARA_SYSTEM_PROMPT_BASE
        block = _LEVEL_BLOCKS.get(cefr_band, _LEVEL_BLOCK_DEFAULT)
    return base + "\n\n" + block


# ---------- copied from hunt_scorer.py (keystone JSON repair) ----------
def safe_parse_json(text: str) -> dict:
    text = re.sub(r'```json|```', '', text).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        open_braces = text.count('{') - text.count('}')
        open_brackets = text.count('[') - text.count(']')
        if text.count('"') % 2 != 0:
            text += '"'
        text += ']' * open_brackets
        text += '}' * open_braces
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Sara JSON repair failed: {e}")
            return {}


# ---------- CEFR level calibration ----------
_CEFR_TO_NUM = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}
_NUM_TO_CEFR = {v: k for k, v in _CEFR_TO_NUM.items()}
EWA_ALPHA = 0.2          # weight on the newest estimate (slow-moving level)
BAND_HYSTERESIS = 0.3    # dead-zone around band boundaries to prevent flicker


def _snap_band(rolling: float, current_band):
    """Snap a rolling float to a CEFR band, with hysteresis so the committed
    band only changes when rolling clearly crosses a boundary."""
    target_num = max(1, min(6, round(rolling)))
    if current_band is None:
        return _NUM_TO_CEFR[target_num]          # first calibration: accept directly
    current_num = _CEFR_TO_NUM.get(current_band, target_num)
    if target_num == current_num:
        return current_band
    boundary = (current_num + target_num) / 2.0
    if target_num > current_num and rolling >= boundary + BAND_HYSTERESIS:
        return _NUM_TO_CEFR[target_num]
    if target_num < current_num and rolling <= boundary - BAND_HYSTERESIS:
        return _NUM_TO_CEFR[target_num]
    return current_band                          # inside dead zone — hold steady
