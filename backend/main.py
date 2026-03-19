import logging
import os
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from insight_api_bridge import InsightApiBridge

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="INSIGHT Intelligence Platform API",
    description="Backend API for the INSIGHT Mark I Foundation Engine",
    version="1.0.0"
)


def _cors_origins() -> list[str]:
    configured = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if configured:
        return [origin.strip() for origin in configured.split(",") if origin.strip()]

    frontend_public = os.getenv("FRONTEND_PUBLIC_URL", "http://localhost:3000").strip()
    defaults = [
        frontend_public,
        "http://localhost:3000",
        "http://localhost:5173",
    ]

    origins: list[str] = []
    for origin in defaults:
        if origin and origin not in origins:
            origins.append(origin)
    return origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the bridge to Mark I API Engine
api_bridge = InsightApiBridge()

# Request models
class BriefingRequest(BaseModel):
    date: str  # Format: "YYYY-MM-DD"
    includeTopics: bool | None = None
    includeUnreferenced: bool | None = True
    refresh: bool | None = False


class ArchiveRequest(BaseModel):
    desiredPosts: int | None = None
    resume: bool | None = True
    pageDelaySeconds: int | None = None
    batchSize: int | None = None
    batchCooldownSeconds: int | None = None


class YouTubeChannelRequest(BaseModel):
    source: str
    limit: int | None = None


class YouTubeVideoRequest(BaseModel):
    source: str
    video: str


class YouTubeChatRequest(BaseModel):
    source: str
    video: str
    question: str


class YouTubeProgressRequest(BaseModel):
    sourceId: str | None = None
    videoUrl: str
    title: str
    durationSeconds: int | None = None
    progressSeconds: int
    notesMarkdown: str | None = None
    completed: bool | None = None


class LiveFetchRequest(BaseModel):
    limit: int | None = None


class SchedulerConfigRequest(BaseModel):
    intervalHours: float | None = None
    syncSourcesEachCycle: bool | None = None
    generateDailyBriefing: bool | None = None
    generateTopicBriefing: bool | None = None


class PostNotesRequest(BaseModel):
    notesMarkdown: str


class PostSummaryRequest(BaseModel):
    refresh: bool | None = False


class PostChatRequest(BaseModel):
    question: str


class PostCommentsRequest(BaseModel):
    limit: int | None = 80
    refresh: bool | None = False

@app.get("/")
async def root():
    return {
        "message": "INSIGHT Intelligence Platform API", 
        "version": "1.0.0",
        "engine": "DB-backed Archive Engine",
        "status": "operational"
    }

@app.get("/hello")
async def hello():
    return {"message": "Hello World"}

# ============= SOURCES ENDPOINTS (DATABASE-BACKED) =============

@app.get("/api/sources")
async def get_sources():
    """Get sources in frontend-compatible format (nested by platform)."""
    try:
        logger.info("📋 Fetching sources from database")
        sources_config = api_bridge.get_sources_config()
        return {"success": True, "data": sources_config}
    except Exception as e:
        logger.exception("Failed to get sources")
        return {"success": False, "error": str(e)}

@app.get("/api/enabled-sources")
async def get_enabled_sources():
    """Get only enabled sources (flat list)."""
    try:
        logger.info("📋 Fetching enabled sources from database")
        enabled = api_bridge.get_enabled_sources()
        return {"success": True, "data": enabled}
    except Exception as e:
        logger.exception("Failed to get enabled sources")
        return {"success": False, "error": str(e)}

@app.post("/api/sources")
async def update_sources(config: dict):
    """Update sources configuration (add/remove/enable/disable)."""
    try:
        logger.info("🔧 Updating sources in database")
        result = api_bridge.update_sources_config(config)
        
        if result["success"]:
            return {
                "success": True,
                "message": result["message"],
                "data": result["stats"]
            }
        else:
            return {
                "success": False,
                "error": "Some operations failed",
                "data": result["stats"]
            }
    except Exception as e:
        logger.exception("Failed to update sources")
        return {"success": False, "error": str(e)}


@app.post("/api/sources/sync/{direction}")
async def sync_sources(direction: str):
    """Synchronize sources.json and the database-backed registry."""
    try:
        logger.info(f"🔄 Syncing sources registry: {direction}")
        return api_bridge.sync_sources_registry(direction)
    except Exception as e:
        logger.exception("Failed to sync sources")
        return {"success": False, "error": str(e)}
    

# ============= POSTS ENDPOINTS (DATABASE-BACKED) =============

@app.get("/api/posts/{date}")
async def get_posts(date: str):
    """Get posts for a specific date."""
    try:
        logger.info(f"📋 Fetching posts for date: {date}")

        result = api_bridge.get_posts_by_date(date)
        
        # Log success
        if result.get("success"):
            logger.info(f"✅ Retrieved {result.get('total', 0)} posts")
        
        return result

    except Exception as e:
        logger.exception("Failed to get posts")
        return {"success": False, "error": str(e)}

@app.get("/api/posts/source/{source_id}")
async def get_posts_by_source(source_id: str):
    """Get all posts for a specific source."""
    try:
        logger.info(f"📋 Fetching posts for source: {source_id}")

        result = api_bridge.get_posts_by_source(source_id)
        
        # Log success
        if result.get("success"):
            logger.info(f"✅ Retrieved {result.get('total', 0)} posts")
        
        return result

    except Exception as e:
        logger.exception("Failed to get posts by source")
        return {"success": False, "error": str(e)}


@app.get("/api/posts/item/{post_id}")
async def get_post_detail(post_id: str):
    """Get a single post with source metadata and saved notes."""
    try:
        logger.info(f"📄 Fetching post detail: {post_id}")
        return api_bridge.get_post_detail(post_id)
    except Exception as e:
        logger.exception("Failed to get post detail")
        return {"success": False, "error": str(e), "post": None}


@app.get("/api/posts/item/{post_id}/notes")
async def get_post_notes(post_id: str):
    try:
        logger.info(f"📝 Fetching notes for post: {post_id}")
        return api_bridge.get_post_notes(post_id)
    except Exception as e:
        logger.exception("Failed to get post notes")
        return {"success": False, "error": str(e), "post_id": post_id, "notes_markdown": ""}


@app.put("/api/posts/item/{post_id}/notes")
async def save_post_notes(post_id: str, request: PostNotesRequest):
    try:
        logger.info(f"📝 Saving notes for post: {post_id}")
        return api_bridge.save_post_notes(post_id, request.notesMarkdown)
    except Exception as e:
        logger.exception("Failed to save post notes")
        return {"success": False, "error": str(e), "post_id": post_id}


@app.post("/api/posts/item/{post_id}/summary")
async def get_post_summary(post_id: str, request: PostSummaryRequest):
    try:
        logger.info(f"🧠 Generating summary for post: {post_id}")
        return api_bridge.get_post_summary(post_id, refresh=bool(request.refresh))
    except Exception as e:
        logger.exception("Failed to get post summary")
        return {"success": False, "error": str(e), "post_id": post_id}


@app.post("/api/posts/item/{post_id}/chat")
async def chat_about_post(post_id: str, request: PostChatRequest):
    try:
        logger.info(f"💬 Chat about post: {post_id}")
        return api_bridge.chat_about_post(post_id, request.question)
    except Exception as e:
        logger.exception("Failed to chat about post")
        return {"success": False, "error": str(e), "post_id": post_id}


@app.post("/api/posts/item/{post_id}/reddit-comments")
async def fetch_reddit_comments(post_id: str, request: PostCommentsRequest):
    try:
        logger.info(f"💬 Fetching Reddit comments for post: {post_id}")
        return await api_bridge.fetch_reddit_comments(
            post_id,
            limit=int(request.limit or 80),
            refresh=bool(request.refresh),
        )
    except Exception as e:
        logger.exception("Failed to fetch Reddit comments")
        return {"success": False, "error": str(e), "post_id": post_id}


@app.post("/api/posts/item/{post_id}/reddit-comments/briefing")
async def get_reddit_comments_briefing(post_id: str, request: PostCommentsRequest):
    try:
        logger.info(f"🧠 Generating Reddit comments briefing for post: {post_id}")
        return await api_bridge.get_reddit_comments_briefing(
            post_id,
            limit=int(request.limit or 80),
            refresh=bool(request.refresh),
        )
    except Exception as e:
        logger.exception("Failed to generate Reddit comments briefing")
        return {"success": False, "error": str(e), "post_id": post_id}

@app.get("/api/sources/with-counts")
async def get_sources_with_counts():
    """Get all sources with their post counts, grouped by platform."""
    try:
        logger.info("📋 Fetching sources with post counts")

        result = api_bridge.get_sources_with_counts()
        
        # Log success
        if result.get("success"):
            logger.info(f"✅ Retrieved sources with {result.get('total_posts', 0)} total posts")
        
        return result

    except Exception as e:
        logger.exception("Failed to get sources with counts")
        return {"success": False, "error": str(e)}

@app.get("/api/sources/{source_id}/settings")
async def get_source_settings(source_id: str):
    """Get settings for a specific source."""
    try:
        logger.info(f"📋 Fetching settings for source: {source_id}")
        
        result = api_bridge.get_source_settings(source_id)
        
        if result.get("success"):
            logger.info(f"✅ Retrieved settings for source {source_id}")
        
        return result
        
    except Exception as e:
        logger.exception(f"Failed to get settings for source {source_id}")
        return {"success": False, "error": str(e)}

@app.put("/api/sources/{source_id}/settings")
async def update_source_settings(source_id: str, settings: dict):
    """Update settings for a specific source."""
    try:
        logger.info(f"🔧 Updating settings for source: {source_id}")
        
        result = api_bridge.update_source_settings(source_id, settings)
        
        if result.get("success"):
            logger.info(f"✅ Updated settings for source {source_id}")
        
        return result
        
    except Exception as e:
        logger.exception(f"Failed to update settings for source {source_id}")
        return {"success": False, "error": str(e)}

@app.get("/api/sources/with-settings")
async def get_sources_with_settings():
    """Get all sources with their settings and post counts."""
    try:
        logger.info("📋 Fetching sources with settings")
        
        result = api_bridge.get_sources_with_settings()
        
        if result.get("success"):
            logger.info(f"✅ Retrieved {result.get('total', 0)} sources with settings")
        
        return result
        
    except Exception as e:
        logger.exception("Failed to get sources with settings")
        return {"success": False, "error": str(e)}


@app.get("/api/archive/{source_id}/status")
async def get_archive_status(source_id: str):
    """Get persisted archive status for a source."""
    try:
        logger.info(f"📦 Fetching archive status for source: {source_id}")
        return api_bridge.get_archive_status(source_id)
    except Exception as e:
        logger.exception(f"Failed to get archive status for {source_id}")
        return {"success": False, "error": str(e)}

@app.get("/api/archive/catalog")
async def get_archive_catalog():
    """List enabled sources with their persisted archive status."""
    try:
        logger.info("📦 Fetching archive catalog")
        return api_bridge.get_archive_catalog()
    except Exception as e:
        logger.exception("Failed to fetch archive catalog")
        return {"success": False, "error": str(e), "sources": [], "total": 0}


@app.post("/api/archive/{source_id}/plan")
async def plan_archive(source_id: str, request: ArchiveRequest):
    """Estimate archive effort for a source."""
    try:
        logger.info(f"🧭 Planning archive for source: {source_id}")
        return await api_bridge.get_archive_plan(
            source_id,
            request.desiredPosts,
            resume=bool(request.resume),
            rate_limit_overrides={
                "page_delay_seconds": request.pageDelaySeconds,
                "batch_size": request.batchSize,
                "batch_cooldown_seconds": request.batchCooldownSeconds,
            },
        )
    except Exception as e:
        logger.exception(f"Failed to plan archive for {source_id}")
        return {"success": False, "error": str(e)}


@app.post("/api/archive/{source_id}/run")
async def run_archive(source_id: str, request: ArchiveRequest):
    """Run an archive job for a single source."""
    try:
        logger.info(f"📦 Running archive for source: {source_id}")
        return await api_bridge.run_archive(
            source_id,
            request.desiredPosts,
            resume=bool(request.resume),
            rate_limit_overrides={
                "page_delay_seconds": request.pageDelaySeconds,
                "batch_size": request.batchSize,
                "batch_cooldown_seconds": request.batchCooldownSeconds,
            },
        )
    except Exception as e:
        logger.exception(f"Failed to run archive for {source_id}")
        return {"success": False, "error": str(e)}


@app.post("/api/sources/{source_id}/fetch-now")
async def fetch_source_now(source_id: str, request: LiveFetchRequest):
    """Fetch the latest posts for a single source immediately."""
    try:
        logger.info(f"⚡ Fetching source immediately: {source_id}")
        return await api_bridge.fetch_source_now(source_id, request.limit)
    except Exception as e:
        logger.exception(f"Failed to fetch source immediately: {source_id}")
        return {"success": False, "error": str(e), "source_id": source_id}


# Briefing generation endpoints


@app.post("/api/daily")
async def generate_daily_briefing(request: BriefingRequest):
    try:
        date = request.date
        logger.info(f"🚀 Generating daily briefing for date: {date}")
        
        if not date:
            raise HTTPException(status_code=400, detail="Date parameter required")
        
        if request.includeTopics:
            result = await api_bridge.generate_daily_briefing_with_topics(
                date,
                include_unreferenced=True if request.includeUnreferenced is None else request.includeUnreferenced,
                refresh=bool(request.refresh),
            )
        else:
            result = await api_bridge.generate_daily_briefing(date)
        
        if isinstance(result, dict) and (result.get("error") or not result.get("success", True)):
            logger.error(f"❌ Engine error: {result['error']}")
            return {"success": False, "error": result["error"]}
        
        logger.info("✅ Briefing generated successfully")
        response_payload = {
            "success": True,
            "briefing": result.get("briefing", result) if isinstance(result, dict) else result,
            "format": result.get("format", "markdown") if isinstance(result, dict) else "markdown",
            "saved_briefing_id": result.get("saved_briefing_id") if isinstance(result, dict) else None,
            "date": result.get("date", date) if isinstance(result, dict) else date,
            "posts_processed": result.get("posts_processed", 0) if isinstance(result, dict) else 0,
            "total_posts_fetched": result.get("total_posts_fetched", 0) if isinstance(result, dict) else 0,
            "posts": result.get("posts", []) if isinstance(result, dict) else []
        }
        # If enhanced data exists, include it without token usage
        if isinstance(result, dict) and result.get("topics") is not None:
            response_payload.update({
                "enhanced": result.get("enhanced", True),
                "cached": result.get("cached", False),
                "topics": result.get("topics", []),
                "unreferenced_posts": result.get("unreferenced_posts", [])
            })

        return response_payload
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate briefing: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/daily/topics")
async def generate_daily_briefing_with_topics(request: BriefingRequest):
    try:
        date = request.date
        logger.info(f"🚀 Generating topic-based daily briefing for date: {date}")
        if not date:
            raise HTTPException(status_code=400, detail="Date parameter required")

        include_unreferenced = True if request.includeUnreferenced is None else request.includeUnreferenced
        result = await api_bridge.generate_daily_briefing_with_topics(
            date,
            include_unreferenced=include_unreferenced,
            refresh=bool(request.refresh),
        )
        if isinstance(result, dict) and (result.get("error") or not result.get("success", True)):
            logger.error(f"❌ Engine error: {result['error']}")
            return {"success": False, "error": result["error"]}

        # Construct payload (no token costs exposed)
        return {
            "success": True,
            "enhanced": result.get("enhanced", True),
            # Topic-based daily briefing string (top-level summary)
            "briefing": result.get("briefing", ""),
            "format": result.get("format", "markdown"),
            "saved_briefing_id": result.get("saved_briefing_id"),
            "cached": result.get("cached", False),
            "topics": result.get("topics", []),
            "unreferenced_posts": result.get("unreferenced_posts", []),
            "posts": result.get("posts", {}),
            "date": result.get("date", date),
            "posts_processed": result.get("posts_processed", 0),
            "total_posts_fetched": result.get("total_posts_fetched", 0)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate topic-based briefing: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/weekly")
async def generate_weekly_briefing(request: BriefingRequest):
    try:
        date = request.date
        logger.info(f"🚀 Generating weekly briefing anchored at date: {date}")
        if not date:
            raise HTTPException(status_code=400, detail="Date parameter required")

        if request.includeTopics:
            result = await api_bridge.generate_weekly_topic_briefing(date, refresh=bool(request.refresh))
        else:
            result = await api_bridge.generate_weekly_briefing(date, refresh=bool(request.refresh))
        if isinstance(result, dict) and (result.get("error") or not result.get("success", True)):
            logger.error(f"❌ Engine error: {result['error']}")
            return {"success": False, "error": result["error"]}

        return {
            "success": True,
            "briefing": result.get("briefing", ""),
            "format": result.get("format", "markdown"),
            "saved_briefing_id": result.get("saved_briefing_id"),
            "cached": result.get("cached", False),
            "date": result.get("date", date),
            "week_start": result.get("week_start"),
            "week_end": result.get("week_end"),
            "subject_key": result.get("subject_key"),
            "daily_briefings_used": result.get("daily_briefings_used", 0),
            "days_covered": result.get("days_covered", []),
            "estimated_tokens": result.get("estimated_tokens"),
            "topics": result.get("topics", []),
            "posts": result.get("posts", {}),
            "variant": result.get("variant", "default"),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate weekly briefing: {e}")
        return {"success": False, "error": str(e)}

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    import time
    return {
        "status": "healthy",
        "engine": "DB-backed Archive Engine",
        "timestamp": str(time.time())
    }


# ============= INGESTION ENDPOINTS =============

@app.post("/api/ingest-posts")
async def ingest_posts():
    """Ingest posts from all sources."""
    try:
        logger.info("🚀 Ingesting posts from all sources")
        result = await api_bridge.ingest_posts()

        if isinstance(result, dict) and "success" in result:
            return result

        if result is None:
            return {
                "success": False, 
                "error": "Failed to ingest posts"
            }
        
    except Exception as e:
        logger.exception("Failed to ingest posts")
        return {"success": False, "error": str(e)}

@app.post("/api/safe-ingest-posts")
async def safe_ingest_posts():
    """Ingest posts from all sources that need updating."""
    try:
        logger.info("🚀 Ingesting posts from all sources that need updating")
        result = await api_bridge.safe_ingest_posts()
        if isinstance(result, dict) and "success" in result:
            return result

        if result is None:
            return {
                "success": False, 
                "error": "Failed to ingest posts"
            }
    except Exception as e:
        logger.exception("Failed to ingest posts from all sources that need updating")
        return {"success": False, "error": str(e)}


@app.get("/api/ingestion/logs")
async def get_ingestion_logs(
    log: str = Query(default="application"),
    lines: int = Query(default=200, ge=1, le=1000),
):
    """Return recent shared backend/ingestion log lines."""
    try:
        logger.info(f"📜 Fetching log tail: log={log} lines={lines}")
        return api_bridge.get_ingestion_logs(log, lines)
    except Exception as e:
        logger.exception("Failed to fetch ingestion logs")
        return {"success": False, "error": str(e), "log": log, "lines": []}


@app.get("/api/operations/overview")
async def get_operations_overview():
    try:
        logger.info("📡 Fetching operations overview")
        return api_bridge.get_operations_overview()
    except Exception as e:
        logger.exception("Failed to fetch operations overview")
        return {"success": False, "error": str(e), "jobs": [], "source_health": [], "alerts": []}


@app.get("/api/operations/jobs/{job_id}")
async def get_operation_job(job_id: str):
    try:
        logger.info("📡 Fetching operation job detail: %s", job_id)
        return api_bridge.get_operation_job(job_id)
    except Exception as e:
        logger.exception("Failed to fetch operation job detail")
        return {"success": False, "error": str(e), "job": None}


@app.get("/api/operations/scheduler")
async def get_scheduler_config():
    try:
        logger.info("⏱️ Fetching scheduler config")
        return api_bridge.get_scheduler_config()
    except Exception as e:
        logger.exception("Failed to fetch scheduler config")
        return {"success": False, "error": str(e)}


@app.put("/api/operations/scheduler")
async def update_scheduler_config(request: SchedulerConfigRequest):
    try:
        logger.info("⏱️ Updating scheduler config")
        payload = {}
        if request.intervalHours is not None:
            payload["interval_hours"] = request.intervalHours
        if request.syncSourcesEachCycle is not None:
            payload["sync_sources_each_cycle"] = request.syncSourcesEachCycle
        if request.generateDailyBriefing is not None:
            payload["generate_daily_briefing"] = request.generateDailyBriefing
        if request.generateTopicBriefing is not None:
            payload["generate_topic_briefing"] = request.generateTopicBriefing
        return api_bridge.update_scheduler_config(payload)
    except Exception as e:
        logger.exception("Failed to update scheduler config")
        return {"success": False, "error": str(e)}


# ============= YOUTUBE ENDPOINTS =============

@app.post("/api/youtube/channel/videos")
async def list_youtube_channel_videos(request: YouTubeChannelRequest):
    try:
        logger.info(f"📺 Listing YouTube videos for {request.source}")
        return api_bridge.list_youtube_channel_videos(request.source, request.limit)
    except Exception as e:
        logger.exception("Failed to list YouTube videos")
        return {"success": False, "error": str(e)}


@app.post("/api/youtube/channel/roadmap")
async def build_youtube_channel_roadmap(request: YouTubeChannelRequest):
    try:
        logger.info(f"🗺️ Building YouTube roadmap for {request.source}")
        return api_bridge.build_youtube_channel_roadmap(request.source, request.limit)
    except Exception as e:
        logger.exception("Failed to build YouTube roadmap")
        return {"success": False, "error": str(e)}


@app.post("/api/youtube/channel/playlists")
async def build_youtube_playlists(request: YouTubeChannelRequest):
    try:
        logger.info(f"📚 Building YouTube playlists for {request.source}")
        return api_bridge.build_youtube_playlists(request.source, request.limit or 20)
    except Exception as e:
        logger.exception("Failed to build YouTube playlists")
        return {"success": False, "error": str(e)}


@app.post("/api/youtube/video/evaluate")
async def evaluate_youtube_video(request: YouTubeVideoRequest):
    try:
        logger.info(f"🎥 Evaluating YouTube video {request.video}")
        return await api_bridge.evaluate_youtube_video(request.source, request.video)
    except Exception as e:
        logger.exception("Failed to evaluate YouTube video")
        return {"success": False, "error": str(e)}


@app.post("/api/youtube/video/chat")
async def chat_with_youtube_video(request: YouTubeChatRequest):
    try:
        logger.info(f"💬 Chatting with YouTube video {request.video}")
        return await api_bridge.chat_with_youtube_video(request.source, request.video, request.question)
    except Exception as e:
        logger.exception("Failed to chat with YouTube video")
        return {"success": False, "error": str(e)}


@app.get("/api/youtube/progress/{video_id}")
async def get_youtube_watch_progress(video_id: str):
    try:
        logger.info(f"▶️ Fetching watch progress for {video_id}")
        return api_bridge.get_youtube_watch_progress(video_id)
    except Exception as e:
        logger.exception("Failed to fetch watch progress")
        return {"success": False, "error": str(e), "progress": None}


@app.put("/api/youtube/progress/{video_id}")
async def save_youtube_watch_progress(video_id: str, request: YouTubeProgressRequest):
    try:
        logger.info(f"💾 Saving watch progress for {video_id}")
        return api_bridge.save_youtube_watch_progress(
            video_id=video_id,
            video_url=request.videoUrl,
            title=request.title,
            duration_seconds=request.durationSeconds,
            progress_seconds=request.progressSeconds,
            source_id=request.sourceId,
            notes_markdown=request.notesMarkdown,
            completed=request.completed,
        )
    except Exception as e:
        logger.exception("Failed to save watch progress")
        return {"success": False, "error": str(e), "progress": None}

# ============= TOPICS ENDPOINTS =============

@app.get("/api/topics/{date}")
async def get_topics(date: str):
    """
    Get all topics for a specific date with their associated posts.
    This is the main endpoint for the topics view.
    """
    try:
        logger.info(f"📋 Fetching topics for date: {date}")
        
        result = api_bridge.get_topics_by_date(date)
        
        # Log success
        if result.get("success"):
            logger.info(f"✅ Retrieved {result.get('total', 0)} topics")
        
        return result
        
    except Exception as e:
        logger.exception("Failed to get topics")
        return {"success": False, "error": str(e)}

@app.get("/api/topics/topic/{topic_id}")
async def get_topic(topic_id: str):
    """Get a single topic with its posts."""
    try:
        logger.info(f"📋 Fetching topic: {topic_id}")
        
        result = api_bridge.get_topic_by_id(topic_id)
        
        # Log success
        if result.get("success"):
            logger.info(f"✅ Retrieved topic: {topic_id}")
        
        return result
        
    except Exception as e:
        logger.exception(f"Failed to get topic {topic_id}")
        return {"success": False, "error": str(e)}

@app.get("/api/topics/{topic_id}/posts")
async def get_topic_posts(topic_id: str):
    """Get all posts for a specific topic."""
    try:
        logger.info(f"📋 Fetching posts for topic: {topic_id}")
        
        result = api_bridge.get_posts_for_topic(topic_id)
        
        # Log success
        if result.get("success"):
            logger.info(f"✅ Retrieved {result.get('total', 0)} posts for topic")
        
        return result
        
    except Exception as e:
        logger.exception(f"Failed to get posts for topic {topic_id}")
        return {"success": False, "error": str(e)}

@app.get("/api/topics/check/{date}")
async def check_topics(date: str):
    """Check if topics exist for a specific date."""
    try:
        logger.info(f"🔍 Checking if topics exist for date: {date}")
        
        result = api_bridge.check_topics_exist(date)
        
        # Log result
        if result.get("success"):
            exists = result.get("exists", False)
            logger.info(f"✅ Topics exist for {date}: {exists}")
        
        return result
        
    except Exception as e:
        logger.exception(f"Failed to check topics for {date}")
        return {"success": False, "error": str(e)}

@app.get("/api/topics/{topic_id}/similar")
async def get_similar_topics(topic_id: str, threshold: float = 0.75, limit: int = 10):
    """
    Find topics similar to a given topic (future: when embeddings are added).
    
    Query params:
        - threshold: Minimum similarity score (0-1), default 0.75
        - limit: Maximum number of results, default 10
    """
    try:
        logger.info(f"🔍 Finding similar topics for: {topic_id}")
        
        result = api_bridge.find_similar_topics(topic_id, threshold, limit)
        
        # Log success
        if result.get("success"):
            logger.info(f"✅ Found {result.get('total', 0)} similar topics")
        
        return result
        
    except Exception as e:
        logger.exception(f"Failed to find similar topics for {topic_id}")
        return {"success": False, "error": str(e)}

@app.put("/api/topics/{topic_id}/title")
async def update_topic_title(topic_id: str, data: dict):
    """
    Update the title of a topic.
    
    Request body:
        - title: New title for the topic
    """
    try:
        logger.info(f"✏️  Updating title for topic: {topic_id}")
        
        new_title = data.get("title")
        if not new_title:
            return {"success": False, "error": "Title is required"}
        
        result = api_bridge.update_topic_title(topic_id, new_title)
        
        # Log success
        if result.get("success"):
            logger.info(f"✅ Updated topic title: {topic_id}")
        
        return result
        
    except Exception as e:
        logger.exception(f"Failed to update topic title for {topic_id}")
        return {"success": False, "error": str(e)}

@app.post("/api/topics/{topic_id}/posts/{post_id}/move-to-outlier")
async def move_post_to_outlier(topic_id: str, post_id: str, data: dict):
    """
    Move a post from a topic to the outlier topic.
    
    Request body:
        - date: Date string (YYYY-MM-DD) for finding/creating outlier topic
    """
    try:
        logger.info(f"✂️  Moving post {post_id} from topic {topic_id} to outlier")
        
        date_str = data.get("date")
        if not date_str:
            return {"success": False, "error": "Date is required"}
        
        result = api_bridge.move_post_to_outlier(post_id, topic_id, date_str)
        
        # Log success
        if result.get("success"):
            logger.info(f"✅ Moved post to outlier topic: {result.get('outlier_topic_id')}")
        
        return result
        
    except Exception as e:
        logger.exception(f"Failed to move post {post_id} to outlier")
        return {"success": False, "error": str(e)}

# ============= TOPIC MODELING ENDPOINTS (TESTING) =============

@app.post("/api/model-topics")
async def model_topics(posts: List[Dict[str, Any]]):
    """Model topics from a list of posts (testing only)."""
    try:
        logger.info("🚀 Modeling topics from a list of posts")
        result = await api_bridge.model_topics(posts)
        return result
    except Exception as e:
        logger.exception("Failed to model topics")
        return {"success": False, "error": str(e)}
