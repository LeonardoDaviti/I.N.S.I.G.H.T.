import logging
import os
import asyncio
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
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
    asyncMode: bool | None = False


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
    asyncMode: bool | None = False


class SchedulerConfigRequest(BaseModel):
    intervalHours: float | None = None
    syncSourcesEachCycle: bool | None = None
    generateDailyBriefing: bool | None = None
    generateTopicBriefing: bool | None = None


class PostNotesRequest(BaseModel):
    notesMarkdown: str


class PostSummaryRequest(BaseModel):
    refresh: bool | None = False
    asyncMode: bool | None = False


class PostHighlightsRequest(BaseModel):
    refresh: bool | None = False


class PostChatRequest(BaseModel):
    question: str
    asyncMode: bool | None = False


class PostReaderSessionRequest(BaseModel):
    durationSeconds: int
    metadata: Dict[str, Any] | None = None


class PostFavoriteRequest(BaseModel):
    favorited: bool


class PostOpenRequest(BaseModel):
    metadata: Dict[str, Any] | None = None


class PostTimelineRequest(BaseModel):
    refresh: bool | None = False


class PostCommentsRequest(BaseModel):
    limit: int | None = 80
    refresh: bool | None = False
    asyncMode: bool | None = False


class EvidenceRebuildPostRequest(BaseModel):
    postId: str


class EvidenceRebuildDateRequest(BaseModel):
    date: str
    limit: int | None = None


class MemoryRebuildPostRequest(BaseModel):
    postId: str


class MemoryRebuildDateRequest(BaseModel):
    date: str
    limit: int | None = None


class EventRebuildPostRequest(BaseModel):
    postId: str


class EventRebuildDateRequest(BaseModel):
    date: str
    limit: int | None = None


class InboxRebuildRequest(BaseModel):
    generatedForDate: str | None = None
    scopeType: str | None = "daily_queue"
    scopeValue: str | None = None
    limit: int | None = 20
    actorId: str | None = None


class InboxActionRequest(BaseModel):
    actionType: str
    actorId: str | None = None
    payload: Dict[str, Any] | None = None


async def _run_async_job_background(task_name: str, fn, *args, **kwargs):
    try:
        await fn(*args, **kwargs)
    except Exception:
        logger.exception("Background async job failed: %s", task_name)


async def _run_sync_job_background(task_name: str, fn, *args, **kwargs):
    try:
        await asyncio.to_thread(fn, *args, **kwargs)
    except Exception:
        logger.exception("Background sync job failed: %s", task_name)


def _accepted_job_response(job_id: str, job_type: str, *, message: str | None = None) -> Dict[str, Any]:
    return {
        "success": True,
        "accepted": True,
        "job_id": job_id,
        "job_type": job_type,
        "status": "running",
        "message": message or f"{job_type} started",
    }

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
        return {"success": False, "error": str(e), "post": None, "summary": None, "summary_references": [], "highlights": [], "reader_state": None}


@app.post("/api/posts/item/{post_id}/highlights")
async def get_post_highlights(post_id: str, request: PostHighlightsRequest):
    try:
        logger.info(f"✨ Fetching post highlights: {post_id}")
        return api_bridge.get_post_highlights(post_id, refresh=bool(request.refresh))
    except Exception as e:
        logger.exception("Failed to get post highlights")
        return {"success": False, "error": str(e), "post_id": post_id, "highlights": []}


@app.get("/api/posts/item/{post_id}/reader-state")
async def get_post_reader_state(post_id: str):
    try:
        logger.info(f"📚 Fetching reader state: {post_id}")
        return api_bridge.get_post_reader_state(post_id)
    except Exception as e:
        logger.exception("Failed to get post reader state")
        return {"success": False, "error": str(e), "post_id": post_id, "reader_state": None}


@app.post("/api/posts/item/{post_id}/opened")
async def record_post_open(post_id: str, request: PostOpenRequest | None = None):
    try:
        logger.info(f"👁️ Recording post open: {post_id}")
        payload = request.model_dump() if hasattr(request, "model_dump") else (request or {})
        return api_bridge.record_post_open(post_id, metadata=payload.get("metadata"))
    except Exception as e:
        logger.exception("Failed to record post open")
        return {"success": False, "error": str(e), "post_id": post_id}


@app.post("/api/posts/item/{post_id}/reading-session")
async def record_post_reading_session(post_id: str, request: PostReaderSessionRequest):
    try:
        logger.info(f"⏱️ Recording reading session: {post_id}")
        return api_bridge.record_post_reading_session(
            post_id,
            duration_seconds=int(request.durationSeconds or 0),
            metadata=request.metadata,
        )
    except Exception as e:
        logger.exception("Failed to record reading session")
        return {"success": False, "error": str(e), "post_id": post_id}


@app.post("/api/posts/item/{post_id}/favorite")
async def toggle_post_favorite(post_id: str, request: PostFavoriteRequest):
    try:
        logger.info(f"⭐ Toggling post favorite: {post_id}")
        return api_bridge.toggle_post_favorite(post_id, bool(request.favorited))
    except Exception as e:
        logger.exception("Failed to toggle post favorite")
        return {"success": False, "error": str(e), "post_id": post_id}


@app.get("/api/posts/item/{post_id}/evidence")
async def get_post_evidence(post_id: str):
    """Get the evidence/debug view for a single post."""
    try:
        logger.info(f"🧩 Fetching post evidence: {post_id}")
        return api_bridge.get_post_evidence(post_id)
    except Exception as e:
        logger.exception("Failed to get post evidence")
        return {"success": False, "error": str(e), "evidence": None}


@app.get("/api/posts/item/{post_id}/memory")
async def get_post_memory(post_id: str):
    """Get the entity-memory debug view for a single post."""
    try:
        logger.info(f"🧠 Fetching post memory: {post_id}")
        return api_bridge.get_post_memory(post_id)
    except Exception as e:
        logger.exception("Failed to get post memory")
        return {"success": False, "error": str(e), "memory": None}


@app.post("/api/evidence/rebuild-for-post")
async def rebuild_evidence_for_post(request: EvidenceRebuildPostRequest):
    try:
        logger.info(f"🔄 Rebuilding evidence for post: {request.postId}")
        return api_bridge.rebuild_post_evidence(request.postId)
    except Exception as e:
        logger.exception("Failed to rebuild post evidence")
        return {"success": False, "error": str(e)}


@app.post("/api/evidence/rebuild-for-date")
async def rebuild_evidence_for_date(request: EvidenceRebuildDateRequest):
    try:
        logger.info(f"🔄 Rebuilding evidence for date: {request.date}")
        return api_bridge.rebuild_evidence_for_date(request.date, limit=request.limit)
    except Exception as e:
        logger.exception("Failed to rebuild evidence for date")
        return {"success": False, "error": str(e)}


@app.post("/api/memory/rebuild-for-post")
async def rebuild_memory_for_post(request: MemoryRebuildPostRequest):
    try:
        logger.info(f"🔄 Rebuilding entity memory for post: {request.postId}")
        return api_bridge.rebuild_post_memory(request.postId)
    except Exception as e:
        logger.exception("Failed to rebuild entity memory for post")
        return {"success": False, "error": str(e)}


@app.post("/api/memory/rebuild-for-date")
async def rebuild_memory_for_date(request: MemoryRebuildDateRequest):
    try:
        logger.info(f"🔄 Rebuilding entity memory for date: {request.date}")
        return api_bridge.rebuild_memory_for_date(request.date, limit=request.limit)
    except Exception as e:
        logger.exception("Failed to rebuild entity memory for date")
        return {"success": False, "error": str(e)}


@app.get("/api/posts/item/{post_id}/events")
async def get_post_events(post_id: str):
    """Get the event-memory debug view for a single post."""
    try:
        logger.info(f"📅 Fetching post events: {post_id}")
        return api_bridge.get_post_events(post_id)
    except Exception as e:
        logger.exception("Failed to get post events")
        return {"success": False, "error": str(e), "events": None}


@app.get("/api/posts/item/{post_id}/story")
async def get_post_story(post_id: str):
    """Get the connected story view for a single post."""
    try:
        logger.info(f"📖 Fetching post story: {post_id}")
        return api_bridge.get_post_story(post_id)
    except Exception as e:
        logger.exception("Failed to get post story")
        return {"success": False, "error": str(e), "stories": []}


@app.get("/api/posts/item/{post_id}/timeline")
async def get_post_timeline(post_id: str):
    """Get the post-centric story timeline view."""
    try:
        logger.info(f"🕰️ Fetching post timeline: {post_id}")
        return api_bridge.get_post_timeline(post_id, refresh=False)
    except Exception as e:
        logger.exception("Failed to get post timeline")
        return {"success": False, "error": str(e), "post_id": post_id, "timeline": None, "related_candidates": []}


@app.post("/api/posts/item/{post_id}/timeline/refresh")
async def refresh_post_timeline(post_id: str, request: PostTimelineRequest | None = None):
    """Refresh the candidate links and timeline for a single post."""
    try:
        logger.info(f"🕰️ Refreshing post timeline: {post_id}")
        payload = request.model_dump() if hasattr(request, "model_dump") else (request or {})
        return api_bridge.get_post_timeline(post_id, refresh=bool(payload.get("refresh", True) or True))
    except Exception as e:
        logger.exception("Failed to refresh post timeline")
        return {"success": False, "error": str(e), "post_id": post_id, "timeline": None, "related_candidates": []}


@app.post("/api/story-candidates/{candidate_id}/accept")
async def accept_story_candidate(candidate_id: str):
    """Accept one story candidate into the target story timeline."""
    try:
        logger.info(f"🕰️ Accepting story candidate: {candidate_id}")
        return api_bridge.accept_story_candidate(candidate_id)
    except Exception as e:
        logger.exception("Failed to accept story candidate")
        return {"success": False, "error": str(e), "candidate": None}


@app.post("/api/story-candidates/{candidate_id}/reject")
async def reject_story_candidate(candidate_id: str):
    """Reject one story candidate from the timeline."""
    try:
        logger.info(f"🕰️ Rejecting story candidate: {candidate_id}")
        return api_bridge.reject_story_candidate(candidate_id)
    except Exception as e:
        logger.exception("Failed to reject story candidate")
        return {"success": False, "error": str(e), "candidate": None}


@app.post("/api/events/rebuild-for-post")
async def rebuild_events_for_post(request: EventRebuildPostRequest):
    try:
        logger.info(f"🔄 Rebuilding event memory for post: {request.postId}")
        return api_bridge.rebuild_post_events(request.postId)
    except Exception as e:
        logger.exception("Failed to rebuild event memory for post")
        return {"success": False, "error": str(e)}


@app.post("/api/events/rebuild-for-date")
async def rebuild_events_for_date(request: EventRebuildDateRequest):
    try:
        logger.info(f"🔄 Rebuilding event memory for date: {request.date}")
        return api_bridge.rebuild_events_for_date(request.date, limit=request.limit)
    except Exception as e:
        logger.exception("Failed to rebuild event memory for date")
        return {"success": False, "error": str(e)}


@app.get("/api/stories")
async def get_stories(
    status: str | None = Query(default=None),
    story_kind: str | None = Query(default=None, alias="storyKind"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List persisted stories."""
    try:
        logger.info("📚 Fetching stories")
        return api_bridge.get_stories(
            status=status,
            story_kind=story_kind,
            limit=int(limit or 100),
            offset=int(offset or 0),
        )
    except Exception as e:
        logger.exception("Failed to get stories")
        return {"success": False, "error": str(e), "stories": [], "total": 0}


@app.get("/api/stories/{story_id}")
async def get_story(story_id: str):
    """Get a single story with attached evidence and updates."""
    try:
        logger.info(f"📚 Fetching story: {story_id}")
        return api_bridge.get_story(story_id)
    except Exception as e:
        logger.exception("Failed to get story")
        return {"success": False, "error": str(e), "story": None}


@app.get("/api/stories/{story_id}/timeline")
async def get_story_timeline(story_id: str):
    """Get a story timeline with update-level evidence."""
    try:
        logger.info(f"📚 Fetching story timeline: {story_id}")
        return api_bridge.get_story_timeline(story_id)
    except Exception as e:
        logger.exception("Failed to get story timeline")
        return {"success": False, "error": str(e), "story": None, "timeline": []}


@app.get("/api/inbox")
async def get_inbox(batchId: str | None = None, limit: int = 20):
    """Get the current inbox batch and its items."""
    try:
        logger.info("📥 Fetching inbox")
        return api_bridge.get_inbox(batch_id=batchId, limit=int(limit or 20))
    except Exception as e:
        logger.exception("Failed to get inbox")
        return {"success": False, "error": str(e), "batch": None, "items": [], "total": 0}


@app.get("/api/inbox/batches")
async def get_inbox_batches(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """List inbox batches."""
    try:
        logger.info("📥 Fetching inbox batches")
        return api_bridge.get_inbox_batches(limit=int(limit or 50), offset=int(offset or 0))
    except Exception as e:
        logger.exception("Failed to get inbox batches")
        return {"success": False, "error": str(e), "batches": [], "total": 0}


@app.get("/api/inbox/items")
async def get_inbox_items(
    batchId: str | None = None,
    status: str | None = None,
    targetType: str | None = None,
    sourceId: str | None = None,
    generatedForDate: str | None = None,
    limit: int = 100,
    offset: int = 0,
):
    """List inbox items with optional filters."""
    try:
        logger.info("📥 Fetching inbox items")
        return api_bridge.get_inbox_items(
            batch_id=batchId,
            status=status,
            target_type=targetType,
            source_id=sourceId,
            generated_for_date=generatedForDate,
            limit=int(limit or 100),
            offset=int(offset or 0),
        )
    except Exception as e:
        logger.exception("Failed to get inbox items")
        return {"success": False, "error": str(e), "items": [], "total": 0}


@app.get("/api/inbox/items/{item_id}")
async def get_inbox_item(item_id: str):
    """Get one inbox item with target detail and prior actions."""
    try:
        logger.info(f"📥 Fetching inbox item: {item_id}")
        return api_bridge.get_inbox_item(item_id)
    except Exception as e:
        logger.exception("Failed to get inbox item")
        return {"success": False, "error": str(e), "item": None, "target": None, "actions": []}


@app.post("/api/inbox/rebuild")
async def rebuild_inbox(request: InboxRebuildRequest | None = None):
    """Rebuild the analyst inbox queue."""
    try:
        logger.info("🔄 Rebuilding inbox")
        payload = request.model_dump() if hasattr(request, "model_dump") else (request or {})
        return api_bridge.rebuild_inbox(
            generated_for_date=payload.get("generatedForDate") or payload.get("generated_for_date"),
            scope_type=payload.get("scopeType") or payload.get("scope_type") or "daily_queue",
            scope_value=payload.get("scopeValue") or payload.get("scope_value"),
            limit=int(payload.get("limit") or 20),
            actor_id=payload.get("actorId") or payload.get("actor_id"),
        )
    except Exception as e:
        logger.exception("Failed to rebuild inbox")
        return {"success": False, "error": str(e), "batch": None, "items": [], "total": 0}


@app.post("/api/inbox/items/{item_id}/actions")
async def record_inbox_action(item_id: str, request: InboxActionRequest):
    """Record a durable analyst action for one inbox item."""
    try:
        logger.info(f"🧭 Recording inbox action for item: {item_id}")
        payload = request.model_dump() if hasattr(request, "model_dump") else (request or {})
        return api_bridge.record_inbox_action(
            item_id,
            payload.get("actionType") or payload.get("action_type"),
            actor_id=payload.get("actorId") or payload.get("actor_id"),
            payload=payload.get("payload"),
        )
    except Exception as e:
        logger.exception("Failed to record inbox action")
        return {"success": False, "error": str(e), "action": None, "item": None, "side_effects": []}


@app.get("/api/inbox/actions")
async def get_inbox_actions(
    limit: int = 100,
    offset: int = 0,
    targetType: str | None = None,
    targetId: str | None = None,
    inboxItemId: str | None = None,
):
    """List inbox action audit records."""
    try:
        logger.info("🧭 Fetching inbox actions")
        return api_bridge.get_inbox_actions(
            limit=int(limit or 100),
            offset=int(offset or 0),
            target_type=targetType,
            target_id=targetId,
            inbox_item_id=inboxItemId,
        )
    except Exception as e:
        logger.exception("Failed to get inbox actions")
        return {"success": False, "error": str(e), "actions": [], "total": 0}


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
async def get_post_summary(post_id: str, request: PostSummaryRequest, background_tasks: BackgroundTasks):
    try:
        logger.info(f"🧠 Generating summary for post: {post_id}")
        if request.asyncMode:
            job_id = api_bridge._start_job_safe(
                "post_analysis",
                trigger="manual",
                message=f"Generate summary for post {post_id}",
                payload={"post_id": post_id, "refresh": bool(request.refresh)},
            )
            if job_id:
                background_tasks.add_task(
                    _run_sync_job_background,
                    "post_analysis",
                    api_bridge.get_post_summary,
                    post_id,
                    refresh=bool(request.refresh),
                    job_id=job_id,
                )
                return _accepted_job_response(job_id, "post_analysis", message="Post summary generation started")
        return api_bridge.get_post_summary(post_id, refresh=bool(request.refresh))
    except Exception as e:
        logger.exception("Failed to get post summary")
        return {"success": False, "error": str(e), "post_id": post_id}


@app.post("/api/posts/item/{post_id}/chat")
async def chat_about_post(post_id: str, request: PostChatRequest, background_tasks: BackgroundTasks):
    try:
        logger.info(f"💬 Chat about post: {post_id}")
        if request.asyncMode:
            job_id = api_bridge._start_job_safe(
                "post_chat_message",
                trigger="manual",
                message=f"Chat about post {post_id}",
                payload={"post_id": post_id, "question_chars": len(request.question or "")},
            )
            if job_id:
                background_tasks.add_task(
                    _run_sync_job_background,
                    "post_chat_message",
                    api_bridge.chat_about_post,
                    post_id,
                    request.question,
                    job_id=job_id,
                )
                return _accepted_job_response(job_id, "post_chat_message", message="Post chat request started")
        return api_bridge.chat_about_post(post_id, request.question)
    except Exception as e:
        logger.exception("Failed to chat about post")
        return {"success": False, "error": str(e), "post_id": post_id}


@app.post("/api/posts/item/{post_id}/reddit-comments")
async def fetch_reddit_comments(post_id: str, request: PostCommentsRequest, background_tasks: BackgroundTasks):
    try:
        logger.info(f"💬 Fetching Reddit comments for post: {post_id}")
        if request.asyncMode:
            job_id = api_bridge._start_job_safe(
                "reddit_comments_fetch",
                trigger="manual",
                message=f"Fetch Reddit comments for {post_id}",
                payload={"post_id": post_id, "limit": int(request.limit or 80), "refresh": bool(request.refresh)},
            )
            if job_id:
                background_tasks.add_task(
                    _run_async_job_background,
                    "reddit_comments_fetch",
                    api_bridge.fetch_reddit_comments,
                    post_id,
                    limit=int(request.limit or 80),
                    refresh=bool(request.refresh),
                    job_id=job_id,
                )
                return _accepted_job_response(job_id, "reddit_comments_fetch", message="Reddit comment fetch started")
        return await api_bridge.fetch_reddit_comments(
            post_id,
            limit=int(request.limit or 80),
            refresh=bool(request.refresh),
        )
    except Exception as e:
        logger.exception("Failed to fetch Reddit comments")
        return {"success": False, "error": str(e), "post_id": post_id}


@app.post("/api/posts/item/{post_id}/reddit-comments/briefing")
async def get_reddit_comments_briefing(post_id: str, request: PostCommentsRequest, background_tasks: BackgroundTasks):
    try:
        logger.info(f"🧠 Generating Reddit comments briefing for post: {post_id}")
        if request.asyncMode:
            job_id = api_bridge._start_job_safe(
                "reddit_comments_briefing",
                trigger="manual",
                message=f"Generate Reddit comments briefing for {post_id}",
                payload={"post_id": post_id, "limit": int(request.limit or 80), "refresh": bool(request.refresh)},
            )
            if job_id:
                background_tasks.add_task(
                    _run_async_job_background,
                    "reddit_comments_briefing",
                    api_bridge.get_reddit_comments_briefing,
                    post_id,
                    limit=int(request.limit or 80),
                    refresh=bool(request.refresh),
                    job_id=job_id,
                )
                return _accepted_job_response(job_id, "reddit_comments_briefing", message="Reddit comments briefing started")
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
async def fetch_source_now(source_id: str, request: LiveFetchRequest, background_tasks: BackgroundTasks):
    """Fetch the latest posts for a single source immediately."""
    try:
        logger.info(f"⚡ Fetching source immediately: {source_id}")
        if request.asyncMode:
            job_id = api_bridge._start_job_safe(
                "fetch_source_now",
                trigger="manual",
                source_id=source_id,
                payload={"limit": request.limit},
            )
            if job_id:
                background_tasks.add_task(
                    _run_async_job_background,
                    "fetch_source_now",
                    api_bridge.fetch_source_now,
                    source_id,
                    request.limit,
                    job_id=job_id,
                )
                return _accepted_job_response(job_id, "fetch_source_now", message="Source fetch started")
        return await api_bridge.fetch_source_now(source_id, request.limit)
    except Exception as e:
        logger.exception(f"Failed to fetch source immediately: {source_id}")
        return {"success": False, "error": str(e), "source_id": source_id}


# Briefing generation endpoints


@app.post("/api/daily")
async def generate_daily_briefing(request: BriefingRequest, background_tasks: BackgroundTasks):
    try:
        date = request.date
        logger.info(f"🚀 Generating daily briefing for date: {date}")
        
        if not date:
            raise HTTPException(status_code=400, detail="Date parameter required")
        
        if request.asyncMode:
            if request.includeTopics:
                job_id = api_bridge._start_job_safe(
                    "topic_briefing",
                    trigger="manual",
                    message=f"Generate topic briefing for {date}",
                    payload={
                        "date": date,
                        "include_unreferenced": True if request.includeUnreferenced is None else request.includeUnreferenced,
                        "refresh": bool(request.refresh),
                    },
                )
                if job_id:
                    background_tasks.add_task(
                        _run_async_job_background,
                        "topic_briefing",
                        api_bridge.generate_daily_briefing_with_topics,
                        date,
                        include_unreferenced=True if request.includeUnreferenced is None else request.includeUnreferenced,
                        refresh=bool(request.refresh),
                        job_id=job_id,
                    )
                    return _accepted_job_response(job_id, "topic_briefing", message="Topic briefing generation started")
            else:
                job_id = api_bridge._start_job_safe(
                    "daily_briefing",
                    trigger="manual",
                    message=f"Generate daily briefing for {date}",
                    payload={"date": date},
                )
                if job_id:
                    background_tasks.add_task(
                        _run_async_job_background,
                        "daily_briefing",
                        api_bridge.generate_daily_briefing,
                        date,
                        job_id=job_id,
                    )
                    return _accepted_job_response(job_id, "daily_briefing", message="Daily briefing generation started")

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
            "posts": result.get("posts", []) if isinstance(result, dict) else [],
            "one_sentence_takeaway": result.get("one_sentence_takeaway") if isinstance(result, dict) else None,
            "references": result.get("references", []) if isinstance(result, dict) else [],
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
async def generate_daily_briefing_with_topics(request: BriefingRequest, background_tasks: BackgroundTasks):
    try:
        date = request.date
        logger.info(f"🚀 Generating topic-based daily briefing for date: {date}")
        if not date:
            raise HTTPException(status_code=400, detail="Date parameter required")

        if request.asyncMode:
            job_id = api_bridge._start_job_safe(
                "topic_briefing",
                trigger="manual",
                message=f"Generate topic briefing for {date}",
                payload={
                    "date": date,
                    "include_unreferenced": True if request.includeUnreferenced is None else request.includeUnreferenced,
                    "refresh": bool(request.refresh),
                },
            )
            if job_id:
                background_tasks.add_task(
                    _run_async_job_background,
                    "topic_briefing",
                    api_bridge.generate_daily_briefing_with_topics,
                    date,
                    include_unreferenced=True if request.includeUnreferenced is None else request.includeUnreferenced,
                    refresh=bool(request.refresh),
                    job_id=job_id,
                )
                return _accepted_job_response(job_id, "topic_briefing", message="Topic briefing generation started")

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
            "total_posts_fetched": result.get("total_posts_fetched", 0),
            "one_sentence_takeaway": result.get("one_sentence_takeaway"),
            "references": result.get("references", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate topic-based briefing: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/weekly")
async def generate_weekly_briefing(request: BriefingRequest, background_tasks: BackgroundTasks):
    try:
        date = request.date
        logger.info(f"🚀 Generating weekly briefing anchored at date: {date}")
        if not date:
            raise HTTPException(status_code=400, detail="Date parameter required")

        if request.asyncMode:
            if request.includeTopics:
                job_id = api_bridge._start_job_safe(
                    "weekly_topic_briefing",
                    trigger="manual",
                    message=f"Generate weekly topic briefing for {date}",
                    payload={"date": date, "refresh": bool(request.refresh)},
                )
                if job_id:
                    background_tasks.add_task(
                        _run_async_job_background,
                        "weekly_topic_briefing",
                        api_bridge.generate_weekly_topic_briefing,
                        date,
                        refresh=bool(request.refresh),
                        job_id=job_id,
                    )
                    return _accepted_job_response(job_id, "weekly_topic_briefing", message="Weekly topic briefing generation started")
            else:
                job_id = api_bridge._start_job_safe(
                    "weekly_briefing",
                    trigger="manual",
                    message=f"Generate weekly briefing for {date}",
                    payload={"date": date, "refresh": bool(request.refresh)},
                )
                if job_id:
                    background_tasks.add_task(
                        _run_async_job_background,
                        "weekly_briefing",
                        api_bridge.generate_weekly_briefing,
                        date,
                        refresh=bool(request.refresh),
                        job_id=job_id,
                    )
                    return _accepted_job_response(job_id, "weekly_briefing", message="Weekly briefing generation started")

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
            "one_sentence_takeaway": result.get("one_sentence_takeaway"),
            "references": result.get("references", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to generate weekly briefing: {e}")
        return {"success": False, "error": str(e)}


@app.get("/api/briefings/vertical/source/{source_id}")
async def get_source_vertical_briefing(
    source_id: str,
    background_tasks: BackgroundTasks,
    start: str | None = None,
    end: str | None = None,
    asyncMode: bool = Query(False),
):
    """Generate or fetch a cached source-scoped vertical briefing."""
    try:
        logger.info(f"🧭 Fetching vertical briefing for source {source_id}")
        if not start or not end:
            raise HTTPException(status_code=400, detail="Start and end parameters required")
        if asyncMode:
            job_id = api_bridge._start_job_safe(
                "vertical_briefing_source",
                trigger="manual",
                message=f"Generate vertical briefing for {source_id}",
                payload={
                    "source_id": source_id,
                    "start_date": start,
                    "end_date": end,
                    "refresh": False,
                },
            )
            if job_id:
                background_tasks.add_task(
                    _run_async_job_background,
                    "vertical_briefing_source",
                    api_bridge.generate_source_vertical_briefing,
                    source_id,
                    start,
                    end,
                    refresh=False,
                    job_id=job_id,
                )
                return _accepted_job_response(job_id, "vertical_briefing_source", message="Vertical briefing generation started")
        return await api_bridge.generate_source_vertical_briefing(source_id, start, end, refresh=False)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to get source vertical briefing")
        return {"success": False, "error": str(e), "vertical_briefing": "", "tracks": [], "posts": {}, "references": []}


@app.post("/api/briefings/vertical/source/{source_id}/refresh")
async def refresh_source_vertical_briefing(
    source_id: str,
    background_tasks: BackgroundTasks,
    start: str | None = None,
    end: str | None = None,
    asyncMode: bool = Query(False),
):
    """Force regeneration of a source-scoped vertical briefing."""
    try:
        logger.info(f"🔄 Refreshing vertical briefing for source {source_id}")
        if not start or not end:
            raise HTTPException(status_code=400, detail="Start and end parameters required")
        if asyncMode:
            job_id = api_bridge._start_job_safe(
                "vertical_briefing_source",
                trigger="manual",
                message=f"Generate vertical briefing for {source_id}",
                payload={
                    "source_id": source_id,
                    "start_date": start,
                    "end_date": end,
                    "refresh": True,
                },
            )
            if job_id:
                background_tasks.add_task(
                    _run_async_job_background,
                    "vertical_briefing_source",
                    api_bridge.generate_source_vertical_briefing,
                    source_id,
                    start,
                    end,
                    refresh=True,
                    job_id=job_id,
                )
                return _accepted_job_response(job_id, "vertical_briefing_source", message="Vertical briefing refresh started")
        return await api_bridge.generate_source_vertical_briefing(source_id, start, end, refresh=True)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to refresh source vertical briefing")
        return {"success": False, "error": str(e), "vertical_briefing": "", "tracks": [], "posts": {}, "references": []}

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
