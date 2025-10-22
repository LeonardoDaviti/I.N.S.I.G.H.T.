# Future Enhancements for I.N.S.I.G.H.T.

## Fetching Improvements
- Fetch from latest (cursor-based) instead of hardcoded limits
- Per-source fetch limits configuration
- Per-source fetch delay/rate limiting strategy
- Conditional fetching (RSS ETag/Last-Modified, Telegram last_message_id)
- Incremental updates (only new posts)

## Storage & Retrieval
- Content hash for duplicate detection beyond URL
- Post versioning (track edits)
- Soft deletes with retention policy
- Post embeddings for semantic search

## Clustering & Meta-Posts
- Historical meta-post continuity (predecessor tracking)
- Cross-day cluster evolution
- Confidence scoring for cluster membership
- Narrative synthesis quality metrics

## Sources Management
- Move from sources.json to database (Mark VII)
- Per-source settings (fetch_limit, enabled, delay, priority)
- Source health monitoring
- Automatic source discovery

## Topics & Analysis
- AI-powered topic extraction (Gemini processor)
- Topic trending over time
- Topic relationships graph
- Custom topic subscriptions

## Performance
- Batch insert optimization
- Read replicas for queries
- Caching layer (Redis)
- Background job queue for fetching

## UI/UX
- Date picker for historical browsing
- Source filtering in frontend
- Real-time fetch status
- Export briefings (PDF, email)