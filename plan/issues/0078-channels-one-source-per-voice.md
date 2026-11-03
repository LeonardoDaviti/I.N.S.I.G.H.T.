# 0078 — Channels: one source for one company, person or blog, made of its channels

Status: **idea, filed for the future** (owner, 2026-11-04). Not scheduled: discuss and decide before speccing.

## The owner's words
"For future channels feature, which is done for each source and automatically combines all channels and sources for a single company/person/blog into single source and gives us control over sub-sources of that mega-source which is just combination of different channels."

## Today
- **Each feed is its own source.** One person's blog, X account, YouTube channel and Telegram channel are four sources with four names. The reader shows them apart, and nothing says they are one voice.
- **Folders and tracks group sources by topic, not by who they are.**
- **A story counts voices** (`story_rules`): one publication for websites, one channel or account for Telegram, X and YouTube.
  - So one person who posts the same news on their blog and on X counts as **2 voices**.
  - That can make a story News (2+ voices) when only one person said it.
  - The same post copied to two of their channels shows twice.

## The idea
- **A channel group** (the "mega-source") is one person, company or blog. Its **channels** are today's sources (blog feed, X, YouTube, Telegram, Reddit user, GitHub, newsletter).
- **The group is a source the reader reads:** one name, one page, one stream of all its channels, with News and Classics as in 0077.
- **Each channel keeps its own controls:** on or off, fetch schedule, priority, and its health (fetch errors, backoff), shown under the group.
- **Found automatically, confirmed by the owner:**
  - from what the channels themselves say: a site's `rel="me"` and header or footer profile links, a channel's own links section, an account's bio address, a Telegram channel's description;
  - and from other signals ensembled: the same name, the same posts appearing on two channels;
  - never from a list of known sites.
  - A suggestion ("These 3 sources look like one voice: join them?") is shown, never applied alone.
- **Adding a channel to a group** goes through the feed finder and page watching (the source-adding rule: the feed finder and page watching), like any source.

## What it changes in reading
- A group is **one voice** in stories, News and Discover. One person's blog and tweet are one voice, not two.
- The same post on two of the group's channels is **one item**: the original first, the other shown as "also on X". Today's copy and repost rules decide which.
- Discover suggests a whole group ("follow their blog too: you already read their X").

## Questions to decide
1. **One page or two levels:** is a group only a source, or can a channel also be read alone?
2. **A channel in two groups** (a company account run by a person): allowed?
3. **Priority and Main digest:** set per group, per channel, or both?
4. **Removing a group:** does it keep its channels as sources, or remove them all?
5. **Names:** the group's name taken from its main channel, or always set by you?

## Measured before speccing
On the lab copy:
- how many of today's 247 sources would join a group;
- how many News rows count one voice twice (and so would change);
- how often the same post appears on two channels of one voice.

## Related
- 0074 (a post in several stories);
- 0077 (News and Classics on a source's page);
- 0065 (Discover from the sources your stories start from);
- Mark X: entities (a person or company as a graph node) are the long-term form of a group.
