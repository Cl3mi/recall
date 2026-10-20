import re

_KV_LINE = re.compile(r"^\s*[A-Z][A-Z0-9_]{2,}\s*[:=]\s*\S+\s*$")
_MIN_RUN = 4


def has_diagnostic_dump(text: str) -> bool:
    """A run of machine-formatted KEY = VALUE lines. Flagged, never deleted: the
    error state in a dump is often the most retrievable thing in the ticket."""
    run = 0
    for line in text.splitlines():
        run = run + 1 if _KV_LINE.match(line) else 0
        if run >= _MIN_RUN:
            return True
    return False
