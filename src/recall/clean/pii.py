import re

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]{2,}\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:[ ]?[A-Z0-9]{4}){2,7}\b")
# Requires a separator or leading + so that bare identifiers like F1247 survive.
_PHONE = re.compile(r"(?:\+\d{1,3}[\s/.-]?)?(?:\(?\d{2,5}\)?[\s/.-]){1,3}\d{3,}")
_URL = re.compile(r"https?://\S+")

REDACTIONS = (
    (_EMAIL, "[EMAIL]"),
    (_IBAN, "[IBAN]"),
    (_URL, "[URL]"),
    (_PHONE, "[TEL]"),
)


def redact(text: str) -> str:
    for pattern, token in REDACTIONS:
        text = pattern.sub(token, text)
    return text
