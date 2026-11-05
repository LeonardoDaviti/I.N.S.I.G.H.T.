-- 0067_tracking_queries.sql (issue 0109 B1)
--
-- A mail or analytics tracker's query names no other page: url_normalization now drops the mail
-- families' keys (HubSpot's _hsenc, _hsmi, __hs*, hsa_*; ConvertKit, beehiiv, Vero, Omeda, Eloqua,
-- MailerLite, Drip, Klaviyo), Google's linker (_ga, _gl) and the ad click ids. The links stored before
-- it keep the tracker in their address (post_links.target_url): the posts holding one are read again,
-- from their stored HTML, by the story job's first step (fill_missing_links), and their links become the
-- page's address. Nothing is fetched; no post changes (no post's own address holds one, on the lab or on
-- the server's copy). The rules' stamp changed with the rule (utils/stamps.py), so the stories regroup
-- once after it. On the server's copy (2026-11-05): 4,900 links in 239 posts (4,846 of them one newsletter's
-- archive), 4,410 addresses after; on the lab 4,882 links in 222 posts.
--
-- The keys are url_normalization's added by 0109 (tests/test_tracking_queries.py reads this pattern
-- against them). Idempotent: a post read again holds none, and keeps its links_scanned_at.

UPDATE posts SET links_scanned_at = NULL
WHERE links_scanned_at IS NOT NULL
  AND id IN (SELECT post_id FROM post_links
             WHERE target_url ~* '[?&](__hsfp|__hssc|__hstc|__s|_bhlid|_ga|_gl|_hsenc|_hsmi|_kx|_openstat|ck_subscriber_id|dclid|elqaid|elqat|elqtrack|elqtrackid|gbraid|gclsrc|hsctatracking|li_fat_id|ml_subscriber|ml_subscriber_hash|msclkid|oly_anon_id|oly_enc_id|rb_clickid|s_cid|ttclid|twclid|vero_conv|vero_id|wbraid|wickedid|yclid|ysclid|hsa_[a-z0-9_]*)=');
