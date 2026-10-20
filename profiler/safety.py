"""Output an AI tool may read must be structurally incapable of carrying corpus data.

Two mechanisms, both enforced by types rather than discipline:

  * `SafetyViolation` takes a registered code, an allowlisted schema path, and
    numeric facts. Passing a string raises TypeError at the raise site.
  * `detail()` sends verbatim values to the quarantine tree, for human eyes only.

`run_scrubbed()` wraps the entry point so a library exception - UnicodeDecodeError
carries the offending bytes in its message - cannot print corpus content either.
"""

from __future__ import annotations

import os
import pathlib
import re
import traceback
from collections.abc import Callable

QUARANTINE_DIR = pathlib.Path("local/quarantine")

# Overridable because the default is RELATIVE, and inside an airlock window the working
# directory is the image's /work - so the detail log landed on the container's ephemeral
# filesystem and `--rm` destroyed it. The runbook told the operator to read a file that
# never existed, meaning a failed sealed run deleted its own only diagnostic, with no AI
# available to help. Window A now points this at the mounted quarantine volume.
DETAIL_LOG = pathlib.Path(
    os.environ.get("RECALL_PROFILER_DETAIL_LOG") or QUARANTINE_DIR / "profiler_detail.log"
)

SINK_UNAVAILABLE = (
    "       WARNING: the detail sink could not be written, so no verbatim record exists.\n"
    "       Set RECALL_PROFILER_DETAIL_LOG to a writable path and re-run."
)

CODES = frozenset(
    {
        "VOCAB_BELOW_MIN_FREQ",
        "TOPVALUE_BELOW_MIN_FREQ",
        "DENYLISTED_COLUMN_VALUES",
        "SHAPE_CONTAINS_DIGITS",
        "ENTITY_PATTERN_MATCH",
        "UNEXPECTED_FAILURE",
    }
)

# Schema paths only. Column names are published in PROJECT_BRIEF.md §4, so they
# are structure rather than content; anything else is rejected.
_LOCATION = re.compile(r"^[a-z_]+(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\[\d+\])?$")


class SafetyViolation(RuntimeError):
    """Carries a code, a schema location and numbers. Never a corpus value."""

    def __init__(self, code: str, location: str, **facts: float) -> None:
        if code not in CODES:
            raise ValueError(f"unregistered safety code {code!r}")
        if not _LOCATION.match(location):
            raise ValueError(
                f"location {location!r} is not a plain schema path; free text may carry corpus data"
            )
        for key, value in facts.items():
            if not isinstance(value, (int, float)):
                raise TypeError(
                    f"fact {key!r} must be numeric - strings may carry corpus data, "
                    "send them to safety.detail() instead"
                )
        self.code = code
        self.location = location
        self.facts = facts
        rendered = " ".join(f"{k}={v}" for k, v in sorted(facts.items()))
        super().__init__(f"{code} at {location}" + (f" ({rendered})" if rendered else ""))


def detail(code: str, location: str, payload: str) -> bool:
    """Record a verbatim value for HUMAN eyes only, inside the quarantine tree.

    **Never raises.** It is called from inside `run_scrubbed`'s exception handler and
    from `selfcheck._reject`, so an exception here escapes the scrubber and Python then
    prints the full chained traceback - including the original exception, which for a
    UnicodeDecodeError or csv.Error carries corpus bytes. That is the exact leak the
    whole safety layer exists to prevent, firing precisely when it matters. A sink that
    cannot be written is a degraded diagnostic; a traceback on stdout is a data leak.

    Returns True if the payload was recorded.
    """
    try:
        DETAIL_LOG.parent.mkdir(parents=True, exist_ok=True)
        with DETAIL_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"[{code}] {location}: {payload}\n")
        return True
    except BaseException:
        # Deliberately swallowed, and deliberately silent about why: the reason string
        # from the OS can embed the path, and the payload must never be re-raised.
        return False


def run_scrubbed(fn: Callable[..., int], *args: object, **kwargs: object) -> int:
    """Entry-point wrapper. Exit 0 ok, 2 safety violation, 3 unexpected failure."""
    try:
        return fn(*args, **kwargs)
    except SafetyViolation as exc:
        try:
            print(f"ABORT {exc}", flush=True)
            print(
                f"       verbatim detail in {DETAIL_LOG.absolute()} - local only, do not copy out",
                flush=True,
            )
        except BaseException:
            pass
        return 2
    except BaseException as exc:
        # Everything in here is belt-and-braces: nothing may escape and become a
        # traceback. type(exc).__name__ is the only thing derived from the exception -
        # never str(exc), which is what carries the offending bytes.
        try:
            recorded = detail("UNEXPECTED_FAILURE", "profiler", traceback.format_exc())
            message = f"ABORT UNEXPECTED_FAILURE type={type(exc).__name__}"
            if recorded:
                message += (
                    f"\n       traceback in {DETAIL_LOG.absolute()} - local only, do not copy out"
                )
            else:
                message += "\n" + SINK_UNAVAILABLE
            print(message, flush=True)
        except BaseException:
            pass
        return 3
