import re

_GRUSS = re.compile(
    r"^\s*(mit freundlichen gr(ü|ue)(ß|ss)en|freundliche gr(ü|ue)(ß|ss)e|mfg|lg|"
    r"beste gr(ü|ue)(ß|ss)e|viele gr(ü|ue)(ß|ss)e|best regards|kind regards)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
_DASH_SIG = re.compile(r"^--\s*$", re.MULTILINE)


def has_signature(text: str) -> bool:
    return bool(_GRUSS.search(text) or _DASH_SIG.search(text))


def strip_signature(text: str) -> str:
    cut = len(text)
    for pattern in (_GRUSS, _DASH_SIG):
        m = pattern.search(text)
        if m and m.start() < cut:
            cut = m.start()
    return text[:cut]
