# Things in a post (track-things-v2)

A reader follows a TRACK (its name, what belongs, what it excludes) and keeps records of the things its posts describe. You get the track, its KINDS of thing with their fields (JSON), and ONE POST (or one window of a long post): its title, its text and, after it, "Links in the post".

Return the things of those kinds that the post itself describes. A post may hold zero, one or several things. Use `practice_or_claim` only for a method, habit, finding or opinion the post states that is not one of the other kinds. Do not invent: skip a thing the post only names in passing, and anything the track excludes.

Whose thing it is: a thing, a result or a claim belongs to the track only when the post says it of what the track is about. When a post compares, tests or recommends other things (a rival, a replacement, an alternative, "both of them", "the others"), a result said of those is not the track's: leave it out, even when the track's subject is named in the same sentence.

A value says only what its own quote says: build it from the quote's words (translated into English when the post is in another language), and add nothing taken from elsewhere in the post: no device, version, date, figure, duration, setting or name that the quote itself does not show. When the value would need words from another sentence, either pick a longer quote that holds them all, or give the shorter value its quote holds.

For each thing give `kind` and `fields`. For EVERY field of its kind decide: fill it when the post states it, leave it out when it does not (never guess). Each field you fill is {"value": ..., "quote": "..."}:
- `quote`: an exact span copied character for character from the post's text or its links (3 to 25 words; a link's quote is the URL itself). No paraphrase, no ellipsis, no added words. The value must be read in its own quote.
- text: a short value in English, at most 120 characters.
- number: {"number": 14, "unit": "...", "range_to": null}. `number` as a JSON number (1500, not "1,500"; 24.5 for "24,5"; 16000 for "16K"); `unit` as the quote writes it, or null when the post gives none; a range ("14-15") is `number` 14 and `range_to` 15. The quote must contain the digits.
- money: {"number": 1500, "currency": "USD", "range_to": null}: `currency` as a 3-letter code (USD, EUR, GBP, ...); the quote must show the currency (a sign or a word) and the digits.
- link: the URL, copied exactly from the text or from "Links in the post"; its quote is that URL.
- enum: one of the field's `values`.

Answer ONE line: {"id": "<the item id>", "things": [{"kind": "...", "fields": {"<field>": {"value": ..., "quote": "..."}}}]} ("things": [] when the post holds none).
