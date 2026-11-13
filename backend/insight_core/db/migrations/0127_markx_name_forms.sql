-- 0127_markx_name_forms.sql (Stealth v10.17, issue 0186: the News page's speed)
--
-- A page's entity book (identity.lazy_book) reads only what the page asks. The maker of a story (perspectives.Makers)
-- asks which org or maker an owner's handle names: the entities and aliases whose key squashes (names.squash) to one
-- of the handle's forms. These indexes answer that by the form; the expression must stay exactly names.SQUASH_SQL
-- (the same regular expression as names.SQUASH; Postgres and Python agree on every code point, measured). Mark X
-- tables only; no row changes. Idempotent.

CREATE INDEX IF NOT EXISTS mx_entity_aliases_squash_idx
    ON mx_entity_aliases ((regexp_replace(key, '[^0-9a-zа-яͰ-Ͽ一-鿿぀-ヿ가-힯+#]+', '', 'g')));
CREATE INDEX IF NOT EXISTS mx_entities_squash_idx
    ON mx_entities ((regexp_replace(key, '[^0-9a-zа-яͰ-Ͽ一-鿿぀-ヿ가-힯+#]+', '', 'g')));
