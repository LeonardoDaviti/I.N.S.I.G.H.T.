-- 0109_markx_happening_candidates.sql (issue 0166, Stealth v10.14: Pairing's happening source)
--
-- mx_candidates.source may be 'happening': two posts whose readings name one happening (markx/happening.py), written
-- only while mx_settings 'pairing_happening' is on (off by default). (0105-0108 are other branches' numbers; renumber
-- at merge if one lands as 0109: nothing depends on the number.)
--
-- Mark X tables only. Idempotent.

ALTER TABLE mx_candidates DROP CONSTRAINT IF EXISTS mx_candidates_source_check;
ALTER TABLE mx_candidates ADD CONSTRAINT mx_candidates_source_check
  CHECK (source IN ('embedding', 'link', 'entity', 'burst', 'happening'));
