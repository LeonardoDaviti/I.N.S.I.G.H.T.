# Topics API Endpoints

This document describes the Topics API endpoints for the INSIGHT platform.

## Overview

The Topics API allows frontend clients to:
1. Fetch all topics for a specific date with their posts
2. Get individual topic details
3. Check if topics exist before fetching
4. Find similar topics (future feature)

## Base URL

```
http://localhost:8000/api
```

---

## Endpoints

### 1. Get Topics by Date

**Primary endpoint for the topics view.**

```http
GET /api/topics/{date}
```

Fetch all topics for a specific date, including their associated posts.

**Parameters:**
- `date` (path, required): Date string in format `YYYY-MM-DD`

**Response:**

```json
{
  "success": true,
  "topics": [
    {
      "id": "uuid-here",
      "title": "OpenAI GPT-5 Release",
      "summary": null,
      "is_outlier": false,
      "created_at": "2025-11-16T10:30:00+00:00",
      "post_count": 5,
      "posts": [
        {
          "id": "post-uuid",
          "url": "https://...",
          "title": "Post title",
          "content": "Post content...",
          "date": "2025-11-16T08:00:00+00:00",
          "platform": "telegram",
          "source": "@ai_news"
        }
      ]
    }
  ],
  "date": "2025-11-16",
  "total": 5
}
```

**Error Response:**

```json
{
  "success": false,
  "error": "Invalid date format: 2025-13-45. Expected YYYY-MM-DD",
  "topics": [],
  "total": 0
}
```

**Example:**

```bash
curl http://localhost:8000/api/topics/2025-11-16
```

---

### 2. Get Single Topic

```http
GET /api/topics/topic/{topic_id}
```

Fetch a single topic with its posts.

**Parameters:**
- `topic_id` (path, required): UUID of the topic

**Response:**

```json
{
  "success": true,
  "topic": {
    "id": "uuid-here",
    "title": "OpenAI GPT-5 Release",
    "summary": null,
    "is_outlier": false,
    "date": "2025-11-16",
    "created_at": "2025-11-16T10:30:00+00:00",
    "post_count": 5,
    "posts": [...]
  }
}
```

**Error Response:**

```json
{
  "success": false,
  "error": "Topic not found: uuid-here",
  "topic": null
}
```

**Example:**

```bash
curl http://localhost:8000/api/topics/topic/12345678-1234-1234-1234-123456789abc
```

---

### 3. Get Posts for Topic

```http
GET /api/topics/{topic_id}/posts
```

Fetch all posts associated with a specific topic.

**Parameters:**
- `topic_id` (path, required): UUID of the topic

**Response:**

```json
{
  "success": true,
  "posts": [
    {
      "id": "post-uuid",
      "url": "https://...",
      "title": "Post title",
      "content": "Post content...",
      "date": "2025-11-16T08:00:00+00:00",
      "platform": "telegram",
      "source": "@ai_news"
    }
  ],
  "topic_id": "uuid-here",
  "total": 5
}
```

**Example:**

```bash
curl http://localhost:8000/api/topics/12345678-1234-1234-1234-123456789abc/posts
```

---

### 4. Check Topics Exist

```http
GET /api/topics/check/{date}
```

Check if topics have been generated for a specific date.

**Parameters:**
- `date` (path, required): Date string in format `YYYY-MM-DD`

**Response:**

```json
{
  "success": true,
  "exists": true,
  "date": "2025-11-16"
}
```

**Use Case:**
Frontend can check if topics exist before deciding whether to:
- Show topics view (if exists)
- Show "Generate Topics" button (if not exists)
- Redirect to posts view (if not exists)

**Example:**

```bash
curl http://localhost:8000/api/topics/check/2025-11-16
```

---

### 5. Find Similar Topics (Future)

```http
GET /api/topics/{topic_id}/similar?threshold=0.75&limit=10
```

Find topics similar to a given topic using vector embeddings.

**Note:** This endpoint is ready for future use when embeddings are added to the system.

**Parameters:**
- `topic_id` (path, required): UUID of the source topic
- `threshold` (query, optional): Minimum similarity score (0-1), default `0.75`
- `limit` (query, optional): Maximum number of results, default `10`

**Response:**

```json
{
  "success": true,
  "similar_topics": [
    {
      "id": "uuid-here",
      "title": "Related topic title",
      "date": "2025-11-15",
      "similarity_score": 0.85
    }
  ],
  "source_topic_id": "uuid-here",
  "total": 3
}
```

**Example:**

```bash
curl "http://localhost:8000/api/topics/12345678-1234-1234-1234-123456789abc/similar?threshold=0.8&limit=5"
```

---

## Data Models

### Topic Object

```typescript
interface Topic {
  id: string;              // UUID
  title: string;           // Topic title (e.g., "OpenAI GPT-5 Release")
  summary: string | null;  // Optional topic summary
  is_outlier: boolean;     // Whether this is an outlier/uncategorized topic
  date: string;            // ISO date string (YYYY-MM-DD)
  created_at: string;      // ISO datetime string
  post_count: number;      // Number of posts in this topic
  posts: Post[];           // Array of associated posts
}
```

### Post Object

```typescript
interface Post {
  id: string;              // UUID
  url: string;             // Post URL
  title: string | null;    // Post title
  content: string;         // Post content
  date: string;            // ISO datetime string
  published_at: string;    // ISO datetime string
  fetched_at: string;      // ISO datetime string
  platform: string;        // "telegram", "rss", etc.
  source: string;          // Handle or URL
  handle_or_url: string;   // Source handle/URL
  media_urls: string[];    // Array of media URLs
  categories: string[];    // Array of categories
}
```

---

## Frontend Integration

### Workflow: Topics View

1. **Check if topics exist:**
   ```javascript
   const checkResponse = await fetch(`/api/topics/check/${date}`);
   const { exists } = await checkResponse.json();
   ```

2. **If topics exist, fetch them:**
   ```javascript
   if (exists) {
     const response = await fetch(`/api/topics/${date}`);
     const { topics } = await response.json();
     // Render topics view
   }
   ```

3. **If topics don't exist:**
   ```javascript
   else {
     // Show "Generate Topics" button or redirect to posts view
     // Topic generation should be done via backend script, not API
   }
   ```

### Example React Hook

```typescript
const useTopics = (date: string) => {
  const [topics, setTopics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [exists, setExists] = useState(false);

  useEffect(() => {
    const fetchTopics = async () => {
      // Check if topics exist
      const checkRes = await fetch(`/api/topics/check/${date}`);
      const { exists: topicsExist } = await checkRes.json();
      setExists(topicsExist);

      if (topicsExist) {
        // Fetch topics
        const res = await fetch(`/api/topics/${date}`);
        const data = await res.json();
        if (data.success) {
          setTopics(data.topics);
        }
      }
      
      setLoading(false);
    };

    fetchTopics();
  }, [date]);

  return { topics, loading, exists };
};
```

---

## Error Handling

All endpoints follow the same error response format:

```json
{
  "success": false,
  "error": "Error message here",
  "topics": [],      // Empty array for list endpoints
  "topic": null,     // null for single item endpoints
  "total": 0
}
```

**Common Error Scenarios:**

1. **Invalid Date Format:**
   - Status: 200 (success: false)
   - Error: "Invalid date format: {date}. Expected YYYY-MM-DD"

2. **Topic Not Found:**
   - Status: 200 (success: false)
   - Error: "Topic not found: {topic_id}"

3. **No Topics for Date:**
   - Status: 200 (success: true)
   - Message: "No topics found for {date}"
   - Topics: []

4. **Database Error:**
   - Status: 200 (success: false)
   - Error: Database error message

---

## Topic Generation

**Important:** Topics are **NOT** generated via API endpoints. Topic generation is a heavy operation that should be done via backend scripts.

### Generate Topics (Backend Script)

```bash
# Generate topics for a specific date
python backend/insight_core/scripts/generate_topics.py 2025-11-16

# Or use default date (today)
python backend/insight_core/scripts/generate_topics.py
```

### Process:
1. Fetches posts for the date
2. Uses AI to model topics
3. Stores topics in database
4. Creates topic-post associations

**Note:** The `/api/model-topics` endpoint exists for testing purposes only and should not be used in production.

---

## Performance Considerations

1. **Caching:** Consider implementing frontend caching for topics data
2. **Pagination:** For dates with many topics/posts, consider adding pagination
3. **Lazy Loading:** Posts can be loaded separately per topic using `/api/topics/{topic_id}/posts`
4. **Incremental Fetching:** Use `/api/topics/check/{date}` to avoid unnecessary fetches

---

## Future Enhancements

1. **Topic Embeddings:** Add vector embeddings for similarity search
2. **Topic Connections:** Automatically link related topics across dates
3. **Topic Summary:** AI-generated summaries for each topic
4. **Topic Trends:** Track topic evolution over time
5. **Topic Filtering:** Filter topics by outlier status, post count, etc.
6. **Bulk Operations:** Batch endpoints for multiple dates

---

## Testing

### Test Endpoint Availability

```bash
# Get topics for a date
curl http://localhost:8000/api/topics/2025-11-16

# Check if topics exist
curl http://localhost:8000/api/topics/check/2025-11-16

# Get single topic
curl http://localhost:8000/api/topics/topic/{uuid}

# Get posts for topic
curl http://localhost:8000/api/topics/{uuid}/posts
```

### Generate Test Data

```bash
# 1. Run ingestion
python backend/insight_core/scripts/ingest.py

# 2. Generate topics
python backend/insight_core/scripts/generate_topics.py 2025-11-16

# 3. Test API
curl http://localhost:8000/api/topics/2025-11-16
```

---

## Related Documentation

- [Topic Generation System](./insight_core/scripts/README_TOPICS.md)
- [Database Schema](./insight_core/db/migrations/0003_topics.sql)
- [Topics Service](./insight_core/services/topics_service.py)
- [Topics Repository](./insight_core/db/repo_topics.py)

