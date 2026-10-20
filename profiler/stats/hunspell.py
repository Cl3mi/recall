from __future__ import annotations

import shutil
import subprocess
from collections import Counter

MISSING_BINARY_WARNING = "hunspell binary unavailable; unrecognised-token mining skipped"


def available(dict_path: str | None) -> bool:
    return bool(dict_path) and shutil.which("hunspell") is not None


def unrecognized(
    counts: Counter[str], min_frequency: int, dict_path: str | None = "de_DE", limit: int = 500
) -> list[dict]:
    """Tokens hunspell does not recognise, pruned by min_frequency like every other
    emitted string. Rare unrecognised tokens are the likeliest to be names."""
    candidates = [t for t, c in counts.items() if c >= min_frequency]
    if not candidates or not available(dict_path):
        return []
    # vocab.tokenize() lowercases, but hunspell is case-sensitive for German nouns,
    # which must be capitalised: it accepts "Motor" and rejects "motor". Checking
    # only the lowercase form would flag every ordinary German noun in the corpus
    # and bury the dealer shorthand this list exists to find - and since the list is
    # a Window A deliverable, recovering it costs a full airlock cycle. So a token
    # counts as unrecognised only if BOTH its own form and its capitalised form are
    # rejected.
    probes = {t for t in candidates} | {t.capitalize() for t in candidates}
    proc = subprocess.run(
        ["hunspell", "-l", "-d", str(dict_path)],
        input="\n".join(sorted(probes)) + "\n",
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode not in (0, 1):
        return []
    rejected = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    flagged = [t for t in candidates if t in rejected and t.capitalize() in rejected]
    return [
        {"token": t, "count": counts[t]}
        for t in sorted(flagged, key=lambda t: -counts.get(t, 0))
        if counts.get(t, 0) >= min_frequency
    ][:limit]
