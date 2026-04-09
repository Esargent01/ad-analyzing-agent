# LLM cost scaling — considerations for growth

Captured during Phase 2 dev setup, 2026-04-09. These are back-of-envelope
numbers based on the current architecture — revisit any time prompts,
agents, or cron frequency change materially.

## The key insight

**LLM cost scales with *campaigns*, not users.** The dashboard is cold-path
from the LLM's perspective — browsing reports, approving/rejecting proposed
variants, and suggesting gene pool entries are all pure DB operations. No
LLM call on any user-facing request. The hot path is the daily cron.

A customer who never logs in but has 5 active campaigns costs exactly the
same in LLM spend as an engaged customer with 5 active campaigns.

## What actually drives LLM cost

The three LLM agents fire on a schedule, not on user actions:

| Agent | Frequency | Trigger | Purpose |
|---|---|---|---|
| `GeneratorAgent` (`src/agents/generator.py`) | Daily per campaign | Cron | Assembles new variant genomes from existing gene pool |
| `AnalystAgent` (`src/agents/analyst.py`) | Daily per campaign | Cron | Writes natural-language cycle summary |
| `CopywriterAgent` (`src/agents/copywriter.py`) | Weekly per campaign | Cron | Suggests new gene pool entries (headlines, subheads, CTAs) |

Cost formula:

```
monthly_llm_cost ≈ active_campaigns
                 × (daily_tokens × 30 + weekly_tokens × 4)
                 × price_per_token
```

Users only enter the formula via `active_campaigns`. One customer with 10
campaigns costs 10× what one customer with 1 campaign costs.

## Rough per-campaign token budgets

Based on what the prompts look like today (2026-04-09). These should be
re-measured once we have the `llm_calls` log table suggested below.

| Agent | Input tokens | Output tokens | Cadence |
|---|---|---|---|
| GeneratorAgent | ~10-13k | ~2k | Daily |
| AnalystAgent | ~4-5k | ~1k | Daily |
| CopywriterAgent | ~4k | ~1.5k | Weekly (amortizes to ~0.6k + 0.2k daily) |

Combined daily per campaign: **~15k input + ~3.5k output** on Sonnet 4.

## Pricing reference (verify against current Anthropic pricing)

| Model | Input $/MTok | Output $/MTok | Ratio vs Sonnet 4 |
|---|---|---|---|
| Claude Sonnet 4 | ~$3 | ~$15 | 1× |
| Claude Haiku 4.5 | ~$1 | ~$5 | ~3× cheaper |
| Claude Haiku 3.5 | ~$0.80 | ~$4 | ~4× cheaper |

## Monthly cost projections

Per campaign per month on Sonnet 4:
`15000 × $3/1M × 30 + 3500 × $15/1M × 30 ≈ $3/campaign/month`

| Active campaigns | All Sonnet 4 | Split: Sonnet copy + Haiku generator/analyst |
|---|---|---|
| 10 | ~$30/mo | ~$12/mo |
| 100 | ~$300/mo | ~$120/mo |
| 1,000 | ~$3,000/mo | ~$1,200/mo |
| 10,000 | ~$30,000/mo | ~$12,000/mo |

Linear and predictable. The per-agent split buys roughly 60% off while
keeping Sonnet quality where it matters most (copy).

## Per-agent model recommendations

The current codebase uses one global `ANTHROPIC_MODEL` env var for all
three agents. A smarter default is per-agent config:

```python
# src/config.py
anthropic_model_copywriter: str = "claude-sonnet-4-20250514"  # keep
anthropic_model_generator:  str = "claude-haiku-4-5"          # downgrade
anthropic_model_analyst:    str = "claude-haiku-4-5"          # downgrade
```

Then update the three call sites:
- `src/services/weekly.py:188`
- `src/services/orchestrator.py:648`
- `src/main.py:1404`

### Per-agent rationale

**CopywriterAgent — keep Sonnet 4.**
Direct-response copywriting under hard constraints: 60-char headlines,
psychological levers, no duplicates of existing gene pool entries, brand
voice, rationale per suggestion. Haiku produces more generic copy, more
near-duplicates, weaker rationale, and more char-limit misses. Every
suggestion is human-reviewed via the approval queue, so bad output isn't
dangerous — but reviewer time is more expensive than the token savings
from downgrading. Absolute spend on this agent is small (weekly, not
daily).

**GeneratorAgent — Haiku is fine.**
Doesn't invent copy; selects existing gene pool values and assembles
genomes guided by element performance data. Closer to constrained
combinatorial search than creative writing. Watch tool-use reliability
for a week before committing.

**AnalystAgent — Haiku is fine.**
Writes narrative summaries from pre-computed stats (the stats are
deterministic per project rules — LLM never does math). Sonnet phrasing
is tighter and catches more narrative threads, but Haiku output is not
harmful and the cost delta matters at scale.

## Where linearity breaks — prompt bloat

Three things grow *within* a campaign over time and will inflate
per-call token counts if left unbounded. These are the most likely
places where per-campaign cost drifts upward silently.

### 1. Gene pool size (biggest lever)

The CopywriterAgent sees every existing entry to avoid duplicates, and
the AnalystAgent sees top performers. A 500-entry gene pool doubles or
triples the Copywriter's input tokens vs. a 50-entry pool.

**Mitigation**: cap context to top-K by performance instead of dumping
the full table. Needs a tweak to `src/agents/copywriter.py::suggest_entries`
to take a `max_context_entries` parameter and truncate by `avg_ctr`
descending.

### 2. Element interactions matrix

O(n²) in gene pool size per campaign. At 100 entries × 100 you're
nominally at 10k pairs, though most are empty. Unbounded inclusion in
prompts will bite at scale.

**Mitigation**: truncate to top-K interactions by absolute lift when
building the generator prompt.

### 3. Variants per cycle

Capped today by `MAX_CONCURRENT_VARIANTS=10`. If raised, the Analyst's
summarization prompt grows proportionally. This is the safest lever to
touch because the cap is explicit.

## What scales with *users* (not LLM, but still real)

These are the costs that track actual user growth:

- **TimescaleDB Cloud**: storage grows with `campaigns × variants ×
  polling_frequency × retention_window`. **This will likely overtake LLM
  cost first at scale** unless compression policies and downsampling are
  configured. Add retention + compression before customer #100.
- **SendGrid**: magic-link emails (per sign-in, rate-limited) + daily /
  weekly report emails (per campaign, not per user). Magic-link is the
  only truly per-user line item; it's pennies.
- **Ad platform API quotas**: Meta and Google rate-limit hard. At
  ~1,000+ campaigns, expect to need batched polling and App Review
  upgrades — solved with engineering, not money.
- **Fly.io + Vercel egress**: negligible for JSON APIs. Only matters if
  media gets served from our infrastructure.

## Cost-cliff risks

Watch for these — they can multiply cost non-linearly:

1. **Retry storms.** A failing cron that retries N times per day
   multiplies LLM cost by N for any campaign it touches. Add idempotency,
   exponential backoff, max-retries.
2. **Gene pool expansion left unbounded.** Copywriter adds ~5 entries
   per weekly run per campaign → ~260 new entries per campaign per year.
   Prune inactive entries or soft-expire them out of prompts.
3. **Multi-tenant noisy neighbors.** One customer with 50 campaigns on
   the same daily cron budget skews the spend profile. Consider
   per-customer campaign caps in config.
4. **Streaming / real-time features.** If a "chat with the analyst" or
   "regenerate this variant live" feature ever lands, the LLM call
   pattern flips from cron-bounded to user-bounded and the cost math
   changes completely. At that point everything in this doc needs to be
   re-derived.

## Practical monitoring — build before customer #10

Two things to add early, before they're urgent:

### 1. `llm_calls` log table

Log every LLM request with:

```sql
CREATE TABLE llm_calls (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    campaign_id     UUID REFERENCES campaigns(id),
    cycle_id        UUID REFERENCES test_cycles(id),
    agent           TEXT NOT NULL,   -- 'generator' | 'analyst' | 'copywriter'
    model           TEXT NOT NULL,
    input_tokens    INTEGER NOT NULL,
    output_tokens   INTEGER NOT NULL,
    cost_usd        NUMERIC(10, 6) NOT NULL,
    latency_ms      INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_llm_calls_campaign ON llm_calls (campaign_id, created_at DESC);
```

The Anthropic SDK returns `usage` in every response — cheap to log,
invaluable for cost debugging and per-campaign attribution.

### 2. Per-campaign monthly cost rollup

Expose in the dashboard. If a specific campaign is burning more than
its peers, you want to see it before the Anthropic invoice does. A
simple SQL rollup over `llm_calls` grouped by campaign + month.

## TL;DR

- **LLM cost is linear in active campaigns**, roughly **$3/campaign/month
  on Sonnet 4**, **~$1.20 on a Sonnet-copy + Haiku-generator/analyst split**.
- **Users don't directly drive LLM spend** — the dashboard is cold-path.
- The real scaling risk isn't volume, it's **prompt bloat from growing
  gene pools and interaction matrices**. Cap inputs to top-K.
- **TimescaleDB will likely overtake LLM costs first** at scale unless
  retention + compression are configured.
- **Add per-call cost logging now**, not later.
- The per-agent model split is the single highest-ROI change and is
  cheap to implement (3 call sites + 3 new config vars).
