-- 0046_discover_addresses.sql (issue 0062)
--
-- Discover counts in the database. discover_addresses holds what Discover reads of each linked
-- address (story_rules.discover_address): its key (a site's host, or on a platform the account;
-- NULL for a platform page that names no account), its site, whether that site is a platform, and
-- whether the address reads like an article (post_links.is_article). They depend on the address
-- alone, so each is worked out once, in Python, the first time Discover meets the address
-- (repo_discover.DiscoverRepository.fill_addresses); `rules` says which version of the rules wrote
-- the row, and a row of older rules is worked out again. Derived: emptying it costs one slower open.
--
-- Idempotent.

CREATE TABLE IF NOT EXISTS discover_addresses (
  url      text PRIMARY KEY,
  key      text,
  site     text NOT NULL,
  platform boolean NOT NULL,
  article  boolean NOT NULL,
  rules    text NOT NULL
);
