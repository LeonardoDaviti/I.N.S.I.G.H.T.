-- 0073_access_tokens.sql (issue 0126 (1), the owner 2026-11-07: gift links kept for clicking, ignored for matching)
--
-- url_normalization now drops an access token (a query key naming a token, gift, unlock or access, or any key whose
-- value is a signed JWT) and a share mark (smid, taid, mrfcid, srnd, leadSource, reflink, dib_tag, syn-<8 hex>) from
-- every compared address.
-- 1. post_links.shared_url: the link's address as its post wrote it, when its compared form dropped one (else null);
--    a story's outside origin opens it.
-- 2. The links stored before keep the key in their address (post_links.target_url): the posts holding one are read
--    again, from their stored HTML, by the story job's first step (fill_missing_links), as 0067 did for the trackers.
-- 3. A post's own compared address (posts.normalized_url, canonical_url) holding one is rewritten without it; its
--    url keeps it. On the server's copy (2026-11-05): 61 posts, 13 keys.
-- Nothing is fetched or deleted. The rules' stamp changed with the rule (utils/stamps.py), so the stories regroup once.
-- The pattern is url_normalization's (tests/test_access_tokens.py reads it against the rule). Idempotent.

ALTER TABLE post_links ADD COLUMN IF NOT EXISTS shared_url text;

UPDATE posts SET links_scanned_at = NULL
WHERE links_scanned_at IS NOT NULL
  AND id IN (SELECT post_id FROM post_links
             WHERE target_url ~* '[?&]([^=&#]*(token|gift|unlock|access)[^=&#]*|smid|taid|mrfcid|srnd|leadsource|reflink|dib_tag|syn-[0-9a-f]{8})=|[?&][^=&#]+=eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(&|#|$)');

UPDATE posts SET
    normalized_url = regexp_replace(regexp_replace(normalized_url,
        '(?<=[?&])(?:[^=&#]*(?:token|gift|unlock|access)[^=&#]*=[^&#]*|(?:smid|taid|mrfcid|srnd|leadsource|reflink|dib_tag|syn-[0-9a-f]{8})=[^&#]*|[^=&#]+=eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?=&|#|$))&?',
        '', 'gi'), '[?&]+$', ''),
    canonical_url = CASE WHEN canonical_url IS NULL THEN NULL ELSE regexp_replace(regexp_replace(canonical_url,
        '(?<=[?&])(?:[^=&#]*(?:token|gift|unlock|access)[^=&#]*=[^&#]*|(?:smid|taid|mrfcid|srnd|leadsource|reflink|dib_tag|syn-[0-9a-f]{8})=[^&#]*|[^=&#]+=eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(?=&|#|$))&?',
        '', 'gi'), '[?&]+$', '') END
WHERE normalized_url ~* '[?&]([^=&#]*(token|gift|unlock|access)[^=&#]*|smid|taid|mrfcid|srnd|leadsource|reflink|dib_tag|syn-[0-9a-f]{8})=|[?&][^=&#]+=eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(&|#|$)'
   OR canonical_url ~* '[?&]([^=&#]*(token|gift|unlock|access)[^=&#]*|smid|taid|mrfcid|srnd|leadsource|reflink|dib_tag|syn-[0-9a-f]{8})=|[?&][^=&#]+=eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+(&|#|$)';
