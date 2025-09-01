# Topic Generation System

This document describes the topic generation pipeline for the INSIGHT project.

## Overview

The topic generation system analyzes posts from multiple sources and automatically creates semantic topics using AI. It consists of:

1. **Repository Layer** (`repo_topics.py`) - Database access for topics
2. **Service Layer** (`topics_service.py`) - Business logic for topic operations
3. **Generation Script** (`generate_topics.py`) - Main script for generating topics
4. **Test Suite** (`test_generate_topics.py`) - Comprehensive testing

## Architecture

```
Posts (Database)
    ↓
GeminiProcessor (AI Topic Modeling)
    ↓
Topic Names + Assignments
    ↓
Topics Table
    ↓
Topic-Post Associations
```

## Components

### 1. TopicsRepository (`repo_topics.py`)

Database access layer with methods:

**Check Operations:**
- `topics_exist_for_date(cur, date)` - Check if topics exist
- `get_topic_by_id(cur, topic_id)` - Get single topic
- `get_topic_by_date_and_title(cur, date, title)` - Find topic by date/title

**Read Operations:**
- `get_topics_by_date(cur, date)` - Get all topics for date
- `get_posts_for_topic(cur, topic_id)` - Get posts for a topic
- `find_similar_topics(cur, topic_id, threshold, limit)` - Find similar topics using pgvector

**Write Operations:**
- `insert_topic(cur, date, title, embedding, is_outlier, summary)` - Insert single topic
- `insert_topic_post(cur, topic_id, post_id)` - Link topic to post
- `insert_topic_connection(cur, source_id, target_id, score)` - Store topic similarity

**Batch Operations:**
- `insert_topics_batch(cur, topics_data)` - Insert multiple topics
- `insert_connections_batch(cur, connections)` - Insert multiple connections

### 2. TopicsService (`topics_service.py`)

Service layer that wraps repository methods with connection management and transactions.

**Additional Methods:**
- `save_topics_with_connections()` - Atomic operation for topics + connections
- `save_topic_with_posts()` - Atomic operation for topic + post associations

### 3. Topic Generator (`generate_topics.py`)

Main script for generating topics from posts.

**Process:**
1. Fetch posts for a date
2. Check if topics already exist (prevents duplicates)
3. Run AI topic modeling using GeminiProcessor
4. Store topics in database
5. Create topic-post associations
6. Handle outlier posts

**Features:**
- AI-powered topic modeling
- Outlier topic handling
- Comprehensive timing statistics
- Transaction safety

### 4. Test Suite (`test_generate_topics.py`)

Comprehensive test suite that validates:
- Setup and configuration
- Post fetching
- Topic generation and storage
- Data verification

## Usage

### Generate Topics

```bash
# Generate topics for today
python backend/insight_core/scripts/generate_topics.py

# Generate topics for specific date
python backend/insight_core/scripts/generate_topics.py 2025-11-16
```

### Run Tests

```bash
# Test with default date
python backend/insight_core/tests/test_generate_topics.py

# Test with specific date
python backend/insight_core/tests/test_generate_topics.py 2025-11-16
```

## Prerequisites

1. **Environment Variables:**
   ```bash
   export GEMINI_API_KEY="your-api-key"
   ```

2. **Database Setup:**
   - Run migration `0003_topics.sql`
   - Ensure pgvector extension is installed

3. **Posts:**
   - Run `ingest.py` first to fetch posts

## Database Schema

### Topics Table

```sql
CREATE TABLE topics (
  id UUID PRIMARY KEY,
  date DATE NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  embedding vector(1024),        -- Reserved for future use
  is_outlier BOOLEAN NOT NULL,
  created_at TIMESTAMPTZ,
  
  UNIQUE(date, title)
);
```

### Topic Posts (Junction Table)

```sql
CREATE TABLE topic_posts (
  topic_id UUID REFERENCES topics(id),
  post_id UUID REFERENCES posts(id),
  PRIMARY KEY (topic_id, post_id)
);
```

### Topic Connections

```sql
CREATE TABLE topic_connections (
  id UUID PRIMARY KEY,
  source_topic_id UUID REFERENCES topics(id),
  target_topic_id UUID REFERENCES topics(id),
  similarity_score FLOAT NOT NULL,
  UNIQUE(source_topic_id, target_topic_id)
);
```

## Workflow Example

```bash
# 1. Ingest posts
python backend/insight_core/scripts/ingest.py

# 2. Generate topics
python backend/insight_core/scripts/generate_topics.py 2025-11-16

# 3. Verify with test
python backend/insight_core/tests/test_generate_topics.py 2025-11-16
```

## Output Example

```
==================================================================
INSIGHT TOPIC GENERATOR
==================================================================
Target date: 2025-11-16

🔧 Setting up AI models...
✅ Setup complete

📥 Fetching posts for 2025-11-16
✅ Retrieved 25 posts for 2025-11-16

🤖 Running topic modeling on 25 posts...
✅ Topic modeling completed in 15.3s
📊 Found 5 topics from 25 posts

💾 Storing topics in database...
✅ Topics stored in database in 2.1s

🔗 Creating topic-post associations...
✅ Created 25 topic-post associations in 0.5s

==================================================================
✅ TOPIC GENERATION COMPLETE
==================================================================
📊 Statistics:
   - Date: 2025-11-16
   - Topics created: 5
   - Posts processed: 25
   - Outlier posts: 3
   - Associations: 25
⏱️  Timing:
   - Topic modeling: 15.30s
   - Storage: 2.10s
   - Associations: 0.50s
   - Total: 17.90s
==================================================================
```

## Topic Types

### Regular Topics
- Created from AI topic modeling
- `is_outlier = TRUE` (all topics in current version)
- Represent coherent groupings of posts
- Have descriptive titles

### Outlier Topics
- For posts that don't fit any category
- `is_outlier = TRUE`
- Title: "Uncategorized Posts"
- Created when AI assigns posts to topic ID `-1`

## Future: Similarity Search

The repository includes methods for similarity search using pgvector (for future use when embeddings are added):

```python
# Future functionality
similar_topics = topics_service.find_similar_topics(
    topic_id="uuid-here",
    threshold=0.75,  # Minimum similarity
    limit=10         # Max results
)
```

## Error Handling

The system handles:
- Missing API keys
- No posts for date
- Duplicate topics (prevents regeneration)
- Database transaction failures

## Performance

Typical timing for 25 posts:
- Topic modeling: 15-30s
- Database operations: 2-3s
- **Total: 17-33s**

## Notes

1. **One Generation Per Date:** The system prevents duplicate topic generation. To regenerate, manually delete existing topics first.

2. **All Topics as Outliers:** In the current version, all topics are stored with `is_outlier=TRUE` since embeddings are not yet generated.

3. **Transaction Safety:** All database operations are wrapped in transactions for atomicity.

4. **Outlier Handling:** Posts assigned topic ID `-1` by the AI are grouped into a single "Uncategorized Posts" topic.

## Future Enhancements

- [ ] Embedding generation for topics
- [ ] Topic connection generation (find similar topics across dates)
- [ ] Topic summary generation
- [ ] Batch processing for multiple dates
- [ ] Topic evolution tracking
- [ ] Interactive topic refinement

