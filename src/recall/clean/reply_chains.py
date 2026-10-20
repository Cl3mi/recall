import re

# German and English mail-client boundaries. Everything from the first hit onward
# is a previous message, not this ticket's problem statement.
_BOUNDARIES = [
    re.compile(
        r"^\s*-{2,}\s*Urspr(ü|ue)ngliche Nachricht\s*-{2,}\s*$", re.IGNORECASE | re.MULTILINE
    ),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*Von:\s+.+$", re.MULTILINE),
    re.compile(r"^\s*From:\s+.+$", re.MULTILINE),
    re.compile(r"^\s*Am\s+\d{1,2}\.\d{1,2}\.\d{2,4}.{0,40}schrieb\b", re.MULTILINE),
    re.compile(r"^\s*On\s+.{5,60}\bwrote:\s*$", re.MULTILINE),
    re.compile(r"^_{10,}\s*$", re.MULTILINE),
]
_QUOTED_LINE = re.compile(r"^\s*>.*$", re.MULTILINE)


def has_quoted_chain(text: str) -> bool:
    return bool(_QUOTED_LINE.search(text)) or any(b.search(text) for b in _BOUNDARIES)


def strip_quoted_chain(text: str) -> str:
    cut = len(text)
    for boundary in _BOUNDARIES:
        m = boundary.search(text)
        if m and m.start() < cut:
            cut = m.start()
    head = text[:cut]
    return _QUOTED_LINE.sub("", head)
