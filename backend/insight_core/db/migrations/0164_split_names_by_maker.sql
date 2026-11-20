-- 0164_split_names_by_maker.sql (Stealth v10.27, issue 0250: one name, many things)
--
-- A bare name's mention placed by the maker split (markx/identity.py split_names, behind entity_bands.json
-- `families.split`, default off) says how: 'rule:maker' (its stated maker), 'rule:post' (a maker its post names
-- otherwise), 'rule:link' (a link of its post to one maker's site), 'facts' (the settled collision answer), or
-- 'unsure' (none of them: it stays on the name's entity). The splits themselves are mx_entity_fixes rows (kind
-- 'maker_split'), their mentions mx_entity_pins (by 'facts'): no new table. Mark X tables only. Idempotent.

ALTER TABLE mx_mentions DROP CONSTRAINT IF EXISTS mx_mentions_placed_check;
ALTER TABLE mx_mentions ADD CONSTRAINT mx_mentions_placed_check
  CHECK (placed IS NULL OR placed IN ('rule:maker', 'rule:context', 'rule:handle', 'rule:post', 'rule:link', 'facts',
                                      'wait', 'unsure'));
