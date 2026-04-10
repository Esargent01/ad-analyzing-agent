"""Custom exception classes for the ad creative agent system."""

from __future__ import annotations


class AdAgentError(Exception):
    """Base exception for all ad agent errors."""


class ConfigError(AdAgentError):
    """Configuration is invalid or missing."""


class DatabaseError(AdAgentError):
    """A database operation failed."""


class PlatformAPIError(AdAgentError):
    """An ad platform API call failed."""

    def __init__(
        self,
        platform: str,
        message: str,
        response_body: str | None = None,
    ) -> None:
        self.platform = platform
        self.response_body = response_body
        super().__init__(f"[{platform}] {message}")


class GenomeValidationError(AdAgentError):
    """A genome failed validation against the gene pool."""


class BudgetExceededError(AdAgentError):
    """The campaign's budget would be exceeded by this action."""


class InsufficientDataError(AdAgentError):
    """Not enough data to perform statistical analysis."""


class LLMError(AdAgentError):
    """The LLM returned an invalid or unparseable response."""


class CycleError(AdAgentError):
    """An error occurred during an optimization cycle phase."""

    def __init__(self, phase: str, message: str) -> None:
        self.phase = phase
        super().__init__(f"[{phase}] {message}")


class DuplicateGenomeError(AdAgentError):
    """A genome already exists in the campaign."""


class DeploymentError(AdAgentError):
    """Failed to deploy a variant to an ad platform."""


class ApprovalRequiredError(AdAgentError):
    """Variant requires human approval before deployment."""


class MetaConnectionMissing(AdAgentError):
    """The user has no Meta OAuth connection on file.

    Raised by ``src.adapters.meta_factory`` when a cycle tries to
    resolve a MetaAdapter for a campaign whose owner has never
    completed the Connect Meta flow (or has disconnected since).
    The orchestrator catches this, skips the cycle, and surfaces
    "owner must reconnect" in the UI / daily report.
    """


class MetaTokenExpired(AdAgentError):
    """The user's long-lived Meta token is past its expiry.

    Meta's long-lived tokens last ~60 days. Phase C does not
    refresh them automatically — instead the factory raises this
    so the orchestrator can skip the cycle and email the owner
    with a reconnect prompt. Phase G is the planned home for an
    automatic refresh job.
    """


class CampaignCapExceeded(AdAgentError):
    """User already owns the maximum number of active campaigns.

    Raised by the Phase D import flow when a user tries to import
    campaign N+1 past ``settings.max_campaigns_per_user``. The cap
    protects the monthly LLM + Meta API spend bound per user —
    it's deliberately low (default 5) and tunable.
    """

    def __init__(self, current: int, maximum: int) -> None:
        self.current = current
        self.maximum = maximum
        super().__init__(
            f"Campaign cap reached: you already own {current} of {maximum} "
            "campaigns. Retire one before importing another."
        )


class CampaignAlreadyImported(AdAgentError):
    """The Meta campaign has already been imported by this user.

    Raised by the Phase D import flow when a user tries to
    double-import a campaign. Kept separate from
    ``CampaignCapExceeded`` so the UI can distinguish "you can't
    import this one" from "you can't import any more".
    """


class MultipleAdAccountsNoDefault(AdAgentError):
    """The user has >1 ad account and no ``ad_account_id`` was chosen.

    Raised by the Phase G import flow when ``list_importable_campaigns``
    is called without an explicit ``ad_account_id`` query param *and*
    the user has multiple reachable accounts with no
    ``default_ad_account_id`` set. The dashboard endpoint maps this
    to HTTP 400 ``pick_account_first`` so the frontend can prompt the
    user to pick before showing any campaigns.
    """


class AdAccountNotAllowed(AdAgentError):
    """The submitted ``ad_account_id`` or ``page_id`` isn't in the user's allowlist.

    The cross-user guard in Phase G: on any import request, the server
    rejects account or Page IDs that aren't in the user's enumerated
    ``available_ad_accounts`` / ``available_pages`` JSONB lists. This
    blocks a malicious client from POSTing another user's ad account
    id, even if they somehow learn the value.
    """
