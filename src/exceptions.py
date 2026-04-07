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
