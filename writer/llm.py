"""Deep check for the writing assistant: asks the EPFL model for problem passages (owner: P4).

Own client (independent of gem_asynchronous.py), same .env settings:
OPENAI_BASE_URL, OPENAI_API_KEY, OPENAI_API_KEY_FALLBACK. The article text is never logged.
"""
import difflib
import json
import os
import re
import unicodedata
from pathlib import Path

from openai import OpenAI

MODEL = os.getenv("WRITER_MODEL", "openai/gpt-oss-120b")
PROMPT = (Path(__file__).parent / "prompts" / "deep_check.txt").read_text(encoding="utf-8")
MAX_ISSUES = 8
# Category → the principle ("enjeu") of the décadréE booklet it comes from, shown on the card.
ENJEU = {"victime": 4, "auteur": 5, "nationalite": 5, "relation": 7, "sensationnalisme": 3}


def ask_model(text):
    """The model's list of problems. Tries the shared key, then the team key (one retry each)."""
    # replace(), not format(): the prompt contains JSON braces
    messages = [{"role": "user", "content": PROMPT.replace("{article}", text)}]
    keys = [k for k in (os.getenv("OPENAI_API_KEY"), os.getenv("OPENAI_API_KEY_FALLBACK")) if k]
    error = None
    for key in keys:
        try:
            client = OpenAI(api_key=key, max_retries=1, timeout=90)
            resp = client.chat.completions.create(model=MODEL, messages=messages, max_tokens=8000, temperature=0.2)
            return _parse(resp.choices[0].message.content or "")
        except Exception as e:
            error = e
    raise RuntimeError(f"deep check failed: {error}")


def _parse(content):
    """The JSON object in the answer, ignoring ``` fences or text around it."""
    start, end = content.find("{"), content.rfind("}")
    if start == -1 or end == -1:
        return []
    return json.loads(content[start:end + 1]).get("problemes", [])[:MAX_ISSUES]


def _normalise(s):
    """Lowercase, no accents, no punctuation, single spaces — plus, for each kept character,
    its index in the original, so a match can be mapped back to the real text."""
    out, pos = [], []
    for i, ch in enumerate(s):
        for c in unicodedata.normalize("NFD", ch.lower()):
            if unicodedata.combining(c):
                continue
            if c.isspace() or not c.isalnum():
                if not out or out[-1] == " ":
                    continue
                c = " "
            out.append(c)
            pos.append(i)
    return "".join(out), pos


def locate(text, excerpt):
    """(start, end) of the excerpt in the text, or None.
    1) exact match after normalising both; 2) else the sentence that is ≥ 85 % similar."""
    norm_text, pos = _normalise(text)
    norm_ex = _normalise(excerpt)[0].strip()
    if not norm_ex:
        return None
    i = norm_text.find(norm_ex)
    if i != -1:
        return pos[i], pos[i + len(norm_ex) - 1] + 1
    best, best_ratio = None, 0.0
    for m in re.finditer(r"[^.!?\n]+[.!?]?", text):
        ratio = difflib.SequenceMatcher(None, _normalise(m.group())[0].strip(), norm_ex).ratio()
        if ratio > best_ratio:
            best, best_ratio = m, ratio
    if best and best_ratio >= 0.85:
        start = best.start() + len(best.group()) - len(best.group().lstrip())
        return start, best.end()
    return None


def _invented_numbers(s, text):
    """True if s contains a number that isn't in the article (e.g. "Cent-sept" read as 167)."""
    return any(n not in text for n in re.findall(r"\d+", s))


def _in_quote(text, pos):
    before = text[:pos]
    return before.rfind("«") > before.rfind("»") or before.count('"') % 2 == 1


def deep_check(text):
    """{issues, unlocated} in the format the editor UI expects (see writer/static/main.js)."""
    issues, unlocated = [], []
    for p in ask_model(text):
        cat = str(p.get("categorie", "")).strip()
        excerpt = str(p.get("extrait", "")).strip()
        reason = str(p.get("raison", "")).strip()
        suggestion = str(p.get("suggestion", "")).strip()
        if not excerpt or not reason or _invented_numbers(reason, text):
            continue
        if _invented_numbers(suggestion, text):
            suggestion = ""
        span = locate(text, excerpt)
        if span is None:
            unlocated.append({"extrait": excerpt, "reason": reason, "suggestion": suggestion})
            continue
        start, end = span
        in_quote = _in_quote(text, start)
        if in_quote or re.search(r'[«»"“”]', text[start:end]):
            suggestion = ""  # reported speech: contextualise it, never rewrite someone's words
        issues.append({
            "key": f"ai:{cat}:{start}", "ruleId": f"IA-{cat or 'autre'}",
            "start": start, "end": end, "match": text[start:end],
            "severity": "hint", "replacements": [suggestion] if suggestion else [],
            "reason": reason,
            "source": f"Suggestion IA — Livret décadréE 2023, enjeu {ENJEU[cat]}" if cat in ENJEU else "Suggestion IA",
            "inQuote": in_quote, "origin": "ai",
        })
    return {"issues": issues, "unlocated": unlocated}
