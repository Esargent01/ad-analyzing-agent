"""LLM-powered ad creative variation generator.

Uses the Anthropic SDK with tool use to generate new ad creative
variants by recombining gene pool elements informed by element
performance and interaction data. The LLM selects values; all
validation is deterministic.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import anthropic
from pydantic import BaseModel, ConfigDict, ValidationError

from src.exceptions import GenomeValidationError, LLMError
from src.models.genome import GenePool, GenomeSchema

if TYPE_CHECKING:
    from src.models.analysis import ElementInsight, InteractionInsight

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt — instructs the LLM on how to create variant genomes.
# Lives as a module constant per coding conventions.
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are a creative strategist for a performance marketing team. Your job is to \
generate new ad creative variants by selecting element values from a fixed gene pool.

STRICT RULES:
1. You may ONLY use values that appear in the gene pool provided. Never invent \
new copy, colors, styles, or audience segments.
2. Each new variant must change EXACTLY ONE element from a proven base combination. \
This enforces "one hypothesis per variant" so we can attribute performance changes \
to a single element.
3. Use the element performance data to favor high-performing elements. Prefer \
elements with high average CTR and high confidence.
4. Use the interaction data to find synergistic combinations. Positive interaction \
lift means the pair works well together — prefer those pairings.
5. Never duplicate an existing genome. Every variant you create must be different \
from all existing genomes.
6. For each variant, provide a clear hypothesis explaining which element you \
changed and why you expect it to perform well.

MEDIA ASSETS:
The `media_asset` slot contains references to real images and videos from the \
advertiser's media library. Each value maps to a specific uploaded image or video. \
When selecting a media_asset, consider visual diversity — pairing different media \
with different copy can reveal which visuals drive the strongest hook rate and CTR. \
If the gene pool also contains a `hero_style` slot, prefer `media_asset` values \
when available as they use real creative assets.

STRATEGY:
- Start from the best-performing existing genome (or a strong combination).
- Pick the single element change most likely to improve performance based on:
  a) Element-level performance data (which values have high CTR?)
  b) Interaction effects (which pairs create synergy?)
  c) Under-explored high-potential combinations.
  d) Visual testing via media_asset — especially if one visual is untested with \
     a high-performing copy combination.
- State a clear, testable hypothesis for each variant.

Call the `create_variant` tool once for each variant you want to propose. \
Do NOT output raw JSON — always use the tool.
"""


# ---------------------------------------------------------------------------
# Pydantic output model
# ---------------------------------------------------------------------------


class GenomeWithHypothesis(BaseModel):
    """A validated genome paired with the hypothesis it tests."""

    model_config = ConfigDict(strict=True)

    genome: dict[str, str]
    hypothesis: str


# ---------------------------------------------------------------------------
# Tool schema builder
# ---------------------------------------------------------------------------


def _build_create_variant_tool(gene_pool: GenePool) -> dict:
    """Build the Anthropic tool-use schema for ``create_variant``.

    Each genome slot becomes a string parameter whose allowed values
    are the entries from the gene pool via an enum constraint.

    Args:
        gene_pool: The approved gene pool with all slot definitions.

    Returns:
        A tool definition dict ready for the Anthropic messages API.
    """
    slot_properties: dict = {}
    for slot_name in gene_pool.all_slot_names():
        allowed = sorted(gene_pool.allowed_values_for(slot_name))
        slot_properties[slot_name] = {
            "type": "string",
            "enum": allowed,
            "description": f"Value for the '{slot_name}' slot. Must be one of the allowed values.",
        }

    slot_properties["hypothesis"] = {
        "type": "string",
        "description": (
            "A concise hypothesis explaining which single element was changed "
            "from the base variant and why this change is expected to improve performance."
        ),
    }

    return {
        "name": "create_variant",
        "description": (
            "Create a new ad creative variant by specifying a value for every genome "
            "slot plus a hypothesis. Each slot value must come from the gene pool."
        ),
        "input_schema": {
            "type": "object",
            "properties": slot_properties,
            "required": list(slot_properties.keys()),
        },
    }


# ---------------------------------------------------------------------------
# Prompt formatters
# ---------------------------------------------------------------------------


def _format_element_rankings(
    element_rankings: list[ElementInsight],
) -> str:
    """Format element performance data for inclusion in the LLM prompt."""
    if not element_rankings:
        return "No element performance data available yet."

    lines: list[str] = ["Slot | Value | Avg CTR | Variants Tested | Confidence"]
    lines.append("--- | --- | --- | --- | ---")
    for ep in sorted(element_rankings, key=lambda e: float(e.avg_ctr), reverse=True):
        conf = f"{ep.confidence:.1f}%" if ep.confidence is not None else "N/A"
        lines.append(
            f"{ep.slot_name} | {ep.slot_value} | {float(ep.avg_ctr):.4f} | "
            f"{ep.variants_tested} | {conf}"
        )
    return "\n".join(lines)


def _format_interactions(
    top_interactions: list[InteractionInsight],
) -> str:
    """Format interaction data for inclusion in the LLM prompt."""
    if not top_interactions:
        return "No interaction data available yet."

    lines: list[str] = [
        "Slot A | Value A | Slot B | Value B | Lift | Variants Tested"
    ]
    lines.append("--- | --- | --- | --- | --- | ---")
    for ix in sorted(
        top_interactions,
        key=lambda i: float(i.interaction_lift) if i.interaction_lift is not None else 0.0,
        reverse=True,
    ):
        lift = f"{float(ix.interaction_lift):+.2%}" if ix.interaction_lift is not None else "N/A"
        lines.append(
            f"{ix.slot_a_name} | {ix.slot_a_value} | "
            f"{ix.slot_b_name} | {ix.slot_b_value} | "
            f"{lift} | {ix.variants_tested}"
        )
    return "\n".join(lines)


def _format_existing_genomes(existing_genomes: list[dict[str, str]]) -> str:
    """Format existing genomes so the LLM can avoid duplicates."""
    if not existing_genomes:
        return "No existing variants yet — you are creating the first generation."
    lines: list[str] = []
    for idx, genome in enumerate(existing_genomes, 1):
        lines.append(f"Variant {idx}: {json.dumps(genome, sort_keys=True)}")
    return "\n".join(lines)


def _format_gene_pool(gene_pool: GenePool) -> str:
    """Format the gene pool as a readable reference for the LLM."""
    lines: list[str] = []
    for slot_name in gene_pool.all_slot_names():
        entries = getattr(gene_pool, slot_name)
        values = [f"  - {e.value}: {e.description}" for e in entries]
        lines.append(f"**{slot_name}**:")
        lines.extend(values)
    return "\n".join(lines)


def _genome_fingerprint(genome: dict[str, str]) -> str:
    """Create a canonical string fingerprint for duplicate detection."""
    return json.dumps(genome, sort_keys=True)


# ---------------------------------------------------------------------------
# Generator agent
# ---------------------------------------------------------------------------


class GeneratorAgent:
    """LLM-powered creative variant generator.

    Uses Anthropic tool use to constrain outputs to valid gene pool values.
    All LLM outputs are validated with Pydantic before returning.

    Args:
        client: An initialized ``anthropic.AsyncAnthropic`` client.
        model: The Anthropic model identifier to use.
    """

    def __init__(self, client: anthropic.AsyncAnthropic, model: str) -> None:
        self._client = client
        self._model = model

    async def generate_variants(
        self,
        gene_pool: GenePool,
        element_rankings: list[ElementInsight],
        top_interactions: list[InteractionInsight],
        current_variants: list[dict[str, str]],
        max_new: int = 3,
    ) -> list[GenomeWithHypothesis]:
        """Generate up to ``max_new`` new variant genomes via LLM tool use.

        The LLM is constrained via tool use to only select values from the
        gene pool. Every response is validated with both the GenomeSchema
        Pydantic model and the gene pool before being accepted.

        Args:
            gene_pool: The approved gene pool defining allowed values per slot.
            element_rankings: Per-element aggregated stats, ranked by performance.
            top_interactions: Highest-lift pairwise interaction pairs.
            current_variants: Genome dicts of currently active variants
                (to avoid duplicates).
            max_new: Maximum number of variants to generate.

        Returns:
            List of validated ``GenomeWithHypothesis`` objects.

        Raises:
            LLMError: If the LLM fails to produce any valid variants.
        """
        tool = _build_create_variant_tool(gene_pool)

        user_message = (
            f"Please generate up to {max_new} new creative variants.\n\n"
            f"## Gene Pool\n{_format_gene_pool(gene_pool)}\n\n"
            f"## Element Performance Rankings\n"
            f"{_format_element_rankings(element_rankings)}\n\n"
            f"## Top Interactions\n{_format_interactions(top_interactions)}\n\n"
            f"## Existing Genomes (do NOT duplicate)\n"
            f"{_format_existing_genomes(current_variants)}\n\n"
            f"Create up to {max_new} new variants using the create_variant tool. "
            f"Each must change exactly ONE element from the best existing combination."
        )

        logger.debug(
            "Generator prompt:\nSystem: %s\nUser: %s",
            SYSTEM_PROMPT,
            user_message,
        )

        try:
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                tools=[tool],
                tool_choice={"type": "any"},
                messages=[{"role": "user", "content": user_message}],
            )
        except anthropic.APIError as exc:
            logger.error(
                "Anthropic API error during variant generation: %s (status=%s)",
                exc,
                getattr(exc, "status_code", None),
            )
            raise LLMError(f"Anthropic API call failed: {exc}") from exc

        logger.debug(
            "Generator response: stop_reason=%s, content_blocks=%d, "
            "input_tokens=%d, output_tokens=%d",
            response.stop_reason,
            len(response.content),
            response.usage.input_tokens,
            response.usage.output_tokens,
        )

        # Extract and validate tool-use results
        results: list[GenomeWithHypothesis] = []
        existing_set = {_genome_fingerprint(g) for g in current_variants}

        for block in response.content:
            if block.type != "tool_use":
                continue

            if block.name != "create_variant":
                logger.warning("LLM called unexpected tool: %s", block.name)
                continue

            tool_input: dict = block.input
            logger.debug("Raw tool_use input: %s", json.dumps(tool_input))

            hypothesis = tool_input.pop("hypothesis", "No hypothesis provided.")

            # Step 1: Validate genome via Pydantic strict schema
            try:
                genome_schema = GenomeSchema.model_validate(tool_input)
            except ValidationError as exc:
                logger.warning(
                    "LLM produced invalid genome schema: %s — input was %s",
                    exc,
                    tool_input,
                )
                continue

            # Step 2: Validate against the gene pool (value allowlist)
            try:
                genome_schema.validate_against_pool(gene_pool)
            except GenomeValidationError as exc:
                logger.warning(
                    "LLM genome failed gene pool validation: %s — genome was %s",
                    exc,
                    tool_input,
                )
                continue

            genome_dict = genome_schema.to_dict()
            genome_key = _genome_fingerprint(genome_dict)

            # Step 3: Check for duplicates (against existing + this batch)
            if genome_key in existing_set:
                logger.info(
                    "Skipping duplicate genome produced by LLM: %s", genome_key
                )
                continue

            # Step 4: Wrap in the output Pydantic model
            try:
                result = GenomeWithHypothesis(
                    genome=genome_dict,
                    hypothesis=hypothesis,
                )
            except ValidationError as exc:
                logger.warning(
                    "Pydantic validation failed for GenomeWithHypothesis: %s", exc
                )
                continue

            existing_set.add(genome_key)
            results.append(result)

            if len(results) >= max_new:
                break

        if not results:
            raise LLMError(
                "LLM failed to produce any valid variant genomes. "
                "Check logs for validation failures."
            )

        logger.info("Generated %d new variants", len(results))
        return results
