# Name collision judge, two makers of one name (Mark X 0250, prompt collide-makers-v1; collide-v1 deepened)

A news reader extracted named things (entities) from posts about AI and tech, English and Russian, some archive posts going back years. One short name (one word) was found in many posts, and the posts state two different makers for it. Each item shows the name and two **groups** of its mentions, A and B, one group a maker: the maker names the posts state (a group's names are already one company: its spellings and aliases), how many mentions state them, the types the extractor gave the mentions, the dates of the group's posts, other names the group's posts mention most, and 3 to 5 numbered sample mentions (the post's kind, date and title, and the words around the name).

Answer one question: is A's thing and B's thing **the same thing** whose maker is named differently, or **different things that share the name**? The reader splits the name into two pages only on "different": a wrong split scatters one thing's posts over two pages, a missed split mixes two things on one page. Both errors count.

## How
1. Write `evidence` first: what the name refers to in A's samples, then in B's, in a few words each (what it is, what it does, who is said to make or run it), then why they are or are not one thing.
2. **One thing, maker names differ** (`same`): the samples fit one thing and the makers are linked:
   - an **ownership change**: a product, network, game or project sold, acquired or spun out, named under its old and its new owner;
   - a **founder** or a creator named as the maker of the thing their company makes (a person in one group, their company in the other);
   - a **foundation**, community or open-source organisation versus the company behind the project (or the project's own organisation);
   - one company's **legal names**, former names, parent and subsidiary, or a brand and its owner ("X Inc." / "X Ltd." / "X Labs" / its parent group);
   - a distributor, cloud or platform that offers another maker's thing (the thing is still one).
3. **Different things** (`different`): the samples show two things that share only the name: a robot and a language model, a programming language and a video game, a wiki tool and a game, two unrelated apps of unrelated companies. Look at what each thing **is** and **does**, the field, the platform and the era: a different kind of thing is strong evidence, but not proof on its own (the extractor types one product `software` in one post and `product` or `model` in another).
4. The groups' types, dates and co-mentioned names are evidence, never a rule: dates far apart fit an old thing and a new namesake, but also one long-lived thing; shared co-mentioned names fit one thing.
5. `cant_tell` when the samples don't show what one group's thing is, or show nothing that tells one thing from two. The reader keeps the name one page on `cant_tell`.
6. Most names in these items are **one thing** under linked makers. Answer `different` only on positive evidence that the two are different things.

## Output
One JSON line per item:
{"id": "<id>", "evidence": "A: ...; B: ...; ...", "a": {"what": "a few words", "kind": "software"}, "b": {"what": "...", "kind": "other"}, "verdict": "same", "why": "owner_change", "confidence": 0.0}
- `verdict`: `same`, `different` or `cant_tell`;
- `why`: for `same` one of `owner_change`, `founder`, `foundation`, `legal_name`, `same_maker`, `other`; for `different` `different_things`; for `cant_tell` `cant_tell`;
- `kind`: one of person, org, model, product, software, dataset, paper, event, place, project, law, other;
- `confidence`: your probability (0 to 1) that the verdict is right.
