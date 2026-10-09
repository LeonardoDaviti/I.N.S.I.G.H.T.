-- 0023_media_url_entities.sql (Mark IX)
--
-- Feed parsing took <img src> values straight out of escaped HTML, so posts.media_urls
-- kept entities: `&amp;`, `&#038;`, `&#38;` (and `&amp;#038;` from double escaping).
-- Signed CDN URLs (external-preview.redd.it) answer 403 to the escaped form. Ingest now
-- decodes them (parsing.normalize_media_url); this repairs rows already stored.
-- Only string elements change; order and non-string elements are kept. Idempotent.

UPDATE posts p
   SET media_urls = (
         SELECT jsonb_agg(
                  CASE WHEN jsonb_typeof(e.value) = 'string'
                       THEN to_jsonb(replace(replace(replace(e.value #>> '{}', '&amp;', '&'), '&#038;', '&'), '&#38;', '&'))
                       ELSE e.value
                  END
                  ORDER BY e.ord)
           FROM jsonb_array_elements(p.media_urls) WITH ORDINALITY AS e(value, ord)
       )
 WHERE jsonb_typeof(p.media_urls) = 'array'
   AND jsonb_array_length(p.media_urls) > 0
   AND p.media_urls::text ~ '&(amp|#0*38);';
