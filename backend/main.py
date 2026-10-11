import logging
import math
import os
import asyncio
import re
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from insight_core.db.repo_reader import FEED_FILTERS, FEED_VIEWS, FeedCursor, FeedScope
from insight_core.ingestion import run_ingestion
from insight_core.ingestion.kinds.base import KindUnavailable
from insight_core.ingestion.ports import JobProgressSink
from insight_core.ingestion.types import FetchRequest, SourceSelector, Trigger
from insight_core.services.credentials_service import LoginFailed
from insight_core.services.media_proxy_service import MediaFetchFailed, MediaNotAllowed
from insight_core.services.operations_service import (
    CADENCE_OVERRIDE_MAX_HOURS,
    CADENCE_OVERRIDE_MIN_HOURS,
    EMPTY_SOURCE_HEALTH,
    sources_failing,
)
from insight_core.services.registry import services

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    services()  # build the services at boot, so a bad configuration fails here
    yield


app = FastAPI(
    title="INSIGHT Intelligence Platform API",
    description="Backend API for the INSIGHT Mark I Foundation Engine",
    version="1.0.0",
    lifespan=lifespan,
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


# ============= ERRORS =============
# Routes call the services and let errors rise. One handler turns a service error into a
# safe JSON answer: the service's own message for errors the caller can act on (a
# ValueError, a not-found LookupError, a failed Telegram sign-in), and "Could not <what>"
# for anything else. That exception is logged, never echoed: driver messages can carry
# DSNs and SQL.
#
# Each route keeps the error shape its callers know:
#   - @error_detail (the Mark IX routes, and the default): an HTTP error {"detail": message},
#     400 for a ValueError, 404 for not found, 429 for a throttled sign-in, 500 otherwise;
#   - @error_envelope (the Mark VIII routes): HTTP 200 {"success": false, "error": message,
#     **fields}, with the same empty fields as their success answer.


@dataclass(frozen=True)
class ErrorShape:
    what: str
    envelope: Optional[Dict[str, Any]] = None   # None: an HTTP error with {"detail"}


DEFAULT_ERROR_SHAPE = ErrorShape("complete the request")


def error_detail(what: str):
    def mark(endpoint):
        endpoint.error_shape = ErrorShape(what)
        return endpoint
    return mark


def error_envelope(what: str, **fields: Any):
    """Values that are callables are called with the request (to echo a path parameter)."""
    def mark(endpoint):
        endpoint.error_shape = ErrorShape(what, fields)
        return endpoint
    return mark


def _path(name: str) -> Callable[[Request], Any]:
    return lambda request: request.path_params.get(name)


_DATABASE_URL = re.compile(r"postgres(?:ql)?(?:\+\w+)?://\S*", re.IGNORECASE)


def _known_error(exc: Exception) -> Optional[tuple[int, str, Dict[str, str]]]:
    """(status, message, headers) for an error the caller can act on; None for anything else."""
    if isinstance(exc, LoginFailed):
        if exc.retry_after:
            return 429, exc.message, {"Retry-After": str(exc.retry_after)}
        return 400, exc.message, {}
    if isinstance(exc, LookupError) and not isinstance(exc, (KeyError, IndexError)):
        return 404, str(exc), {}
    if isinstance(exc, ValueError):
        return 400, str(exc), {}
    return None


def service_error_response(request: Request, exc: Exception, shape: ErrorShape) -> JSONResponse:
    """The one error handler: a service error as a safe JSON answer in the route's shape."""
    known = _known_error(exc)
    if known is None:
        logger.error("%s %s failed", request.method, request.url.path, exc_info=exc)
        status, message, headers = 500, f"Could not {shape.what}. Check the backend logs.", {}
    else:
        status, message, headers = known
        message = _DATABASE_URL.sub("<database url>", message)
    if shape.envelope is None:
        return JSONResponse(status_code=status, content={"detail": message}, headers=headers or None)
    fields = {key: value(request) if callable(value) else value for key, value in shape.envelope.items()}
    return JSONResponse(status_code=200, content={"success": False, "error": message, **fields})


class ServiceRoute(APIRoute):
    """Every route answers its errors through service_error_response. HTTPException and
    request validation keep FastAPI's own handlers.

    (A route-level wrapper rather than app.exception_handler(Exception): Starlette runs an
    Exception handler outside the CORS middleware and re-raises after it.)"""

    def get_route_handler(self):
        handle = super().get_route_handler()
        shape = getattr(self.endpoint, "error_shape", DEFAULT_ERROR_SHAPE)

        async def route_handler(request: Request):
            try:
                return await handle(request)
            except (StarletteHTTPException, RequestValidationError):
                raise
            except Exception as exc:
                return service_error_response(request, exc, shape)

        return route_handler


app.router.route_class = ServiceRoute

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



# ============= JOBS =============
# Work that outlives the request runs as a background task with a job_runs row the frontend
# polls. A job row that cannot be written is logged (OperationsService.try_*); an untracked
# manual fetch or archive never starts (503).


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


async def _run_ingestion_job(request: FetchRequest, *, job_id: str | None = None) -> Dict[str, Any]:
    """run_ingestion with job progress; the job is finished in every case. Returns the report payload."""
    ops = services().operations
    status, message, payload = "failed", "Ingestion run did not finish", {}
    try:
        report = await run_ingestion(request, progress=JobProgressSink(ops, job_id))
        status, message, payload = report.job_status, report.summary_line(), report.to_payload()
        return payload
    except Exception as e:
        logger.exception("Ingestion run failed")
        message = f"Ingestion run failed: {e}"
        payload = {"success": False, "error": str(e), "selector": request.selector.as_dict()}
        return payload
    finally:
        ops.try_finish_job(job_id, status=status, message=message, payload=payload, compact=True)


def _accept_ingestion_run(
    background_tasks: BackgroundTasks,
    request: FetchRequest,
    *,
    message: str,
    source_id: str | None = None,
) -> JSONResponse:
    """Start an ingestion_run job and run it in the background (spec §A.5).

    Async-only: when the job cannot be tracked the run does not happen (503) - a manual
    fetch must never run synchronously inside the request again.
    """
    job_id = services().operations.try_start_job(
        "ingestion_run",
        trigger="manual",
        source_id=source_id,
        message=message,
        payload={"selector": request.selector.as_dict(), "force": request.force, "limit": request.limit},
    )
    if not job_id:
        return JSONResponse(status_code=503, content={"success": False, "error": "job tracking unavailable"})
    background_tasks.add_task(_run_async_job_background, "ingestion_run", _run_ingestion_job, request, job_id=job_id)
    return JSONResponse(
        status_code=202,
        content={"success": True, "accepted": True, "job_id": job_id, "job_type": "ingestion_run",
                 "status": "running", "message": message},
    )


async def _run_archive(
    source_id: str,
    desired_posts: int | None = None,
    *,
    resume: bool = True,
    rate_limit_overrides: Dict[str, Any] | None = None,
    job_id: str | None = None,
) -> Dict[str, Any]:
    """Archive posts for a single source into the shared posts table.

    With job_id (the route already started the job) progress lands on that job; otherwise
    the run starts its own archive_source job. An unavailable kind answers
    {success: false, unavailable: true}; any other failure fails the job and raises.
    """
    ops = services().operations
    job_id = job_id or ops.try_start_job(
        "archive_source",
        trigger="manual",
        source_id=source_id,
        payload={"desired_posts": desired_posts, "resume": resume, "rate_limit": rate_limit_overrides or {}},
    )
    try:
        ops.try_append_job_event(
            job_id,
            message="Archive job started",
            level="info",
            payload={"desired_posts": desired_posts, "resume": resume, "rate_limit": rate_limit_overrides or {}},
        )
        result = await services().source_fetch.archive_source(
            source_id,
            desired_posts,
            progress_callback=lambda event: ops.try_append_job_event(
                job_id,
                message=str(event.get("message") or event.get("stage") or "Archive progress"),
                level="info",
                progress=event.get("progress"),
                payload=event,
            ),
            resume=resume,
            rate_limit_overrides=rate_limit_overrides,
        )
    except KindUnavailable as e:
        ops.try_finish_job(job_id, status="failed", message=f"Unavailable: {e.reason}",
                           payload={"source_id": source_id, "unavailable": True})
        return {"success": False, "error": e.reason, "unavailable": True, "source_id": source_id}
    except Exception as e:
        ops.try_finish_job(job_id, status="failed", message=str(e), payload={"source_id": source_id})
        raise
    # An archive run is not a live fetch: it does not touch source_fetch_state, so paging old
    # posts can neither delay the next live fetch nor reset its backoff. Its own status lives
    # in settings.archive.
    ops.try_finish_job(
        job_id,
        status="success" if result.get("success") else "failed",
        message=result.get("error") or f"Archived {result.get('posts_fetched', 0)} posts",
        payload=result,
    )
    return result


# Sources with an archive running in this process. One uvicorn worker runs every background
# job, so a set is the whole truth; a restart empties it, as it ends the runs it tracked.
_archiving_sources: set[str] = set()


async def _run_archive_once(source_id: str, *args, **kwargs):
    try:
        await _run_async_job_background("archive_source", _run_archive, source_id, *args, **kwargs)
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
    before any job exists; an unknown source is 404; untracked jobs never run (503), like
    a manual fetch.
    """
    try:
        support = services().source_fetch.archive_support(source_id)
    except ValueError as exc:
        return JSONResponse(status_code=404, content={"success": False, "error": str(exc)})
    if not support.get("archivable"):
        reason = support.get("reason") or "This source cannot archive"
        return JSONResponse(status_code=409, content={"success": False, "detail": reason, "error": reason,
                                                      "unavailable": bool(support.get("unavailable"))})
    if source_id in _archiving_sources:
        reason = "An archive of this source is already running"
        return JSONResponse(status_code=409, content={"success": False, "detail": reason, "error": reason})
    resume = bool(request.resume)
    job_id = services().operations.try_start_job(
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


def _unavailable(reason: str) -> JSONResponse:
    """409 for an archive request on a kind this process cannot fetch (E7)."""
    return JSONResponse(status_code=409, content={"success": False, "detail": reason, "error": reason})


async def _fetch_reddit_comments(post_id: str, *, limit: int = 80, refresh: bool = False,
                                 job_id: str | None = None) -> Dict[str, Any]:
    ops = services().operations
    job_id = job_id or ops.try_start_job(
        "reddit_comments_fetch",
        trigger="manual",
        message=f"Fetch Reddit comments for {post_id}",
        payload={"post_id": post_id, "limit": limit, "refresh": refresh},
    )
    try:
        ops.try_append_job_event(job_id, message=f"Fetching Reddit comments for {post_id}", level="info")
        comments = await services().post_detail.fetch_reddit_comments(post_id, limit=limit, refresh=refresh)
    except Exception as e:
        ops.try_finish_job(job_id, status="failed", message=str(e), payload={"post_id": post_id})
        raise
    result = {"success": True, **comments}
    ops.try_finish_job(job_id, status="success", message=f"Fetched {result.get('comment_count', 0)} comments",
                       payload=result)
    return result


def _export_sources_json() -> None:
    """Mirror the sources to sources.json. A source change still succeeds when this fails."""
    try:
        services().source_config_sync.sync_db_to_json()
    except Exception:
        logger.exception("Could not export sources.json")


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
@error_envelope("load the sources")
async def get_sources():
    """Get sources in frontend-compatible format (nested by platform)."""
    return {"success": True, "data": services().sources.config_view()}

@app.get("/api/enabled-sources")
@error_envelope("load the enabled sources")
async def get_enabled_sources():
    """Get only enabled sources (flat list)."""
    return {"success": True, "data": services().sources.get_enabled_sources()}

@app.post("/api/sources")
@error_envelope("update the sources")
async def update_sources(config: dict):
    """Update sources configuration (add/remove/enable/disable)."""
    logger.info("🔧 Updating sources in database")
    result = services().sources.apply_config(config)
    _export_sources_json()
    if result["success"]:
        return {"success": True, "message": result["message"], "data": result["stats"]}
    return {"success": False, "error": "Some operations failed", "data": result["stats"]}


@app.post("/api/sources/sync/{direction}")
@error_envelope("sync the sources")
async def sync_sources(direction: str):
    """Synchronize sources.json and the database-backed registry."""
    logger.info(f"🔄 Syncing sources registry: {direction}")
    sync = services().source_config_sync
    if direction == "json-to-db":
        return sync.sync_json_to_db(mirror=True)
    if direction == "db-to-json":
        return sync.sync_db_to_json()
    return {"success": False, "error": f"Unsupported sync direction: {direction}"}


# ============= POSTS ENDPOINTS (DATABASE-BACKED) =============

@app.get("/api/posts/{date}")
@error_envelope("load the posts", posts=[], total=0)
async def get_posts(date: str):
    """Get posts for a specific date (YYYY-MM-DD)."""
    try:
        day = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return {"success": False, "error": f"Invalid date format: {date}. Expected YYYY-MM-DD",
                "posts": [], "total": 0}
    posts = services().posts.get_posts_by_date(day)
    return {"success": True, "posts": posts, "date": date, "total": len(posts), "source": "database"}

@app.get("/api/posts/source/{source_id}")
@error_envelope(
    "load the posts", posts=[], total=0, returned=0,
    offset=lambda request: max(0, int(request.query_params.get("offset") or 0)),
    limit=lambda request: int(request.query_params["limit"]) if request.query_params.get("limit") else None,
    has_more=False, source_id=_path("source_id"),
)
async def get_posts_by_source(
    source_id: str,
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Get posts for a specific source, newest first, one page at a time."""
    posts_service = services().posts
    posts = posts_service.get_posts_by_source(source_id, limit=limit, offset=offset)
    total = int(posts_service.get_source_post_stats(source_id).get("post_count", 0))
    current_offset = max(0, int(offset or 0))
    return {
        "success": True,
        "posts": posts,
        "source_id": source_id,
        "total": total,
        "returned": len(posts),
        "offset": current_offset,
        "limit": limit,
        "has_more": current_offset + len(posts) < total,
    }


@app.get("/api/posts/item/{post_id}")
@error_envelope("load the post", post=None, reader_state=None)
async def get_post_detail(post_id: str):
    """Get a single post with source metadata and saved notes."""
    detail = services().post_detail
    post = detail.get_post_by_id(post_id)
    if not post:
        return {"success": False, "error": f"Post {post_id} not found", "post": None}
    return {"success": True, "post": post, "reader_state": detail.get_post_reader_state(post_id)}


@app.get("/api/posts/item/{post_id}/reader-state")
@error_envelope("load the reader state", post_id=_path("post_id"), reader_state=None)
async def get_post_reader_state(post_id: str):
    state = services().post_detail.get_post_reader_state(post_id)
    return {"success": True, "post_id": post_id, "reader_state": state}


@app.post("/api/posts/item/{post_id}/opened")
@error_envelope("record the post open", event=None)
async def record_post_open(post_id: str, request: PostOpenRequest | None = None):
    metadata = request.metadata if request else None
    return {"success": True, "event": services().post_detail.record_post_open(post_id, metadata=metadata)}


@app.post("/api/posts/item/{post_id}/reading-session")
@error_envelope("record the reading session", event=None)
async def record_post_reading_session(post_id: str, request: PostReaderSessionRequest):
    event = services().post_detail.record_reading_session(
        post_id,
        duration_seconds=int(request.durationSeconds or 0),
        metadata=request.metadata,
    )
    return {"success": True, "event": event}


@app.post("/api/posts/item/{post_id}/favorite")
@error_envelope("update the star", post_id=_path("post_id"))
async def toggle_post_favorite(post_id: str, request: PostFavoriteRequest):
    logger.info(f"⭐ Toggling post favorite: {post_id}")
    return {"success": True, **services().post_detail.toggle_favorite(post_id, bool(request.favorited))}


# ============= READER (Mark IX) =============
# New endpoints follow the §4 error contract: non-2xx with {"detail": "<human message>"}.
# A ValueError (a bad scope, cursor, filter or id) is the 400.

MAX_FEED_LIMIT = 100
MAX_READ_BATCH = 500


def _require_post_ids(ids: List[str]) -> List[str]:
    if len(ids) > MAX_READ_BATCH:
        raise ValueError(f"at most {MAX_READ_BATCH} ids per request")
    try:
        return [str(uuid.UUID(str(pid))) for pid in ids]
    except ValueError:
        raise ValueError("ids must be post UUIDs") from None


@app.get("/api/feed")
@error_detail("load the feed")
async def get_feed(scope: str = "all", filter: str = "all", view: str = "stream",
                   cursor: str | None = None, limit: int = 30, days: int | None = None):
    """Keyset-paginated, newest-first feed: FeedPage (stream) or FeedGroupsPage (by_source)."""
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
    return services().reader.feed(feed_scope, filter=filter, view=view, cursor=feed_cursor,
                                  limit=int(limit), days=days)


@app.get("/api/feed/unread-counts")
@error_detail("load unread counts")
async def get_feed_unread_counts():
    return services().reader.unread_counts()


# An image is served with the headers a stranger's file needs on our origin: no sniffing,
# and an SVG opened on its own can run nothing.
_MEDIA_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
}


@app.get("/api/media")
@error_detail("load the image")
async def get_media(post: str, url: str):
    """One image of one post, fetched now (issue 0006). Not stored: the frontend nginx caches
    it for 24 hours and the browser as long. 404: not an image of this post or not a host we
    fetch from; 502: the origin failed. Failures are cached for 10 minutes."""
    try:
        image = await asyncio.to_thread(services().media_proxy.fetch, post, url)
    except MediaNotAllowed:
        return Response(status_code=404, headers={**_MEDIA_HEADERS, "Cache-Control": "public, max-age=600"})
    except MediaFetchFailed as exc:
        logger.info("Media proxy: %s for post %s", exc, post)
        return Response(status_code=502, headers={**_MEDIA_HEADERS, "Cache-Control": "public, max-age=600"})
    return Response(content=image.body, media_type=image.content_type,
                    headers={**_MEDIA_HEADERS, "Cache-Control": "public, max-age=86400"})


@app.post("/api/feed/mark-read")
@error_detail("mark posts read")
async def mark_feed_read(request: FeedMarkReadRequest):
    """Mark all read from newest_cursor down to through_cursor, bounded by the unread window."""
    scope = FeedScope.parse(request.scope)
    through = FeedCursor.decode(request.through_cursor)
    newest = FeedCursor.decode(request.newest_cursor)
    return services().reader.mark_read_through(scope, through, newest)


@app.put("/api/feed/read")
@error_detail("update read state")
async def set_feed_read(request: FeedReadRequest):
    """Batch read/unread (the mark-through Undo)."""
    ids = _require_post_ids(request.ids)
    return {"success": True, "updated": services().reader.set_read(ids, bool(request.read))}


@app.put("/api/posts/item/{post_id}/read")
@error_detail("update read state")
async def set_post_read(post_id: str, request: PostReadRequest):
    (post_id,) = _require_post_ids([post_id])
    updated = services().reader.set_read([post_id], bool(request.read))
    return {"success": True, "post_id": post_id, "updated": updated}


@app.post("/api/posts/item/{post_id}/reddit-comments")
@error_envelope("fetch the Reddit comments", post_id=_path("post_id"))
async def fetch_reddit_comments(post_id: str, request: PostCommentsRequest, background_tasks: BackgroundTasks):
    logger.info(f"💬 Fetching Reddit comments for post: {post_id}")
    limit, refresh = int(request.limit or 80), bool(request.refresh)
    if request.asyncMode:
        job_id = services().operations.try_start_job(
            "reddit_comments_fetch",
            trigger="manual",
            message=f"Fetch Reddit comments for {post_id}",
            payload={"post_id": post_id, "limit": limit, "refresh": refresh},
        )
        if job_id:
            background_tasks.add_task(
                _run_async_job_background, "reddit_comments_fetch", _fetch_reddit_comments,
                post_id, limit=limit, refresh=refresh, job_id=job_id,
            )
            return _accepted_job_response(job_id, "reddit_comments_fetch", message="Reddit comment fetch started")
    return await _fetch_reddit_comments(post_id, limit=limit, refresh=refresh)


@app.get("/api/sources/with-counts")
@error_envelope("load the sources", platforms={}, total_posts=0)
async def get_sources_with_counts():
    """Get all sources with their post counts, grouped by platform."""
    return {"success": True, **services().sources.counts_by_platform()}

@app.get("/api/sources/{source_id}/settings")
@error_envelope("load the source settings", settings={})
async def get_source_settings(source_id: str):
    """Get settings for a specific source."""
    source = services().sources.get_source_with_settings(source_id)
    return {"success": True, "source_id": source_id, "settings": source.get("settings", {}), "source": source}

@app.put("/api/sources/{source_id}/settings")
@error_envelope("update the source settings")
async def update_source_settings(source_id: str, settings: dict):
    """Update settings for a specific source."""
    logger.info(f"🔧 Updating settings for source: {source_id}")
    result = services().sources.update_source_settings(source_id, settings)
    return {"success": True, "source_id": source_id, "settings": result.get("settings", {})}

@app.get("/api/sources/with-settings")
@error_envelope("load the sources", sources=[])
async def get_sources_with_settings():
    """Get all sources with their settings and post counts."""
    sources = services().sources.with_settings_and_counts()
    return {"success": True, "sources": sources, "total": len(sources)}


# ============= FOLDERS ENDPOINTS =============


@app.get("/api/folders")
@error_envelope("load the folders", folders=[])
async def get_folders():
    """List folders with source and post counts."""
    folders = services().folders.list_folders()
    return {"success": True, "folders": folders, "total": len(folders)}


@app.post("/api/folders")
@error_envelope("create the folder", folder=None)
async def create_folder(config: dict):
    """Create a folder or track.

    Body: {name, description?, sort_order?, kind?, exclude_from_main_digest?, match_keywords?}
    kind is "folder" (default) or "track".
    """
    logger.info("📁 Creating folder")
    name = str(config.get("name") or "").strip()
    if not name:
        return {"success": False, "error": "Folder name is required", "folder": None}
    folder = services().folders.create_folder(
        name=name,
        description=config.get("description"),
        sort_order=int(config.get("sort_order", 999)),
        kind=str(config.get("kind") or "folder"),
        exclude_from_main_digest=bool(config.get("exclude_from_main_digest", False)),
        match_keywords=config.get("match_keywords") or [],
    )
    return {"success": True, "folder": folder}


@app.put("/api/folders/{folder_id}")
@error_envelope("update the folder", folder=None)
async def update_folder(folder_id: str, fields: dict):
    """Update folder fields.

    Body: any of {name, description, sort_order, kind, exclude_from_main_digest, match_keywords}
    """
    logger.info(f"📁 Updating folder: {folder_id}")
    return {"success": True, "folder": services().folders.update_folder(folder_id, fields)}


@app.delete("/api/folders/{folder_id}")
@error_envelope("delete the folder")
async def delete_folder(folder_id: str):
    """Delete a folder."""
    logger.info(f"📁 Deleting folder: {folder_id}")
    if not services().folders.delete_folder(folder_id):
        return {"success": False, "error": f"Folder {folder_id} not found"}
    return {"success": True, "deleted": True, "folder_id": folder_id}


@app.get("/api/folders/{folder_id}/sources")
@error_envelope("load the folder's sources", sources=[])
async def get_folder_sources(folder_id: str):
    """List the sources attached to a folder."""
    sources = services().folders.list_sources(folder_id)
    return {"success": True, "sources": sources, "total": len(sources)}


@app.post("/api/folders/{folder_id}/sources")
@error_envelope("add the source to the folder")
async def add_folder_source(folder_id: str, body: dict):
    """Attach a source to a folder. Body: {source_id}"""
    source_id = str(body.get("source_id") or "").strip()
    if not source_id:
        return {"success": False, "error": "source_id is required"}
    logger.info(f"📁 Adding source {source_id} to folder {folder_id}")
    added = services().folders.add_source(folder_id, source_id)
    return {"success": True, "added": added, "folder_id": folder_id, "source_id": source_id}


@app.post("/api/folders/{folder_id}/ingest")
async def ingest_folder(folder_id: str, background_tasks: BackgroundTasks, body: dict | None = None):
    """Fetch every enabled source in a folder/track now (forced). Body: {limit?: int}.

    Returns 202 with the ingestion_run job; poll /api/operations/jobs/{id} for the run report.
    Politeness comes from the source kinds' profiles and the host floors, not a delay knob.
    """
    limit = (body or {}).get("limit")
    request = FetchRequest(SourceSelector.folder(folder_id), Trigger.MANUAL, force=True, limit=limit)
    return _accept_ingestion_run(background_tasks, request, message=f"Fetch track {folder_id}")


@app.get("/api/folders/{folder_id}/posts")
@error_envelope("load the track feed", posts=[])
async def get_folder_posts(
    folder_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    days: int | None = Query(None, ge=1, le=365),
):
    """Reading feed for a folder/track: newest posts from its sources, newest first."""
    folders = services().folders
    folder = folders.get_folder(folder_id)
    if not folder:
        return {"success": False, "error": f"Folder {folder_id} not found", "posts": []}
    source_ids = folders.list_source_ids(folder_id)
    feed = services().posts.get_folder_feed(source_ids, limit=limit, offset=offset, since_days=days)
    return {"success": True, "folder": folder, "source_count": len(source_ids), **feed}


@app.put("/api/sources/{source_id}/main-digest")
@error_envelope("update the main-digest setting")
async def set_source_main_digest(source_id: str, body: dict):
    """Include/exclude one source from the main digests. Body: {in_main_digest: bool}"""
    value = bool(body.get("in_main_digest", True))
    logger.info(f"\U0001F5DE Source {source_id} -> in_main_digest={value}")
    return {"success": True, **services().sources.set_in_main_digest(source_id, value)}


@app.put("/api/folders/{folder_id}/main-digest")
@error_envelope("update the main-digest setting")
async def set_folder_main_digest(folder_id: str, body: dict):
    """Apply the digest switch to every source in a folder/track.

    Body: {in_main_digest: bool}. Sending false keeps a track's sources out of the "all"
    feed while they are still ingested.
    """
    value = bool(body.get("in_main_digest", True))
    logger.info(f"\U0001F5DE Folder {folder_id} -> in_main_digest={value}")
    result = services().sources.set_folder_in_main_digest(folder_id, value)
    # Keep the folder's declared intent in step with what was applied.
    services().folders.update_folder(folder_id, {"exclude_from_main_digest": not value})
    return {"success": True, **result}


@app.delete("/api/folders/{folder_id}/sources/{source_id}")
@error_envelope("remove the source from the folder")
async def remove_folder_source(folder_id: str, source_id: str):
    """Detach a source from a folder."""
    logger.info(f"📁 Removing source {source_id} from folder {folder_id}")
    removed = services().folders.remove_source(folder_id, source_id)
    return {"success": True, "removed": removed, "folder_id": folder_id, "source_id": source_id}


@app.post("/api/sources/add")
@error_envelope("add the source")
async def add_single_source(body: dict):
    """Add one source (non-destructive). Body: {platform, handle_or_url, display_name?, fetch_delay_seconds?, priority?, max_posts_per_fetch?, state?}"""
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
    sources = services().sources
    source_id = sources.add_source(platform, handle)["source_id"]
    if settings:
        sources.update_source_settings(source_id, settings)
    sources.update_source_status(source_id, enabled)
    _export_sources_json()
    return {"success": True, "source_id": source_id, "platform": platform, "handle_or_url": handle}


@app.put("/api/sources/{source_id}/enabled")
@error_envelope("update the source")
async def set_source_enabled(source_id: str, body: dict):
    """Enable/disable a source. Body: {enabled: bool}"""
    enabled = bool(body.get("enabled"))
    services().sources.update_source_status(source_id, enabled)
    _export_sources_json()
    return {"success": True, "source_id": source_id, "enabled": enabled}


@app.delete("/api/sources/{source_id}")
@error_envelope("delete the source")
async def delete_single_source(source_id: str):
    """Delete a single source (and its posts)."""
    logger.info(f"🗑️ Deleting source {source_id}")
    if not services().sources.delete_source(source_id):
        return {"success": False, "error": f"Source {source_id} not found"}
    _export_sources_json()
    return {"success": True, "deleted": True, "source_id": source_id}


@app.get("/api/sources/{source_id}/folders")
@error_envelope("load the source's folders", folder_ids=[])
async def get_source_folders(source_id: str):
    """List the folder ids a source belongs to."""
    return {"success": True, "folder_ids": services().folders.list_folders_for_source(source_id)}


@app.get("/api/archive/{source_id}/status")
@error_envelope("load the archive status", source_id=_path("source_id"))
async def get_archive_status(source_id: str):
    """Persisted archive metadata plus current storage stats, what the source can archive, and
    the newest archive job (a running one the sheet attaches to, or the last result)."""
    svc = services()
    source = svc.sources.get_source_with_settings(source_id)
    post_stats = svc.posts.get_source_post_stats(source_id)
    oldest, latest = post_stats.get("oldest_published_at"), post_stats.get("latest_published_at")
    try:
        support = svc.source_fetch.archive_support(source_id)
    except Exception:
        logger.exception("Archive support check failed for %s", source_id)
        support = None
    try:
        latest_job = svc.operations.latest_job_for_source("archive_source", source_id)
    except Exception:
        logger.exception("Could not read the latest archive job for %s", source_id)
        latest_job = None
    return {
        "success": True,
        "source_id": source_id,
        "archive": {
            **source.get("settings", {}).get("archive", {}),
            "stored_posts": post_stats["post_count"],
            "oldest_published_at": oldest.isoformat() if oldest else None,
            "latest_published_at": latest.isoformat() if latest else None,
        },
        "source": source,
        "support": support,
        "latest_job": latest_job,
    }

@app.get("/api/archive/catalog")
@error_envelope("load the archive catalog", sources=[], total=0)
async def get_archive_catalog():
    """List enabled sources with their persisted archive status."""
    catalog = services().source_fetch.archive_catalog()
    return {"success": True, "sources": catalog, "total": len(catalog)}


@app.post("/api/archive/{source_id}/plan")
@error_envelope("plan the archive")
async def plan_archive(source_id: str, request: ArchiveRequest):
    """Estimate archive effort for a source."""
    logger.info(f"🧭 Planning archive for source: {source_id}")
    try:
        plan = await services().source_fetch.plan_archive(
            source_id,
            request.desiredPosts,
            resume=bool(request.resume),
            rate_limit_overrides={
                "page_delay_seconds": request.pageDelaySeconds,
                "batch_size": request.batchSize,
                "batch_cooldown_seconds": request.batchCooldownSeconds,
            },
        )
    except KindUnavailable as e:
        return _unavailable(e.reason)
    return {"success": True, "archive": plan}


@app.post("/api/archive/{source_id}/run")
@error_envelope("run the archive", source_id=_path("source_id"))
async def run_archive(source_id: str, request: ArchiveRequest, background_tasks: BackgroundTasks):
    """Run an archive job for a single source (202 + archive_source job when background)."""
    rate_limit_overrides = {
        "page_delay_seconds": request.pageDelaySeconds,
        "batch_size": request.batchSize,
        "batch_cooldown_seconds": request.batchCooldownSeconds,
    }
    if request.background:
        return _accept_archive_run(background_tasks, source_id, request, rate_limit_overrides)
    logger.info(f"📦 Running archive for source: {source_id}")
    result = await _run_archive(
        source_id,
        request.desiredPosts,
        resume=bool(request.resume),
        rate_limit_overrides=rate_limit_overrides,
    )
    if result.get("unavailable"):
        return _unavailable(result.get("error"))
    return result


@app.post("/api/sources/{source_id}/fetch-now")
async def fetch_source_now(source_id: str, request: LiveFetchRequest, background_tasks: BackgroundTasks):
    """Fetch one source now (forced, even when disabled). 202 + ingestion_run job."""
    fetch = FetchRequest(SourceSelector.source(source_id), Trigger.MANUAL, force=True, limit=request.limit)
    return _accept_ingestion_run(background_tasks, fetch, message=f"Fetch source {source_id}", source_id=source_id)


@app.get("/api/sources/health")
@error_detail("load source health")
async def get_sources_health():
    """SourcesHealthResponse: every source's schedule (decide_fetch preview) + a summary."""
    return services().operations.get_source_health()


@app.put("/api/sources/{source_id}/cadence")
@error_detail("set the cadence override")
async def set_source_cadence(source_id: str, request: CadenceOverrideRequest):
    """Set (or clear, with null) a source's fetch interval override, in hours [1, 2160].
    404 for an unknown source."""
    hours = request.override_hours
    if hours is not None and not (
        math.isfinite(hours) and CADENCE_OVERRIDE_MIN_HOURS <= hours <= CADENCE_OVERRIDE_MAX_HOURS
    ):
        raise HTTPException(
            status_code=400,
            detail=f"override_hours must be null or between {CADENCE_OVERRIDE_MIN_HOURS:g} "
                   f"and {CADENCE_OVERRIDE_MAX_HOURS:g}",
        )
    return {"success": True, "row": services().operations.set_cadence_override(source_id, hours)}


# ============= CONNECTIONS (credentials, Mark IX §10.1) =============
# Write-only: no route returns a stored value, a ciphertext or a Telegram session, and none
# logs a request body. Request fields are typed Any so a malformed body is rejected by the
# service with a message that never echoes it (a 422 would). Unknown provider or field: 404;
# invalid value: 400; failed sign-in: 400, or 429 with Retry-After.


class CredentialValueRequest(BaseModel):
    value: Any = None


class TelegramLoginStartRequest(BaseModel):
    phone: Any = None


class TelegramLoginCodeRequest(BaseModel):
    code: Any = None


class TelegramLoginPasswordRequest(BaseModel):
    password: Any = None


@app.get("/api/credentials")
@error_detail("load the connections")
async def get_credentials():
    """Every connection: per field {set, last4, updated_at, source}, the last test, sign-in stage."""
    return services().credentials.list()


@app.put("/api/credentials/{provider}/{key}")
@error_detail("save the connection")
async def put_credential(provider: str, key: str, request: CredentialValueRequest):
    return services().credentials.put(provider, key, request.value)


@app.delete("/api/credentials/{provider}/{key}")
@error_detail("remove the connection")
async def delete_credential(provider: str, key: str):
    return services().credentials.delete(provider, key)


@app.post("/api/credentials/{provider}/test")
@error_detail("test the connection")
async def test_credential(provider: str):
    return await services().credentials.test(provider)


@app.post("/api/credentials/telegram/login/start")
@error_detail("start the Telegram sign-in")
async def telegram_login_start(request: TelegramLoginStartRequest):
    """Send the login code to the phone. -> {stage: "code"}"""
    return await services().credentials.login_start(request.phone)


@app.post("/api/credentials/telegram/login/code")
@error_detail("check the Telegram code")
async def telegram_login_code(request: TelegramLoginCodeRequest):
    """-> {stage: "password"} (two-step verification) or {stage: "done", account}"""
    return await services().credentials.login_code(request.code)


@app.post("/api/credentials/telegram/login/password")
@error_detail("check the Telegram password")
async def telegram_login_password(request: TelegramLoginPasswordRequest):
    """-> {stage: "done", account}"""
    return await services().credentials.login_password(request.password)


@app.post("/api/credentials/telegram/login/cancel")
@error_detail("cancel the Telegram sign-in")
async def telegram_login_cancel():
    return services().credentials.login_cancel()


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
@error_detail("build the system status")
async def get_status():
    """Unified machine-readable system state: corpus freshness, sources, folders,
    scheduler config, and recent jobs.
    Designed as the single read an agent makes to understand the whole system."""
    svc = services()
    ops = svc.operations
    health_summary = ops.get_source_health()["summary"]
    return {
        "success": True,
        "healthy": True,
        "generated_at": datetime.now().isoformat(),
        "corpus": {**ops.get_database_counts(), "total_sources": len(svc.sources.get_all_sources()),
                   **ops.get_corpus_freshness()},
        "scheduler": ops.get_scheduler_config(),
        "folders": [
            {"id": f["id"], "name": f["name"],
             "source_count": f.get("source_count", 0), "post_count": f.get("post_count", 0)}
            for f in svc.folders.list_folders()
        ],
        "recent_jobs": [
            {"id": j["id"], "job_type": j.get("job_type", ""), "status": j.get("status", ""),
             "started_at": j.get("started_at"), "finished_at": j.get("finished_at"),
             "message": j.get("message")}
            for j in ops.list_recent_jobs(20)
        ],
        "source_health_summary": {
            "monitored": sum(health_summary.values()),
            # Failing sources: retrying now or waiting in backoff.
            "errors": sources_failing(health_summary),
        },
    }


# ============= INGESTION ENDPOINTS =============

@app.post("/api/ingestion/run")
async def run_ingestion_cycle(background_tasks: BackgroundTasks, request: IngestionRunRequest | None = None):
    """The manual "Run cycle": every enabled source; due ones only unless force. 202 + job."""
    force = bool(request.force) if request else False
    fetch = FetchRequest(SourceSelector.all(), Trigger.MANUAL, force=force)
    return _accept_ingestion_run(background_tasks, fetch,
                                 message="Forced ingestion cycle" if force else "Ingestion cycle")


@app.get("/api/ingestion/logs")
@error_envelope("read the log", log=lambda request: request.query_params.get("log", "application"), lines=[])
async def get_ingestion_logs(
    log: str = Query(default="application"),
    lines: int = Query(default=200, ge=1, le=1000),
):
    """Return recent shared backend/ingestion log lines."""
    return services().system_logs.get_log_tail(log, lines)


@app.get("/api/operations/overview")
@error_envelope("load the operations overview", jobs=[], source_health=EMPTY_SOURCE_HEALTH, alerts=[])
async def get_operations_overview():
    return services().operations.get_operations_overview()


@app.get("/api/operations/jobs/{job_id}")
@error_envelope("load the job", job=None)
async def get_operation_job(job_id: str):
    job = services().operations.get_job(job_id)
    if not job:
        return {"success": False, "error": f"Job {job_id} not found", "job": None}
    return {"success": True, "job": job}


@app.get("/api/operations/scheduler")
@error_envelope("load the scheduler settings")
async def get_scheduler_config():
    ops = services().operations
    scheduler = ops.get_scheduler_config()
    try:
        scheduler["state"] = ops.get_scheduler_state()
    except Exception:
        logger.exception("Could not read the scheduler state")
        scheduler["state"] = {}
    return {"success": True, "scheduler": scheduler}


@app.put("/api/operations/scheduler")
@error_envelope("save the scheduler settings")
async def update_scheduler_config(request: SchedulerConfigRequest):
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
    return {"success": True, "scheduler": services().operations.update_scheduler_config(payload)}


# ============= YOUTUBE ENDPOINTS =============

@app.post("/api/youtube/channel/videos")
@error_envelope("list the channel's videos")
async def list_youtube_channel_videos(request: YouTubeChannelRequest):
    logger.info(f"📺 Listing YouTube videos for {request.source}")
    return {"success": True, **services().youtube.list_channel_videos(request.source, limit=request.limit)}


@app.get("/api/youtube/progress/{video_id}")
@error_envelope("load the watch progress", progress=None)
async def get_youtube_watch_progress(video_id: str):
    return {"success": True, "progress": services().youtube.get_watch_progress(video_id)}


@app.put("/api/youtube/progress/{video_id}")
@error_envelope("save the watch progress", progress=None)
async def save_youtube_watch_progress(video_id: str, request: YouTubeProgressRequest):
    progress = services().youtube.save_watch_progress(
        video_id=video_id,
        video_url=request.videoUrl,
        title=request.title,
        duration_seconds=request.durationSeconds,
        progress_seconds=request.progressSeconds,
        source_id=request.sourceId,
        notes_markdown=request.notesMarkdown,
        completed=request.completed,
    )
    return {"success": True, "progress": progress}
