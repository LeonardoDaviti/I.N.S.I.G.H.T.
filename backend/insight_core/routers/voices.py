"""Voices' routes (issue 0132 A): an APIRouter, included by main.py in one line. The app's own (no bearer).

GET    /api/voices                         {voices: [voice]}: every voice the owner keeps
GET    /api/voices/suggestions             {computed_at, computing, voices: [{key, sources, edges [{a, b, verdict,
                                           evidence [{rule, line, posts}]}], voice_ids, same_channel}], possible, related}
POST   /api/voices/suggestions/refresh     {started}: judge every pair again, in the background
POST   /api/voices                         {source_ids, voice_id?, name?, kind?, evidence?, by_hand?} -> {voice,
                                           queued_sources}: Join (a suggestion) or Make a voice (by_hand)
GET    /api/voices/{voice_id}              {voice, not_followed [{key, url, label, platform, of, why}]}
GET    /api/voices/profiles/setting        {on}: channel profiles fetched monthly (0132 C2; on by default)
PUT    /api/voices/profiles/setting        {on} -> {on}
                                           (suggestions also carry not_followed [{subject {kind, id, name}, channels}]
                                           and profiles: how many current profiles they read)
PUT    /api/voices/{voice_id}              {name?, kind?} -> {voice}
DELETE /api/voices/{voice_id}              the voice removed; its channels stay sources -> {source_ids, queued_sources}
POST   /api/voices/not-same                {a, b, evidence?}: never suggested together again
POST   /api/voices/related                 {a, b, evidence?} -> {voices}: two related voices (staff <-> company)
POST   /api/voices/leave                   {source_id}: a channel leaves its voice
GET    /api/sources/{source_id}/voice      {voice | null}

A voice is {id, name, kind, entity_id, created_at, confirmed_at, channels [{id, name, platform, kind, enabled,
in_main_digest, priority, posts, last_post_at}], related [{id, name, evidence}], in_main_digest, priority}.
A bad body is 400 {"detail"}, an unknown id 404.
"""
from __future__ import annotations

import functools
import uuid
from typing import Any, Callable, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["voices"])
_service: Optional[Any] = None


def service():
    """The voices service, built once per process from the app's database."""
    global _service
    if _service is None:
        from insight_core.services.registry import services
        from insight_core.services.voices_service import VoicesService
        _service = VoicesService(services().db_url)
    return _service


def use(svc: Any) -> None:
    """Tests: answer from this service (None: build it again)."""
    global _service
    _service = svc


def answered(fn: Callable) -> Callable:
    """A ValueError is 400, a LookupError 404, each {"detail"}."""
    @functools.wraps(fn)
    def run(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
    return run


def _id(value: str, what: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except ValueError:
        raise ValueError(f"{what} must be a uuid") from None


class JoinRequest(BaseModel):
    source_ids: List[str]
    voice_id: Optional[str] = None
    name: Optional[str] = None
    kind: Optional[str] = None
    evidence: Optional[Any] = None
    by_hand: bool = False


class PairRequest(BaseModel):
    a: str
    b: str
    evidence: Optional[Any] = None


class LeaveRequest(BaseModel):
    source_id: str


class RenameRequest(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None


@router.get("/api/voices")
@answered
def list_voices():
    return service().voices()


@router.get("/api/voices/suggestions")
@answered
def suggestions():
    return service().suggestions()


@router.post("/api/voices/suggestions/refresh")
@answered
def refresh_suggestions():
    return {"success": True, "started": service().start_refresh()}


@router.post("/api/voices")
@answered
def join(request: JoinRequest):
    return service().join([_id(s, "source id") for s in request.source_ids],
                          voice_id=_id(request.voice_id, "voice id") if request.voice_id else None,
                          name=request.name, kind=request.kind, evidence=request.evidence, by_hand=request.by_hand)


@router.post("/api/voices/not-same")
@answered
def not_same(request: PairRequest):
    return service().not_same(_id(request.a, "source id"), _id(request.b, "source id"), request.evidence)


@router.post("/api/voices/related")
@answered
def related(request: PairRequest):
    return service().related(_id(request.a, "source id"), _id(request.b, "source id"), request.evidence)


@router.post("/api/voices/leave")
@answered
def leave(request: LeaveRequest):
    return service().leave(_id(request.source_id, "source id"))


class ProfilesSettingRequest(BaseModel):
    on: bool


@router.get("/api/voices/profiles/setting")
@answered
def profiles_setting():
    return service().profiles_setting()


@router.put("/api/voices/profiles/setting")
@answered
def set_profiles_setting(request: ProfilesSettingRequest):
    return service().set_profiles_setting(request.on)


@router.get("/api/voices/{voice_id}")
@answered
def get_voice(voice_id: str):
    return service().voice(_id(voice_id, "voice id"))


@router.put("/api/voices/{voice_id}")
@answered
def rename(voice_id: str, request: RenameRequest):
    fields = request.model_fields_set if hasattr(request, "model_fields_set") else request.__fields_set__
    return service().rename(_id(voice_id, "voice id"), request.name, request.kind, set_kind="kind" in fields)


@router.delete("/api/voices/{voice_id}")
@answered
def remove(voice_id: str):
    return service().remove(_id(voice_id, "voice id"))


@router.get("/api/sources/{source_id}/voice")
@answered
def voice_of_source(source_id: str):
    return service().of_source(_id(source_id, "source id"))
