"""Sealed temporal baseline CLI, for an operator-created disposable database only."""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
from contextlib import redirect_stderr, redirect_stdout, suppress
from pathlib import Path

DSN = "postgresql://recall:recall_dev_only@127.0.0.1:5432/recall"


class _BadInput(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise _BadInput


class _Discard:
    """Discard row-bearing library diagnostics without retaining their contents."""

    def write(self, text):
        return len(text)

    def flush(self):
        pass


def _rows(source: Path) -> list[dict[str, str]]:
    from insight.extract import MAX_CELL_BYTES
    from profiler.columns import EXPECTED_COLUMNS

    csv.field_size_limit(MAX_CELL_BYTES)
    with source.open(newline="", encoding="utf-8", errors="replace") as handle:
        reader = csv.DictReader(handle, strict=True)
        fields = reader.fieldnames
        if (
            fields is None
            or len(fields) != len(EXPECTED_COLUMNS)
            or set(fields) != set(EXPECTED_COLUMNS)
        ):
            raise _BadInput
        rows = list(reader)
    if not rows or any(None in row or any(v is None for v in row.values()) for row in rows):
        raise _BadInput
    return rows


def _pipeline(source: Path) -> dict:
    # All imports and row-bearing operations are inside main's diagnostic boundary.
    # No recall.config import, inherited DSN, label override or fake production model.
    import psycopg

    from profiler.gate.embedder import E5Embedder
    from recall import eval_real, index
    from recall.db import migrate

    rows = _rows(source)
    embedder = E5Embedder()
    migrate.apply_all(DSN)
    index.build(DSN, rows, embedder)
    with psycopg.connect(DSN) as conn:
        return eval_real.run_real(conn, embedder)


def _prepare(source: Path) -> tuple[Path, Path]:
    from recall.sealed import sealed_path

    paths = tuple(
        sealed_path(name)
        for name in (
            "eval_real.json",
            "eval_real.json.tmp",
            "window_c.log",
        )
    )
    # Complete all identity checks before deleting a report or opening the log.
    for path in paths:
        if path.is_symlink() or (path.exists() and source.samefile(path)):
            raise _BadInput
    return paths[:2]


def _remove(paths):
    for path in paths:
        path.unlink(missing_ok=True)


def _log(logger, code):
    # Ordinary library logging is globally suppressed at this CLI boundary. Only
    # these fixed application codes are dispatched directly to the sealed handler.
    logger.handle(logging.LogRecord(logger.name, logging.INFO, __file__, 0, code, (), None))


def _execute(argv, outputs: list[Path]) -> int:
    if os.environ.get("RECALL_WINDOW_C") != "1":
        raise _BadInput
    parser = _Parser(prog="recall.window_c", add_help=False, allow_abbrev=False)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--out", required=True, choices=("eval_real.json",))
    args = parser.parse_args(argv)
    try:
        source = args.csv.resolve(strict=True)
        if not source.is_file():
            raise _BadInput
    except OSError:
        raise _BadInput from None
    final, temporary = _prepare(source)
    outputs.extend((final, temporary))
    _remove(outputs)

    from recall import eval_real
    from recall.sealed import sealed_atomic_json, sealed_logger

    logger = sealed_logger("window_c")
    _log(logger, "C_START")
    report = _pipeline(source)
    if not eval_real.validate_report(report):
        _log(logger, "E_REPORT")
        return 2
    sealed_atomic_json("eval_real.json", report)
    _log(logger, "C_DONE")
    return 0


def main(argv: list[str] | None = None) -> int:
    outputs: list[Path] = []
    previous_disable = logging.root.manager.disable
    # A logger can retain a preexisting stderr handler. Suppress ordinary logging
    # as well as prints/warnings throughout row-bearing work and fallible imports.
    logging.disable(logging.CRITICAL)
    try:
        with redirect_stdout(_Discard()), redirect_stderr(_Discard()):
            try:
                result = _execute(argv, outputs)
            except (_BadInput, csv.Error):
                result = 4
            except BaseException:
                result = 3
            if result:
                try:
                    _remove(outputs)
                except BaseException:
                    result = 3
                if outputs:
                    try:
                        from recall.sealed import sealed_logger

                        _log(
                            sealed_logger("window_c"),
                            {2: "E_REPORT", 3: "E_FAILURE", 4: "E_INPUT"}[result],
                        )
                    except BaseException:
                        pass
    finally:
        logging.disable(previous_disable)
    if result:
        with suppress(BaseException):
            sys.stderr.write({2: "E_REPORT\n", 3: "E_FAILURE\n", 4: "E_INPUT\n"}[result])
    return result


if __name__ == "__main__":
    raise SystemExit(main())
