"""Shared JWT-claims type.

Lives in its own module (rather than in ``auth.dependencies`` or ``auth.jwt``)
so the validators (``jwt.py``, ``google_jwt.py``) and the FastAPI dependencies
(``dependencies.py``) can all import it without an import cycle — ``jwt.py`` and
``google_jwt.py`` already import each other, so the claims type can't live in
either of them.
"""

from typing import TypedDict


class TokenClaims(TypedDict, total=False):
    sub: str
    email: str
    given_name: str | None
    family_name: str | None
    picture: str | None
