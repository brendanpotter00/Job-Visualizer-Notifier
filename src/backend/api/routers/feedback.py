"""Public user-feedback endpoint.

``POST /api/feedback`` accepts a free-form message from anyone. A valid Bearer
token attaches the submitter's identity snapshot; without one — or with a
missing, expired, malformed, or currently-unverifiable token — the row is stored
anonymously. Feedback is never blocked on auth: the endpoint depends on
``get_optional_user_lenient`` (which returns None rather than raising on a bad
token), so an expired session degrades to an anonymous submission instead of a
401.
"""

import logging

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from posthog import identify_context, new_context
from psycopg2.extensions import connection as Connection

from ..auth.dependencies import TokenClaims, get_optional_user_lenient
from ..auth.jwt import get_normalized_subject
from ..dependencies import get_db
from ..models import FeedbackResponse, FeedbackSubmitRequest
from ..services.feedback_service import submit_feedback
from ..services.posthog_client import get_posthog
from ..services.rate_limit import enforce_feedback_rate_limit
from ..services.user_service import get_or_create_user

logger = logging.getLogger(__name__)

router = APIRouter()


def _resolve_optional_submitter(
    conn: Connection, user: TokenClaims | None
) -> tuple[str | None, str | None, str | None]:
    """Resolve the (user_id, email, display_name) snapshot for the submitter.

    ``user`` is None (anonymous) when there was no token OR the token could not
    be verified — ``get_optional_user_lenient`` collapses both to None. A
    successfully-validated token that merely lacks the required sub/email claims
    is likewise treated as anonymous rather than 401. On a DB error resolving the
    user, roll back and fall back to anonymous so a transient hiccup never loses
    the message (mirrors features' ``_resolve_optional_user_id``).
    """
    if user is None:
        return None, None, None
    auth0_id = get_normalized_subject(user)
    email = user.get("email")
    if not auth0_id or not email:
        return None, None, None
    try:
        row = get_or_create_user(
            conn,
            auth0_id=auth0_id,
            email=email,
            given_name=user.get("given_name"),
            family_name=user.get("family_name"),
            picture_url=user.get("picture"),
        )
    except (psycopg2.Error, RuntimeError):
        # get_or_create_user raises RuntimeError on ambiguous identity and
        # psycopg2.Error on DB failure. On the public path we degrade to
        # anonymous rather than 500 — recording the message matters more.
        conn.rollback()
        logger.exception(
            "Failed to resolve submitter for feedback (email=%s); "
            "recording as anonymous", email,
        )
        return None, None, None
    return row["id"], row["email"], row.get("display_name")


@router.post(
    "",
    response_model=FeedbackResponse,
    status_code=201,
    dependencies=[Depends(enforce_feedback_rate_limit)],
)
def post_feedback(
    body: FeedbackSubmitRequest,
    conn: Connection = Depends(get_db),
    user: TokenClaims | None = Depends(get_optional_user_lenient),
) -> FeedbackResponse:
    message = body.message.strip()
    if not message:
        raise HTTPException(status_code=422, detail="Message must not be empty")
    user_id, user_email, display_name = _resolve_optional_submitter(conn, user)
    try:
        row = submit_feedback(
            conn,
            message=message,
            user_id=user_id,
            user_email=user_email,
            display_name=display_name,
        )
    except psycopg2.Error:
        logger.exception("Failed to submit feedback")
        raise HTTPException(status_code=500, detail="Failed to submit feedback")
    ph = get_posthog()
    if ph:
        try:
            auth0_id = get_normalized_subject(user) if user else None
            distinct_id = auth0_id or "anonymous"
            with new_context():
                if auth0_id:
                    identify_context(auth0_id)
                ph.capture(
                    "feedback_submitted",
                    distinct_id=distinct_id,
                    properties={
                        "is_authenticated": user_id is not None,
                        "message_length": len(message),
                    },
                )
        except Exception:
            logger.warning(
                "PostHog capture failed for feedback_submitted", exc_info=True
            )
    return FeedbackResponse(
        id=row["id"],
        message=row["message"],
        user_id=row["user_id"],
        user_email=row["user_email"],
        display_name=row["display_name"],
        created_at=row["created_at"],
    )
