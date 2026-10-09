# I.N.S.I.G.H.T. Connector Development Guide v2.3

> **Obsolete since Mark IX (slice B5).** The connector package and the tool registry are gone;
> new fetch strategies are source kinds behind `insight_core/ingestion/kinds/base.py`
> (see `plan/INSIGHT_mark_ix_plan.md` §D). Kept for history only.

## 🎯 Building Battle-Hardened Intelligence Connectors

This guide provides comprehensive instructions for developing new connectors for the I.N.S.I.G.H.T. platform. All connectors must follow The Citadel standards for bulletproof error handling and reliability.

---

## 📋 Table of Contents

1. [Quick Start Checklist](#quick-start-checklist)
2. [The Unified Data Model](#the-unified-data-model)
3. [Connector Architecture](#connector-architecture)
4. [Step-by-Step Implementation](#step-by-step-implementation)
5. [The Citadel Standards](#the-citadel-standards)
6. [Platform-Specific Patterns](#platform-specific-patterns)
7. [Testing & Validation](#testing--validation)
8. [Integration Guidelines](#integration-guidelines)

---

## ⚡ Quick Start Checklist

Before you begin developing a new connector:

- [ ] **Platform API Research**: Understand rate limits, authentication, pagination
- [ ] **Data Model Mapping**: Plan how platform data maps to unified format
- [ ] **Error Scenarios**: Identify all possible failure modes
- [ ] **Authentication Strategy**: Plan credential management
- [ ] **Rate Limiting**: Understand platform constraints
- [ ] **Content Types**: Identify what constitutes a "post" on your platform

---

## 🏗️ The Unified Data Model

Every connector must return data in this **exact** format:

```python
{
    # Required Core Fields
    "source_platform": str,    # Platform identifier ("youtube", "reddit", "twitter")
    "source_id": str,          # Source identifier (channel ID, subreddit, user handle)
    "post_id": str,            # Unique post ID within the source
    "author": str,             # Best effort author identification
    "content": str,            # Full text content of the post
    "timestamp": datetime,     # UTC timestamp as datetime object
    "media_urls": List[str],   # List of media URLs (images, videos, etc.)
    "post_url": str           # Direct link to original post
    
    # Optional Extended Fields (platform-specific)
    # Add these for backward compatibility or enhanced functionality
}
```

### Field Guidelines

| Field | Type | Purpose | Examples |
|-------|------|---------|----------|
| `source_platform` | `str` | Platform identifier | `"youtube"`, `"reddit"`, `"twitter"` |
| `source_id` | `str` | Source within platform | Channel ID, subreddit name, user handle |
| `post_id` | `str` | Unique post identifier | Video ID, post ID, tweet ID |
| `author` | `str` | Content creator | Channel name, username, display name |
| `content` | `str` | Main text content | Description, post text, tweet content |
| `timestamp` | `datetime` | **UTC timezone required** | Video upload time, post time |
| `media_urls` | `List[str]` | All media attachments | Thumbnails, images, video links |
| `post_url` | `str` | Direct link to content | Full URL to view original |

---

## 🔧 Connector Architecture

### Base Class Structure

```python
from connectors.base_connector import BaseConnector
from datetime import datetime, timezone
import logging
import asyncio

class YourPlatformConnector(BaseConnector):
    """
    I.N.S.I.G.H.T. [Platform] Connector v2.3 - The Citadel
    
    Handles [Platform]-specific logic including:
    - Authentication and API management
    - Content fetching and processing
    - Rate limiting and throttling
    - CITADEL: Comprehensive error handling and resilience
    
    This connector follows the unified architecture while providing
    [Platform]-specific functionality for content retrieval.
    """
    
    def __init__(self, **credentials):
        super().__init__("your_platform")
        # Initialize platform-specific configuration
        self.api_client = None
        self.timeout = 30  # Standard Citadel timeout
        
        self.logger.info("YourPlatform Connector v2.3 'The Citadel' initialized")
```

### Required Methods Implementation

Every connector must implement these four abstract methods:

```python
async def connect(self) -> None:
    """Establish connection and authenticate"""
    
async def disconnect(self) -> None:
    """Clean up resources and disconnect"""
    
async def fetch_posts(self, source_identifier: str, limit: int) -> List[Dict[str, Any]]:
    """Fetch N posts from single source"""
    
async def fetch_posts_by_timeframe(self, sources: List[str], days: int) -> List[Dict[str, Any]]:
    """Fetch posts from multiple sources within timeframe"""
```

---

## 🛠️ Step-by-Step Implementation

### Step 1: Research Your Platform

**API Documentation Review:**
- Authentication methods (OAuth, API keys, etc.)
- Rate limiting rules and best practices
- Available endpoints for content retrieval
- Pagination mechanisms
- Error response formats

**Data Structure Analysis:**
- What constitutes a "post" on your platform?
- How is content structured? (text, media, metadata)
- What timestamp formats are used?
- How are authors/creators identified?

### Step 2: Set Up Basic Structure

```python
# connectors/your_platform_connector.py
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from .base_connector import BaseConnector

class YourPlatformConnector(BaseConnector):
    def __init__(self, api_key: str, **kwargs):
        super().__init__("your_platform")
        self.api_key = api_key
        self.api_client = None
        self.timeout = 30
        
        # Platform-specific configuration
        self.rate_limit_delay = 1.0  # Seconds between requests
        self.max_retries = 3
        
        self.logger.info(f"{self.platform_name.title()} Connector v2.3 'The Citadel' initialized")
```

### Step 3: Implement Connection Management

```python
async def connect(self) -> None:
    """Establish connection to the platform."""
    try:
        # Initialize your API client
        self.api_client = YourPlatformAPI(api_key=self.api_key)
        
        # Test the connection
        await self._test_connection()
        
        self.logger.info(f"{self.platform_name.title()} connection successful")
        
    except Exception as e:
        self.logger.error(f"{self.platform_name.title()} connection failed: {e}")
        raise ConnectionError(f"Failed to connect to {self.platform_name}: {e}")

async def disconnect(self) -> None:
    """Clean up resources."""
    if self.api_client:
        try:
            await self.api_client.close()
        except Exception as e:
            self.logger.warning(f"Error during {self.platform_name} cleanup: {e}")
    
    self.logger.info(f"{self.platform_name.title()} cleanup complete")
```

### Step 4: Implement Core Fetching Logic

```python
async def fetch_posts(self, source_identifier: str, limit: int) -> List[Dict[str, Any]]:
    """
    Fetch posts from a single source.
    HARDENED: Bulletproof error handling following Citadel standards.
    """
    self.logger.info(f"Fetching {limit} posts from {self.platform_name} source: {source_identifier}")
    
    # Validate client connection
    if not self.api_client:
        self.logger.error(f"ERROR: Failed to fetch from {source_identifier} - Reason: Client not connected")
        return []
    
    try:
        # Implement your platform's fetching logic with timeout protection
        posts = await asyncio.wait_for(
            self._fetch_posts_internal(source_identifier, limit),
            timeout=self.timeout
        )
        
        self.logger.info(f"Successfully fetched {len(posts)} posts from {source_identifier}")
        return posts
        
    except asyncio.TimeoutError:
        self.logger.error(f"ERROR: Failed to fetch from {source_identifier} - Reason: Timeout after {self.timeout}s")
        return []
    except Exception as e:
        self.logger.error(f"ERROR: Failed to fetch from {source_identifier} - Reason: {str(e)}")
        return []
```

### Step 5: Implement Data Transformation

```python
def _transform_to_unified_format(self, raw_post: dict, source_id: str) -> Dict[str, Any]:
    """
    Transform platform-specific data to unified format.
    This is where you map your platform's data structure to the standard model.
    """
    try:
        # Extract and clean content
        content = self._extract_content(raw_post)
        
        # Normalize timestamp to UTC
        timestamp = self._normalize_timestamp(raw_post.get('created_time'))
        
        # Extract media URLs
        media_urls = self._extract_media_urls(raw_post)
        
        # Create unified post using base connector helper
        unified_post = self._create_unified_post(
            source_platform=self.platform_name,
            source_id=source_id,
            post_id=str(raw_post.get('id', '')),
            author=raw_post.get('author', {}).get('name', 'Unknown'),
            content=content,
            timestamp=timestamp,
            media_urls=media_urls,
            post_url=self._build_post_url(raw_post, source_id)
        )
        
        # Add platform-specific fields for enhanced functionality
        unified_post['platform_specific'] = {
            'likes': raw_post.get('likes', 0),
            'shares': raw_post.get('shares', 0),
            'comments': raw_post.get('comments', 0),
            # Add other platform-specific metrics
        }
        
        return unified_post
        
    except Exception as e:
        self.logger.error(f"Error transforming post data: {e}")
        raise ValueError(f"Failed to transform post to unified format: {e}")
```

---

## 🛡️ The Citadel Standards

All connectors must implement these bulletproof error handling patterns:

### 1. Global Timeout Protection

```python
# Wrap ALL external API calls with timeout
try:
    result = await asyncio.wait_for(
        your_api_call(params),
        timeout=self.timeout
    )
except asyncio.TimeoutError:
    self.logger.error(f"ERROR: Operation timed out after {self.timeout}s")
    return []  # Always return empty list, never crash
```

### 2. Comprehensive Error Categories

Handle these error types for your platform:

```python
try:
    # Your API call
    pass
except SpecificPlatformError as e:
    self.logger.error(f"ERROR: Platform-specific error: {e}")
    return []
except AuthenticationError as e:
    self.logger.error(f"ERROR: Authentication failed: {e}")
    return []
except RateLimitError as e:
    self.logger.error(f"ERROR: Rate limit exceeded: {e}")
    return []
except NetworkError as e:
    self.logger.error(f"ERROR: Network error: {e}")
    return []
except Exception as e:
    self.logger.error(f"ERROR: Unexpected error: {e}")
    return []
```

### 3. Individual Source Isolation

```python
async def fetch_posts_by_timeframe(self, sources: List[str], days: int) -> List[Dict[str, Any]]:
    """Multi-source fetching with isolation."""
    all_posts = []
    successful_sources = 0
    failed_sources = 0
    
    for source in sources:
        try:
            # Each source is independently protected
            posts = await self.fetch_posts(source, limit=100)
            if posts:
                all_posts.extend(posts)
                successful_sources += 1
            else:
                failed_sources += 1
        except Exception as e:
            self.logger.error(f"ERROR: Failed to process {source}: {e}")
            failed_sources += 1
            continue  # CRITICAL: Continue processing other sources
    
    self.logger.info(f"Multi-source complete: {successful_sources} successful, {failed_sources} failed")
    return sorted(all_posts, key=lambda p: p.get('timestamp', datetime.min))
```

### 4. Graceful Degradation

```python
def _extract_content(self, raw_post: dict) -> str:
    """Extract content with fallback strategy."""
    try:
        # Primary content source
        if 'description' in raw_post and raw_post['description']:
            return raw_post['description']
    except Exception:
        pass
    
    try:
        # Secondary content source
        if 'title' in raw_post and raw_post['title']:
            return raw_post['title']
    except Exception:
        pass
    
    # Final fallback
    return "Content unavailable"
```

---

## 🌐 Platform-Specific Patterns

### YouTube Connector Example

```python
class YouTubeConnector(BaseConnector):
    """
    Key considerations for YouTube:
    - Video vs Channel vs Playlist sources
    - API quota management (careful with requests)
    - Video descriptions as content
    - Thumbnail extraction
    - Comment fetching (optional)
    """
    
    async def fetch_posts(self, source_identifier: str, limit: int):
        # source_identifier could be:
        # - Channel ID: UCxxxxxxx
        # - Channel handle: @channelname
        # - Playlist ID: PLxxxxxxx
        pass
```

### Reddit Connector Example

```python
class RedditConnector(BaseConnector):
    """
    Key considerations for Reddit:
    - Subreddit vs User post sources
    - Post types: text, link, image, video
    - Comment threads (optional)
    - Reddit's rate limiting
    - NSFW content filtering
    """
    
    async def fetch_posts(self, source_identifier: str, limit: int):
        # source_identifier could be:
        # - Subreddit: r/subredditname
        # - User: u/username
        # - Multi-reddit: m/multiname
        pass
```

### X (Twitter) Connector Example

```python
class TwitterConnector(BaseConnector):
    """
    Key considerations for X:
    - API v2 vs v1.1 differences
    - Tweet threads handling
    - Retweet vs Quote tweet vs Reply
    - Media attachment processing
    - Rate limit complexity
    """
    
    async def fetch_posts(self, source_identifier: str, limit: int):
        # source_identifier could be:
        # - User handle: @username
        # - User ID: 123456789
        # - List ID: list_id
        pass
```

---

## 🧪 Testing & Validation

### Unit Test Template

```python
import pytest
from connectors.your_platform_connector import YourPlatformConnector

class TestYourPlatformConnector:
    
    @pytest.fixture
    async def connector(self):
        conn = YourPlatformConnector(api_key="test_key")
        await conn.connect()
        yield conn
        await conn.disconnect()
    
    async def test_fetch_posts_success(self, connector):
        posts = await connector.fetch_posts("test_source", 5)
        assert isinstance(posts, list)
        assert len(posts) <= 5
        
        for post in posts:
            # Validate unified data model
            assert "source_platform" in post
            assert "content" in post
            assert "timestamp" in post
            assert isinstance(post["media_urls"], list)
    
    async def test_fetch_posts_timeout(self, connector):
        # Test timeout handling
        connector.timeout = 0.001  # Force timeout
        posts = await connector.fetch_posts("test_source", 5)
        assert posts == []  # Should return empty list
    
    async def test_fetch_posts_invalid_source(self, connector):
        posts = await connector.fetch_posts("invalid_source", 5)
        assert posts == []  # Should handle gracefully
```

### Integration Test Checklist

- [ ] **Connection Testing**: Can connect and authenticate
- [ ] **Basic Fetching**: Can retrieve posts from valid sources
- [ ] **Error Handling**: Gracefully handles invalid sources
- [ ] **Timeout Protection**: Respects timeout limits
- [ ] **Data Model Compliance**: All posts match unified format
- [ ] **Multi-Source**: Can handle multiple sources simultaneously
- [ ] **Rate Limiting**: Respects platform rate limits

---

## 🔗 Integration Guidelines

### Adding to Main Application

1. **Register in `main.py`**:
```python
def _setup_connectors(self):
    # Existing connectors...
    
    # Your new connector
    your_platform_key = os.getenv('YOUR_PLATFORM_API_KEY')
    if your_platform_key:
        self.connectors['your_platform'] = YourPlatformConnector(
            api_key=your_platform_key
        )
        logging.info("YourPlatform connector registered")
    else:
        logging.warning("YourPlatform credentials not found in .env file")
```

2. **Update Mission Profiles**:
Add support for your platform in existing missions or create new ones.

3. **Environment Configuration**:
```bash
# .env file
YOUR_PLATFORM_API_KEY=your_api_key_here
YOUR_PLATFORM_API_SECRET=your_api_secret_here
```

### Documentation Updates

When adding a new connector:
- [ ] Update main README with new platform support
- [ ] Add environment variable documentation
- [ ] Include platform-specific usage examples
- [ ] Update connector registry in main application

---

## 📚 Best Practices Summary

### DO:
✅ **Always use timeout protection** with `asyncio.wait_for()`  
✅ **Return empty lists on errors**, never crash the system  
✅ **Log errors with specific source identification**  
✅ **Handle individual source failures independently**  
✅ **Validate all data before creating unified posts**  
✅ **Use UTC timestamps consistently**  
✅ **Follow The Citadel error handling patterns**  

### DON'T:
❌ **Never let one source failure affect others**  
❌ **Don't ignore timeout protection**  
❌ **Don't return None instead of empty lists**  
❌ **Don't assume API responses are always valid**  
❌ **Don't hardcode platform-specific values in main app**  
❌ **Don't skip error logging**  

---

## 🎯 Success Criteria

Your connector is ready for production when:

1. **Citadel Compliance**: Follows all error handling patterns
2. **Data Model Compliance**: Returns perfect unified format
3. **Timeout Protection**: All operations respect time limits
4. **Error Isolation**: Individual failures don't affect system
5. **Comprehensive Testing**: Unit and integration tests pass
6. **Documentation**: Clear usage examples and error scenarios
7. **Rate Limit Respect**: Follows platform API guidelines

---

## 🚀 Advanced Features

### Optional Enhancements

```python
# Content analysis hints for Mark IV
unified_post['content_analysis_hints'] = {
    'platform_metrics': {
        'engagement_rate': calculate_engagement(raw_post),
        'virality_score': calculate_virality(raw_post)
    },
    'content_type': classify_content_type(raw_post),
    'sentiment_hint': detect_sentiment(raw_post['content'])
}

# Platform-specific metadata for enhanced analysis
unified_post['platform_metadata'] = {
    'hashtags': extract_hashtags(raw_post),
    'mentions': extract_mentions(raw_post),
    'links': extract_links(raw_post)
}
```

---

## 📞 Support and Resources

- **Base Connector Interface**: `connectors/base_connector.py`
- **Reference Implementations**: `connectors/rss_connector.py`, `connectors/telegram_connector.py`
- **Error Handling Guide**: This document, Section "The Citadel Standards"
- **Integration Examples**: `main.py` connector registration

Remember: When in doubt, follow the patterns established by the RSS and Telegram connectors. They've been battle-tested and follow all Citadel standards.

---

**The Citadel Principle**: *"A connector that cannot handle failure is not a connector; it's a liability."* 