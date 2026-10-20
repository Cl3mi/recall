"""Content sniffing: catch client data whatever the file is called."""

from __future__ import annotations

import re
from pathlib import Path

_NOISE = re.compile(r"[\s\"'`]+")

HEAD_BYTES = 8192
LARGE_BYTES = 1_000_000

CODE_SUFFIXES = frozenset(
    {
        ".py",
        ".js",
        ".ts",
        ".svelte",
        ".md",
        ".sh",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".html",
        ".css",
        ".sql",
        ".lock",
        ".cfg",
        ".ini",
        ".rst",
        ".mjs",
        ".cjs",
    }
)
ARCHIVE_SUFFIXES = frozenset({".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".tar"})
ARCHIVE_MAGIC = (b"PK\x03\x04", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00", b"7z\xbc\xaf\x27\x1c")
LARGE_TEXT_SUFFIXES = frozenset({"", ".txt", ".dat", ".out", ".bin"})
DELIMITERS = (",", ";", "\t", "|")


def _utf16_text(head: bytes) -> str | None:
    """Decoded text if head is UTF-16 (BOM, or ASCII text with NUL in every other byte)."""
    if head.startswith((b"\xff\xfe", b"\xfe\xff")):
        return head.decode("utf-16", errors="replace")
    sample = head[:200]
    if len(sample) < 4:
        return None
    even, odd = sample[0::2], sample[1::2]
    if not any(odd) and all(even):
        return head.decode("utf-16-le", errors="replace")
    if not any(even) and all(odd):
        return head.decode("utf-16-be", errors="replace")
    return None


def _squash(text: str) -> str:
    """Drop whitespace and quote characters so `a, b ,c` and `"a","b"` match `a,b,c`."""
    return _NOISE.sub("", text)


def _delimited(text: str, truncated: bool) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if truncated and len(lines) < 20 and len(lines) > 1:
        lines = lines[:-1]  # the last line may be cut mid-row by the read limit
    lines = lines[:20]
    if len(lines) < 3:
        return False
    for delimiter in DELIMITERS:
        counts = {ln.count(delimiter) for ln in lines}
        if len(counts) != 1:
            continue
        count = next(iter(counts))
        if count >= 2 or (count == 1 and len(lines) >= 5):
            return True
    return False


def sniff(path: Path, header: str | None, large_check: bool = True) -> str | None:
    """Reason this file looks like client data, or None. Never returns file content."""
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            head = fh.read(HEAD_BYTES)
    except OSError:
        return None
    suffix = path.suffix.lower()
    if suffix in ARCHIVE_SUFFIXES:
        return "archive"
    if head.startswith(ARCHIVE_MAGIC):
        return "archive"
    if head.startswith(b"PAR1"):
        return "binary-table"
    if b"\0" in head:
        text = _utf16_text(head)
        if text is None:
            return None
    else:
        text = head.decode("utf-8", errors="replace")
    if header and _squash(header) and _squash(header) in _squash(text):
        return "header-fingerprint"
    if suffix in CODE_SUFFIXES:
        return None
    if _delimited(text, truncated=len(head) >= HEAD_BYTES):
        return "delimited-table"
    if large_check and size > LARGE_BYTES and suffix in LARGE_TEXT_SUFFIXES:
        return "large-text"
    return None
