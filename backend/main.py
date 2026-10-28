import json
import logging
import math
import os
import asyncio
import re
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import psycopg
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.routing import APIRoute
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from insight_core.db import database
from insight_core.db.repo_reader import FeedCursor, FeedQuery, FeedScope
from insight_core.ingestion import run_ingestion
from insight_core.ingestion.feed_finder import find_feeds
from insight_core.ingestion.http import KindHttp
from insight_core.ingestion.kinds import page_watch
from insight_core.ingestion.kinds import saved as saved_kind
from insight_core.ingestion.kinds.base import KindUnavailable
from insight_core.ingestion.ports import JobProgressSink
from insight_core.ingestion.types import FetchRequest, SourceSelector, Trigger
from insight_core.services.credentials_service import LoginFailed
from insight_core.services.media_proxy_service import MediaFetchFailed, MediaNotAllowed
from insight_core.services.operations_service import (
    CADENCE_OVERRIDE_MAX_HOURS,
    CADENCE_OVERRIDE_MIN_HOURS,
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
    database.close_all()


app = FastAPI(title="INSIGHT API", description="The INSIGHT reader's backend.", lifespan=lifespan)


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
# safe HTTP error {"detail": message}: the service's own message for errors the caller can
# act on (400 for a ValueError, 404 for a not-found LookupError, 400 or 429 for a failed
# Telegram sign-in), and "Could not <what>. Check the backend logs." (500) for anything
# else. That exception is logged, never echoed: driver messages can carry DSNs and SQL.
# A 4xx is logged too, as a warning. A route names its <what> with @error_detail.
#
# A path id (post_id, folder_id, source_id, job_id) that is not a uuid names no row: 404
# before the route runs. A value the database still cannot read is a 400.


DEFAULT_ERROR_WHAT = "complete the request"


def error_detail(what: str):
    def mark(endpoint):
        endpoint.error_what = what
        return endpoint
    return mark


_DATABASE_URL = re.compile(r"postgres(?:ql)?(?:\+\w+)?://\S*", re.IGNORECASE)


def _known_error(exc: Exception) -> Optional[tuple[int, str, Dict[str, str]]]:
    """(status, message, headers) for an error the caller can act on; None for anything else."""
    if isinstance(exc, LoginFailed):
        if exc.retry_after:
            return 429, exc.message, {"Retry-After": str(exc.retry_after)}
        return 400, exc.message, {}
    if isinstance(exc, LookupError) and not isinstance(exc, (KeyError, IndexError)):
        return 404, str(exc), {}
    if isinstance(exc, psycopg.errors.InvalidTextRepresentation):
        return 400, "Invalid value.", {}
    # Bad stored data (a JSON column, a file) is ours to fix, not the caller's: a 500.
    if isinstance(exc, ValueError) and not isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError)):
        return 400, str(exc), {}
    return None


UUID_PATH_PARAMS = ("post_id", "folder_id", "source_id", "job_id")


def check_path_ids(path_params: Dict[str, Any]) -> None:
    """LookupError (404) when a path id is not a uuid: it names no row."""
    for name in UUID_PATH_PARAMS:
        if name in path_params:
            try:
                uuid.UUID(str(path_params[name]))
            except ValueError:
                raise LookupError("Not found.") from None


def service_error_response(request: Request, exc: Exception, what: str) -> JSONResponse:
    """The one error handler: a service error as a safe {"detail"} answer."""
    known = _known_error(exc)
    if known is None:
        logger.error("%s %s failed", request.method, request.url.path, exc_info=exc)
        status, message, headers = 500, f"Could not {what}. Check the backend logs.", {}
    else:
        status, message, headers = known
        message = _DATABASE_URL.sub("<database url>", message)
        cause = f" ({_DATABASE_URL.sub('<database url>', str(exc))})" if isinstance(exc, psycopg.Error) else ""
        logger.warning("%s %s answered %s: %s%s", request.method, request.url.path, status, message, cause)
    return JSONResponse(status_code=status, content={"detail": message}, headers=headers or None)


class ServiceRoute(APIRoute):
    """Every route answers its errors through service_error_response. HTTPException and
    request validation keep FastAPI's own handlers.

    (A route-level wrapper rather than app.exception_handler(Exception): Starlette runs an
    Exception handler outside the CORS middleware and re-raises after it.)"""

    def get_route_handler(self):
        handle = super().get_route_handler()
        what = getattr(self.endpoint, "error_what", DEFAULT_ERROR_WHAT)

        async def route_handler(request: Request):
            try:
                check_path_ids(request.path_params)
                return await handle(request)
            except (StarletteHTTPException, RequestValidationError):
                raise
            except Exception as exc:
                return service_error_response(request, exc, what)

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
    resume: bool | None = True
    pageDelaySeconds: int | None = None
    batchSize: int | None = None
    batchCooldownSeconds: int | None = None
    # True: start an archive_source job and answer 202 at once (the source sheet polls
    # the job). False runs the archive inside the request and answers its result.
    background: bool = False


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


class PostPositionRequest(BaseModel):
    """Where a long post was left: the top block in view of `blocks`. block None: finished."""
    block: int | None = None
    blocks: int | None = None


class ReadStateRequest(BaseModel):
    """PUT /api/feed/read: either `ids` (one post or many, read or unread), or a mark-through:
    `through_cursor` and `newest_cursor` in `scope` (read only)."""
    read: bool = True
    ids: List[str] | None = None
    keep_later: bool = False   # a read that is only an open: the post stays in Later
    scope: str = "all"
    through_cursor: str | None = None
    newest_cursor: str | None = None


class LaterRequest(BaseModel):
    """PUT /api/feed/later: put posts in Later or take them out (issue 0022)."""
    ids: List[str] = []
    later: bool = True


class NewSourceRequest(BaseModel):
    platform: str = "rss"
    handle_or_url: str = ""
    display_name: str | None = None
    fetch_delay_seconds: int | None = None
    priority: int | None = None
    state: str | None = "enabled"
    page_watch: Dict[str, Any] | None = None     # settings.page_watch: follow a page (issue 0028)


class FindFeedRequest(BaseModel):
    url: str = ""


class PageWatchPreviewRequest(BaseModel):
    url: str = ""
    prefix: str | None = None


class SavePageRequest(BaseModel):
    url: str = ""
    title: str | None = None     # the page's title as the bookmarklet read it


class SwitchSourceRequest(BaseModel):
    url: str = ""
    page_watch: Dict[str, Any] | None = None     # follow the page at url (issue 0028) instead of a feed


class SourceEnabledRequest(BaseModel):
    enabled: bool


class MainDigestRequest(BaseModel):
    in_main_digest: bool = True


class FolderSourceRequest(BaseModel):
    source_id: str = ""


class PostOpenRequest(BaseModel):
    metadata: Dict[str, Any] | None = None



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
        payload={"resume": resume, "rate_limit": rate_limit_overrides or {}},
    )
    try:
        ops.try_append_job_event(
            job_id,
            message="Archive job started",
            level="info",
            payload={"resume": resume, "rate_limit": rate_limit_overrides or {}},
        )
        result = await services().source_fetch.archive_source(
            source_id,
            progress_callback=lambda event: ops.try_append_job_event(
                job_id,
                message=str(event.get("message") or event.get("stage") or "Archive progress"),
                level=event.get("level") or "info",
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
        # A paused archive (issue 0016) is a success whose message says why it paused.
        message=result.get("error") or result.get("message") or f"Archived {result.get('posts_fetched', 0)} posts",
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
    except LookupError as exc:
        return JSONResponse(status_code=404, content={"success": False, "detail": str(exc), "error": str(exc)})
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
        payload={"resume": resume, "rate_limit": rate_limit_overrides},
    )
    if not job_id:
        return JSONResponse(status_code=503, content={"success": False, "error": "job tracking unavailable"})
    _archiving_sources.add(source_id)
    background_tasks.add_task(
        _run_archive_once, source_id, resume=resume, rate_limit_overrides=rate_limit_overrides, job_id=job_id,
    )
    return JSONResponse(status_code=202, content=_accepted_job_response(job_id, "archive_source", message="Archive started"))


def _unavailable(reason: str) -> JSONResponse:
    """409 for an archive request on a kind this process cannot fetch (E7)."""
    return JSONResponse(status_code=409, content={"success": False, "detail": reason, "error": reason})


def _export_sources_json() -> None:
    """Mirror the sources to sources.json. A source change still succeeds when this fails."""
    try:
        services().source_config_sync.sync_db_to_json()
    except Exception:
        logger.exception("Could not export sources.json")


@app.get("/")
async def root():
    return {"message": "INSIGHT API", "status": "operational"}

# ============= POSTS =============

@app.get("/api/posts/item/{post_id}")
@error_detail("load the post")
async def get_post_detail(post_id: str):
    """One post with its source metadata and reader state. 404 for an unknown post."""
    detail = services().post_detail
    post = detail.get_post_by_id(post_id)
    if not post:
        raise LookupError(f"Post {post_id} not found")
    return {"success": True, "post": post, "reader_state": detail.get_post_reader_state(post_id)}


@app.post("/api/posts/item/{post_id}/opened")
@error_detail("record the post open")
async def record_post_open(post_id: str, request: PostOpenRequest | None = None):
    metadata = request.metadata if request else None
    return {"success": True, "event": services().post_detail.record_post_open(post_id, metadata=metadata)}


@app.post("/api/posts/item/{post_id}/reading-session")
@error_detail("record the reading session")
async def record_post_reading_session(post_id: str, request: PostReaderSessionRequest):
    event = services().post_detail.record_reading_session(
        post_id,
        duration_seconds=int(request.durationSeconds or 0),
        metadata=request.metadata,
    )
    return {"success": True, "event": event}


@app.post("/api/posts/item/{post_id}/favorite")
@error_detail("update the star")
async def toggle_post_favorite(post_id: str, request: PostFavoriteRequest):
    return {"success": True, **services().post_detail.toggle_favorite(post_id, bool(request.favorited))}


@app.put("/api/posts/item/{post_id}/position")
@error_detail("save where you stopped")
async def save_post_position(post_id: str, request: PostPositionRequest):
    services().post_detail.save_position(post_id, request.block, request.blocks)
    return {"success": True}


# ============= READER =============
# One listing (GET /api/feed) and one read-state route (PUT /api/feed/read). A ValueError
# (a bad scope, cursor, filter, date or id) is the 400.

MAX_READ_BATCH = 500


def _require_post_ids(ids: List[str]) -> List[str]:
    if not ids:
        raise ValueError("ids must not be empty")
    if len(ids) > MAX_READ_BATCH:
        raise ValueError(f"at most {MAX_READ_BATCH} ids per request")
    try:
        return [str(uuid.UUID(str(pid))) for pid in ids]
    except ValueError:
        raise ValueError("ids must be post UUIDs") from None


@app.get("/api/feed")
@error_detail("load the feed")
async def get_feed(scope: str = "all", filter: str = "all", view: str = "stream",
                   cursor: str | None = None, limit: int = 30, days: int | None = None,
                   date: str | None = None):
    """Every post list: newest first, keyset-paginated. FeedPage (stream) or FeedGroupsPage
    (by_source). scope: all | source:<uuid> | folder:<uuid>; filter: all | unread | later | starred
    (starred is Keep; later is oldest saved first);
    days: the last N days, or date: one day (YYYY-MM-DD, UTC)."""
    query = FeedQuery.parse(scope=scope, filter=filter, view=view, cursor=cursor, limit=limit,
                            days=days, date=date)
    return services().reader.list_posts(query)


@app.get("/api/feed/unread-counts")
@error_detail("load unread counts")
async def get_feed_unread_counts():
    return services().reader.unread_counts()


@app.put("/api/feed/read")
@error_detail("update read state")
async def set_read_state(request: ReadStateRequest):
    """Read state, three ways, one answer {success, updated, ids} (ids: the posts changed):
    - {ids, read}: one post or many (at most 500), read or unread; marking read also takes
      them out of Later, unless keep_later (the read is only an open);
    - {scope, through_cursor, newest_cursor}: mark read every unread post in scope from
      newest down to through, bounded by the unread window. The answer's ids undo it."""
    if request.through_cursor is not None or request.newest_cursor is not None:
        if request.ids is not None:
            raise ValueError("send ids or through_cursor, not both")
        if not request.read:
            raise ValueError("mark-through only marks read")
        if not request.through_cursor or not request.newest_cursor:
            raise ValueError("mark-through needs through_cursor and newest_cursor")
        scope = FeedScope.parse(request.scope)
        through = FeedCursor.decode(request.through_cursor)
        newest = FeedCursor.decode(request.newest_cursor)
        return services().reader.mark_read_through(scope, through, newest)
    if request.ids is None:
        raise ValueError("send ids, or through_cursor and newest_cursor")
    return services().reader.set_read(_require_post_ids(request.ids), bool(request.read),
                                      keep_later=bool(request.keep_later))


@app.put("/api/feed/later")
@error_detail("update Later")
async def set_later_state(request: LaterRequest):
    """Read later (issue 0022): {ids, later}, at most 500 ids; one answer {success, updated, ids}.
    Nothing clears Later on a clock; an explicit mark read (PUT /api/feed/read) does."""
    return services().reader.set_later(_require_post_ids(request.ids), bool(request.later))


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


# ============= SOURCES =============
# One route per action. A change also rewrites sources.json, the server's list of sources.


@app.get("/api/sources")
@error_detail("load the sources")
async def list_sources():
    """Every source with its settings (platform defaults merged), post_count and in_main_digest."""
    sources = services().sources.get_all_sources_with_settings()
    return {"success": True, "sources": sources, "total": len(sources),
            "total_posts": sum(int(s.get("post_count") or 0) for s in sources)}


OPML_NS = "https://insight.local/opml"
ET.register_namespace("insight", OPML_NS)


def sources_opml(sources: List[Dict[str, Any]], folders: List[Dict[str, Any]],
                 memberships: Dict[str, List[str]]) -> bytes:
    """Every source as an OPML outline (issue 0035): one outline per track, in track order,
    each source under its first track (category names all of them), then the sources in none.
    insight:displayName, insight:pageWatchPrefix ("" when the path is inferred) and
    insight:platform (when not rss) carry what INSIGHT needs to add it back. The built-in
    Saved source (issue 0031) is no subscription and is left out."""
    root = ET.Element("opml", version="2.0")
    ET.SubElement(ET.SubElement(root, "head"), "title").text = "INSIGHT sources"
    body = ET.SubElement(root, "body")
    ordered = sorted(folders, key=lambda f: (f.get("sort_order") or 0, f["name"]))
    names = {f["id"]: f["name"] for f in ordered}
    groups = {f["id"]: ET.SubElement(body, "outline", text=f["name"], title=f["name"]) for f in ordered}
    rank = {f["id"]: i for i, f in enumerate(ordered)}
    outlines = []
    for source in sources:
        if source.get("platform") == saved_kind.PLATFORM:
            continue
        settings = source.get("settings") or {}
        tracks = sorted((fid for fid in memberships.get(source["id"], []) if fid in names), key=rank.get)
        name = str(settings.get("display_name") or "").strip()
        address = source["handle_or_url"]
        attrs = {"type": "rss", "text": name or address, "title": name or address, "xmlUrl": address}
        if tracks:
            attrs["category"] = ",".join(names[fid] for fid in tracks)
        if name:
            attrs[f"{{{OPML_NS}}}displayName"] = name
        if isinstance(settings.get("page_watch"), dict):
            attrs["htmlUrl"] = address
            attrs[f"{{{OPML_NS}}}pageWatchPrefix"] = str(settings["page_watch"].get("prefix") or "")
        if source.get("platform") not in (None, "", "rss"):
            attrs[f"{{{OPML_NS}}}platform"] = source["platform"]
        outlines.append((groups[tracks[0]] if tracks else None, attrs))
    for parent, attrs in outlines:
        if parent is not None:
            ET.SubElement(parent, "outline", attrs)
    for parent, attrs in outlines:
        if parent is None:
            ET.SubElement(body, "outline", attrs)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


@app.get("/api/sources/export.opml")
@error_detail("export the sources")
async def export_sources_opml():
    """Every source as OPML 2.0, grouped by track, for another reader or an off-site copy (issue 0035)."""
    folders_service = services().folders
    sources = services().sources.get_all_sources_with_settings()
    memberships = {s["id"]: folders_service.list_folders_for_source(s["id"]) for s in sources}
    return Response(content=sources_opml(sources, folders_service.list_folders(), memberships),
                    media_type="text/x-opml",
                    headers={"Content-Disposition": 'attachment; filename="insight-sources.opml"'})


@app.post("/api/sources")
@error_detail("add the source")
async def add_source(request: NewSourceRequest):
    """Add one source. 400 when it is already a source or handle_or_url is empty."""
    platform = (request.platform or "rss").strip()
    settings = request.model_dump(include={"display_name", "fetch_delay_seconds", "priority"}, exclude_none=True)
    if request.page_watch is not None:
        settings["page_watch"] = request.page_watch
    created = services().sources.add_with_settings(platform, request.handle_or_url, settings=settings,
                                                   enabled=(request.state or "enabled") == "enabled")
    _export_sources_json()
    return {"success": True, "source_id": created["source_id"], "platform": platform,
            "handle_or_url": created["handle"]}


# The Add source dialog's own client (the feed finder, the page-watch preview): a short timeout,
# and its own few threads, so slow sites asked about never take ingestion's.
FEED_FINDER_HTTP = KindHttp(timeout=5, executor=ThreadPoolExecutor(max_workers=8, thread_name_prefix="add-source-http"))


@app.post("/api/sources/find-feed")
@error_detail("look for the feed")
async def find_feed(request: FindFeedRequest):
    """The feeds for any page address (issue 0026): status feed (it is one), found, direct (a
    kind reads the site itself) or none, with feeds [{url, title}]. 400 when url is empty.
    None for a site's home page (issue 0041): homepage true, and pages, the site's own blog or
    news pages the finder read that can be followed instead, each with its page-watch preview
    ({url, prefix, found, sitemap, items}), the most articles first."""
    finding = await find_feeds(FEED_FINDER_HTTP, services().source_fetch.kinds, request.url)
    homepage = finding.status == "none" and page_watch.is_home(request.url)
    return {"success": True, "status": finding.status,
            "feeds": [{"url": feed.url, "title": feed.title} for feed in finding.feeds],
            "homepage": homepage, "pages": await page_watch.offers(FEED_FINDER_HTTP, finding.pages) if homepage else []}


@app.post("/api/sources/page-watch/preview")
@error_detail("preview the page")
async def preview_page_watch(request: PageWatchPreviewRequest):
    """Following a page without a feed (issue 0028): {prefix, found (article URLs discovered),
    sitemap (some came from the sitemap), items [{url, title, published_at}]}, the first 5 read.
    No items: the page's articles cannot be read (built with JavaScript). 400 when url is empty
    or the page cannot be read."""
    return {"success": True, **await page_watch.preview(FEED_FINDER_HTTP, request.url, request.prefix)}


@app.post("/api/saved")
@error_detail("save the page")
async def save_page(request: SavePageRequest):
    """Save any page (issue 0031) as an unread post of the Saved source, created by the first
    save. {status: saved, post_id, title, source_id, readable, reason, feed} or, for a page
    already stored, {status: already, post_id, title}. readable false: the page could not be
    read as an article and was saved with its title and address (reason says why, never the
    site's answer). feed: a feed of the site that is not a source yet ({url, title}), or null.
    400 when url is empty or not http(s). A POST from INSIGHT's own save page: a website cannot
    save silently."""
    return await services().saved.save(FEED_FINDER_HTTP, request.url, request.title)


@app.put("/api/sources/{source_id}/settings")
@error_detail("update the source settings")
async def update_source_settings(source_id: str, settings: dict):
    """Body: any of {display_name, fetch_delay_seconds, priority}; posts per fetch is the kind's own."""
    result = services().sources.update_source_settings(source_id, settings)
    return {"success": True, "source_id": source_id, "settings": result.get("settings", {})}


@app.put("/api/sources/{source_id}/enabled")
@error_detail("update the source")
async def set_source_enabled(source_id: str, request: SourceEnabledRequest):
    services().sources.update_source_status(source_id, request.enabled)
    _export_sources_json()
    return {"success": True, "source_id": source_id, "enabled": request.enabled}


@app.put("/api/sources/{source_id}/main-digest")
@error_detail("update the main-digest setting")
async def set_source_main_digest(source_id: str, request: MainDigestRequest):
    """Include (true) or exclude (false) one source from the "all" feed."""
    return {"success": True, **services().sources.set_in_main_digest(source_id, request.in_main_digest)}


@app.delete("/api/sources/{source_id}")
@error_detail("delete the source")
async def delete_source(source_id: str):
    """Delete one source and its posts."""
    if not services().sources.delete_source(source_id):
        raise LookupError(f"Source {source_id} not found")
    _export_sources_json()
    return {"success": True, "deleted": True, "source_id": source_id}


@app.post("/api/sources/{source_id}/switch")
@error_detail("switch the source")
async def switch_source(source_id: str, request: SwitchSourceRequest):
    """Point a source at its replacement (issue 0036): a feed, or with page_watch ({} or
    {prefix}) a page to follow. Its id, name, tracks, read state and posts stay; its failures
    clear; sources.json is rewritten in step (the switch is undone when it cannot be). Nothing
    is re-fetched now. 404 for no such source; 400 for a bad address or one already a source."""
    old = await asyncio.to_thread(services().source_config_sync.switch_source, source_id, request.url,
                                  request.page_watch)
    source = services().sources.get_source_by_id(source_id) or {}
    return {"success": True, "source_id": source_id, "handle_or_url": source.get("handle_or_url"),
            "previous": old["handle_or_url"]}


@app.post("/api/sources/{source_id}/replacement/dismiss")
@error_detail("dismiss the replacement")
async def dismiss_replacement(source_id: str):
    """Hide the source doctor's finding until the next failure streak; the fresh health row.
    404 when the source has no finding."""
    return {"success": True, "row": services().operations.dismiss_replacement(source_id)}


@app.get("/api/sources/{source_id}/folders")
@error_detail("load the source's folders")
async def get_source_folders(source_id: str):
    """The folder ids a source belongs to."""
    return {"success": True, "folder_ids": services().folders.list_folders_for_source(source_id)}


# ============= FOLDERS (tracks) =============


@app.get("/api/folders")
@error_detail("load the folders")
async def get_folders():
    """Folders with source and post counts."""
    folders = services().folders.list_folders()
    return {"success": True, "folders": folders, "total": len(folders)}


@app.post("/api/folders")
@error_detail("create the folder")
async def create_folder(config: dict):
    """Create a folder or track.

    Body: {name, description?, sort_order?, kind?, exclude_from_main_digest?, match_keywords?}
    kind is "folder" (default) or "track".
    """
    name = str(config.get("name") or "").strip()
    if not name:
        raise ValueError("Folder name is required")
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
@error_detail("update the folder")
async def update_folder(folder_id: str, fields: dict):
    """Body: any of {name, description, sort_order, kind, exclude_from_main_digest, match_keywords}"""
    return {"success": True, "folder": services().folders.update_folder(folder_id, fields)}


@app.delete("/api/folders/{folder_id}")
@error_detail("delete the folder")
async def delete_folder(folder_id: str):
    if not services().folders.delete_folder(folder_id):
        raise LookupError(f"Folder {folder_id} not found")
    return {"success": True, "deleted": True, "folder_id": folder_id}


@app.post("/api/folders/{folder_id}/sources")
@error_detail("add the source to the folder")
async def add_folder_source(folder_id: str, request: FolderSourceRequest):
    """Attach a source to a folder. Body: {source_id}"""
    source_id = request.source_id.strip()
    if not source_id:
        raise ValueError("source_id is required")
    added = services().folders.add_source(folder_id, source_id)
    return {"success": True, "added": added, "folder_id": folder_id, "source_id": source_id}


@app.delete("/api/folders/{folder_id}/sources/{source_id}")
@error_detail("remove the source from the folder")
async def remove_folder_source(folder_id: str, source_id: str):
    removed = services().folders.remove_source(folder_id, source_id)
    return {"success": True, "removed": removed, "folder_id": folder_id, "source_id": source_id}


@app.put("/api/folders/{folder_id}/main-digest")
@error_detail("update the main-digest setting")
async def set_folder_main_digest(folder_id: str, request: MainDigestRequest):
    """Apply the digest switch to every source in a folder/track. Sending false keeps a
    track's sources out of the "all" feed while they are still ingested. The sources hold the
    answer; the track shows what its sources say (issue 0027)."""
    result = services().sources.set_folder_in_main_digest(folder_id, request.in_main_digest)
    return {"success": True, **result}


@app.post("/api/folders/{folder_id}/ingest")
async def ingest_folder(folder_id: str, background_tasks: BackgroundTasks, body: dict | None = None):
    """Fetch every enabled source in a folder/track now (forced). Body: {limit?: int}.

    Returns 202 with the ingestion_run job; poll /api/operations/jobs/{id} for the run report.
    Politeness comes from the source kinds' profiles and the host floors, not a delay knob.
    """
    limit = (body or {}).get("limit")
    request = FetchRequest(SourceSelector.folder(folder_id), Trigger.MANUAL, force=True, limit=limit)
    return _accept_ingestion_run(background_tasks, request, message=f"Fetch track {folder_id}")


# ============= ARCHIVE =============


@app.get("/api/archive/{source_id}/status")
@error_detail("load the archive status")
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
@error_detail("load the archive catalog")
async def get_archive_catalog():
    """List enabled sources with their persisted archive status."""
    catalog = services().source_fetch.archive_catalog()
    return {"success": True, "sources": catalog, "total": len(catalog)}


@app.post("/api/archive/{source_id}/plan")
@error_detail("plan the archive")
async def plan_archive(source_id: str, request: ArchiveRequest):
    """Measure a source and say where its archive continues from and how much is older."""
    logger.info(f"🧭 Planning archive for source: {source_id}")
    try:
        plan = await services().source_fetch.plan_archive(
            source_id,
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
@error_detail("run the archive")
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


@app.get("/api/version")
async def get_version():
    """The build this image was stamped with (INSIGHT_VERSION, INSIGHT_COMMIT,
    INSIGHT_COMMIT_DATE; issue 0020). Each is null when unset, as in local dev."""
    return {key: os.getenv(f"INSIGHT_{key.upper()}") or None for key in ("version", "commit", "commit_date")}


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
@error_detail("read the log")
async def get_ingestion_logs(
    log: str = Query(default="application"),
    lines: int = Query(default=200, ge=1, le=1000),
):
    """Return recent shared backend/ingestion log lines."""
    return services().system_logs.get_log_tail(log, lines)


@app.get("/api/operations/overview")
@error_detail("load the operations overview")
async def get_operations_overview():
    return services().operations.get_operations_overview()


@app.get("/api/operations/jobs/{job_id}")
@error_detail("load the job")
async def get_operation_job(job_id: str):
    job = services().operations.get_job(job_id)
    if not job:
        raise LookupError(f"Job {job_id} not found")
    return {"success": True, "job": job}


@app.get("/api/operations/scheduler")
@error_detail("load the scheduler settings")
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
@error_detail("save the scheduler settings")
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

@app.get("/api/youtube/progress/{video_id}")
@error_detail("load the watch progress")
async def get_youtube_watch_progress(video_id: str):
    return {"success": True, "progress": services().youtube.get_watch_progress(video_id)}


@app.put("/api/youtube/progress/{video_id}")
@error_detail("save the watch progress")
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
