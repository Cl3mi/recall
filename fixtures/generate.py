"""Ask the model for German fault text, one prompt per near-duplicate group.

The model receives plan NUMBERS and invented themes only - never corpus text. That is
what makes the leakage gate a formality rather than a gamble: no real n-gram was ever
available to copy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from datasketch import MinHash, MinHashLSH

from fixtures.llm import Client
from profiler.stats import clusters, vocab
from recall.clean import pipeline

# Invented seed themes. Deliberately not drawn from the profile's top tokens: reusing
# real vocabulary would put real n-grams within the model's reach and the gate would be
# measuring our luck rather than our method.
THEMES = [
    "Hydraulikpumpe verliert Druck",
    "Getriebe schaltet nicht in den zweiten Gang",
    "Bremsleitung undicht an der Hinterachse",
    "Motor startet nach Kaltstart nicht",
    "Kuehlwasserverlust am Zylinderkopf",
    "Ladekran senkt sich selbstaendig ab",
    "Lenkung schwergaengig bei Volllast",
    "Elektronik meldet Sensorfehler am Ausleger",
    "Klimaanlage kuehlt nicht ausreichend",
    "Reifendruckverlust an der Vorderachse",
]


# One subsystem per singleton batch. 1,500 rows give 1,140 singletons in 46 batches of 25,
# and the model has no memory across batches: asked 46 times for "25 different faults" it
# reaches for the same names, so 182 of 1,140 singletons (16.0%) collided into 73 spurious
# near-duplicate clusters - Ansaugfilter x8, Bodenbearbeitungsgeraet x7. That is exactly the
# singleton band's deficit and the mid band's surplus. Steering each batch to its own
# subsystem stops batches competing for the same vocabulary. MUST stay longer than the batch
# count, or batches share a subsystem and the collisions come back.
SUBSYSTEMS = [
    "Hydraulikkreis",
    "Getriebe",
    "Bremsanlage",
    "Motorblock",
    "Kuehlsystem",
    "Ladekran",
    "Lenkung",
    "Bordelektronik",
    "Klimaanlage",
    "Bereifung",
    "Zapfwelle",
    "Frontlader",
    "Dreipunkthydraulik",
    "Kraftstoffsystem",
    "Abgasanlage",
    "Turbolader",
    "Anlasser",
    "Lichtmaschine",
    "Batteriemanagement",
    "Kabelbaum",
    "Fahrerkabine",
    "Sitzfederung",
    "Scheibenwischer",
    "Beleuchtung",
    "Anhaengerkupplung",
    "Druckluftanlage",
    "Achsantrieb",
    "Differentialsperre",
    "Radnabe",
    "Federung",
    "Schaltgestaenge",
    "Kupplungspaket",
    "Oelkuehler",
    "Filtergehaeuse",
    "Einspritzpumpe",
    "Ventilsteuerung",
    "Zylinderkopfdichtung",
    "Kurbelwellenlager",
    "Schwungrad",
    "Hydraulikschlauch",
    "Steuerventil",
    "Arbeitsscheinwerfer",
    "Rueckfahrkamera",
    "Bordcomputer",
    "Regensensor",
    "Neigungssensor",
    "Wiegeeinrichtung",
    "Streuwerk",
    "Haspelantrieb",
    "Schneidwerk",
]

# Padding text. `f"Stoerung {group}"` was not distinct: profiler.stats.vocab.tokenize DROPS
# DIGITS, so every padded singleton tokenised to exactly ['stoerung'] and all 12 of them
# collapsed into one near-duplicate cluster. Distinctness has to come from WORDS.
_PAD_MARKERS = ["ohne Befund", "unklare Meldung", "offener Vorgang", "keine Angabe"]

# A third varying word, because SUBSYSTEMS x _PAD_MARKERS is only 50 x 4 = 200 combinations
# and the planner emits up to 1,200 singleton groups. Measured 2026-08-27: `_pad_title` gave
# 200 distinct titles over 1,200 group ids, and groups 360 and 560 were both
# 'Zapfwelle keine Angabe' - byte-identical titles with empty descriptions, so Jaccard 1.000
# and a guaranteed cluster with no approximation involved. Padding is 1 row today but was 43
# two rounds ago, where such a pair is expected rather than unlucky. The padding path exists
# so a short model cannot stall a run; manufacturing the clusters the bands measure is the one
# thing it must not do.
_PAD_ROUNDS = ["Erstmeldung", "Folgemeldung", "Nachtrag", "Sammelvorgang", "Restposten", "Altfall"]


@dataclass(frozen=True)
class Voice:
    """How a ticket is written, not what it says.

    PROJECT_BRIEF section 8 asks for variants in different voices. Finding 9 is why it
    matters mechanically: clustering is minhash over the TOKEN SET of cleaned
    title+description at threshold 0.7, and two short formulaic descriptions collide
    whatever component they name. A terse mechanic's note and a rambling customer email
    about the same fault share few tokens, so voice moves Jaccard where a subsystem hint
    could not - that was measured at 182 collisions to 173.
    """

    cue: str
    instruction: str


VOICES = [
    Voice(
        cue="Monteurnotiz",
        instruction=(
            "Schreibe als Monteurnotiz: knapp, Stichworte, kein ganzer Satz, "
            "Fachbegriffe und Messwerte statt Erklaerungen."
        ),
    ),
    Voice(
        cue="Kundenmail",
        instruction=(
            "Schreibe als Kundenmail: weitschweifig, in Ich-Form, mit Vorgeschichte "
            "und Nebensaechlichkeiten, unsicher in der Fachsprache."
        ),
    ),
    Voice(
        cue="Formularauszug",
        instruction=(
            "Schreibe als Formularauszug: Feldnamen mit Werten, Abkuerzungen, "
            "immer gleiche Satzbausteine, keine Prosa."
        ),
    ),
]

# An invented product line. PROJECT_BRIEF section 8: obviously fake designations make a leak
# visually obvious. These are INVENTED, never extracted: model_designations.family_count in the
# profile is 0, so there is nothing to parse, and the real product vocabulary that does exist
# (dimension_hints.vehicleModelId top tokens) must never reach a prompt.
#
# The shape matters. profiler/stats/vocab.py's _TOKEN is
# [A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß0-9\-]{1,} - a token must START with a letter but may contain
# digits and hyphens - so "TX-2200" survives tokenization as ONE token while a bare "98" is
# dropped entirely. A designation is only lexically useful if it survives whole.
MODEL_FAMILIES = ["TX", "LR", "VG", "MK", "ND"]


def _designation(index: int) -> str:
    """An invented machine designation, e.g. TX-2240.

    Deterministic in `index` so a prompt is reproducible and its cache key stable.
    """
    family = MODEL_FAMILIES[index % len(MODEL_FAMILIES)]
    series = 2200 + (index // len(MODEL_FAMILIES)) * 10 % 800
    return f"{family}-{series}"


@dataclass(frozen=True)
class Ticket:
    group: int
    title: str
    description: str
    solution: str


# Singletons are asked for in batches of distinct faults rather than one prompt each.
# With ten themes and 1,140 singletons, a per-group prompt collapses to ten identical
# prompts and therefore ten identical tickets - the fixture would be one huge cluster and
# the measured band shares would be meaningless.
SINGLETON_BATCH = 25

# The most any single prompt may ask for. Finding 7: asked for a 216-member group in one
# prompt the model returned 3 records, then 6 and 5 on its two top-ups - 14 of 216, padding
# 202 - and padded tickets carry no solution, so corpus solutions fill came out 0.739
# against a planned 0.870 and verify refused the fixture. Every group of 15 or fewer filled
# on the first prompt, and singleton batches of 25 returned 22-31, so the model is not the
# problem: an absurd count DEGRADES the response rather than truncating it. A probe
# confirmed it independently at 5 records with finish_reason 'stop'. 20 sits inside the
# range measured to work rather than extrapolating from it.
GROUP_BATCH = 20

# Top-up asks per batch before padding. This bound is deliberate and is NOT the thing
# finding 7 changed: padding exists so a short model does not stall the run, and a run that
# retried until satisfied would spin forever on a model that cannot deliver. The fix was the
# size of the ask, not the number of attempts.
TOPUP_ATTEMPTS = 2

# Multiplier on the offset a singleton batch's `series` gains on top-up attempt n, applied as
# `series + len(SUBSYSTEMS) * TOPUP_SERIES_STRIDE * attempt`.
#
# A whole multiple of len(SUBSYSTEMS) changes the prompt text - so the cache cannot serve the
# first ask again - while leaving `series % len(SUBSYSTEMS)` alone, which keeps the top-up in
# the subsystem the batch was steered to.
#
# The multiplier also decides which VOICE the top-up lands on, since `_prompt_distinct` picks
# that with `series % len(VOICES)`. len(SUBSYSTEMS) * 2000 is 1 mod len(VOICES), so attempt n
# advances the voice by exactly n: a batch's three asks use three different voices and its last
# ask differs from the next batch's first. 1000 is 2 mod len(VOICES) and ran +0, +2, +1, ending
# on the voice the next batch opens with - adjacent asks then shared a voice, which is the one
# thing the voice exists to prevent, and a test caught it.
TOPUP_SERIES_STRIDE = 2000


# The profiler's own clustering parameters, so the generator rejects exactly what the
# acceptance test will cluster. profiler/stats/clusters.py runs
# `MinHashLSH(threshold=0.7, num_perm=128)` over the token set of cleaned title+description.
#
# The mechanism matters more than the number, and this was measured the hard way. An earlier
# version of this filter compared EXACT Jaccard against 0.7 and still left 19 colliding
# singletons. `clusters.profile` builds its clusters from `lsh.query()` buckets and never
# re-verifies Jaccard, and MinHashLSH is approximate: 7 of the 15 surviving pairs measured
# BELOW 0.7 - 0.647, 0.667 four times, 0.600 twice. So no exact-Jaccard cutoff at 0.7 can
# prevent clustering, and guessing a margin is expensive - an exact 0.6 rule costs 30.8% of
# supply against 26.5% for querying LSH itself. Use the same index and inherit its
# approximation instead of modelling it.
CLUSTER_THRESHOLD = 0.7
CLUSTER_PERM = 128


def _cluster_text(title: str, description: str) -> str:
    """Exactly the string `profiler/__main__.py` hands to `clusters.profile` for a row.

    One definition, in one place. The expression is the same single-space join the profiler
    uses; stating it twice would be two definitions kept in sync by hand, and `fixtures/plan.py`
    already records where that leads - "if they disagreed about what a form is, the verifier
    would bless exactly the fixtures the renderer got wrong."
    """
    return pipeline.clean(f"{title} {description}").text


def _cluster_tokens(title: str, description: str) -> frozenset[str]:
    """The token set the profiler will compare for this ticket."""
    return frozenset(vocab.tokenize(_cluster_text(title, description)))


def _signature(title: str, description: str = "") -> MinHash:
    """The MinHash the profiler's LSH will index this text under.

    Calls `clusters._minhash` rather than rebuilding its body. The private name is reached
    into deliberately: two hand-synchronised copies of "how a document becomes a signature" is
    the failure this whole filter exists to avoid, and if the profiler ever changes what it
    hashes - §8's gate talks in 8-token shingles - a copy here would silently start filtering
    something the acceptance test no longer measures.
    """
    return clusters._minhash(_cluster_text(title, description), CLUSTER_PERM)


def _keep_distinct(candidates: list[Ticket], limit: int, accepted: list[Ticket]) -> None:
    """Extend `accepted` with candidates the profiler would not cluster with what it holds.

    Measured 2026-08-26: the model repeats itself inside ONE response. 175 of 1,112 parsed
    singleton tickets were literal repeats, 48 reached the fixture, and 100% of the resulting
    collisions sat inside a single batch at median Jaccard 1.000. First candidate wins, which
    mirrors the profiler's own greedy sweep.

    TWO indexes, because a row is clustered on whatever text it ends up carrying. `full` is
    cleaned title+description, which is what the profiler compares for a row that keeps its
    description. `title` is the title alone, which is what it compares once fill-by-year
    blanks the description - and that case is not hypothetical: 12 of the 19 collisions left
    by the full-text-only rule were rows whose descriptions had all been blanked, four of them
    the same 'Bildunterspannung'. Dedup runs before blanking and cannot know which rows will
    lose their description, so it has to hold for both.

    Bucketing a PAIR depends only on that pair's signatures and the band partition, not on
    what else is indexed, so a per-batch index predicts the whole-corpus one FOR THE PAIRS IT
    EXAMINES - and it examines within-batch pairs only.

    **That is a coverage limit, not a fidelity one, and it is the honest caveat on this
    filter.** `clusters.profile` clusters by a greedy sweep, `lsh.query(hashes[i]) | {i}`, so a
    row can join a cluster through a member it was never compared against: a group row, or a
    singleton from another batch. Neither is checked here. At 1,500 rows both measured zero -
    see docs/STATE.md finding 11 - but that rests on voices, per-batch subsystems and invented
    designations making cross-batch overlap unlikely, which is empirical rather than
    structural.

    It will not hold at mirror-set scale. PROJECT_BRIEF section 8's ~65,000-row mirror gives
    about 1,976 batches against 50 SUBSYSTEMS, 3 VOICES and 400 distinct designations
    (`_designation(0) == _designation(400)`), so SUBSYSTEMS' own stated requirement - "MUST stay
    longer than the batch count" - is violated roughly 40-fold and this filter is blind to it.
    Finding 9 returns at that scale. Whoever builds the mirror should dedup against a
    corpus-wide index, not extrapolate from the fixture's zeros.
    """
    full = MinHashLSH(threshold=CLUSTER_THRESHOLD, num_perm=CLUSTER_PERM)
    title = MinHashLSH(threshold=CLUSTER_THRESHOLD, num_perm=CLUSTER_PERM)
    for index, held in enumerate(accepted):
        full.insert(str(index), _signature(held.title, held.description))
        title.insert(str(index), _signature(held.title))
    for item in candidates:
        if len(accepted) >= limit:
            return
        item_full = _signature(item.title, item.description)
        item_title = _signature(item.title)
        if full.query(item_full) or title.query(item_title):
            continue
        key = str(len(accepted))
        full.insert(key, item_full)
        title.insert(key, item_title)
        accepted.append(item)


def _prompt(theme: str, count: int, series: int) -> str:
    """ONE problem, `count` different ways of resolving it.

    Finding 8: clustering is minhash-lsh over the TOKEN SET of cleaned title+description at
    threshold 0.7, so a group clusters only if its members share the PROBLEM text. This
    prompt used to ask for a different diagnosis per ticket, which varied the problem too -
    50 of 51 groups fragmented, group 0 across 143 clusters at purity 0.06, and the large
    band came out 0.0000 against a real 0.1440. The corpus's own largest cluster is 2,034
    tickets of repeated handover boilerplate: recurring problems repeat their wording.

    The variety the product needs is in the RESOLUTION, which is also where the architecture
    puts it - the primary vector represents the problem, a separate vector the solution.

    Each resolution must name its OWN diagnosis. Sharing the description would otherwise drop
    the per-ticket diagnosis, and enrichment reads root cause and resolution steps out of
    `solutions`. Nothing the application needs may be lost by this change.

    `series` keeps two groups sharing a theme from sharing a prompt, and therefore from
    collapsing into a single cluster.
    """
    return (
        f"Du schreibst Werkstatt-Tickets fuer Landmaschinen auf Deutsch.\n"
        f"Fehlerbild: {theme}\n"
        f"Maschine: {_designation(series)}\n"
        f"Serie {series}\n\n"
        f"Schreibe {count} Tickets zu genau EINEM Fehlerbild.\n"
        f"Alle {count} Tickets beschreiben DASSELBE Problem mit demselben Wortlaut - "
        f"Titel und Befund sind in jedem Ticket gleich und werden nicht variiert.\n"
        f"Nur der Loesungsweg unterscheidet sich: andere Diagnose, anderes Ersatzteil, "
        f"andere Reihenfolge. Nicht dieselbe Loesung anders formuliert.\n"
        f"Jeder Loesungsweg nennt SEINE EIGENE Diagnose und die durchgefuehrte Reparatur.\n\n"
        f"Format - Titel und Befund genau einmal, dann {count} unterschiedliche "
        f"Loesungswege:\n"
        f"TITEL: <kurz>\nBEFUND: <2-3 Saetze>\n"
        f"LOESUNG 1: <2-3 Saetze>\nLOESUNG 2: <2-3 Saetze>\n"
    )


def _series(group: int, batch: int, attempt: int) -> int:
    """A distinct prompt id per (group, batch, attempt).

    `series` exists so two groups sharing a theme do not share a prompt, and therefore do
    not collapse into one cluster. Batch 0's first ask keeps the bare group index and its
    top-ups keep `group * 1000 + attempt`, which is what those prompts were before batching:
    a group of GROUP_BATCH or fewer sends byte-identical prompts to the ones already
    cached, so an existing cache still hits and only genuinely new asks cost a model call.
    """
    if batch == 0 and attempt == 0:
        return group
    return group * 1000 + batch * 10 + attempt


def _pad_title(group: int) -> str:
    """A padded singleton's title, lexically distinct from its neighbours.

    Distinctness must come from words: the profiler's tokenizer drops digits, so
    `Stoerung 98` and `Stoerung 99` are the same token set and every padded singleton
    clustered together.

    Three varying words, not two. SUBSYSTEMS x _PAD_MARKERS is 200 combinations against up to
    1,200 singleton groups, so the two-word form repeated with period 200 - groups 360 and 560
    were both 'Zapfwelle keine Angabe'. `_PAD_ROUNDS` carries the third, taking the period to
    1,200 and covering the planner's whole range.
    """
    marker = _PAD_MARKERS[(group // len(SUBSYSTEMS)) % len(_PAD_MARKERS)]
    round_word = _PAD_ROUNDS[(group // (len(SUBSYSTEMS) * len(_PAD_MARKERS))) % len(_PAD_ROUNDS)]
    return f"{SUBSYSTEMS[group % len(SUBSYSTEMS)]} {marker} {round_word}"


def _prompt_distinct(count: int, series: int, avoid: tuple[str, ...] = ()) -> str:
    """Unrelated faults, one per ticket - the corpus is 76% singletons.

    Each batch gets a subsystem AND a voice. The subsystem alone was not enough: it moved
    collisions from across batches to within them, 182 to 173, because 25 genuinely different
    faults inside one subsystem forces minor variations on one component. The VOICE is what
    moves Jaccard, because clustering compares token SETS and two differently-voiced tickets
    about the same fault barely overlap.

    Voice cycles on a different modulus from the subsystem so adjacent batches share neither.

    The voice instruction sits AFTER the count sentence on purpose. It opens with "Schreibe
    als ...", and callers read the count back out of the prompt with
    `split("Schreibe ")[1]` - putting the instruction first made that read "als" and the
    singleton top-up tests went red.

    `avoid` lists the faults this batch has already accepted. Dedup alone leaves 32 of 46
    batches short by 319 rows in total, because the model cannot see what it already produced
    - the same root cause as the duplicates themselves. An EMPTY avoid tuple leaves the prompt
    identical to the no-avoid form, so only top-ups carry the block and a first ask stays
    cache-eligible. (The test pins that equivalence, not that any particular entry on disk
    still hits: `Maschine:` and `Stil:` in this same prompt already invalidated every
    singleton entry written before they existed.)
    """
    subsystem = SUBSYSTEMS[series % len(SUBSYSTEMS)]
    voice = VOICES[series % len(VOICES)]
    taken = ""
    if avoid:
        listed = "\n".join(f"- {name}" for name in avoid)
        taken = (
            f"Diese Fehlerbilder sind schon vergeben. Vermeide sie und auch Varianten "
            f"davon:\n{listed}\n\n"
        )
    return (
        f"Du schreibst Werkstatt-Tickets fuer Landmaschinen auf Deutsch.\n"
        f"Serie {series}\n"
        f"Maschine: {_designation(series)}\n"
        f"Baugruppe: {subsystem}\n"
        f"Stil: {voice.cue}\n\n"
        f"Schreibe {count} Tickets zu {count} VERSCHIEDENEN Fehlerbildern an der "
        f"Baugruppe {subsystem} - unterschiedliche Bauteile, unterschiedliche Symptome, "
        f"kein Zusammenhang zwischen den Tickets. Verwende nur Fehlerbilder, die zu "
        f"{subsystem} gehoeren.\n\n"
        f"{voice.instruction}\n"
        f"Formuliere jedes Ticket anders. Wiederhole keine Satzbausteine aus einem "
        f"anderen Ticket.\n\n"
        f"{taken}"
        f"Format je Ticket, jeweils eine Zeile:\n"
        f"TITEL: <kurz>\nBEFUND: <2-3 Saetze>\nLOESUNG: <2-3 Saetze>\n---\n"
    )


# The model decorates the format it was given: '**TITEL:**', '1. TITEL:', '- TITEL:'.
# An unrecognised prefix used to produce a ticket with an EMPTY title, which flows into
# the fixture instead of registering as a shortfall the retry path can still fix.
_DECORATION = re.compile(r"^[\s>#*\-–—]*(?:\d+[.)])?\s*")
_FIELD = re.compile(r"^(TITEL|BEFUND|LOESUNG)\**\s*:\s*(.*)$", re.IGNORECASE)
_KEYS = {"TITEL": "title", "BEFUND": "description", "LOESUNG": "solution"}


def _parse(text: str, group: int) -> list[Ticket]:
    """The records the model actually emitted, not the ones the prompt asked for.

    A record is flushed on the separator OR on the next TITEL, because two well-formed
    records run together without a '---' used to parse as one - the earlier overwritten
    in place. A record without a title is not a ticket: emitting it with an empty title
    hid a shortfall that the retry path exists to fix.
    """
    tickets: list[Ticket] = []
    current: dict[str, str] = {}

    def flush() -> None:
        nonlocal current
        if current.get("title"):
            tickets.append(
                Ticket(
                    group,
                    current["title"],
                    current.get("description", ""),
                    current.get("solution", ""),
                )
            )
        current = {}

    for raw in text.splitlines():
        stripped = raw.strip()
        if stripped.startswith("---"):
            flush()
            continue
        match = _FIELD.match(_DECORATION.sub("", stripped))
        if not match:
            continue
        field = _KEYS[match.group(1).upper()]
        if field == "title" and current.get("title"):
            flush()  # a new record began without a separator
        current[field] = match.group(2).strip().strip("*").strip()

    flush()
    return tickets


# `LOESUNG 1:` carries a digit before the colon, which `_FIELD` cannot match. Only the
# variants parser needs this; `_parse` keeps its own regex and its four pinned tests.
_FIELD_NUMBERED = re.compile(r"^(TITEL|BEFUND|LOESUNG)\s*\d*\**\s*:\s*(.*)$", re.IGNORECASE)


def _parse_variants(text: str) -> tuple[str, str, list[str]]:
    """One problem, and every resolution offered for it.

    Deliberately separate from `_parse`, which still serves the singleton path where each
    record IS its own ticket and whose contract four tests pin.

    The first TITEL and BEFUND win; later ones are ignored, because the model repeats the
    header per block whenever it feels like it and `llm.Fake` always does. Text with no TITEL
    yields no problem, so the caller pads rather than emitting a titleless ticket - finding 4.
    """
    title = ""
    description = ""
    resolutions: list[str] = []
    for raw in text.splitlines():
        match = _FIELD_NUMBERED.match(_DECORATION.sub("", raw.strip()))
        if not match:
            continue
        field = _KEYS[match.group(1).upper()]
        value = match.group(2).strip().strip("*").strip()
        if field == "title" and not title:
            title = value
        elif field == "description" and not description:
            description = value
        elif field == "solution" and value:
            resolutions.append(value)
    return title, description, resolutions


def tickets(
    group_sizes: list[int], client: Client, stats: dict[str, int] | None = None
) -> list[Ticket]:
    """One ticket per group member.

    Multi-member groups get one prompt each, asking for that many different approaches to
    a single fault. Singletons are batched, because asking once per singleton would send
    the same prompt over a thousand times.

    `stats` collects what had to be padded. Padding keeps a run from stalling, but it
    emits byte-identical duplicates with no solution inside a group meant to hold
    different approaches - a degradation the caller must be told about rather than
    discover in the profile afterwards.
    """
    out: list[Ticket] = []
    padded = 0
    groups_short = 0

    for index, size in enumerate(group_sizes):
        if size < 2:
            continue
        theme = THEMES[index % len(THEMES)]
        members: list[Ticket] = []
        short_batches = 0
        # The group's ONE problem, taken from the first batch that yields one and reused by
        # every later batch. Letting each batch keep its own problem statement would fragment
        # a 216-member group into 11 clusters, which is finding 8 in a smaller costume.
        title = ""
        description = ""
        for batch, start in enumerate(range(0, size, GROUP_BATCH)):
            want = min(GROUP_BATCH, size - start)
            got_title, got_desc, ways = _parse_variants(
                client(_prompt(theme, want, _series(index, batch, 0)))
            )
            if not title and got_title:
                title, description = got_title, got_desc
            attempt = 0
            while len(ways) < want and attempt < TOPUP_ATTEMPTS:
                attempt += 1
                shortfall = want - len(ways)
                more_title, more_desc, more = _parse_variants(
                    client(_prompt(theme, shortfall, _series(index, batch, attempt)))
                )
                if not title and more_title:
                    title, description = more_title, more_desc
                ways.extend(more)
            if len(ways) < want:  # the model kept coming up short; do not stall the run
                short_batches += 1
                padded += want - len(ways)
                ways.extend([""] * (want - len(ways)))
            members.extend(
                Ticket(index, title or theme, description or theme, way) for way in ways[:want]
            )
        # Counted per GROUP, not per batch: `groups_short` answers "how many near-duplicate
        # groups were degraded", and a 216-member group short in three batches is still one
        # degraded group.
        if short_batches:
            groups_short += 1
        out.extend(members)

    singletons = [i for i, size in enumerate(group_sizes) if size < 2]
    for series, start in enumerate(range(0, len(singletons), SINGLETON_BATCH)):
        batch = singletons[start : start + SINGLETON_BATCH]
        produced: list[Ticket] = []
        _keep_distinct(
            _parse(client(_prompt_distinct(len(batch), series)), -1), len(batch), produced
        )
        # The same two top-ups the group path gets. The singleton path had none, and once
        # each batch was steered to a single subsystem - which makes 25 genuinely different
        # faults harder to produce - padding rose from 12 to 43. Padded rows carry no
        # solution, so corpus solutions fill fell to 0.838 against a planned 0.870 and verify
        # refused the fixture. TOPUP_ATTEMPTS is unchanged; it is simply applied here too.
        attempt = 0
        while len(produced) < len(batch) and attempt < TOPUP_ATTEMPTS:
            attempt += 1
            shortfall = len(batch) - len(produced)
            # The top-up names what is already taken, because dedup converts repetition into a
            # shortfall the model cannot fill blind - see _prompt_distinct's `avoid` docstring.
            _keep_distinct(
                _parse(
                    client(
                        _prompt_distinct(
                            shortfall,
                            series + len(SUBSYSTEMS) * TOPUP_SERIES_STRIDE * attempt,
                            tuple(item.title for item in produced),
                        )
                    ),
                    -1,
                ),
                len(batch),
                produced,
            )
        if len(produced) < len(batch):
            groups_short += 1
            padded += len(batch) - len(produced)
        for offset, group in enumerate(batch):
            if offset < len(produced):
                item = produced[offset]
                out.append(Ticket(group, item.title, item.description, item.solution))
            else:
                out.append(Ticket(group, _pad_title(group), "", ""))

    if stats is not None:
        stats["padded"] = padded
        stats["groups_short"] = groups_short
    return out
