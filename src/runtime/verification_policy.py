"""Conservative experimental decisions; OCR agreement is not proof of identity."""
import re
from difflib import SequenceMatcher


def title_key(text):
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", text).lower()


def needs_review(target, text):
    a, b = title_key(target), title_key(text)
    if not a or not b:
        return False
    if a == b:
        return True
    # Short similar titles are too ambiguous. No substring acceptance.
    return (len(a) >= 6 and abs(len(a)-len(b)) <= 2
            and SequenceMatcher(None, a, b).ratio() >= 0.80)


def decide(target, tiny_text, v4_text, v4_confidence):
    exact = bool(title_key(target)) and title_key(target) == title_key(v4_text)
    accepted = exact and v4_confidence >= 0.90
    return dict(accepted=accepted,
                status=("corroborated" if title_key(tiny_text) == title_key(target) else "verified_by_v4")
                if accepted else "unconfirmed",
                reason="v4_exact_title_and_confidence" if accepted else "v4_disagrees_or_low_confidence")
