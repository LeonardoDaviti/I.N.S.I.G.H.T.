import logging
import math
import os
import asyncio
import uuid
from typing import List, Dict, Any

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from insight_api_bridge import InsightApiBridge
from insight_core.db.repo_reader import FEED_FILTERS, FEED_VIEWS, FeedCursor, FeedScope
from insight_core.ingestion.types import FetchRequest, SourceSelector, Trigger
from insight_core.services.credentials_service import CredentialInvalid, CredentialNotFound, LoginFailed
from insight_core.services.media_proxy_service import MediaFetchFailed, MediaNotAllowed, MediaProxyService
from insight_core.services.operations_service import (
    CADENCE_OVERRIDE_MAX_HOURS,
    CADENCE_OVERRIDE_MIN_HOURS,
    EMPTY_SOURCE_HEALTH,
)

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
media_proxy = MediaProxyService(api_bridge.db)

# Request models
class CorpusStatus(BaseModel):
    total_posts: int = 0
    enabled_sources: int = 0
    total_sources: int = 0
    latest_post_at: str | None = None
    oldest_post_at: str | None = None
    latest_fetch_at: str | None = None
    posts_last_24h: int = 0


class FolderStatus(BaseModel):
    id: str
    name: str
    source_count: int = 0
    post_count: int = 0


class JobStatus(BaseModel):
    id: str
    job_type: str
    status: str
    started_at: str | None = None
    finished_at: str | None = None
    message: str | None = None


class SystemStatus(BaseModel):
    success: bool = True
    healthy: bool = True
    generated_at: str
    corpus: CorpusStatus
    scheduler: Dict[str, Any] = {}
    folders: List[FolderStatus] = []
    recent_jobs: List[JobStatus] = []
    source_health_summary: Dict[str, int] = {}


class ArchiveRequest(BaseModel):
    desiredPosts: int | None = None
    resume: bool | None = True
    pageDelaySeconds: int | None = None
    batchSize: int | None = None
    batchCooldownSeconds: int | None = None
    # True: start an archive_source job and answer 202 at once (the source sheet polls
    # the job). False keeps the old synchronous answer for the Mark VIII archive tab.
    background: bool = False


class YouTubeChannelRequest(BaseModel):
    source: str
    limit: int | None = None


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


class CadenceOverrideRequest(BaseModel):
    override_hours: float | None = None   # null clears the override


class IngestionRunRequest(BaseModel):
    force: bool | None = False


class SchedulerConfigRequest(BaseModel):
    intervalHours: float | None = None
    syncSourcesEachCycle: bool | None = None
    ingestTickMinutes: float | None = None


class PostReaderSessionRequest(BaseModel):
    durationSeconds: int
    metadata: Dict[str, Any] | None = None


class PostFavoriteRequest(BaseModel):
    favorited: bool


class PostReadRequest(BaseModel):
    read: bool


class FeedReadRequest(BaseModel):
    ids: List[str]
    read: bool


class FeedMarkReadRequest(BaseModel):
    scope: str = "all"
    through_cursor: str
    newest_cursor: str


class PostOpenRequest(BaseModel):
    metadata: Dict[str, Any] | None = None


class PostCommentsRequest(BaseModel):
    limit: int | None = 80
    refresh: bool | None = False
    asyncMode: bool | None = False


async def _run_async_job_background(task_name: str, fn, *args, **kwargs):
    try:
        await fn(*args, **kwargs)
    except Exception:
        logger.exception("Background async job failed: %s", task_name)


def _accepted_job_response(job_id: str, job_type: str, *, message: str | None = None) -> Dict[str, Any]:
    return {
        "success": True,
        "accepted": True,
        "job_id": job_id,
        "job_type": job_type,
        "status": "running",
        "message": message or f"{job_type} started",
    }

def _accept_ingestion_run(
    background_tasks: BackgroundTasks,
    request: FetchRequest,
    run,
    *args,
    message: str,
    source_id: str | None = None,
) -> JSONResponse:
    """Start an ingestion_run job and run it in the background (spec §A.5).

    Async-only: when the job cannot be tracked the run does not happen (503) - a manual
    fetch must never run synchronously inside the request again.
    """
    job_id = api_bridge._start_job_safe(
        "ingestion_run",
        trigger="manual",
        source_id=source_id,
        message=message,
        payload={"selector": request.selector.as_dict(), "force": request.force, "limit": request.limit},
    )
    if not job_id:
        return JSONResponse(status_code=503, content={"success": False, "error": "job tracking unavailable"})
    background_tasks.add_task(_run_async_job_background, "ingestion_run", run, *args, job_id=job_id)
    return JSONResponse(
        status_code=202,
        content={"success": True, "accepted": True, "job_id": job_id, "job_type": "ingestion_run",
                 "status": "running", "message": message},
    )


# Sources with an archive running in this process. One uvicorn worker runs every background
# job, so a set is the whole truth; a restart empties it, as it ends the runs it tracked.
_archiving_sources: set[str] = set()


async def _run_archive_once(source_id: str, *args, **kwargs):
    try:
        await _run_async_job_background("archive_source", api_bridge.run_archive, source_id, *args, **kwargs)
    finally:
        _archiving_sources.discard(source_id)


def _accept_archive_run(
    background_tasks: BackgroundTasks,
    source_id: str,
    request: "ArchiveRequest",
    rate_limit_overrides: Dict[str, Any],
) -> JSONResponse:
    """Start an archive_source job and run the archive in the background.

    A source that cannot archive (kind unavailable, a feed with nothing older) is 409
    before any job exists; untracked jobs never run (503), like a manual fetch.
    """
    try:
        support = api_bridge.archive_support(source_id)
    except Exception as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    if not support.get("archivable"):
        reason = support.get("reason") or "This source cannot archive"
        return JSONResponse(status_code=409, content={"success": False, "detail": reason, "error": reason,
                                                      "unavailable": bool(support.get("unavailable"))})
    if source_id in _archiving_sources:
        reason = "An archive of this source is already running"
        return JSONResponse(status_code=409, content={"success": False, "detail": reason, "error": reason})
    resume = bool(request.resume)
    job_id = api_bridge._start_job_safe(
        "archive_source",
        trigger="manual",
        source_id=source_id,
        message="Archive",
        payload={"desired_posts": request.desiredPosts, "resume": resume, "rate_limit": rate_limit_overrides},
    )
    if not job_id:
        return JSONResponse(status_code=503, content={"success": False, "error": "job tracking unavailable"})
    _archiving_sources.add(source_id)
    background_tasks.add_task(
        _run_archive_once, source_id, request.desiredPosts,
        resume=resume, rate_limit_overrides=rate_limit_overrides, job_id=job_id,
    )
    return JSONResponse(status_code=202, content=_accepted_job_response(job_id, "archive_source", message="Archive started"))


def _unavailable_or(result: Any) -> Any:
    """409 for an archive request on a kind this process cannot fetch (E7)."""
    if isinstance(result, dict) and result.get("unavailable"):
        return JSONResponse(status_code=409, content={"success": False, "detail": result.get("error"),
                                                      "error": result.get("error")})
    return result


@app.get("/")
async def root():
    return {
        "message": "INSIGHT Intelligence Platform API", 
        "version": "1.0.0",
        "engine": "DB-backed Archive Engine",
        "status": "operational"
    }

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
async def get_posts_by_source(
    source_id: str,
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Get posts for a specific source."""
    try:
        logger.info(f"📋 Fetching posts for source: {source_id}")

        result = api_bridge.get_posts_by_source(source_id, limit=limit, offset=offset)
        
        # Log success
        if result.get("success"):
            logger.info(
                "✅ Retrieved %s posts for source %s (offset=%s total=%s)",
                result.get("returned", len(result.get("posts") or [])),
                source_id,
                result.get("offset", offset),
                result.get("total", 0),
            )
        
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
        return {"success": False, "error": str(e), "post": None, "reader_state": None}


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


# ============= READER (Mark IX) =============
# New endpoints follow the §4 error contract: non-2xx with {"detail": "<human message>"}.

MAX_FEED_LIMIT = 100
MAX_READ_BATCH = 500


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


def _server_error(what: str) -> HTTPException:
    # The exception is logged, never echoed: driver messages can carry DSNs and SQL.
    logger.exception("Endpoint failed: %s", what)
    return HTTPException(status_code=500, detail=f"Could not {what}. Check the backend logs.")


def _require_post_ids(ids: List[str]) -> List[str]:
    if len(ids) > MAX_READ_BATCH:
        raise ValueError(f"at most {MAX_READ_BATCH} ids per request")
    try:
        return [str(uuid.UUID(str(pid))) for pid in ids]
    except ValueError:
        raise ValueError("ids must be post UUIDs") from None


@app.get("/api/feed")
async def get_feed(scope: str = "all", filter: str = "all", view: str = "stream",
                   cursor: str | None = None, limit: int = 30, days: int | None = None):
    """Keyset-paginated, newest-first feed: FeedPage (stream) or FeedGroupsPage (by_source)."""
    try:
        feed_scope = FeedScope.parse(scope)
        if filter not in FEED_FILTERS:
            raise ValueError(f"filter must be one of {', '.join(FEED_FILTERS)}")
        if view not in FEED_VIEWS:
            raise ValueError(f"view must be one of {', '.join(FEED_VIEWS)}")
        if not 1 <= int(limit) <= MAX_FEED_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_FEED_LIMIT}")
        if days is not None and int(days) < 1:
            raise ValueError("days must be at least 1")
        feed_cursor = FeedCursor.decode(cursor) if cursor else None
    except ValueError as exc:
        raise _bad_request(exc)
    try:
        return api_bridge.get_feed(feed_scope, filter=filter, view=view, cursor=feed_cursor,
                                   limit=int(limit), days=days)
    except ValueError as exc:
        raise _bad_request(exc)
    except Exception:
        raise _server_error("load the feed")


@app.get("/api/feed/unread-counts")
async def get_feed_unread_counts():
    try:
        return api_bridge.get_unread_counts()
    except Exception:
        raise _server_error("load unread counts")


# An image is served with the headers a stranger's file needs on our origin: no sniffing,
# and an SVG opened on its own can run nothing.
_MEDIA_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
}


@app.get("/api/media")
async def get_media(post: str, url: str):
    """One image of one post, fetched now (issue 0006). Not stored: the frontend nginx caches
    it for 24 hours and the browser as long. 404: not an image of this post or not a host we
    fetch from; 502: the origin failed. Failures are cached for 10 minutes."""
    try:
        image = await asyncio.to_thread(media_proxy.fetch, post, url)
    except MediaNotAllowed:
        return Response(status_code=404, headers={**_MEDIA_HEADERS, "Cache-Control": "public, max-age=600"})
    except MediaFetchFailed as exc:
        logger.info("Media proxy: %s for post %s", exc, post)
        return Response(status_code=502, headers={**_MEDIA_HEADERS, "Cache-Control": "public, max-age=600"})
    return Response(content=image.body, media_type=image.content_type,
                    headers={**_MEDIA_HEADERS, "Cache-Control": "public, max-age=86400"})


@app.post("/api/feed/mark-read")
async def mark_feed_read(request: FeedMarkReadRequest):
    """Mark all read from newest_cursor down to through_cursor, bounded by the unread window."""
    try:
        scope = FeedScope.parse(request.scope)
        through = FeedCursor.decode(request.through_cursor)
        newest = FeedCursor.decode(request.newest_cursor)
    except ValueError as exc:
        raise _bad_request(exc)
    try:
        return api_bridge.mark_read_through(scope, through, newest)
    except Exception:
        raise _server_error("mark posts read")


@app.put("/api/feed/read")
async def set_feed_read(request: FeedReadRequest):
    """Batch read/unread (the mark-through Undo)."""
    try:
        ids = _require_post_ids(request.ids)
    except ValueError as exc:
        raise _bad_request(exc)
    try:
        return api_bridge.set_posts_read(ids, bool(request.read))
    except Exception:
        raise _server_error("update read state")


@app.put("/api/posts/item/{post_id}/read")
async def set_post_read(post_id: str, request: PostReadRequest):
    try:
        (post_id,) = _require_post_ids([post_id])
    except ValueError as exc:
        raise _bad_request(exc)
    try:
        return api_bridge.set_post_read(post_id, bool(request.read))
    except Exception:
        raise _server_error("update read state")


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


# ============= FOLDERS ENDPOINTS =============


@app.get("/api/folders")
async def get_folders():
    """List folders with source and post counts."""
    try:
        logger.info("📁 Fetching folders")
        return api_bridge.get_folders()
    except Exception as e:
        logger.exception("Failed to get folders")
        return {"success": False, "error": str(e), "folders": []}


@app.post("/api/folders")
async def create_folder(config: dict):
    """Create a folder or track.

    Body: {name, description?, sort_order?, kind?, exclude_from_main_digest?, match_keywords?}
    kind is "folder" (default) or "track".
    """
    try:
        logger.info("📁 Creating folder")
        return api_bridge.create_folder(config)
    except Exception as e:
        logger.exception("Failed to create folder")
        return {"success": False, "error": str(e), "folder": None}


@app.put("/api/folders/{folder_id}")
async def update_folder(folder_id: str, fields: dict):
    """Update folder fields.

    Body: any of {name, description, sort_order, kind, exclude_from_main_digest, match_keywords}
    """
    try:
        logger.info(f"📁 Updating folder: {folder_id}")
        return api_bridge.update_folder(folder_id, fields)
    except Exception as e:
        logger.exception("Failed to update folder")
        return {"success": False, "error": str(e), "folder": None}


@app.delete("/api/folders/{folder_id}")
async def delete_folder(folder_id: str):
    """Delete a folder."""
    try:
        logger.info(f"📁 Deleting folder: {folder_id}")
        return api_bridge.delete_folder(folder_id)
    except Exception as e:
        logger.exception("Failed to delete folder")
        return {"success": False, "error": str(e)}


@app.get("/api/folders/{folder_id}/sources")
async def get_folder_sources(folder_id: str):
    """List the sources attached to a folder."""
    try:
        logger.info(f"📁 Fetching sources for folder: {folder_id}")
        return api_bridge.get_folder_sources(folder_id)
    except Exception as e:
        logger.exception("Failed to get folder sources")
        return {"success": False, "error": str(e), "sources": []}


@app.post("/api/folders/{folder_id}/sources")
async def add_folder_source(folder_id: str, body: dict):
    """Attach a source to a folder. Body: {source_id}"""
    try:
        source_id = str(body.get("source_id") or "").strip()
        if not source_id:
            return {"success": False, "error": "source_id is required"}
        logger.info(f"📁 Adding source {source_id} to folder {folder_id}")
        return api_bridge.add_source_to_folder(folder_id, source_id)
    except Exception as e:
        logger.exception("Failed to add source to folder")
        return {"success": False, "error": str(e)}


@app.post("/api/folders/{folder_id}/ingest")
async def ingest_folder(folder_id: str, background_tasks: BackgroundTasks, body: dict | None = None):
    """Fetch every enabled source in a folder/track now (forced). Body: {limit?: int}.

    Returns 202 with the ingestion_run job; poll /api/operations/jobs/{id} for the run report.
    Politeness comes from the source kinds' profiles and the host floors, not a delay knob.
    """
    limit = (body or {}).get("limit")
    request = FetchRequest(SourceSelector.folder(folder_id), Trigger.MANUAL, force=True, limit=limit)
    return _accept_ingestion_run(background_tasks, request, api_bridge.ingest_folder_now, folder_id, limit,
                                 message=f"Fetch track {folder_id}")


@app.get("/api/folders/{folder_id}/posts")
async def get_folder_posts(
    folder_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    days: int | None = Query(None, ge=1, le=365),
):
    """Reading feed for a folder/track: newest posts from its sources, newest first."""
    try:
        logger.info(f"\U0001F4D6 Folder feed {folder_id} limit={limit} offset={offset} days={days}")
        return api_bridge.get_folder_posts(folder_id, limit=limit, offset=offset, since_days=days)
    except Exception as e:
        logger.exception("Failed to load folder feed")
        return {"success": False, "error": str(e), "posts": []}


@app.put("/api/sources/{source_id}/main-digest")
async def set_source_main_digest(source_id: str, body: dict):
    """Include/exclude one source from the main digests. Body: {in_main_digest: bool}"""
    try:
        value = bool(body.get("in_main_digest", True))
        logger.info(f"\U0001F5DE Source {source_id} -> in_main_digest={value}")
        return api_bridge.set_source_main_digest(source_id, value)
    except Exception as e:
        logger.exception("Failed to set source main-digest flag")
        return {"success": False, "error": str(e)}


@app.put("/api/folders/{folder_id}/main-digest")
async def set_folder_main_digest(folder_id: str, body: dict):
    """Apply the digest switch to every source in a folder/track.

    Body: {in_main_digest: bool}. Sending false keeps a track's sources out of the "all"
    feed while they are still ingested.
    """
    try:
        value = bool(body.get("in_main_digest", True))
        logger.info(f"\U0001F5DE Folder {folder_id} -> in_main_digest={value}")
        return api_bridge.set_folder_main_digest(folder_id, value)
    except Exception as e:
        logger.exception("Failed to set folder main-digest flag")
        return {"success": False, "error": str(e)}


@app.delete("/api/folders/{folder_id}/sources/{source_id}")
async def remove_folder_source(folder_id: str, source_id: str):
    """Detach a source from a folder."""
    try:
        logger.info(f"📁 Removing source {source_id} from folder {folder_id}")
        return api_bridge.remove_source_from_folder(folder_id, source_id)
    except Exception as e:
        logger.exception("Failed to remove source from folder")
        return {"success": False, "error": str(e)}


@app.post("/api/sources/add")
async def add_single_source(body: dict):
    """Add one source (non-destructive). Body: {platform, handle_or_url, display_name?, fetch_delay_seconds?, priority?, max_posts_per_fetch?, state?}"""
    try:
        platform = str(body.get("platform") or "rss").strip()
        handle = str(body.get("handle_or_url") or "").strip()
        if not handle:
            return {"success": False, "error": "handle_or_url is required"}
        settings = {
            k: body[k]
            for k in ("display_name", "fetch_delay_seconds", "priority", "max_posts_per_fetch")
            if body.get(k) is not None
        }
        enabled = str(body.get("state") or "enabled") == "enabled"
        logger.info(f"➕ Adding source {platform}/{handle}")
        return api_bridge.add_source_with_settings(platform, handle, settings or None, enabled)
    except Exception as e:
        logger.exception("Failed to add source")
        return {"success": False, "error": str(e)}


@app.put("/api/sources/{source_id}/enabled")
async def set_source_enabled(source_id: str, body: dict):
    """Enable/disable a source. Body: {enabled: bool}"""
    try:
        return api_bridge.set_source_enabled(source_id, bool(body.get("enabled")))
    except Exception as e:
        logger.exception("Failed to set source enabled")
        return {"success": False, "error": str(e)}


@app.delete("/api/sources/{source_id}")
async def delete_single_source(source_id: str):
    """Delete a single source (and its posts)."""
    try:
        logger.info(f"🗑️ Deleting source {source_id}")
        return api_bridge.delete_source_api(source_id)
    except Exception as e:
        logger.exception("Failed to delete source")
        return {"success": False, "error": str(e)}


@app.get("/api/sources/{source_id}/folders")
async def get_source_folders(source_id: str):
    """List the folder ids a source belongs to."""
    try:
        return api_bridge.get_source_folders(source_id)
    except Exception as e:
        logger.exception("Failed to get source folders")
        return {"success": False, "error": str(e), "folder_ids": []}


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
        return _unavailable_or(await api_bridge.get_archive_plan(
            source_id,
            request.desiredPosts,
            resume=bool(request.resume),
            rate_limit_overrides={
                "page_delay_seconds": request.pageDelaySeconds,
                "batch_size": request.batchSize,
                "batch_cooldown_seconds": request.batchCooldownSeconds,
            },
        ))
    except Exception as e:
        logger.exception(f"Failed to plan archive for {source_id}")
        return {"success": False, "error": str(e)}


@app.post("/api/archive/{source_id}/run")
async def run_archive(source_id: str, request: ArchiveRequest, background_tasks: BackgroundTasks):
    """Run an archive job for a single source (202 + archive_source job when background)."""
    rate_limit_overrides = {
        "page_delay_seconds": request.pageDelaySeconds,
        "batch_size": request.batchSize,
        "batch_cooldown_seconds": request.batchCooldownSeconds,
    }
    if request.background:
        return _accept_archive_run(background_tasks, source_id, request, rate_limit_overrides)
    try:
        logger.info(f"📦 Running archive for source: {source_id}")
        return _unavailable_or(await api_bridge.run_archive(
            source_id,
            request.desiredPosts,
            resume=bool(request.resume),
            rate_limit_overrides=rate_limit_overrides,
        ))
    except Exception as e:
        logger.exception(f"Failed to run archive for {source_id}")
        return {"success": False, "error": str(e)}


@app.post("/api/sources/{source_id}/fetch-now")
async def fetch_source_now(source_id: str, request: LiveFetchRequest, background_tasks: BackgroundTasks):
    """Fetch one source now (forced, even when disabled). 202 + ingestion_run job."""
    fetch = FetchRequest(SourceSelector.source(source_id), Trigger.MANUAL, force=True, limit=request.limit)
    return _accept_ingestion_run(background_tasks, fetch, api_bridge.fetch_source_now, source_id, request.limit,
                                 message=f"Fetch source {source_id}", source_id=source_id)


@app.get("/api/sources/health")
async def get_sources_health():
    """SourcesHealthResponse: every source's schedule (decide_fetch preview) + a summary."""
    try:
        return api_bridge.get_sources_health()
    except Exception:
        raise _server_error("load source health")


@app.put("/api/sources/{source_id}/cadence")
async def set_source_cadence(source_id: str, request: CadenceOverrideRequest):
    """Set (or clear, with null) a source's fetch interval override, in hours [1, 2160]."""
    hours = request.override_hours
    if hours is not None and not (
        math.isfinite(hours) and CADENCE_OVERRIDE_MIN_HOURS <= hours <= CADENCE_OVERRIDE_MAX_HOURS
    ):
        raise HTTPException(
            status_code=400,
            detail=f"override_hours must be null or between {CADENCE_OVERRIDE_MIN_HOURS:g} "
                   f"and {CADENCE_OVERRIDE_MAX_HOURS:g}",
        )
    try:
        return api_bridge.set_cadence_override(source_id, hours)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception:
        raise _server_error("set the cadence override")


# ============= CONNECTIONS (credentials, Mark IX §10.1) =============
# Write-only: no route returns a stored value, a ciphertext or a Telegram session, and none
# logs a request body. Request fields are typed Any so a malformed body is rejected by the
# service with a message that never echoes it (a 422 would).


class CredentialValueRequest(BaseModel):
    value: Any = None


class TelegramLoginStartRequest(BaseModel):
    phone: Any = None


class TelegramLoginCodeRequest(BaseModel):
    code: Any = None


class TelegramLoginPasswordRequest(BaseModel):
    password: Any = None


def _credential_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CredentialNotFound):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, CredentialInvalid):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, LoginFailed):
        if exc.retry_after:
            return HTTPException(status_code=429, detail=exc.message,
                                 headers={"Retry-After": str(exc.retry_after)})
        return HTTPException(status_code=400, detail=exc.message)
    return _server_error("update the connection")


_CREDENTIAL_ERRORS = (CredentialNotFound, CredentialInvalid, LoginFailed)


@app.get("/api/credentials")
async def get_credentials():
    """Every connection: per field {set, last4, updated_at, source}, the last test, sign-in stage."""
    try:
        return api_bridge.get_credentials()
    except Exception:
        raise _server_error("load the connections")


@app.put("/api/credentials/{provider}/{key}")
async def put_credential(provider: str, key: str, request: CredentialValueRequest):
    try:
        return api_bridge.put_credential(provider, key, request.value)
    except _CREDENTIAL_ERRORS as exc:
        raise _credential_error(exc)
    except Exception:
        raise _server_error("save the connection")


@app.delete("/api/credentials/{provider}/{key}")
async def delete_credential(provider: str, key: str):
    try:
        return api_bridge.delete_credential(provider, key)
    except _CREDENTIAL_ERRORS as exc:
        raise _credential_error(exc)
    except Exception:
        raise _server_error("remove the connection")


@app.post("/api/credentials/{provider}/test")
async def test_credential(provider: str):
    try:
        return await api_bridge.test_credentials(provider)
    except _CREDENTIAL_ERRORS as exc:
        raise _credential_error(exc)
    except Exception:
        raise _server_error("test the connection")


@app.post("/api/credentials/telegram/login/start")
async def telegram_login_start(request: TelegramLoginStartRequest):
    """Send the login code to the phone. -> {stage: "code"}"""
    try:
        return await api_bridge.telegram_login_start(request.phone)
    except _CREDENTIAL_ERRORS as exc:
        raise _credential_error(exc)
    except Exception:
        raise _server_error("start the Telegram sign-in")


@app.post("/api/credentials/telegram/login/code")
async def telegram_login_code(request: TelegramLoginCodeRequest):
    """-> {stage: "password"} (two-step verification) or {stage: "done", account}"""
    try:
        return await api_bridge.telegram_login_code(request.code)
    except _CREDENTIAL_ERRORS as exc:
        raise _credential_error(exc)
    except Exception:
        raise _server_error("check the Telegram code")


@app.post("/api/credentials/telegram/login/password")
async def telegram_login_password(request: TelegramLoginPasswordRequest):
    """-> {stage: "done", account}"""
    try:
        return await api_bridge.telegram_login_password(request.password)
    except _CREDENTIAL_ERRORS as exc:
        raise _credential_error(exc)
    except Exception:
        raise _server_error("check the Telegram password")


@app.post("/api/credentials/telegram/login/cancel")
async def telegram_login_cancel():
    return api_bridge.telegram_login_cancel()


@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring"""
    import time
    return {
        "status": "healthy",
        "engine": "DB-backed Archive Engine",
        "timestamp": str(time.time())
    }


@app.get("/api/status", response_model=SystemStatus)
async def get_status():
    """Unified machine-readable system state: corpus freshness, sources, folders,
    scheduler config, and recent jobs.
    Designed as the single read an agent makes to understand the whole system."""
    try:
        return api_bridge.get_status()
    except Exception as e:
        logger.exception("Failed to build system status")
        raise HTTPException(status_code=500, detail=str(e))


# ============= INGESTION ENDPOINTS =============

@app.post("/api/ingestion/run")
async def run_ingestion_cycle(background_tasks: BackgroundTasks, request: IngestionRunRequest | None = None):
    """The manual "Run cycle": every enabled source; due ones only unless force. 202 + job."""
    force = bool(request.force) if request else False
    fetch = FetchRequest(SourceSelector.all(), Trigger.MANUAL, force=force)
    return _accept_ingestion_run(background_tasks, fetch, api_bridge.run_ingestion_cycle, force,
                                 message="Forced ingestion cycle" if force else "Ingestion cycle")


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
        return {"success": False, "error": str(e), "jobs": [], "source_health": EMPTY_SOURCE_HEALTH, "alerts": []}


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
        if request.ingestTickMinutes is not None:
            if request.ingestTickMinutes < 15:
                raise HTTPException(status_code=400, detail="ingestTickMinutes must be at least 15")
            payload["ingest_tick_minutes"] = request.ingestTickMinutes
        return api_bridge.update_scheduler_config(payload)
    except HTTPException:
        raise
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
