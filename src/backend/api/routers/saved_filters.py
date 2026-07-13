"""User saved-filters endpoints.

Self-contained router (mounted at ``/api/users/saved-filters``) covering scalar
saved filters and the keyword-list CRUD sub-resource. All routes require a
logged-in user (``get_current_user``) and resolve the DB user by email
(``get_user_by_email``), mirroring ``routers/users.py``. (Canonical-location
search moved to the public ``routers/locations.py`` — the Recent/Trend filter
dropdowns it feeds must work signed-out.)

Service exceptions are mapped to HTTP status codes here:

* ``UnknownActiveList``        -> 409 (PUT saved-filters pointer not owned)
* ``DuplicateListName``        -> 409 (create/rename collision or reserved name)
* ``KeywordListLimitReached``  -> 422 (per-user list cap)
* ``KeywordListNotFound``      -> 404 (PATCH/DELETE not owned)
* ``BuiltinListReadOnly``      -> 422 (PATCH/DELETE the built-in id)
"""

import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Path, status
from posthog import identify_context, new_context
from psycopg2.extensions import connection as Connection

from ..auth.dependencies import TokenClaims, get_current_user
from ..auth.jwt import get_normalized_subject
from ..dependencies import get_db
from ..models import (
    KeywordListCreateRequest,
    KeywordListResponse,
    KeywordListsResponse,
    KeywordListUpdateRequest,
    SavedFiltersResponse,
    SavedFiltersUpdateRequest,
)
from ..services import saved_filters_service
from ..services.posthog_client import get_posthog
from ..services.saved_filters_service import (
    BuiltinListReadOnly,
    DuplicateListName,
    KeywordListLimitReached,
    KeywordListNotFound,
    KeywordListRow,
    SavedFiltersRow,
    UnknownActiveList,
)
from ..services.user_service import get_user_by_email

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_email(user: TokenClaims) -> str:
    email = user.get("email")
    if not email:
        raise HTTPException(
            status_code=401, detail="Token missing required 'email' claim"
        )
    return email


def _resolve_user_id(conn: Connection, user: TokenClaims) -> str:
    """Resolve the caller's DB user id by email, 404 if no row.

    Mirrors the PUT enabled-companies handler (``users.py``): the user row is
    created lazily on first ``GET /api/users``, so a saved-filters mutation before
    that returns 404.
    """
    email = _require_email(user)
    row = get_user_by_email(conn, email)
    if row is None:
        raise HTTPException(status_code=404, detail="User not found")
    return row["id"]


def _saved_filters_response(prefs: SavedFiltersRow) -> SavedFiltersResponse:
    # ``model_validate`` over the snake_case dict (``populate_by_name=True``)
    # also runs the ``TimeWindow`` Literal check at runtime: a corrupt stored
    # window surfaces as a 500 rather than being silently coerced.
    return SavedFiltersResponse.model_validate(prefs)


def _keyword_list_response(row: KeywordListRow) -> KeywordListResponse:
    # ``model_validate`` validates each tag's ``mode`` Literal and the row shape
    # without per-field casts; ``row["tags"]`` is a list of {text, mode} dicts.
    return KeywordListResponse.model_validate(row)


# --- Scalar saved filters -----------------------------------------------------


@router.get("", response_model=SavedFiltersResponse)
def get_saved_filters(
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> SavedFiltersResponse:
    """Return the caller's scalar saved filters, or server defaults.

    Never 404s: a user with no row (or no users row yet) gets the defaults.
    """
    email = _require_email(user)
    row = get_user_by_email(conn, email)
    if row is None:
        return _saved_filters_response(saved_filters_service.default_saved_filters())
    try:
        prefs = saved_filters_service.get_saved_filters(conn, row["id"])
    except psycopg2.Error:
        conn.rollback()
        logger.exception("Failed to load saved filters for user=%s", row["id"])
        raise HTTPException(status_code=500, detail="Failed to load saved filters")
    return _saved_filters_response(prefs)


@router.put("", response_model=SavedFiltersResponse)
def put_saved_filters(
    body: SavedFiltersUpdateRequest,
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> SavedFiltersResponse:
    """Full-replace the caller's scalar saved filters (upsert)."""
    user_id = _resolve_user_id(conn, user)
    try:
        prefs = saved_filters_service.upsert_saved_filters(
            conn,
            user_id,
            recent_time_window=body.recent_time_window,
            trend_time_window=body.trend_time_window,
            locations=body.locations,
            category=body.category,
            level=body.level,
            recent_active_keyword_list_id=body.recent_active_keyword_list_id,
            trend_active_keyword_list_id=body.trend_active_keyword_list_id,
        )
    except UnknownActiveList:
        raise HTTPException(
            status_code=409,
            detail="An active keyword list id does not exist or is not yours",
        )
    except psycopg2.Error:
        logger.exception("Failed to save saved filters for user=%s", user_id)
        raise HTTPException(status_code=500, detail="Failed to save saved filters")
    auth0_id = get_normalized_subject(user)
    ph = get_posthog()
    if ph and auth0_id:
        try:
            with new_context():
                identify_context(auth0_id)
                ph.capture(
                    "saved_filters_updated",
                    distinct_id=auth0_id,
                    properties={
                        "recent_time_window": body.recent_time_window,
                        "trend_time_window": body.trend_time_window,
                        "location_count": len(body.locations) if body.locations else 0,
                        "category_count": len(body.category) if body.category else 0,
                        "level_count": len(body.level) if body.level else 0,
                        "has_recent_keyword_list": body.recent_active_keyword_list_id is not None,
                        "has_trend_keyword_list": body.trend_active_keyword_list_id is not None,
                    },
                )
        except Exception:
            logger.warning(
                "PostHog capture failed for saved_filters_updated", exc_info=True
            )
    return _saved_filters_response(prefs)


# --- Keyword lists ------------------------------------------------------------


@router.get("/keyword-lists", response_model=KeywordListsResponse)
def get_keyword_lists(
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> KeywordListsResponse:
    """List the caller's keyword lists (by position), built-in "Software
    Engineering" list last. Never 404s — a user with no row gets just the
    built-in list."""
    email = _require_email(user)
    row = get_user_by_email(conn, email)
    if row is None:
        return KeywordListsResponse(
            lists=[_keyword_list_response(saved_filters_service.builtin_swe_list())]
        )
    try:
        rows = saved_filters_service.list_keyword_lists(conn, row["id"])
    except psycopg2.Error:
        conn.rollback()
        logger.exception("Failed to list keyword lists for user=%s", row["id"])
        raise HTTPException(
            status_code=500, detail="Failed to load keyword lists"
        )
    return KeywordListsResponse(
        lists=[_keyword_list_response(r) for r in rows]
    )


@router.post(
    "/keyword-lists",
    response_model=KeywordListResponse,
    status_code=status.HTTP_201_CREATED,
)
def post_keyword_list(
    body: KeywordListCreateRequest,
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> KeywordListResponse:
    """Create a new keyword list."""
    user_id = _resolve_user_id(conn, user)
    tags = [{"text": t.text, "mode": t.mode} for t in body.tags]
    try:
        row = saved_filters_service.create_keyword_list(
            conn, user_id, name=body.name, tags=tags
        )
    except DuplicateListName:
        raise HTTPException(
            status_code=409, detail="A list with that name already exists"
        )
    except KeywordListLimitReached:
        raise HTTPException(
            status_code=422,
            detail=(
                "Keyword list limit reached "
                f"({saved_filters_service.MAX_KEYWORD_LISTS_PER_USER})"
            ),
        )
    except psycopg2.Error:
        logger.exception("Failed to create keyword list for user=%s", user_id)
        raise HTTPException(
            status_code=500, detail="Failed to create keyword list"
        )
    auth0_id = get_normalized_subject(user)
    ph = get_posthog()
    if ph and auth0_id:
        try:
            with new_context():
                identify_context(auth0_id)
                ph.capture(
                    "keyword_list_created",
                    distinct_id=auth0_id,
                    properties={"tag_count": len(tags)},
                )
        except Exception:
            logger.warning(
                "PostHog capture failed for keyword_list_created", exc_info=True
            )
    return _keyword_list_response(row)


@router.patch("/keyword-lists/{list_id}", response_model=KeywordListResponse)
def patch_keyword_list(
    body: KeywordListUpdateRequest,
    list_id: str = Path(min_length=1, max_length=64),
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> KeywordListResponse:
    """Rename / replace tags / reorder a keyword list (partial update)."""
    user_id = _resolve_user_id(conn, user)
    tags = (
        [{"text": t.text, "mode": t.mode} for t in body.tags]
        if body.tags is not None
        else None
    )
    try:
        row = saved_filters_service.update_keyword_list(
            conn,
            user_id,
            list_id,
            name=body.name,
            tags=tags,
            position=body.position,
        )
    except BuiltinListReadOnly:
        raise HTTPException(
            status_code=422, detail="The built-in list is read-only"
        )
    except KeywordListNotFound:
        raise HTTPException(status_code=404, detail="Keyword list not found")
    except DuplicateListName:
        raise HTTPException(
            status_code=409, detail="A list with that name already exists"
        )
    except psycopg2.Error:
        logger.exception(
            "Failed to update keyword list %s for user=%s", list_id, user_id
        )
        raise HTTPException(
            status_code=500, detail="Failed to update keyword list"
        )
    auth0_id = get_normalized_subject(user)
    ph = get_posthog()
    if ph and auth0_id:
        try:
            with new_context():
                identify_context(auth0_id)
                ph.capture(
                    "keyword_list_updated",
                    distinct_id=auth0_id,
                    properties={
                        "renamed": body.name is not None,
                        "tags_updated": body.tags is not None,
                        "reordered": body.position is not None,
                    },
                )
        except Exception:
            logger.warning(
                "PostHog capture failed for keyword_list_updated", exc_info=True
            )
    return _keyword_list_response(row)


@router.delete(
    "/keyword-lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_keyword_list(
    list_id: str = Path(min_length=1, max_length=64),
    conn: Connection = Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
) -> None:
    """Delete a keyword list (NULLs any active pointer referencing it)."""
    user_id = _resolve_user_id(conn, user)
    try:
        saved_filters_service.delete_keyword_list(conn, user_id, list_id)
    except BuiltinListReadOnly:
        raise HTTPException(
            status_code=422, detail="The built-in list is read-only"
        )
    except KeywordListNotFound:
        raise HTTPException(status_code=404, detail="Keyword list not found")
    except psycopg2.Error:
        logger.exception(
            "Failed to delete keyword list %s for user=%s", list_id, user_id
        )
        raise HTTPException(
            status_code=500, detail="Failed to delete keyword list"
        )
    auth0_id = get_normalized_subject(user)
    ph = get_posthog()
    if ph and auth0_id:
        try:
            with new_context():
                identify_context(auth0_id)
                ph.capture("keyword_list_deleted", distinct_id=auth0_id)
        except Exception:
            logger.warning(
                "PostHog capture failed for keyword_list_deleted", exc_info=True
            )
