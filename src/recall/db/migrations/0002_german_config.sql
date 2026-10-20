-- German technical text search. Two configurations exist deliberately:
--   de_tech     : dictionaries see real umlauts (the intended production config)
--   de_tech_ua  : unaccent runs first, as PROJECT_BRIEF.md §7 suggested
-- tests/integration/test_german_fts.py records which cases each one handles.
--
-- The dictionary is de_compound, NOT the stock de_de shipped by hunspell-de-de.
-- Do not "simplify" it back: igerman98 declares COMPOUNDBEGIN/MIDDLE/END in its
-- affix file but grants those flags to words through hunspell *affix flag
-- continuation* (e.g. "SFX j 0 0/xoc ." gives class j the flags x, o, c).
-- PostgreSQL's spell.c does not implement flag continuation, so with de_de it
-- sees zero COMPOUNDBEGIN entries out of 21,214 compound-capable ones, no
-- compound is ever legal, every compound lexizes to NULL and falls through to
-- german_stem, which stems the whole word instead of splitting it.
-- infra/postgres/derive-compound-dict.pl resolves that intent statically at
-- image-build time into de_compound.dict / de_compound.affix. de_de.dict and
-- de_de.affix stay in the image for comparison.

create text search dictionary german_hunspell (
    template  = ispell,
    dictfile  = de_compound,
    afffile   = de_compound,
    stopwords = german
);

-- Filled at M4 by recall.german.synonyms from the profile's unrecognised-token list.
-- The backing file de_tech_synonyms.syn is created empty by the Postgres image.
create text search dictionary de_synonyms (
    template = synonym,
    synonyms = de_tech_synonyms
);

create text search configuration de_tech (copy = german);
alter text search configuration de_tech
    alter mapping for asciiword, word, hword, hword_part, hword_asciipart
    with de_synonyms, german_hunspell, german_stem;

create text search configuration de_tech_ua (copy = german);
alter text search configuration de_tech_ua
    alter mapping for asciiword, word, hword, hword_part, hword_asciipart
    with unaccent, de_synonyms, german_hunspell, german_stem;
