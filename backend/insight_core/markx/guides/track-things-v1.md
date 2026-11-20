# Things in a post (track-things-v1)

A reader follows a TRACK (its name, what belongs, what it excludes) and keeps records of the things its posts describe. You get the track, its KINDS of thing with their fields (JSON), and ONE POST (or one window of a long post): its title, its text and, after it, "Links in the post".

Return the things of those kinds that the post itself describes. A post may hold zero, one or several things. Use `practice_or_claim` only for a method, habit, finding or opinion the post states that is not one of the other kinds. Do not invent: skip a thing the post only names in passing, and anything the track excludes.

For each thing give `kind` and `fields`. For EVERY field of its kind decide: fill it when the post states it, leave it out when it does not (never guess). Each field you fill is {"value": ..., "quote": "..."}:
- `quote`: an exact span copied character for character from the post's text or its links (3 to 25 words; a link's quote is the URL itself). No paraphrase, no ellipsis, no added words. The value must be read in its own quote.
- text: a short value in English, at most 120 characters.
- number: {"number": 14, "unit": "...", "range_to": null}. `number` as a JSON number (1500, not "1,500"; 24.5 for "24,5"; 16000 for "16K"); `unit` as the quote writes it, or null when the post gives none; a range ("14-15") is `number` 14 and `range_to` 15. The quote must contain the digits.
- money: {"number": 1500, "currency": "USD", "range_to": null}: `currency` as a 3-letter code (USD, EUR, GBP, ...); the quote must show the currency (a sign or a word) and the digits.
- link: the URL, copied exactly from the text or from "Links in the post"; its quote is that URL.
- enum: one of the field's `values`.

Answer ONE line: {"id": "<the item id>", "things": [{"kind": "...", "fields": {"<field>": {"value": ..., "quote": "..."}}}]} ("things": [] when the post holds none).
