# I.N.S.I.G.H.T. Scripts

Scripts for data ingestion and export operations.

---

## 📥 Ingestion (Mark IX)

Every fetch - the scheduler tick, the UI's "Run cycle", track fetch, fetch-now and the CLI -
is one call to `insight_core.ingestion.run_ingestion(FetchRequest) -> RunReport`, so each
applies the same policy: the yt-dlp switch, backoff, politeness gates, fetch-state
recording, the save batch, enrichment and the archive-metadata (inspection) refresh.
`scripts/ingest.py` and the `/api/ingest-posts` and `/api/safe-ingest-posts` routes are gone.

### CLI: safe_ingest.py

```bash
cd backend
python -m insight_core.scripts.safe_ingest            # all enabled sources, due ones only
python -m insight_core.scripts.safe_ingest --force    # ignore cadence and backoff
python -m insight_core.scripts.safe_ingest --folder <folder-id>   # one track's enabled sources
python -m insight_core.scripts.safe_ingest --source <source-id>   # one source, even if disabled
```

It prints the run report as JSON and exits 1 when the run failed or was partial. `--force`
never overrides unavailability: with `INSIGHT_YTDLP_ENABLED=0` YouTube stays skipped.

### API

- `POST /api/ingestion/run {force?: bool}` - the manual cycle
- `POST /api/sources/{id}/fetch-now {limit?: int}` - one source, forced
- `POST /api/folders/{id}/ingest {limit?: int}` - one track, forced

Each answers `202 {job_id, job_type: "ingestion_run"}` and runs in the background; poll
`GET /api/operations/jobs/{job_id}` for the run report (in the job payload). When the job
cannot be tracked the answer is 503 and nothing runs. An archive plan or run on a kind the
process cannot fetch (yt-dlp off) answers 409.

### How a source is decided

`ingestion.schedule.decide_fetch`, fed by the source's cadence columns and its row in
`source_fetch_state`:

1. **Unavailable** (yt-dlp switched off, no Telegram session) → skipped as unavailable,
   never as backoff, even when forced
2. **Forced** → fetched
3. **In backoff** after consecutive errors (1h, 2h, 4h ... 24h; 7d once dormant) → skipped
   until the retry time, then retried
4. **New source** (no successful fetch, 0 posts) → fetched
5. **Due**: the adaptive fetch interval has elapsed since the last *successful* fetch (an
   empty fetch counts) → fetched, otherwise deferred

The interval comes from the mean gap between the source's latest 20 posts (half the gap,
clamped to 24h..21d; 24h probation while there are fewer than 3 dated posts; 168h minimum
for yt-dlp), capped by a backlog guard so a fast feed is polled before it can overflow.
`sources.fetch_interval_hours_override` replaces all of that for one source.

### Scheduler (run_scheduler.py, the ingestion container)

- **Ingestion tick** every `scheduler_config.ingest_tick_minutes` (default 60, minimum 15):
  one run over all enabled sources; cadence makes it touch only the due ones. Two full runs
  never overlap (a Postgres advisory run lock); a second one reports `skipped_busy`.
- **Daily work** once `interval_hours` have passed since the last one: prune job_runs,
  refresh source cadence, sync sources.json, experts, daily / topic briefings. The first
  tick after a deploy seeds the gate from the last successful `scheduler_cycle` job.
- The state (`last_tick_at`, `next_tick_at`, `last_daily_work_at`, `next_daily_work_at`) is in
  `system_settings['scheduler_state']` and served by `GET /api/operations/scheduler`.

### Configuration

- `INSIGHT_YTDLP_ENABLED` (default 1)
- `INSIGHT_INGEST_TICK_MINUTES` (60, the default for `ingest_tick_minutes`),
  `INSIGHT_INGEST_INTERVAL_HOURS` (20, the default daily-work interval)
- `INSIGHT_BACKOFF_BASE_MINUTES` (60), `INSIGHT_BACKOFF_MAX_HOURS` (24),
  `INSIGHT_BACKOFF_DORMANT_AFTER` (10), `INSIGHT_BACKOFF_DORMANT_MAX_HOURS` (168)
- `INSIGHT_FETCH_MAX_CONCURRENCY` (8), `INSIGHT_YTDLP_CONCURRENCY` (2), `INSIGHT_YTDLP_MIN_INTERVAL` (3s)
- `INSIGHT_SAVE_COMMIT_BATCH` (20), `INSIGHT_ENRICH_CHUNK_SIZE` (100)
- `INSIGHT_ARCHIVE_INSPECT_INTERVAL_HOURS` (168), `INSIGHT_REFRESH_ARCHIVE_METADATA` (1; 0 skips
  the inspection refresh)

---

## 📤 export.py - Export Posts

Export posts to CSV for BERTopic and clustering analysis.

### Usage

```bash
cd /home/man/Documents/I.N.S.I.G.H.T./backend
python insight_core/scripts/export.py
```

### Features

**Two export modes:**

1. **Single Date Export**
   - Export all posts from a specific date
   - Example: `2025-11-02` → creates `2025-11-02.csv`

2. **Date Range Export**
   - Export all posts from a date range
   - Example: `2025-10-10` to `2025-10-29` → creates `2025-10-10_to_2025-10-29.csv`

### CSV Columns

| Column | Description |
|--------|-------------|
| `id` | Post UUID |
| `title` | Post title |
| `content` | Full post content |
| `text` | Combined title + content (use this for BERTopic) |
| `url` | Original post URL |
| `platform` | Platform (telegram, youtube, reddit, rss) |
| `source` | Source handle/URL |
| `published_at` | Publication timestamp |
| `categories` | Post categories/tags (comma-separated) |
| `media_urls` | Media URLs (comma-separated) |

### Output

- CSV files saved in: `/home/man/Documents/I.N.S.I.G.H.T./backend/insight_core/scripts/`
- Filename format:
  - Single date: `{YYYY-MM-DD}.csv`
  - Date range: `{start-date}_to_{end-date}.csv`

### Example Session

```
📤 I.N.S.I.G.H.T. Posts Export Tool
============================================================

Export posts to CSV for BERTopic analysis

Export options:
  1. Single date
  2. Date range

Select option (1 or 2) [default: 1]: 2

📅 Date Range Export
Enter start date (YYYY-MM-DD): 2025-10-10
Enter end date (YYYY-MM-DD): 2025-10-29

📊 Exporting posts from 2025-10-10 to 2025-10-29...
This may take a moment for large date ranges...

   Fetching posts for 2025-10-10...
   ✅ Found 45 posts for 2025-10-10
   Fetching posts for 2025-10-11...
   ✅ Found 52 posts for 2025-10-11
   ...
   
✅ Total posts collected: 856
💾 Writing to: .../2025-10-10_to_2025-10-29.csv
✅ Successfully exported 856 posts to 2025-10-10_to_2025-10-29.csv

============================================================
✅ Export completed successfully!
============================================================
```

### Using with BERTopic

```python
import pandas as pd
from bertopic import BERTopic

# Load exported data
df = pd.read_csv('2025-10-10_to_2025-10-29.csv')

# Use the 'text' column (title + content combined)
docs = df['text'].tolist()

# Create and fit BERTopic model
topic_model = BERTopic(language='multilingual')
topics, probs = topic_model.fit_transform(docs)

# View discovered topics
topic_model.get_topic_info()

# Visualize topics
topic_model.visualize_topics()
```

---

## 📋 export_sources.py - Export Sources

Export all sources (with post counts) to CSV.

### Usage

```bash
cd /home/man/Documents/I.N.S.I.G.H.T./backend
python insight_core/scripts/export_sources.py
```

### Features

- Exports all sources from database
- Includes post count per source
- Groups statistics by platform
- Creates `sources.csv` in scripts folder

### CSV Columns

| Column | Description |
|--------|-------------|
| `id` | Source UUID |
| `platform` | Platform type |
| `handle_or_url` | Source identifier |
| `enabled` | Whether source is active |
| `post_count` | Number of posts from this source |
| `created_at` | When source was added |
| `updated_at` | Last update timestamp |

### Output

- Filename: `sources.csv`
- Location: `/home/man/Documents/I.N.S.I.G.H.T./backend/insight_core/scripts/`

### Example Session

```
📤 I.N.S.I.G.H.T. Sources Export Tool
============================================================

Export all sources to CSV

📋 Fetching sources from database
✅ Found 23 sources
💾 Writing to: .../sources.csv
✅ Successfully exported 23 sources to sources.csv

📈 Summary Statistics:
   Total sources: 23
   Enabled sources: 18
   Disabled sources: 5
   Total posts: 1,245

📊 By Platform:
   reddit: 5 sources, 234 posts
   rss: 8 sources, 567 posts
   telegram: 7 sources, 389 posts
   youtube: 3 sources, 55 posts

============================================================
✅ Export completed successfully!
============================================================
```

### Using the Data

```python
import pandas as pd

# Load sources
df = pd.read_csv('sources.csv')

# Analyze source performance
print(df.groupby('platform')['post_count'].sum())

# Find most active sources
top_sources = df.nlargest(10, 'post_count')
print(top_sources[['platform', 'handle_or_url', 'post_count']])

# Filter enabled sources only
enabled = df[df['enabled'] == True]
```

---

## 🔧 Troubleshooting

### "No posts found for date"

**Cause:** Database has no posts for the specified date.

**Solutions:**
1. Check if posts were ingested: `python -m insight_core.scripts.safe_ingest --force`
2. Verify date format is correct: `YYYY-MM-DD`
3. Check database connection: logs in console

### "Invalid date format"

**Cause:** Date not in YYYY-MM-DD format.

**Solution:** Use correct format, e.g., `2025-11-02` (not `11/02/2025` or `2025-11-2`)

### "End date is before start date"

**Cause:** In range export, end date comes before start date.

**Solution:** Swap the dates, start date should be earlier.

---

## 🎯 Next Steps

After exporting data:

1. **For BERTopic Analysis:** See the 8-week roadmap in the conversation above
2. **For Google Colab:** Upload the CSV to Colab and start experimenting
3. **For Local Analysis:** Use pandas, scikit-learn, or BERTopic locally

## 📊 Quick Analysis Template

```python
import pandas as pd
import matplotlib.pyplot as plt

# Load data
df = pd.read_csv('2025-10-10_to_2025-10-29.csv')

# Basic statistics
print(f"Total posts: {len(df)}")
print(f"Platforms: {df['platform'].value_counts()}")
print(f"Date range: {df['published_at'].min()} to {df['published_at'].max()}")

# Visualize
df['platform'].value_counts().plot(kind='bar')
plt.title('Posts by Platform')
plt.show()
```

---

## 💡 Tips

- **Large date ranges:** May take several minutes to export
- **Memory:** CSV format is efficient, can handle 1000+ posts easily
- **Encoding:** All files use UTF-8 encoding (supports multilingual content)
- **Backup:** CSV files are plain text, easy to backup and version control

