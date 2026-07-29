#!/usr/bin/env python3
"""Z.A.E.B.A.L. detector — Hermes integration.

Reads user message from stdin (JSON: {"session_id": "...", "prompt": "..."}),
detects profanity, tracks streak, outputs escalation level or silence.

Exit 0, non-empty stdout → protocol level injected into context.
Exit 0, empty stdout     → nothing happens (clean message).
"""

import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path

# Wordlists: core/wordlists/ (repo layout) or references/ (skill layout)
BASE_DIR = Path(__file__).resolve().parent
WORDLISTS_CANDIDATES = [
    BASE_DIR / "wordlists",
    BASE_DIR.parent / "references",
    BASE_DIR / "references",
]
WORDLISTS_DIR = next((p for p in WORDLISTS_CANDIDATES if p.is_dir()), BASE_DIR / "wordlists")

STATE_DIR = Path(os.environ.get("ZAEBAL_STATE_DIR", str(Path.home() / ".zaebal")))
STATE_FILE = STATE_DIR / "state.json"

WINDOW_SECONDS = 30 * 60
MAX_SESSIONS = 50

# Leet tables
LEET_RU = str.maketrans({
    "0": "о", "3": "е", "6": "б", "ё": "е", "Ё": "е",
    "a": "а", "c": "с", "e": "е", "o": "о", "p": "р", "x": "х", "y": "у",
    "@": "а", "$": "з",
})
LEET_EN = str.maketrans({
    "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
    "@": "a", "$": "s", "ё": "e", "Ё": "e",
})

# Valence / addressee heuristics
_PRAISE = re.compile(
    r"\b(спасиб|благодар|получилос|отличн|крут|здорово|молодц|красав"
    r"|thank|great|awesome|amazing|perfect|nice|love|excellent"
    r"|работает)"
    r"|(?<!не )\bработает\b"
)
_SECOND_PERSON = re.compile(
    r"\b(?:ты|теб|тво|тобо|ваш|вы|вас|вам)"
    r"|\b(?:you|your|u|claude|codex|kimi|opencode|клод|гпт|бендер|hermes)\b"
)
_COMPLAINT = re.compile(
    r"\b(?:опять|снова|сломал|сломано?|поломал|глючит|падает"
    r"|still|again|broken|wrong|doesn'?t work|not working"
    r"|сколько можно|не работает|\bне то\b|\bне так\b)"
)
_ACK = re.compile(
    r"\b(?:ладно|хорошо|давай|продолжай|продолжаем|согласен|принято|принимаю"
    r"|ок|окей|go ahead|continue|lgtm|по плану)"
)

_NONWORD = re.compile(r"[^\w\u4e00-\u9fff]+", re.UNICODE)
_SPACES = re.compile(r"\s+")
_REPEATS = re.compile(r"(.)\1{2,}")


def load_wordlists():
    """Load profanity roots from wordlist files."""
    words = {"ru": set(), "en": set()}
    for lang in ("ru", "en"):
        path = WORDLISTS_DIR / f"{lang}.txt"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                words[lang].add(line.lower())
    return words


WORDLISTS = load_wordlists()


def normalize(text, leet_table=None, punct_to_space=True):
    """NFKC + leet-deobfuscation + collapse repeats."""
    text = unicodedata.normalize("NFKC", text)
    if leet_table:
        text = text.translate(leet_table)
    text = text.lower()
    if punct_to_space:
        text = _NONWORD.sub(" ", text)
    else:
        text = _SPACES.sub(" ", text)
    text = _REPEATS.sub(r"\1", text)
    return text.strip()


def detect_profanity(text):
    """Check if text contains profanity roots. Returns (lang, matched_root) or None."""
    for lang, table in (("ru", LEET_RU), ("en", LEET_EN)):
        normalized = normalize(text, table, punct_to_space=False)
        for root in WORDLISTS[lang]:
            if root in normalized:
                return lang, root
    return None


def classify(text):
    """Classify user intent. Returns weight: 0 (clean/praise), 0.5 (ambiguous), 1.0 (directed)."""
    normalized = normalize(text, LEET_RU if any(c in text.lower() for c in "йцукенгшщзхъфывапролджэячсмитьбюё") else LEET_EN)

    # Explicit acknowledgment → reset
    if _ACK.search(normalized):
        return 0, "acknowledgment"

    # Praise with profanity → no streak
    if _PRAISE.search(normalized):
        # But check if complaint overrides praise
        if _COMPLAINT.search(normalized):
            pass  # fall through to directed check
        else:
            return 0, "praise"

    # Check profanity presence
    detected = detect_profanity(text)
    if not detected:
        return 0, "clean"

    # Directed complaint (second person + profanity)
    if _SECOND_PERSON.search(normalized):
        return 1.0, "directed"

    # Ambiguous profanity
    return 0.5, "ambiguous"


def load_state():
    """Load session state from JSON file."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_state(state):
    """Save session state atomically."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Prune old sessions
    if len(state) > MAX_SESSIONS:
        # Keep only the most recent MAX_SESSIONS
        sorted_sessions = sorted(
            state.items(),
            key=lambda x: max(e["ts"] for e in x[1]["events"]) if x[1]["events"] else 0,
            reverse=True
        )[:MAX_SESSIONS]
        state = dict(sorted_sessions)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def update_streak(session_id, weight):
    """Update streak for a session. Returns (streak_weight, level)."""
    now = time.time()
    state = load_state()

    if session_id not in state:
        state[session_id] = {"events": [], "streak": 0.0}

    session = state[session_id]
    # Prune events outside window
    cutoff = now - WINDOW_SECONDS
    session["events"] = [e for e in session["events"] if e["ts"] > cutoff]

    if weight == 0:
        # Reset streak on acknowledgment/praise
        session["streak"] = 0.0
        session["events"] = []
        save_state(state)
        return 0.0, 0

    # Add event
    session["events"].append({"ts": now, "weight": weight})
    # Recalculate streak from events in window
    session["streak"] = sum(e["weight"] for e in session["events"])
    save_state(state)

    streak = session["streak"]
    if streak >= 4.0:
        return streak, 3
    elif streak >= 2.0:
        return streak, 2
    elif streak >= 1.0:
        return streak, 1
    return streak, 0


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, OSError):
        sys.exit(0)  # fail-open

    session_id = payload.get("session_id", "default")
    prompt = payload.get("prompt", "")

    if not prompt:
        sys.exit(0)

    weight, reason = classify(prompt)
    streak, level = update_streak(session_id, weight)

    if level == 0:
        # Clean or acknowledgment — silence
        sys.exit(0)

    # Output protocol level
    output = f'<zaebal level="{level}" streak="{streak:.1f}" reason="{reason}">\n'

    if level == 1:
        output += (
            "User is swearing. Execute Z.A.E.B.A.L. Level 1 protocol:\n"
            "1. STOP. Do not perform the next action.\n"
            "2. Launch two independent sub-agent auditors with raw artifacts.\n"
            "3. Inventory your beliefs — tag each FACT or HYPOTHESIS.\n"
            "4. Check 'written ≠ took effect' for every config/hook/env.\n"
            "5. Make a micro-plan and notify the human.\n"
            "</zaebal>\n"
        )
    elif level == 2:
        output += (
            "Profanity repeats. Execute Z.A.E.B.A.L. Level 2 protocol:\n"
            "1. STOP. No edits until analyzed.\n"
            "2. Check the named belief from the verdict (if any).\n"
            "3. Inventory beliefs — FACT only if confirmed by execution.\n"
            "4. Compare against the original request (verbatim).\n"
            "5. Notify the human and proceed with confirmation.\n"
            "</zaebal>\n"
        )
    elif level == 3:
        output += (
            "Accusation streak. Execute Z.A.E.B.A.L. Level 3 protocol:\n"
            "1. FULL STOP of all agents and background tasks.\n"
            "2. External auditor verdict is attached below.\n"
            "3. Show the human: wrong belief + original request + what was done + discrepancy.\n"
            "4. Prepare handoff plan (text only, no edits).\n"
            "5. Wait for explicit acknowledgment to continue.\n"
            "</zaebal>\n"
        )

    print(output)


if __name__ == "__main__":
    main()
