-- 0021_arxiv_out_of_main_digest.sql (Mark IX, B7; product-owner decision 2 of 2026-10-09)
--
-- In the latest 30-day window the four arXiv RSS listings produce 47% of all posts, so a
-- flat main feed buries the low-volume blogs. They leave the main digest but stay enabled
-- and readable through their track and scope=source:<id>.
--
-- The migrator records this file, so it runs once: re-enabling the flag in the UI later
-- sticks. The two export.arxiv.org query feeds are not part of the decision.

UPDATE sources
   SET in_main_digest = false, updated_at = now()
 WHERE handle_or_url IN (
   'https://rss.arxiv.org/rss/cs.AI',
   'https://rss.arxiv.org/rss/cs.CL',
   'https://rss.arxiv.org/rss/cs.LG',
   'https://rss.arxiv.org/rss/physics.optics'
 );
