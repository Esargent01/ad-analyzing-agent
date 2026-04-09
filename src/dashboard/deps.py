"""FastAPI dependency-injection helpers for the dashboard.

Four dependencies, each usable via ``Depends(...)`` on route signatures:

- :func:`get_db_session` — async generator wrapping
  ``src.db.engine.get_session`` so FastAPI can use it with ``Depends``.
- :func:`get_current_user` — reads the ``session_token`` cookie, verifies
  it, fetches the user row, and returns it. Raises 401 on failure.
- :func:`require_campaign_access` — ensures the current user has an entry
  in ``user_campaigns`` for the requested campaign. Raises **404** (not
  403) on mismatch so we never leak existence to strangers.
- :func:`require_csrf` — enforces the double-submit cookie pattern on
  state-changing requests.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Cookie, Depends, Header, HTTPException, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.dashboard.auth import verify_session_token
from src.db.engine import get_session
from src.db.tables import User, UserCampaign


# ---------------------------------------------------------------------------
# DB session
# ---------------------------------------------------------------------------


async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async DB session for FastAPI ``Depends``.

    ``get_session`` in ``src/db/engine.py`` is an ``@asynccontextmanager``
    which FastAPI cannot consume directly — ``Depends`` requires an async
    generator. This thin wrapper bridges the two.
    """
    async with get_session() as session:
        yield session


# ---------------------------------------------------------------------------
# Authenticated user
# ---------------------------------------------------------------------------


async def get_current_user(
    session: AsyncSession = Depends(get_db_session),
    session_token: str | None = Cookie(default=None),
) -> User:
    """Resolve the ``session_token`` cookie to a ``User`` row.

    Raises ``HTTPException(401)`` when:
    - the cookie is missing
    - the token is malformed, tampered, or expired
    - the underlying user no longer exists or is deactivated
    """
    if not session_token:
        raise HTTPException(status_code=401, detail="not authenticated")

    user_id = verify_session_token(session_token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="not authenticated")

    stmt = select(User).where(User.id == user_id, User.is_active.is_(True))
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")

    return user


# ---------------------------------------------------------------------------
# Campaign access scoping
# ---------------------------------------------------------------------------


async def require_campaign_access(
    campaign_id: UUID = Path(...),
    session: AsyncSession = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> UUID:
    """Confirm the current user has access to ``campaign_id``.

    Returns the validated UUID so handlers can use it directly. Raises
    **404** on any access failure — we never distinguish "campaign does
    not exist" from "campaign exists but you can't see it" to avoid
    leaking existence to strangers.
    """
    stmt = select(UserCampaign).where(
        UserCampaign.user_id == user.id,
        UserCampaign.campaign_id == campaign_id,
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="not found")
    return campaign_id


# ---------------------------------------------------------------------------
# CSRF (double-submit cookie)
# ---------------------------------------------------------------------------


async def require_csrf(
    x_csrf_token: str | None = Header(default=None),
    csrf_token: str | None = Cookie(default=None),
) -> None:
    """Reject requests whose CSRF header doesn't match the cookie.

    On sign-in we issue both an HttpOnly ``session_token`` cookie *and*
    a readable ``csrf_token`` cookie. The frontend copies ``csrf_token``
    into an ``X-CSRF-Token`` header on every mutating request. Because
    an attacker on a third-party origin cannot read the cookie, the
    matching header proves the request came from our frontend.
    """
    if not csrf_token or not x_csrf_token:
        raise HTTPException(status_code=403, detail="csrf check failed")
    # Use compare_digest to keep timing constant across mismatches.
    import hmac as _hmac

    if not _hmac.compare_digest(csrf_token, x_csrf_token):
        raise HTTPException(status_code=403, detail="csrf check failed")
