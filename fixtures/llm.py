"""Talk to the model, and remember what it said.

Sampling is not reproducible, so the fixture ITSELF is the artifact: generated once,
verified, gated and committed. The cache exists so a partial failure resumes instead of
restarting, and so a rerun during review costs nothing.
"""

from __future__ import annotations

import contextlib
import hashlib
import inspect
import json
import pathlib
import random
import re
from collections.abc import Callable
from typing import Protocol


class Client(Protocol):
    identity: str

    def __call__(self, prompt: str) -> str: ...


# The most tokens a single response may generate. Finding 10: the request carried no bound at
# all, so a draw was limited only by the server's --max-model-len 32768 while the client gave
# up after 120s, and one unlucky draw aborted a whole run with the singleton phase saving
# nothing. Measured 2026-08-26 on Qwen2.5-32B-Instruct-AWQ at temperature 0.8: 12 controlled
# draws of one singleton prompt ran 1,012-2,601 completion tokens (17-43s), a 28-call prefill
# drew 112.6s / 6,665 tokens - seven seconds inside the timeout - and the two draws that killed
# consecutive runs were still generating past 120s at ~59 tok/s, so roughly 7,000 tokens.
# 4096 sits well above every measured draw and caps a runaway at about 70s.
#
# This is NOT part of the cache key. `Cached` keys on sha256(identity + "\0" + prompt), which
# excludes request parameters, so adding this leaves every existing cached response valid.
MAX_TOKENS = 4096


def _slug(identity: str) -> str:
    """A directory name a human can read, so a cache directory says which client filled it."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", identity).strip("-") or "client"


class Cached:
    """Wrap a client with a content-addressed disk cache, namespaced by WHO answered.

    Keying on the prompt alone made --fake a lie. Prompts are fully determined by
    profile, rows and seed and carry no trace of the client, and the cache is consulted
    before the inner client, so a stub run poisoned every entry and a later model run
    returned byte-identical stub German without ever contacting the H100 - verified
    against a dead port, exit 0, no warning, no provenance marker.

    The identity goes into the key AND into the entry: the key keeps the two runs apart,
    and the recorded identity means a hand-moved file cannot be served to the wrong
    client either.
    """

    def __init__(self, inner: Callable[[str], str], cache_dir: pathlib.Path, identity: str) -> None:
        if not identity:
            raise ValueError(
                "a cache needs the identity of the client that fills it; without one, "
                "a --fake run answers for the model"
            )
        self._inner = inner
        self._identity = identity
        self._dir = pathlib.Path(cache_dir) / _slug(identity)
        self._dir.mkdir(parents=True, exist_ok=True)

    def __call__(self, prompt: str) -> str:
        key = hashlib.sha256(f"{self._identity}\0{prompt}".encode()).hexdigest()[:32]
        path = self._dir / f"{key}.json"
        if path.exists():
            entry = json.loads(path.read_text(encoding="utf-8"))
            if entry.get("identity") == self._identity:
                return entry["response"]
        answer = self._inner(prompt)
        path.write_text(
            json.dumps({"identity": self._identity, "response": answer}, ensure_ascii=False),
            encoding="utf-8",
        )
        return answer


_ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def _letters(value: int) -> str:
    """A short all-letter tag, base-26.

    Letters, never digits. `profiler/stats/vocab.py`'s `_TOKEN` is
    `[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\\-]{1,}`, so a token must START with a letter and a
    bare number is dropped entirely - `Stoerung 98` tokenises to just `['stoerung']`. That
    is the mistake `generate._PAD_MARKERS` already exists to correct, and the same one this
    stub made: distinctness has to come from WORDS.
    """
    text = ""
    value = abs(value)
    while True:
        text = _ALPHABET[value % 26] + text
        value //= 26
        if not value:
            return text


class Fake:
    """Deterministic stand-in so tests need no GPU.

    It must emit the same block format the real prompt asks for - a bare sentence would
    parse to zero tickets and every group would fall through to the padding path,
    producing one repeated string for the whole fixture.

    Every block must also be LEXICALLY distinct under the profiler's own tokenizer, not
    merely a distinct string. This stub used to vary a block only by `rng.randrange(10**6)`
    and the bare index `n`, both digit-only, so all 200 blocks shared one cleaned token set:
    1,140 distinct singleton STRINGS that were a single cluster. `docs/STATE.md` recorded
    that as the reason `--fake` cannot prove cluster bands, and it became a hard failure once
    `generate` started rejecting near-duplicates - 60 stub singletons collapsed to 4 and the
    rest padded.

    So content is indexed by `n` across three lists whose product (7 x 5 x 6 = 210) exceeds
    BLOCKS, which makes the (part, symptom, place) triple unique per block, and each block
    carries two letter codes unique to its (prompt, n). Each list is additionally ROTATED by a
    per-prompt offset, so the same `n` under two prompts does not repeat its content words.

    **Do not reason about this from exact Jaccard.** An earlier version of this docstring
    computed s/(2m-s) per pair, concluded "all under 0.7 with margin", and was wrong: the
    profiler clusters on `MinHashLSH` buckets it never re-verifies, and at
    `_optimal_param(0.7, 128)` = (b=14, r=9) a pair at J=0.60 buckets with probability 0.132.
    The old stub put the same `n` under two prompts at exactly 0.60, and measured over a
    1,140-singleton population `clusters.profile` reported a singleton rate of **0.3974** -
    the stub was clustering 60% of its own singletons while every pairwise Jaccard sat below
    0.7. `fixtures/generate.py`'s CLUSTER_THRESHOLD comment records the same lesson from the
    other direction.

    The only trustworthy statement is a measured one, so:
    `tests/unit/test_fixture_generate.py::test_the_fake_stub_does_not_cluster_its_own_singletons`
    runs `clusters.profile` over a realistic multi-prompt population and pins the rate.
    """

    _PARTS = ["Dichtung", "Ventil", "Sensor", "Schlauch", "Lager", "Pumpe", "Filter"]
    _SYMPTOMS = ["klemmt", "leckt", "vibriert", "ueberhitzt", "blockiert"]
    _PLACES = ["vorne", "hinten", "links", "rechts", "oben", "unten"]
    _ACTIONS = ["getauscht", "gereinigt", "nachgezogen", "entlueftet", "kalibriert"]
    # Must exceed the largest group the planner can emit - 190 at 1,500 rows (the
    # handover cluster) - or generate.tickets' two retries exhaust the supply, the
    # group falls through to the padding path, and solutions fill silently drops (measured:
    # 0.833 against a planned 0.870 at BLOCKS=40). A materially larger corpus would need
    # this raised again.
    #
    # It must ALSO stay at or below len(_PARTS) * len(_SYMPTOMS) * len(_PLACES) = 210, which
    # is what makes each block's (part, symptom, place) triple unique and therefore keeps two
    # blocks of one prompt below the clustering threshold. Asserted below rather than trusted.
    BLOCKS = 200

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed
        # The identity carries a fingerprint of the stub's own content, not just the seed.
        # Finding 1 established that a client must declare WHO answered, because `Cached`
        # keys on sha256(identity + "\0" + prompt) and a stub run otherwise poisons the
        # model's cache. This closes the same hole one level down: the identity used to be
        # `fake:seed=N` whatever the stub emitted, so when this stub's text changed, 493
        # entries written by the OLD stub still sat under the identity the NEW one claimed
        # and were served straight back - 60 stub singletons collapsed to 4 and the rest
        # padded, which read as a dedup bug rather than a cache bug. An identity has to say
        # WHICH VERSION answered too.
        self.identity = f"fake:{_stub_fingerprint(type(self))}:seed={seed}"

    def __call__(self, prompt: str) -> str:
        rng = random.Random(f"{self._seed}:{prompt}")
        # One letter tag per PROMPT, so two prompts never emit the same block, and one per
        # block on top of it. Together they make the code unique to (prompt, n) - which is
        # what keeps the same `n` under two different prompts below the 0.7 threshold.
        tag = _letters(rng.randrange(26**4))
        parts, symptoms, places = self._PARTS, self._SYMPTOMS, self._PLACES
        # A separate rotation per list, drawn per PROMPT. Without these, block `n` of every
        # prompt shared its three content words and differed only in the code - measured at
        # exactly J=0.60, where LSH buckets 132 pairs in 1,000, which is what drove the stub's
        # singleton rate down to 0.3974. Three independent offsets mean two prompts have to
        # collide on all three at once before block `n` repeats its content.
        offsets = (
            rng.randrange(len(parts)),
            rng.randrange(len(symptoms)),
            rng.randrange(len(places)),
        )
        blocks = []
        for n in range(self.BLOCKS):
            part = parts[(n + offsets[0]) % len(parts)]
            symptom = symptoms[(n // len(parts) + offsets[1]) % len(symptoms)]
            place = places[(n // (len(parts) * len(symptoms)) + offsets[2]) % len(places)]
            action = self._ACTIONS[n % len(self._ACTIONS)]
            # TWO codes, not one. A single shared code left the title and the description
            # overlapping on it, so a blanked row and its unblanked twin still shared a token.
            # Separate codes keep the title's token set and the description's disjoint.
            code = f"{tag}{_letters(n)}"
            code_body = f"{tag}x{_letters(n)}"
            # Deliberately no connective prose: a word shared by every block raises the
            # overlap of every pair at once, and LSH is far less forgiving of that than the
            # exact-Jaccard arithmetic this stub used to be justified by.
            blocks.append(
                f"TITEL: {part} {symptom} {code}\n"
                f"BEFUND: {place} {code_body}.\n"
                f"LOESUNG: {part} {action}, Pruefschritt {code_body}.\n---"
            )
        return "\n".join(blocks)


# Defined after the class because it reads the class. `Fake.__init__` looks it up at call
# time, so the ordering is fine.
def _stub_fingerprint(cls: type[Fake]) -> str:
    """A short hash of everything that determines what `cls` emits.

    Takes the CLASS, not nothing. Reading `Fake._PARTS` and `Fake.__call__` by name made the
    fingerprint blind to subclasses: `class Wide(Fake): BLOCKS = 260` emitted different text
    under the base class's identity, which is the same hole this function exists to close,
    still open on the subclass route. Nothing in the repo subclasses `Fake` today, but the
    reviewer hit it running experimental stub variants during review - had those gone through
    `--fake` they would have been served the base stub's cached entries.

    Hashing the word lists alone would NOT be enough, and that is not hypothetical: the change
    that caused the stale-cache bug was to the block TEMPLATE, not to the vocabulary. So the
    source of `__call__` goes in too, which also means the fingerprint cannot be forgotten the
    way a hand-bumped version number can.

    Recomputed per instantiation rather than cached at import, so a test can alter the stub and
    observe the identity move. It is a sha256 over a few hundred bytes and `Fake` is built a
    few dozen times in the whole suite.

    A formatting-only edit to `__call__` also moves the fingerprint. That is accepted: the only
    cost is regenerating stub responses, which needs no GPU, and the alternative is a
    fingerprint that misses real changes.
    """
    material = repr((cls._PARTS, cls._SYMPTOMS, cls._PLACES, cls._ACTIONS, cls.BLOCKS, _ALPHABET))
    # `_letters` is in here because the closure of the emitted text is larger than `__call__`.
    # It decides the code in every block of every prompt, and it was outside the fingerprint:
    # measured, swapping its algorithm changed the emitted text while leaving the identity at
    # fake:90690df9:seed=7. Exactly the bug class this function closes, one level out.
    #
    # Source unavailable (a frozen build) still leaves the lists and BLOCKS versioning the
    # data half. A weaker fingerprint beats an exception on a path this cheap.
    with contextlib.suppress(OSError):
        material += inspect.getsource(cls.__call__)
        material += inspect.getsource(_letters)
    return hashlib.sha256(material.encode()).hexdigest()[:8]


# The BLOCKS <= len(_PARTS) * len(_SYMPTOMS) * len(_PLACES) bound that Fake's distinctness
# argument rests on is asserted by
# tests/unit/test_fixture_generate.py::test_the_stub_has_enough_combinations_for_its_block_count
# rather than here: a module-level assert in library code disappears under `python -O`, and on
# this project the tests are where intent is pinned.


class VLLM:
    """OpenAI-compatible client for vLLM on the H100.

    httpx is imported lazily so the test suite never needs it installed for fixture work,
    and so a machine without the box configured can still run everything else.
    """

    def __init__(self, base_url: str, model: str, temperature: float = 0.8) -> None:
        self._base_url = base_url
        self._model = model
        self._temperature = temperature
        self.identity = f"vllm:{model}@t{temperature}"

    def __call__(self, prompt: str) -> str:
        import httpx

        response = httpx.post(
            f"{self._base_url}/v1/chat/completions",
            json={
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": self._temperature,
                "max_tokens": MAX_TOKENS,
            },
            timeout=120.0,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"].strip()
