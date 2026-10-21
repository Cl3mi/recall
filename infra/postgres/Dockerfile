FROM postgres:18-bookworm

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        postgresql-18-pgvector \
        hunspell-de-de; \
    rm -rf /var/lib/apt/lists/*

COPY derive-compound-dict.pl /usr/local/bin/derive-compound-dict.pl

RUN set -eux; \
    share="$(pg_config --sharedir)/tsearch_data"; \
    cp /usr/share/hunspell/de_DE.dic "$share/de_de.dict"; \
    cp /usr/share/hunspell/de_DE.aff "$share/de_de.affix"; \
    : > "$share/de_tech_synonyms.syn"; \
    grep -qi '^SET *UTF-8' "$share/de_de.affix" \
      || echo "WARNING: de_DE.aff is not UTF-8; compound splitting may misbehave" >&2; \
    perl /usr/local/bin/derive-compound-dict.pl \
        "$share/de_de.affix"      "$share/de_de.dict" \
        "$share/de_compound.affix" "$share/de_compound.dict"; \
    ls -l "$share/de_de.dict" "$share/de_de.affix" "$share/de_tech_synonyms.syn" \
        "$share/de_compound.dict" "$share/de_compound.affix"
