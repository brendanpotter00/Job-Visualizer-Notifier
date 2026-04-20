"""Feature voting endpoints."""

import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Path, Request

from ..auth.dependencies import TokenClaims, get_current_user, get_optional_user
from ..auth.jwt import get_normalized_subject
from ..dependencies import get_db
from ..models import (
    FeatureListResponse,
    FeatureResponse,
    FeatureUpvoteStateResponse,
)
from ..services.features_service import (
    FeatureNotFound,
    add_upvote,
    list_features_with_upvotes,
    remove_upvote,
)
from ..services.user_service import get_or_create_user, get_user_by_email

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_user_id_for_mutation(conn, env: str, user: TokenClaims) -> str:
    auth0_id = get_normalized_subject(user)
    if not auth0_id:
        raise HTTPException(status_code=401, detail="Token missing required 'sub' claim")
    email = user.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Token missing required 'email' claim")
    try:
        row = get_or_create_user(
            conn, env,
            auth0_id=auth0_id,
            email=email,
            given_name=user.get("given_name"),
            family_name=user.get("family_name"),
            picture_url=user.get("picture"),
        )
    except psycopg2.Error:
        logger.exception("Failed to get/create user during feature upvote (sub=%s)", auth0_id)
        raise HTTPException(status_code=500, detail="Failed to resolve user")
    return row["id"]


def _resolve_optional_user_id(conn, env: str, user: TokenClaims | None) -> str | None:
    # GET is best-effort: a DB hiccup when looking up the caller should not fail
    # the whole list endpoint. Treat the caller as anonymous (hasUpvoted=false on
    # every row) and log so the symptom is debuggable.
    if user is None:
        return None
    email = user.get("email")
    if not email:
        return None
    try:
        row = get_user_by_email(conn, env, email)
    except psycopg2.Error:
        conn.rollback()
        logger.exception(
            "Failed to resolve optional user for list_features (email=%s); "
            "falling back to anonymous",
            email,
        )
        return None
    return row["id"] if row else None


@router.get("", response_model=FeatureListResponse)
def list_features(
    request: Request,
    conn=Depends(get_db),
    user: TokenClaims | None = Depends(get_optional_user),
):
    env = request.app.state.env
    user_id = _resolve_optional_user_id(conn, env, user)
    try:
        rows = list_features_with_upvotes(conn, env, user_id)
    except psycopg2.Error:
        # Roll back so the pooled connection isn't returned in an aborted-transaction
        # state — the next caller of get_db would otherwise see "current transaction
        # is aborted" on their very first statement.
        conn.rollback()
        logger.exception("Failed to list features (env=%s)", env)
        raise HTTPException(status_code=500, detail="Failed to list features")
    items = [
        FeatureResponse(
            id=r["id"],
            title=r["title"],
            description=r["description"],
            created_at=r["created_at"],
            upvote_count=r["upvote_count"],
            has_upvoted=r["has_upvoted"],
        )
        for r in rows
    ]
    return FeatureListResponse(features=items)


@router.post("/{feature_id}/upvote", response_model=FeatureUpvoteStateResponse)
def post_upvote(
    request: Request,
    feature_id: str = Path(min_length=1, max_length=64),
    conn=Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
):
    env = request.app.state.env
    user_id = _resolve_user_id_for_mutation(conn, env, user)
    try:
        result = add_upvote(conn, env, feature_id, user_id)
    except FeatureNotFound:
        raise HTTPException(status_code=404, detail="Feature not found")
    except psycopg2.Error:
        logger.exception("Failed to add upvote for feature_id=%s", feature_id)
        raise HTTPException(status_code=500, detail="Failed to record upvote")
    return FeatureUpvoteStateResponse(
        feature_id=result["feature_id"],
        upvote_count=result["upvote_count"],
        has_upvoted=result["has_upvoted"],
    )


@router.delete("/{feature_id}/upvote", response_model=FeatureUpvoteStateResponse)
def delete_upvote(
    request: Request,
    feature_id: str = Path(min_length=1, max_length=64),
    conn=Depends(get_db),
    user: TokenClaims = Depends(get_current_user),
):
    env = request.app.state.env
    user_id = _resolve_user_id_for_mutation(conn, env, user)
    try:
        result = remove_upvote(conn, env, feature_id, user_id)
    except FeatureNotFound:
        raise HTTPException(status_code=404, detail="Feature not found")
    except psycopg2.Error:
        logger.exception("Failed to remove upvote for feature_id=%s", feature_id)
        raise HTTPException(status_code=500, detail="Failed to remove upvote")
    return FeatureUpvoteStateResponse(
        feature_id=result["feature_id"],
        upvote_count=result["upvote_count"],
        has_upvoted=result["has_upvoted"],
    )
