"""Phase H: execute an approved proposal against Meta.

This module is the **only** place in the cycle path that calls
``MetaAdapter.pause_ad`` / ``update_budget``. The orchestrator used to
fire those mutations inline during ``_phase_act``; Phase H moved every
such decision into ``approval_queue`` as a *proposal*, and the
executor turns an approved proposal into the actual side-effect.

The control flow is intentionally tight:

1. The HTTP handler receives ``POST /api/campaigns/.../approve``.
2. It calls :func:`src.db.queries.approve_proposal` which flips the
   row's ``approved`` flag to ``True`` and persists the review
   metadata.
3. It then calls :func:`execute_approved_action` (this module) inside
   the same transaction. The executor resolves the per-campaign Meta
   adapter via the Phase G factory, dispatches on ``action_type``,
   and — if Meta accepts the change — stamps ``executed_at`` so
   double-clicks are idempotent.
4. If Meta rejects the change the executor marks the row as rejected
   with ``rejection_reason="meta_error: …"`` and returns an error
   result. The HTTP handler maps that to a 502 so the UI stays in sync
   with reality.

Keeping this in a dedicated module (rather than scattered through the
handler or the adapter) makes the invariant greppable: any future
mutation path on Meta has to come through here, and any future cycle
code that tries to shortcut around the approval queue will fail a
grep-level audit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.adapters.meta_factory import get_meta_adapter_for_campaign
from src.db.queries import mark_proposal_executed
from src.db.tables import ApprovalActionType, ApprovalQueueItem
from src.exceptions import MetaConnectionMissing, MetaTokenExpired

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome of an ``execute_approved_action`` call.

    The handler returns 200 on ``ok=True`` and 502 on ``ok=False``.
    ``message`` is safe to surface in the UI — it won't include stack
    traces or tokens.
    """

    ok: bool
    action_type: ApprovalActionType
    approval_id: UUID
    message: str


class ApprovalExecutionError(Exception):
    """Raised internally by the executor when an action shape is invalid.

    Distinct from ``MetaError`` so the HTTP handler can tell "we didn't
    even try to talk to Meta because the row was malformed" apart from
    "Meta rejected the mutation".
    """


async def execute_approved_action(
    session: AsyncSession,
    *,
    approval_id: UUID,
    reviewer_user_id: UUID | None = None,
) -> ExecutionResult:
    """Push the side-effect of a freshly approved proposal to Meta.

    Precondition: ``approve_proposal`` has already flipped
    ``approved=True`` on the row. This function loads it back, checks
    ``executed_at`` for idempotency, builds a per-campaign adapter,
    and dispatches on ``action_type``.

    Error handling:
    - Row not found → returns ``ok=False`` with a clear message (the
      handler will 404).
    - Row is ``approved=False`` → ``ok=False`` (shouldn't happen in
      normal flow, but defensive).
    - Row already has ``executed_at`` set → ``ok=True`` immediately
      (double-click protection — the mutation already happened on a
      prior request).
    - Meta factory raises ``MetaConnectionMissing`` /
      ``MetaTokenExpired`` → roll back approval to
      ``approved=False, rejection_reason="meta_connection_missing"``
      and return ``ok=False``.
    - Adapter call raises → same: roll back, return ``ok=False`` with
      a truncated exception string.

    The executor never raises; the handler reads ``ExecutionResult.ok``.
    """
    item = await session.get(ApprovalQueueItem, approval_id)
    if item is None:
        return ExecutionResult(
            ok=False,
            action_type=ApprovalActionType.new_variant,
            approval_id=approval_id,
            message="Approval row not found.",
        )

    # Defensive: we should only be called after approve_proposal has
    # flipped approved=True. If something wrote the row as rejected
    # between approve and execute, bail out without touching Meta.
    if item.approved is not True:
        return ExecutionResult(
            ok=False,
            action_type=item.action_type,
            approval_id=approval_id,
            message="Proposal is not in an approved state.",
        )

    # Idempotency: if executed_at is already set, the mutation landed
    # on a prior call. Double-click is a no-op — return ok.
    if item.executed_at is not None:
        return ExecutionResult(
            ok=True,
            action_type=item.action_type,
            approval_id=approval_id,
            message="Proposal was already executed.",
        )

    # Construct a per-campaign adapter via the Phase G factory. This
    # is the only place inside the cycle path where we construct a
    # mutable adapter — the orchestrator only uses read-only poll
    # paths, so the propose-only invariant holds.
    try:
        adapter = await get_meta_adapter_for_campaign(session, item.campaign_id)
    except (MetaConnectionMissing, MetaTokenExpired) as exc:
        await _mark_rolled_back(
            session,
            item,
            rejection_reason=f"meta_connection_error: {exc}",
        )
        return ExecutionResult(
            ok=False,
            action_type=item.action_type,
            approval_id=approval_id,
            message=(
                "Couldn't reach Meta — the campaign owner may need to reconnect their Meta account."
            ),
        )

    # Dispatch on action_type. Each branch is responsible for its
    # own payload validation so malformed rows surface a clear
    # ApprovalExecutionError message.
    try:
        if item.action_type == ApprovalActionType.pause_variant:
            await _execute_pause(session, adapter, item)
        elif item.action_type == ApprovalActionType.scale_budget:
            await _execute_scale(session, adapter, item)
        elif item.action_type == ApprovalActionType.new_variant:
            # New variant deployment is handled by the existing
            # weekly deployer path — this executor hands off rather
            # than duplicating the logic. The handler at this point
            # has marked the row approved; the weekly deployer runs
            # against approved-but-not-executed rows.
            logger.info(
                "Approval %s is a new_variant; delegating to weekly deployer (no-op in executor)",
                approval_id,
            )
        elif item.action_type == ApprovalActionType.promote_winner:
            # Promotion is a DB state flip; the orchestrator's
            # promote branch already did the status update. Nothing
            # for the executor to push to Meta here. Reserved for
            # future "also pause losers" behaviour.
            logger.info(
                "Approval %s is a promote_winner; nothing to push to Meta",
                approval_id,
            )
        else:
            raise ApprovalExecutionError(f"Unknown approval action_type: {item.action_type!r}")
    except Exception as exc:  # noqa: BLE001 — surface as rejection
        logger.exception(
            "Executor failed for approval %s (action=%s): %s",
            approval_id,
            item.action_type,
            exc,
        )
        await _mark_rolled_back(
            session,
            item,
            rejection_reason=f"meta_error: {str(exc)[:200]}",
        )
        return ExecutionResult(
            ok=False,
            action_type=item.action_type,
            approval_id=approval_id,
            message=(
                "Meta rejected the change. We rolled the approval back so "
                "you can try again in a few minutes."
            ),
        )

    # Success: stamp executed_at so double-clicks are idempotent and
    # the dashboard can distinguish "approved but pending execution"
    # from "approved and landed".
    await mark_proposal_executed(session, approval_id)
    return ExecutionResult(
        ok=True,
        action_type=item.action_type,
        approval_id=approval_id,
        message="Change applied to Meta.",
    )


# ---------------------------------------------------------------------------
# Per-action executors. Each one validates its payload + makes the
# single adapter call it's supposed to make. Keep them small and
# straight-line so the audit trail at a glance reads "pause_ad →
# update_budget → done".
# ---------------------------------------------------------------------------


async def _execute_pause(
    session: AsyncSession,
    adapter,  # type: ignore[no-untyped-def]
    item: ApprovalQueueItem,
) -> None:
    """Push the pause to Meta and flip the local variant's status.

    Mirrors the pre-Phase-H inline path in ``orchestrator._phase_act``
    (lines 486-505 of the old file): update the variant row to
    ``status='paused'``, then call ``adapter.pause_ad``. Order matters
    — we update the DB first so a Meta-call failure that somehow
    returns 200 but didn't land leaves the DB saying "paused" which
    the next cycle will re-queue the proposal for.
    """
    payload = item.action_payload or {}
    platform_ad_id = payload.get("platform_ad_id")
    if not platform_ad_id:
        raise ApprovalExecutionError("pause_variant payload missing 'platform_ad_id'")

    deployment_id = payload.get("deployment_id")
    if deployment_id:
        await session.execute(
            text(
                """
                UPDATE variants
                SET status = 'paused', paused_at = NOW()
                WHERE id = (
                    SELECT variant_id FROM deployments WHERE id = :did
                )
                """
            ),
            {"did": deployment_id},
        )
        await session.execute(
            text("UPDATE deployments SET is_active = FALSE, updated_at = NOW() WHERE id = :did"),
            {"did": deployment_id},
        )

    await adapter.pause_ad(platform_ad_id)


async def _execute_scale(
    session: AsyncSession,
    adapter,  # type: ignore[no-untyped-def]
    item: ApprovalQueueItem,
) -> None:
    """Push the budget change to Meta and update the local deployment row.

    Mirrors the pre-Phase-H inline path in ``orchestrator._phase_act``
    (line 553 of the old file). We call Meta first because the
    deployment row's ``daily_budget`` is the source of truth for the
    "what did we set it to" audit; if Meta rejects, we don't want the
    DB saying we scaled when we didn't.
    """
    payload = item.action_payload or {}
    platform_ad_id = payload.get("platform_ad_id")
    proposed_budget = payload.get("proposed_budget")
    deployment_id = payload.get("deployment_id")
    if not platform_ad_id or proposed_budget is None:
        raise ApprovalExecutionError(
            "scale_budget payload missing 'platform_ad_id' or 'proposed_budget'"
        )

    await adapter.update_budget(platform_ad_id, float(proposed_budget))

    if deployment_id:
        await session.execute(
            text(
                "UPDATE deployments SET daily_budget = :budget, updated_at = NOW() WHERE id = :did"
            ),
            {"budget": Decimal(str(proposed_budget)), "did": deployment_id},
        )


async def _mark_rolled_back(
    session: AsyncSession,
    item: ApprovalQueueItem,
    *,
    rejection_reason: str,
) -> None:
    """Roll the approval back to rejected state after a failed execution.

    We don't delete the row — the rejection_reason is useful audit
    history for "why did this proposal not land" questions later. The
    next cycle's idempotency check (``has_open_proposal``) ignores
    rejected rows, so the proposal can be re-queued cleanly on the
    following pass if the issue persists.
    """
    item.approved = False
    item.rejection_reason = rejection_reason
    await session.flush()
