"""Conservative optional recovery of missing leading/trailing title characters."""
from verification_policy import title_key


def use_expanded_text(original, expanded, confidence, target=None):
    old,new=title_key(original),title_key(expanded)
    if target is not None and new!=title_key(target):
        return False
    # Punctuation-only changes and substitutions provide no evidence of recovery.
    return bool(old and confidence>=.90 and 1<=len(new)-len(old)<=2
                and (new.startswith(old) or new.endswith(old)))
