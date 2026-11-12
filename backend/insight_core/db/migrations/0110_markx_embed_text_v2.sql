-- 0110_markx_embed_text_v2.sql (Stealth v10.14: markx embed text v2, a text that says nothing gets no vector)
--
-- markx embed text v1 embedded a post whose title and text were only web addresses or a media placeholder as one
-- constant ("(empty)", "[Photo]", ...): hundreds of posts shared one vector, every pair of them an embedding
-- candidate at cosine 1.0. v2 describes such a post by its links, and when nothing describes it, the post gets
-- no vector. mx_embed_skips records those posts under the embed text version that skipped them, so the planner
-- doesn't read them again every plan (a later version reads them again).
--
-- The v1 vectors of such texts are set aside by the code (markx/embed.py set_aside: their rows kept as they are
-- under the model 'bge-m3:said-nothing'); nothing is deleted. Mark X tables only. Idempotent.

CREATE TABLE IF NOT EXISTS mx_embed_skips (
  post_id      uuid NOT NULL,
  text_version text NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (post_id, text_version)
);
