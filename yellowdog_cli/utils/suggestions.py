"""
The word meant by a misspelt one ('submti' for 'submit'), offered with a
usage error: a command after 'yd', a noun's verb, an option, a sort key, a
resource type. Stdlib only, since 'yd' answers a misspelt command before any
command's module is imported.
"""

from collections.abc import Iterable
from difflib import SequenceMatcher

# How alike a word must be to be offered (difflib's ratio, 0 to 1)
SIMILARITY_CUTOFF = 0.6


def did_you_mean(word: str, candidates: Iterable[str]) -> str | None:
    """
    "did you mean 'submit'?", or None when no candidate is close: the
    closest, or those equally close ('bat' or 'hat' for 'cat'), since a
    second, less alike ('--pac' beside '--namespace' for '--namepsace')
    reads as noise.
    """
    ratios = {
        candidate: SequenceMatcher(None, word, candidate).ratio()
        for candidate in candidates
    }
    best = max(ratios.values(), default=0.0)
    if best < SIMILARITY_CUTOFF:
        return None
    matches = [candidate for candidate, ratio in ratios.items() if ratio == best]
    return "did you mean " + " or ".join(f"'{match}'" for match in matches) + "?"
