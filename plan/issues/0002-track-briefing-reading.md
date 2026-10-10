# 0002 — Track briefing: readable and clickable (analysis version)

Status: **discussion** (owner review, 2026-10-10). Hidden while `INSIGHT_ANALYSIS=off`. This is input for the analysis version.

## Owner feedback on the current track briefing (`TrackBriefingPanel`)

- **Remove the briefing header metadata:** "Agentic News briefing", the post count, the date range, the topic count, "via gemini-3.5-flash-lite", and the trailing date. None of it helps reading.
- **Remove the track header block** ("Agentic News · 2 sources · 355 posts · description") sitting above the briefing date.
- **Keep the "issues" date strip.** The owner likes it.
- **Topics must be clickable:** open a topic (e.g. "GPT-6 Astra, Sol, and Luna Release Architecture and Pricing Shifts · 4 posts") into its own reading view.
- **Topic text is unreadable as written:** one huge paragraph with inline "(Post 16)" citations. It needs:
  - short paragraphs or bullets;
  - citations as quiet links to the posts, not "(Post N)" text;
  - the "INSIGHT application:" paragraph set apart, or dropped.
- **Staleness:** the briefing at the top of a track was last written on 29 Sep. Briefings stopped, but posts kept arriving (Simon Willison up to 10 Oct), so the track *looked* stuck. Whatever comes back must never show a stale briefing above fresh posts without saying so. Better: put posts first.

## Related

- Topic (one day) vs story (evolves over time): see the Mark X grilling notes.
- [0001](0001-entity-pages-and-milestones.md): milestones (the owner likes this feature).
