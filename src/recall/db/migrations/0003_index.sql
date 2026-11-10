-- M3 index: the projection retrieval reads, and the labels that define relevance.
--
-- ticket     : one row per exported ticket. Identity columns (dealer, customer, contact) and the
--              raw row are deliberately NOT copied: nothing in M3 reads them.
-- eval_label : what counts as "the same problem". Its own table so retrieval SQL cannot read it;
--              whatever defines relevance must be invisible to the retriever, or the metric is
--              circular. tests/integration/test_index_build.py pins that retrieve.py never names it.
--
-- The HNSW index is created by recall.index.build AFTER the bulk load (faster than maintaining it
-- during inserts, and CREATE INDEX CONCURRENTLY cannot run through this runner).
-- vector(1024) is multilingual-e5-large.

create table ticket (
    ticket_id        text primary key,
    created          date,
    category_id      text,
    vehicle_model_id text,
    vehicle_serial   text,
    problem_text     text not null,
    solution_text    text not null,
    problem_vec      vector(1024) not null,
    solution_vec     vector(1024),
    problem_tsv      tsvector generated always as (to_tsvector('de_tech'::regconfig, problem_text)) stored,
    source_sha256    text not null
);

create index ticket_problem_tsv_idx on ticket using gin (problem_tsv);

create table eval_label (
    ticket_id   text primary key references ticket (ticket_id) on delete cascade,
    problem_key text,
    fehlercode  text
);
