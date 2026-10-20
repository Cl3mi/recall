from __future__ import annotations

import re
from dataclasses import dataclass

from recall.clean import dumps, html, pii, reply_chains, signatures

_WS = re.compile(r"[ \t]+")
_BLANKS = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class CleanReport:
    had_html: bool = False
    had_quoted_chain: bool = False
    had_signature: bool = False
    had_diag_dump: bool = False
    is_all_caps: bool = False
    has_no_punctuation: bool = False
    original_chars: int = 0
    cleaned_chars: int = 0


@dataclass(frozen=True)
class Cleaned:
    text: str
    report: CleanReport


def clean(text: str | None) -> Cleaned:
    original = text or ""
    report_kwargs = {
        "had_html": html.looks_like_html(original),
        "had_quoted_chain": reply_chains.has_quoted_chain(original),
        "had_signature": signatures.has_signature(original),
        "had_diag_dump": dumps.has_diagnostic_dump(original),
        "is_all_caps": bool(original.strip())
        and original == original.upper()
        and any(c.isalpha() for c in original),
        "has_no_punctuation": bool(original.strip()) and not any(c in ".!?;" for c in original),
        "original_chars": len(original),
    }
    out = html.strip_html(original)
    out = reply_chains.strip_quoted_chain(out)
    out = signatures.strip_signature(out)
    out = pii.redact(out)
    out = _BLANKS.sub("\n\n", _WS.sub(" ", out)).strip()
    return Cleaned(text=out, report=CleanReport(cleaned_chars=len(out), **report_kwargs))
