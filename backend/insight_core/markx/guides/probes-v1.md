# Track example posts (probes-v1)

The reader keeps a TRACK: a topic in their own words. A search finds the track's posts by how close each post's meaning is to a few example posts, so an abstract description ("cool", "worth printing", "cheap") finds little: the posts that belong are concrete. You get the track (its name, `Belongs:` what belongs, `Not:` what does not, `Sub-topics:` when given, and examples the reader marked in or out when given). Write the example posts.

- `probes`: 12 to 20 short example posts that clearly belong, as they would really appear in a feed (a forum post, a repository's page, a blog post, a channel message): a concrete title and one or two sentences with the specifics such a post has (names of tools, hardware, numbers, what was built or done). At most 300 characters each, English.
- Spread them over the track's likely sub-topics (and the given ones): every kind of post the reader would want, not 15 variations of one. Mix long and short ones, and plain ones ("22 tok/s on a 12 GB card") as well as polished ones.
- Do not copy the description's words; write what a post that fits would say.
- `near_misses`: up to 4 example posts that look close but do not belong (from `Not:`, or the nearest thing the description rules out: news about a company in the field, a sale, an opinion with nothing built), same form.

Answer ONE line: {"id": "<the item id>", "probes": ["...", "..."], "near_misses": ["...", "..."]}
