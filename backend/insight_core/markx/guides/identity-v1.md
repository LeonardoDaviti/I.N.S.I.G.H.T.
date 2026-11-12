# Same maker (identity-v1)

The reader researches who makes something (a model, a tool, a paper) and where they publish. Each item gives you TWO accounts or pages, A and B, what each says about itself (its address, title, description, the names and links it shows) and how B was found from A. Decide whether A and B belong to the same person or organisation (or B is an official channel of A's project).

How to decide:
- `yes` only when the evidence ties them: one links the other as its own (a profile's website or social links, a model card's or repository's links to its maker), they name each other, or they share a handle and the same work.
- A shared name alone is NOT enough: many people and companies share names. Two accounts with the same name and different work (another field, another country, another product) are `no`.
- An account that only mentions, reposts, reviews or discusses A's work is `no` (a fan, a journalist, a user, an aggregator), even when it links A.
- An employer, a university, a platform or a publisher that hosts A is `no` (it is not A), unless the item is about the organisation itself.
- `unsure` when the text does not let you tell (a page that could not be read, a bare handle).
- `confidence` (0 to 1): how sure you are of your answer. 0.9+ only when the pages leave no doubt.
- `why`: ONE line (at most 25 words): the evidence, e.g. "B's profile links A's repository and names the same company".

Answer per item: {"id": "<the item id>", "same": "yes" | "no" | "unsure", "confidence": 0.0-1.0, "why": "..."}
