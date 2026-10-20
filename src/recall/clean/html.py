import html as _html
import re

from selectolax.parser import HTMLParser

_TAGGY = re.compile(r"<[a-z/!][^>]{0,200}>", re.IGNORECASE)


def looks_like_html(text: str) -> bool:
    return bool(_TAGGY.search(text))


def strip_html(text: str) -> str:
    if not looks_like_html(text):
        return text
    parsed = HTMLParser(text)
    out = parsed.text(separator=" ") if parsed.body is not None else _TAGGY.sub(" ", text)
    return _html.unescape(out)
