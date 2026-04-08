"""LLM-powered copywriter agent for gene pool expansion.

Uses the Anthropic SDK with tool use to suggest new headline, subhead,
and CTA variations for the gene pool. Suggestions are inserted as
inactive entries pending human approval.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import anthropic
from pydantic import BaseModel, ConfigDict

from src.exceptions import LLMError

if TYPE_CHECKING:
    from src.db.tables import ElementPerformance, GenePoolEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a direct-response copywriter specializing in paid social ads. Your job \
is to suggest new creative text elements (headlines, subheadlines, CTA button text) \
for an A/B testing system.

STRICT RULES:
1. Only suggest text for the slot(s) you are asked about: headline, subhead, or cta_text.
2. Every suggestion must be distinct from the existing entries provided. Do NOT repeat \
or closely paraphrase existing values.
3. Keep headlines under 60 characters, subheads under 100 characters, CTAs under 25 characters.
4. Each suggestion must include a clear rationale explaining the psychological lever \
or copy principle behind it (e.g., social proof, urgency, curiosity gap, loss aversion).
5. Use the element performance data to understand what WORKS for this brand. \
High-CTR elements hint at the audience's motivations. Generate variations that \
test adjacent angles, not random ideas.
6. If brand context is provided, match the brand's voice and tone.

Call the `suggest_entry` tool once for each suggestion.
"""


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class SuggestedEntry(BaseModel):
    """A single gene pool entry suggestion from the LLM."""

    model_config = ConfigDict(frozen=True)

    slot_name: str
    value: str
    description: str
    rationale: str


# ---------------------------------------------------------------------------
# Copywriter agent
# ---------------------------------------------------------------------------


class CopywriterAgent:
    """Suggests new gene pool entries using LLM-powered copywriting.

    Args:
        api_key: Anthropic API key.
        model: Model name to use (default: claude-sonnet-4-20250514).
    """

    TEXT_SLOTS = frozenset({"headline", "subhead", "cta_text"})

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
    ) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    async def suggest_entries(
        self,
        existing_entries: list[GenePoolEntry],
        top_elements: list[ElementPerformance] | None = None,
        slot_name: str | None = None,
        brand_context: str | None = None,
        count: int = 5,
    ) -> list[SuggestedEntry]:
        """Generate gene pool entry suggestions.

        Args:
            existing_entries: Current gene pool entries for context and dedup.
            top_elements: Top-performing elements for performance-informed suggestions.
            slot_name: Specific slot to suggest for (None = all text slots).
            brand_context: Optional brand voice / product description.
            count: Number of suggestions to generate.

        Returns:
            List of validated SuggestedEntry objects.
        """
        target_slots = [slot_name] if slot_name else list(self.TEXT_SLOTS)

        # Build user prompt
        user_parts: list[str] = []

        if brand_context:
            user_parts.append(f"BRAND CONTEXT:\n{brand_context}\n")

        # Current entries grouped by slot
        user_parts.append("EXISTING GENE POOL ENTRIES (do not duplicate these):")
        for s in target_slots:
            entries_for_slot = [e for e in existing_entries if e.slot_name == s]
            if entries_for_slot:
                user_parts.append(f"\n  {s}:")
                for e in entries_for_slot:
                    user_parts.append(f"    - {e.slot_value}")

        # Performance data
        if top_elements:
            user_parts.append("\nTOP-PERFORMING ELEMENTS (by CTR):")
            for ep in top_elements[:15]:
                if ep.slot_name in self.TEXT_SLOTS:
                    conf = f", confidence {ep.confidence}%" if ep.confidence else ""
                    user_parts.append(
                        f"  [{ep.slot_name}] {ep.slot_value} — "
                        f"CTR {ep.avg_ctr:.2%}, {ep.variants_tested} variants{conf}"
                    )

        slot_label = slot_name if slot_name else "headline, subhead, and cta_text"
        user_parts.append(
            f"\nPlease suggest {count} new entries for: {slot_label}. "
            f"Call the suggest_entry tool for each."
        )

        user_message = "\n".join(user_parts)

        # Build tool schema
        allowed_slots = target_slots
        tool = {
            "name": "suggest_entry",
            "description": "Suggest a new gene pool entry for a text creative slot.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "slot_name": {
                        "type": "string",
                        "enum": allowed_slots,
                        "description": "Which slot this suggestion is for.",
                    },
                    "value": {
                        "type": "string",
                        "description": "The suggested text value.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Short human-readable note about this entry.",
                    },
                    "rationale": {
                        "type": "string",
                        "description": (
                            "Why this variation is worth testing (copy principle, angle, etc)."
                        ),
                    },
                },
                "required": ["slot_name", "value", "description", "rationale"],
            },
        }

        # Call the LLM
        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_message}],
                tools=[tool],
            )
        except anthropic.APIError as exc:
            raise LLMError(f"Anthropic API error: {exc}") from exc

        # Extract tool calls
        suggestions: list[SuggestedEntry] = []
        existing_values = {(e.slot_name, e.slot_value) for e in existing_entries}

        for block in response.content:
            if block.type != "tool_use" or block.name != "suggest_entry":
                continue

            try:
                entry = SuggestedEntry.model_validate(block.input)
            except Exception as exc:
                logger.warning("Invalid suggestion from LLM: %s", exc)
                continue

            # Dedup against existing and batch
            key = (entry.slot_name, entry.value)
            if key in existing_values:
                logger.warning("LLM suggested duplicate: %s", entry.value)
                continue
            existing_values.add(key)

            # Validate slot
            if entry.slot_name not in self.TEXT_SLOTS:
                logger.warning("LLM suggested for invalid slot: %s", entry.slot_name)
                continue

            suggestions.append(entry)

        if not suggestions:
            raise LLMError("LLM produced no valid suggestions")

        logger.info("Copywriter generated %d suggestions", len(suggestions))
        return suggestions
