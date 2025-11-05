# I.N.S.I.G.H.T. Scripts

Scripts for data ingestion and export operations.

---

## 📥 safe_ingest.py - Safe Ingestion

Smart ingestion script that only fetches from sources that need updating. Perfect for development to avoid redundant API calls.

### Usage

```bash
cd /home/man/Documents/I.N.S.I.G.H.T./backend
python insight_core/scripts/safe_ingest.py
```

### How It Works

The script intelligently filters sources before fetching:

1. **New Sources (0 posts)** → ✅ FETCH
   - Newly added sources that have never been fetched
   
2. **Stale Sources (>24h)** → ✅ FETCH
   - Sources with posts older than 24 hours
   
3. **Recent Sources (<24h)** → ⏭️ SKIP
   - Sources fetched within the last 24 hours

### Features

- **Zero Schema Changes**: Uses existing `posts.fetched_at` data
- **Development-Friendly**: Prevents redundant fetches during feature development
- **Transparent Logging**: Shows exactly why each source is fetched or skipped
- **Production-Ready**: Same reliability as regular `ingest.py`

### Configuration

You can adjust the skip threshold at the top of the script:

```python
SKIP_THRESHOLD_HOURS = 24  # Change to 12, 48, etc.
```

### Example Session

```
📊 Found 15 enabled sources
✅ TechCrunch RSS: 📦 New source (0 posts)
✅ Hacker News: 🔄 Stale data (26.3h old, 145 posts)
⏭️  Reddit/Python: ⏭️ Recently fetched 2.5h ago (89 posts)
⏭️  AI News Telegram: ⏭️ Recently fetched 1.2h ago (34 posts)
============================================================
📥 Sources to fetch: 2
⏭️  Sources to skip:  13
============================================================
🔌 Connected to rss connector
📥 [1] Fetching up to 50 posts from TechCrunch RSS
✅ [1] TechCrunch RSS: fetched 23 posts
✅ Ingested 23 posts from 2 sources
```

### When to Use

- **Use `safe_ingest.py`**: During development, testing, or when you want to avoid hitting rate limits
- **Use `ingest.py`**: For scheduled production runs or when you want to force-refresh all sources

### Comparison with Regular Ingest

| Feature | `ingest.py` | `safe_ingest.py` |
|---------|-------------|------------------|
| Fetches all enabled sources | ✅ Always | ⚠️ Only if needed |
| Good for production | ✅ Yes | ✅ Yes |
| Good for development | ⚠️ Redundant | ✅ Efficient |
| Avoids rate limits | ❌ No | ✅ Yes |
| Checks post history | ❌ No | ✅ Yes |

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
1. Check if posts were ingested: `python insight_core/scripts/ingest.py`
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

