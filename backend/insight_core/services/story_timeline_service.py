"""Post-centric story timeline and narrative trace orchestration."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import psycopg

from insight_core.db.repo_story_candidates import StoryCandidateRepository
from insight_core.logs.core.logger_config import get_component_logger
from insight_core.services.post_detail_service import PostDetailService
from insight_core.services.stories_service import StoriesService


class StoryTimelineService:
    """Build timeline views for one post using the existing story layer."""

    AUTO_ACCEPT_THRESHOLD = 0.92
    PROPOSE_THRESHOLD = 0.42

    def __init__(self, db_url: str):
        self.db_url = db_url
        self.repo = StoryCandidateRepository(db_url)
        self.post_detail_service = PostDetailService(db_url)
        self.stories_service = StoriesService(db_url)
        self.logger = get_component_logger("story_timeline_service")

    def get_post_timeline(self, post_id: str, *, refresh: bool = False) -> Dict[str, Any]:
        source_post = self.post_detail_service.get_post_by_id(post_id)
        if not source_post:
            raise ValueError(f"Post {post_id} not found")

        post_story = self.stories_service.get_post_story(post_id)
        primary_story = post_story.get("primary_story")

        if refresh:
            candidates = self._refresh_candidates(source_post, primary_story)
        else:
            candidates = self._load_candidates(post_id)
            if not candidates:
                candidates = self._refresh_candidates(source_post, primary_story)

        story_detail = None
        timeline_view = self._empty_timeline_view()
        if primary_story and primary_story.get("id"):
            story_detail = self.stories_service.get_story_detail(str(primary_story["id"]))
            timeline_view = self._build_timeline_view(story_detail, post_id)

        return {
            "success": True,
            "post_id": post_id,
            "post": source_post,
            "has_story": bool(primary_story),
            "primary_story": primary_story,
            "story": story_detail,
            "timeline": timeline_view,
            "related_candidates": candidates,
            "refreshed": bool(refresh),
        }

    def refresh_post_timeline(self, post_id: str) -> Dict[str, Any]:
        return self.get_post_timeline(post_id, refresh=True)

    def accept_candidate(self, candidate_id: str) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                candidate = self.repo.get_candidate_by_id(cur, candidate_id)
                if not candidate:
                    raise ValueError(f"Story candidate {candidate_id} not found")

                source_story = self.stories_service.get_post_story(candidate["source_post_id"])
                target_story = (
                    candidate.get("candidate_story_id")
                    or (source_story.get("primary_story") or {}).get("id")
                )
                if not target_story:
                    raise ValueError("Candidate cannot be accepted because no target story exists")

                source_post = self.post_detail_service.get_post_by_id(candidate["source_post_id"])
                candidate_post = self.post_detail_service.get_post_by_id(candidate["candidate_post_id"])
                if not source_post or not candidate_post:
                    raise ValueError("Source or candidate post is missing")

                self._attach_candidate_to_story(
                    target_story,
                    source_post=source_post,
                    candidate_post=candidate_post,
                    candidate=candidate,
                )

                updated = self.repo.update_candidate_decision(
                    cur,
                    candidate_id,
                    decision_status="accepted",
                    decision_reason=candidate.get("decision_reason") or "Accepted into story timeline",
                    candidate_story_id=target_story,
                    metadata={"accepted_manually": True},
                )
                conn.commit()

        timeline = self.get_post_timeline(candidate["source_post_id"], refresh=False)
        return {
            "success": True,
            "candidate": updated,
            "timeline": timeline,
        }

    def reject_candidate(self, candidate_id: str) -> Dict[str, Any]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                candidate = self.repo.get_candidate_by_id(cur, candidate_id)
                if not candidate:
                    raise ValueError(f"Story candidate {candidate_id} not found")
                updated = self.repo.update_candidate_decision(
                    cur,
                    candidate_id,
                    decision_status="rejected",
                    decision_reason="Rejected from this story timeline",
                    metadata={"rejected_manually": True},
                )
                conn.commit()

        timeline = self.get_post_timeline(candidate["source_post_id"], refresh=False)
        return {
            "success": True,
            "candidate": updated,
            "timeline": timeline,
        }

    def _refresh_candidates(
        self,
        source_post: Dict[str, Any],
        primary_story: Dict[str, Any] | None,
    ) -> List[Dict[str, Any]]:
        primary_story_id = str(primary_story["id"]) if primary_story and primary_story.get("id") else None
        candidate_rows = self._load_candidate_pool(source_post, primary_story_id=primary_story_id)

        prepared: List[Dict[str, Any]] = []
        for candidate in candidate_rows:
            scored = self._score_candidate(source_post, candidate, primary_story_id=primary_story_id)
            if not scored:
                continue
            prepared.append(scored)

        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                self.repo.replace_candidates_for_post(cur, str(source_post["id"]), prepared)
                conn.commit()

        candidates = self._load_candidates(str(source_post["id"]))
        if primary_story_id:
            for candidate in candidates:
                if candidate.get("decision_status") != "accepted":
                    continue
                candidate_post = candidate.get("candidate_post") or {}
                try:
                    self._attach_candidate_to_story(
                        primary_story_id,
                        source_post=source_post,
                        candidate_post=candidate_post,
                        candidate=candidate,
                    )
                except Exception as exc:
                    self.logger.warning("Failed to auto-attach candidate %s to story %s: %s", candidate.get("id"), primary_story_id, exc)
        return candidates

    def _load_candidates(self, post_id: str) -> List[Dict[str, Any]]:
        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                return self.repo.get_candidates_for_post(cur, post_id, limit=20)

    def _load_candidate_pool(
        self,
        source_post: Dict[str, Any],
        *,
        primary_story_id: str | None,
        window_days: int = 30,
        limit: int = 120,
    ) -> List[Dict[str, Any]]:
        source_timestamp = self._post_timestamp(source_post) or datetime.now(timezone.utc)
        start = source_timestamp - timedelta(days=window_days)
        end = source_timestamp + timedelta(days=window_days)

        with psycopg.connect(self.db_url) as conn:
            with conn.cursor() as cur:
                params: List[Any] = [str(source_post["id"]), start, end]
                exclude_same_story = ""
                if primary_story_id:
                    exclude_same_story = """
                        AND NOT EXISTS (
                            SELECT 1 FROM story_posts existing_sp
                            WHERE existing_sp.post_id = p.id AND existing_sp.story_id = %s
                        )
                    """
                    params.append(primary_story_id)
                params.extend([source_timestamp, int(limit)])
                cur.execute(
                    f"""
                    SELECT
                        p.id,
                        p.title,
                        p.content,
                        p.published_at,
                        p.fetched_at,
                        p.categories,
                        p.normalized_url,
                        p.canonical_url,
                        p.title_hash,
                        p.content_hash,
                        p.url_host,
                        p.source_id,
                        p.title_pivot,
                        p.summary_pivot,
                        s.platform,
                        s.handle_or_url,
                        candidate_story.story_id
                    FROM posts p
                    JOIN sources s ON s.id = p.source_id
                    LEFT JOIN LATERAL (
                        SELECT sp.story_id
                        FROM story_posts sp
                        JOIN stories st ON st.id = sp.story_id
                        WHERE sp.post_id = p.id
                        ORDER BY
                            CASE sp.role WHEN 'anchor' THEN 0 ELSE 1 END,
                            COALESCE(st.last_seen_at, st.created_at) DESC
                        LIMIT 1
                    ) candidate_story ON TRUE
                    WHERE p.id <> %s
                      AND COALESCE(p.published_at, p.fetched_at, p.created_at) BETWEEN %s AND %s
                      {exclude_same_story}
                    ORDER BY ABS(EXTRACT(EPOCH FROM (COALESCE(p.published_at, p.fetched_at, p.created_at) - %s))) ASC
                    LIMIT %s
                    """,
                    params,
                )
                rows = cur.fetchall()

        pool: List[Dict[str, Any]] = []
        for row in rows:
            pool.append(
                {
                    "id": str(row[0]),
                    "title": row[1],
                    "content": row[2],
                    "published_at": row[3].isoformat() if row[3] else None,
                    "fetched_at": row[4].isoformat() if row[4] else None,
                    "categories": row[5] or [],
                    "normalized_url": row[6],
                    "canonical_url": row[7],
                    "title_hash": row[8],
                    "content_hash": row[9],
                    "url_host": row[10],
                    "source_id": str(row[11]) if row[11] else None,
                    "title_pivot": row[12],
                    "summary_pivot": row[13],
                    "platform": row[14],
                    "source": row[15],
                    "source_display_name": row[15],
                    "candidate_story_id": str(row[16]) if row[16] else None,
                }
            )
        return pool

    def _score_candidate(
        self,
        source_post: Dict[str, Any],
        candidate: Dict[str, Any],
        *,
        primary_story_id: str | None,
    ) -> Optional[Dict[str, Any]]:
        score = 0.0
        signals: List[str] = []
        method = "title_similarity"
        method_rank = 0

        def set_method(name: str, rank: int) -> None:
            nonlocal method, method_rank
            if rank > method_rank:
                method = name
                method_rank = rank

        if source_post.get("canonical_url") and source_post.get("canonical_url") == candidate.get("canonical_url"):
            score = max(score, 1.0)
            signals.append("same canonical URL")
            set_method("same_canonical_url", 95)
        if source_post.get("normalized_url") and source_post.get("normalized_url") == candidate.get("normalized_url"):
            score = max(score, 0.98)
            signals.append("same normalized URL")
            set_method("same_normalized_url", 100)
        if source_post.get("content_hash") and source_post.get("content_hash") == candidate.get("content_hash"):
            score = max(score, 0.98)
            signals.append("same content hash")
            set_method("same_content_hash", 90)
        if source_post.get("title_hash") and source_post.get("title_hash") == candidate.get("title_hash"):
            score = max(score, 0.86)
            signals.append("same title hash")
            set_method("same_title_hash", 80)

        title_similarity = self._token_similarity(
            " ".join(filter(None, [source_post.get("title"), source_post.get("title_pivot")])),
            " ".join(filter(None, [candidate.get("title"), candidate.get("title_pivot")])),
        )
        if title_similarity >= 0.72:
            score = max(score, 0.74)
            signals.append(f"title overlap {title_similarity:.2f}")
            set_method("title_similarity", 50)
        elif title_similarity >= 0.45:
            score = max(score, 0.52)
            signals.append(f"title overlap {title_similarity:.2f}")

        summary_similarity = self._token_similarity(
            " ".join(filter(None, [source_post.get("summary_pivot"), source_post.get("content")])),
            " ".join(filter(None, [candidate.get("summary_pivot"), candidate.get("content")])),
        )
        if summary_similarity >= 0.65:
            score = max(score, 0.68)
            signals.append(f"summary overlap {summary_similarity:.2f}")
            set_method("summary_similarity", 40)
        elif summary_similarity >= 0.42:
            score = max(score, 0.49)
            signals.append(f"summary overlap {summary_similarity:.2f}")

        shared_categories = sorted(set(source_post.get("categories") or []).intersection(candidate.get("categories") or []))
        if shared_categories:
            score += min(0.12, 0.04 * len(shared_categories))
            signals.append(f"shared tags: {', '.join(shared_categories[:3])}")

        if source_post.get("url_host") and source_post.get("url_host") == candidate.get("url_host") and title_similarity >= 0.3:
            score += 0.08
            signals.append("same host")

        time_delta_days = self._time_delta_days(source_post, candidate)
        if time_delta_days is not None and time_delta_days <= 3:
            score += 0.08
            signals.append(f"{time_delta_days}d apart")
        elif time_delta_days is not None and time_delta_days <= 10:
            score += 0.04
            signals.append(f"{time_delta_days}d apart")

        score = min(score, 1.0)
        if score < self.PROPOSE_THRESHOLD:
            return None

        temporal_relation = self._temporal_relation(source_post, candidate)
        auto_accept = bool(primary_story_id) and (
            method in {"same_canonical_url", "same_normalized_url", "same_content_hash"}
            or (score >= self.AUTO_ACCEPT_THRESHOLD and title_similarity >= 0.72)
        )
        decision_status = "accepted" if auto_accept else "proposed"
        decision_reason = "; ".join(signals[:4]) or "Candidate retrieved for story timeline review"
        return {
            "candidate_post_id": str(candidate["id"]),
            "candidate_story_id": primary_story_id if auto_accept else candidate.get("candidate_story_id"),
            "retrieval_method": method,
            "retrieval_score": round(score, 3),
            "decision_status": decision_status,
            "decision_reason": decision_reason,
            "metadata": {
                "signals": signals,
                "temporal_relation": temporal_relation,
                "title_similarity": round(title_similarity, 3),
                "summary_similarity": round(summary_similarity, 3),
                "candidate_story_id": candidate.get("candidate_story_id"),
            },
        }

    def _attach_candidate_to_story(
        self,
        story_id: str,
        *,
        source_post: Dict[str, Any],
        candidate_post: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> None:
        role = self._candidate_story_role(source_post, candidate_post, candidate)
        score = float(candidate.get("retrieval_score") or 0.0)
        self.stories_service.attach_post_to_story(
            story_id,
            str(candidate_post["id"]),
            role=role,
            relevance_score=score,
            anchor_score=0.0,
            is_anchor_candidate=False,
            evidence_weight=score,
            added_by_method="story_timeline_auto",
            metadata={
                "source_post_id": str(source_post["id"]),
                "candidate_id": candidate.get("id"),
                "temporal_relation": (candidate.get("metadata") or {}).get("temporal_relation"),
                "signals": (candidate.get("metadata") or {}).get("signals") or [],
            },
        )

        candidate_date = self._post_timestamp(candidate_post)
        if candidate_date is None:
            return

        detail = self.stories_service.get_story_detail(story_id)
        if not detail:
            return

        first_seen = self._normalize_datetime(detail.get("first_seen_at"))
        last_seen = self._normalize_datetime(detail.get("last_seen_at"))
        update_fields: Dict[str, Any] = {}
        if first_seen is None or candidate_date < first_seen:
            update_fields["first_seen_at"] = candidate_date
        if last_seen is None or candidate_date > last_seen:
            update_fields["last_seen_at"] = candidate_date
        if update_fields:
            self.stories_service.update_story(story_id, **update_fields)

        update_date = candidate_date.date()
        existing_update = next(
            (update for update in detail.get("updates", []) if str(update.get("update_date")) == update_date.isoformat()),
            None,
        )
        if existing_update:
            self.stories_service.attach_post_to_story_update(existing_update["id"], str(candidate_post["id"]), role=role)
            return

        self.stories_service.create_story_update(
            story_id,
            update_date,
            title=str(candidate_post.get("title") or detail.get("canonical_title") or "Story update"),
            summary=self._candidate_update_summary(candidate_post, candidate),
            importance_score=score,
            created_by_method="story_timeline_auto",
            metadata={
                "source_post_id": str(source_post["id"]),
                "candidate_id": candidate.get("id"),
                "auto_generated": True,
            },
            post_ids=[str(candidate_post["id"])],
        )

    def _build_timeline_view(self, story_detail: Dict[str, Any] | None, post_id: str) -> Dict[str, Any]:
        if not story_detail:
            return self._empty_timeline_view()

        updates = list(story_detail.get("timeline") or [])
        current_update = None
        earlier: List[Dict[str, Any]] = []
        later: List[Dict[str, Any]] = []
        grouped_dates: List[str] = []

        for update in updates:
            posts = list(update.get("posts") or [])
            update_copy = {
                **update,
                "contains_current_post": any(str(item.get("post_id")) == post_id for item in posts),
            }
            grouped_dates.append(str(update.get("update_date") or ""))
            if update_copy["contains_current_post"]:
                current_update = update_copy

        if current_update:
            current_date = str(current_update.get("update_date") or "")
            for update in updates:
                update_copy = {
                    **update,
                    "contains_current_post": current_update.get("id") == update.get("id"),
                }
                update_date = str(update.get("update_date") or "")
                if update_copy["contains_current_post"]:
                    continue
                if update_date < current_date:
                    earlier.append(update_copy)
                else:
                    later.append(update_copy)
        else:
            earlier = list(updates)

        return {
            "grouped_dates": [value for value in grouped_dates if value],
            "current_update": current_update,
            "earlier_updates": earlier,
            "later_updates": later,
            "total_updates": len(updates),
        }

    def _empty_timeline_view(self) -> Dict[str, Any]:
        return {
            "grouped_dates": [],
            "current_update": None,
            "earlier_updates": [],
            "later_updates": [],
            "total_updates": 0,
        }

    def _candidate_story_role(
        self,
        source_post: Dict[str, Any],
        candidate_post: Dict[str, Any],
        candidate: Dict[str, Any],
    ) -> str:
        method = str(candidate.get("retrieval_method") or "")
        if method in {"same_canonical_url", "same_normalized_url", "same_content_hash"}:
            return "corroboration"
        relation = (candidate.get("metadata") or {}).get("temporal_relation")
        if relation == "later":
            return "follow_up"
        if relation == "earlier":
            return "context"
        source_title = str(source_post.get("title") or "").strip().lower()
        candidate_title = str(candidate_post.get("title") or "").strip().lower()
        if source_title and candidate_title and source_title != candidate_title:
            return "commentary"
        return "context"

    def _candidate_update_summary(self, candidate_post: Dict[str, Any], candidate: Dict[str, Any]) -> str:
        signals = (candidate.get("metadata") or {}).get("signals") or []
        reason = "; ".join(str(signal) for signal in signals[:3]) or str(candidate.get("decision_reason") or "")
        title = str(candidate_post.get("title") or "Update").strip()
        if reason:
            return f"{title}. Timeline attachment reason: {reason}."
        return title

    def _post_timestamp(self, post: Dict[str, Any]) -> Optional[datetime]:
        for key in ("published_at", "fetched_at", "created_at", "date"):
            value = post.get(key)
            normalized = self._normalize_datetime(value)
            if normalized is not None:
                return normalized
        return None

    def _normalize_datetime(self, value: Any) -> Optional[datetime]:
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        if not value:
            return None
        try:
            text = str(value).replace("Z", "+00:00")
            normalized = datetime.fromisoformat(text)
            return normalized if normalized.tzinfo else normalized.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def _time_delta_days(self, source_post: Dict[str, Any], candidate_post: Dict[str, Any]) -> Optional[int]:
        source_dt = self._post_timestamp(source_post)
        candidate_dt = self._post_timestamp(candidate_post)
        if not source_dt or not candidate_dt:
            return None
        return abs((candidate_dt - source_dt).days)

    def _temporal_relation(self, source_post: Dict[str, Any], candidate_post: Dict[str, Any]) -> str:
        source_dt = self._post_timestamp(source_post)
        candidate_dt = self._post_timestamp(candidate_post)
        if not source_dt or not candidate_dt:
            return "unknown"
        if candidate_dt.date() == source_dt.date():
            return "same_day"
        return "earlier" if candidate_dt < source_dt else "later"

    def _token_similarity(self, left: str, right: str) -> float:
        left_tokens = self._tokenize(left)
        right_tokens = self._tokenize(right)
        if not left_tokens or not right_tokens:
            return 0.0
        intersection = len(left_tokens.intersection(right_tokens))
        union = len(left_tokens.union(right_tokens))
        return intersection / union if union else 0.0

    def _tokenize(self, value: str) -> set[str]:
        text = str(value or "").lower()
        tokens = {
            token
            for token in re.findall(r"[a-z0-9]{3,}", text)
            if token not in {"with", "from", "that", "this", "about", "into", "over", "after", "before", "their", "there", "have", "been"}
        }
        return tokens
