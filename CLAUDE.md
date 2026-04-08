# Ad creative testing agent system

A multi-agent system that recursively tests ad creative variants across platforms, monitors performance daily, and generates optimized combinations using element-level insights and interaction effects. The system runs autonomous optimization cycles — decomposing creatives into swappable components, testing combinations, attributing performance to individual elements, and compounding learnings over time.

## Architecture overview

This is a hybrid system: LLMs handle creative recombination strategy and natural-language reporting, while deterministic code handles statistics, API calls, and orchestration. Only two of six logical agents use LLM calls (generator, analyst summary). Everything else is pure Python.

The system runs on a daily cron cycle:
1. **Monitor** — poll ad platform APIs for metrics
2. **Analyze** — run statistical tests, compute element performance, detect fatigue
3. **Act** — pause losers, scale winners via Thompson sampling
4. **Generate** — create new variant genomes informed by element + interaction data
5. **Deploy** — push new variants to ad platforms
6. **Report** — send Slack daily summary, weekly PDF email

## Tech stack

- **Language**: Python 3.11+, async throughout (asyncio + httpx)
- **Database**: PostgreSQL 16 + TimescaleDB extension
- **ORM**: SQLAlchemy 2.0 async with asyncpg driver
- **Migrations**: Alembic (async mode)
- **Validation**: Pydantic v2 with strict mode
- **Config**: pydantic-settings (environment variables, .env file)
- **LLM**: Anthropic SDK — Claude Sonnet via tool use / function calling
- **Statistics**: scipy.stats for significance tests, never LLM
- **HTTP client**: httpx (async), never requests
- **Ad platforms**: facebook-business SDK, google-ads-python
- **Reports**: Jinja2 templates, Slack Block Kit, weasyprint for PDF
- **Testing**: pytest + pytest-asyncio + pytest-cov
- **Formatting**: ruff format + ruff check
- **Containers**: Docker + docker-compose (Postgres + app)

## Project structure

```
ad-creative-agent/
├── CLAUDE.md                    # This file — project context
├── pyproject.toml               # Dependencies and tool config
├── docker-compose.yml           # Postgres + TimescaleDB + app
├── Dockerfile
├── alembic.ini
├── alembic/
│   └── versions/                # Migration files
├── gene_pool_seed.json          # Initial gene pool data
├── src/
│   ├── __init__.py
│   ├── main.py                  # CLI entry point (click)
│   ├── config.py                # Settings via pydantic-settings
│   ├── models/                  # Pydantic schemas
│   │   ├── genome.py            # GenomeSchema, gene pool validation
│   │   ├── variant.py           # VariantCreate, VariantResponse
│   │   ├── metrics.py           # MetricsSnapshot, DailyRollup
│   │   ├── analysis.py          # AnalysisResult, ElementInsight
│   │   └── reports.py           # CycleReport, WeeklyReport
│   ├── db/
│   │   ├── engine.py            # Async engine + session factory
│   │   ├── tables.py            # SQLAlchemy ORM models (all tables)
│   │   ├── queries.py           # Reusable query functions
│   │   └── seed.py              # Gene pool seeder script
│   ├── agents/
│   │   ├── generator.py         # LLM-powered variation generator
│   │   └── analyst.py           # Deterministic analysis + LLM summary
│   ├── adapters/
│   │   ├── base.py              # Abstract adapter interface
│   │   ├── meta.py              # Meta Marketing API adapter
│   │   ├── google_ads.py        # Google Ads API adapter
│   │   └── mock.py              # Mock adapter for testing
│   ├── services/
│   │   ├── orchestrator.py      # Main cycle coordinator
│   │   ├── poller.py            # Metrics polling from platforms
│   │   ├── stats.py             # Statistical significance tests
│   │   ├── allocation.py        # Thompson sampling budget allocation
│   │   ├── interactions.py      # Pairwise element interaction tracker
│   │   └── fatigue.py           # Audience fatigue detection
│   └── reports/
│       ├── slack.py             # Slack Block Kit formatter
│       ├── email.py             # Weekly email report
│       └── templates/           # Jinja2 HTML templates
│           └── weekly_report.html
└── tests/
    ├── conftest.py              # Shared fixtures, test database
    ├── factories.py             # Test data factories
    ├── unit/
    │   ├── test_genome.py       # Genome validation tests
    │   ├── test_stats.py        # Statistical test verification
    │   ├── test_allocation.py   # Thompson sampling tests
    │   ├── test_interactions.py # Interaction tracker tests
    │   ├── test_fatigue.py      # Fatigue detection tests
    │   ├── test_generator.py    # Generator with mocked LLM
    │   └── test_analyst.py      # Analyst with mocked LLM
    └── integration/
        ├── test_poller.py       # Poller with mock adapter
        ├── test_orchestrator.py # Full cycle with mocks
        └── test_meta_adapter.py # Meta API with sandbox
```

## Key domain concepts

### Creative genome
A JSON object where each key is a **slot name** and each value is a **slot value** drawn from the gene pool. The genome fully describes a creative variant — its copy, media, CTA, and targeting. Each slot maps directly to a controllable ad platform field.

```json
{
  "headline": "Limited time: 40% off today only",
  "subhead": "Join 12,000+ happy customers",
  "cta_text": "Claim my discount",
  "media_asset": "Short Form - Top Down Outro - Caption1.mov",
  "audience": "retargeting_30d"
}
```

### Gene pool
The set of approved values for each slot. The generator agent can ONLY select values that exist in the gene pool. It never invents new copy or creative elements. New gene pool entries require human approval.

### Variant
A genome plus metadata: unique code (V1, V2...), status (draft/active/paused/winner/retired), generation number, parent variant IDs, and the hypothesis being tested.

### Element performance
Aggregated stats for a single gene pool element across all variants that used it. Answers: "How does this headline perform on average across all variants that use it?" Updated after each cycle by the analyst.

### Element interactions
Pairwise lift between element combinations. Answers: "Does this video perform differently when paired with different headlines?" The most valuable long-term data asset. Stored with canonical ordering (slot_a < slot_b) to prevent duplicates.

### Test cycle
One execution of the orchestrator. Produces a CycleReport with: metrics pulled, significance tests run, actions taken, variants launched/paused, and the natural-language summary.

## Coding conventions

### General
- All functions are async unless they are pure computation (stats, validation)
- Type hints on every function signature and variable where non-obvious
- Pydantic models use strict mode — no implicit coercion
- Never use `Any` type — always be specific
- Prefer composition over inheritance
- No global mutable state — pass dependencies explicitly

### Async patterns
- Use `async with` for database sessions and HTTP clients
- Never use `asyncio.run()` inside async code — it's only for the entry point
- Use `asyncio.gather()` for concurrent independent operations (e.g., polling multiple deployments)
- Always set timeouts on external calls: `httpx.AsyncClient(timeout=30.0)`

### Database
- Always use async sessions: `async_sessionmaker`
- Queries go in `db/queries.py` as standalone async functions, not methods on models
- Use SQLAlchemy's `select()` construct, never raw SQL strings in application code
- Raw SQL is acceptable only in Alembic migrations
- Always use transactions for multi-table writes
- TimescaleDB hypertable operations use raw SQL in migrations only

### LLM integration
- The Anthropic SDK is the only LLM client — no LangChain, no wrappers
- Use tool use / function calling to constrain outputs to valid schemas
- Always validate LLM output with Pydantic before using it
- Never trust LLM output for statistical calculations
- Log full prompts and responses for debugging (redact in production)
- System prompts live as constants in the agent module, not in separate files

### Testing
- Every module needs tests before it's considered done
- Unit tests mock external dependencies (DB, APIs, LLM)
- Integration tests use a real test database (docker-compose creates it)
- Use factories.py for generating test data, not fixtures for every shape
- Statistical tests must include known-outcome cases to verify correctness
- Target: 90%+ line coverage on services/ and agents/

### Error handling
- Each orchestrator step is wrapped in try/except — one failure doesn't stop the cycle
- Log structured errors with context (variant_id, cycle_number, etc.)
- Use custom exception classes in `src/exceptions.py`
- Never silently swallow exceptions — always log at minimum
- External API errors should include the response body in the log

### Configuration
- All config via environment variables loaded through pydantic-settings
- Secrets (API keys) are never in code or committed to git
- Use `.env` for local development, environment variables in production
- Config class lives in `src/config.py` with sensible defaults for dev

## Database schema reference

The full schema is in `schema.sql`. Key tables:

| Table | Purpose |
|-------|---------|
| `gene_pool` | Approved creative elements per slot |
| `campaigns` | Top-level container with budget and thresholds |
| `variants` | Creative genomes with status and lineage |
| `deployments` | Maps variants to platform ad IDs |
| `metrics` | TimescaleDB hypertable, polled every 6 hours |
| `element_performance` | Aggregated per-element stats (the knowledge base) |
| `element_interactions` | Pairwise element lift effects |
| `test_cycles` | Audit log of orchestrator executions |
| `cycle_actions` | Granular action log (launch, pause, scale) |
| `approval_queue` | Optional human-in-the-loop gate |

Key views: `variant_leaderboard`, `element_rankings`, `top_interactions`

Key functions: `next_variant_code()`, `genome_exists()`, `remaining_budget()`

## Statistical methods

- **Variant comparison**: Two-proportion z-test (scipy.stats.norm) comparing variant CTR against baseline. A variant is a "winner" when p-value < campaign's confidence_threshold (default 0.05).
- **Minimum sample size**: Variants need `min_impressions_for_significance` (default 1000) before any significance test is run.
- **Element attribution**: Average CTR across all variants containing that element, weighted by impressions. Confidence = 1 - p_value from one-sample t-test against global mean.
- **Interaction lift**: `combined_avg / max(solo_a_avg, solo_b_avg) - 1`. Positive = synergy, negative = conflict.
- **Fatigue detection**: CTR declining for 3+ consecutive days on the same audience segment.
- **Budget allocation**: Thompson sampling with Beta(successes+1, failures+1) prior per variant.

## CLI commands

```bash
# Run a single optimization cycle
python -m src.main run-cycle --campaign-id <uuid>

# Seed the gene pool from JSON
python -m src.main seed-gene-pool --file gene_pool_seed.json

# Create a new campaign
python -m src.main create-campaign --name "Q2 Product Launch" \
  --platform meta --daily-budget 100 --max-variants 10

# Check system health
python -m src.main health-check

# Generate a weekly report manually
python -m src.main weekly-report --campaign-id <uuid>

# Backfill element performance from existing metrics
python -m src.main backfill-elements --campaign-id <uuid>
```

## Environment variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/adagent

# Anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# Meta Marketing API
META_APP_ID=...
META_APP_SECRET=...
META_ACCESS_TOKEN=...
META_AD_ACCOUNT_ID=act_...

# Slack
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...

# Email (SendGrid)
SENDGRID_API_KEY=...
REPORT_EMAIL_TO=team@company.com
REPORT_EMAIL_FROM=adagent@company.com

# Application
LOG_LEVEL=INFO
CYCLE_SCHEDULE_CRON=0 6 * * *
MAX_CONCURRENT_VARIANTS=10
MIN_IMPRESSIONS=1000
CONFIDENCE_THRESHOLD=0.95
```

## Common tasks for Claude Code

### Adding a new gene pool slot
1. Add the slot values to `gene_pool_seed.json`
2. Update `GenomeSchema` in `src/models/genome.py` to include the new slot
3. Create an Alembic migration to add seed data
4. Update the generator agent's system prompt to be aware of the new slot
5. Run `/test` to verify nothing broke

### Adding a new ad platform
1. Create `src/adapters/<platform>.py` implementing the `BaseAdapter` interface
2. Map genome slots to the platform's creative format
3. Create a mock client in the adapter for testing
4. Add platform to the `platform_type` enum in the DB schema
5. Create a migration for the new enum value
6. Write integration tests mirroring `test_meta_adapter.py`

### Debugging a failed cycle
1. Check `test_cycles` table for the cycle with `error_log` populated
2. Check `cycle_actions` for partial completion — which steps succeeded
3. Check application logs for the full stack trace
4. Common issues: API rate limit (check backoff), budget exhaustion (check `remaining_budget()`), LLM returned invalid genome (check validation gate)

## Build commands

```bash
# Install dependencies
pip install -e ".[dev]" --break-system-packages

# Run tests
pytest -xvs

# Run tests with coverage
pytest --cov=src --cov-report=term-missing

# Format and lint
ruff format . && ruff check --fix .

# Run database migrations
alembic upgrade head

# Start local Postgres + TimescaleDB
docker-compose up -d db

# Build and run everything
docker-compose up --build
```

## Important constraints

1. **Gene pool is the source of truth** — the generator agent must never invent creative elements outside the gene pool. Every slot value in a genome must exist in the `gene_pool` table.

2. **Statistics are deterministic** — never use an LLM for statistical calculations, significance tests, or numerical analysis. Use scipy.stats.

3. **Budget guardrails are non-negotiable** — the system must never exceed the campaign's daily_budget. Per-variant caps are enforced in the deployment step.

4. **One hypothesis per variant** — when generating new variants, change exactly one element from a proven combination. This enables proper attribution of performance changes.

5. **Canonical interaction ordering** — element pairs in the `element_interactions` table must satisfy `slot_a_name < slot_b_name` (or same slot with `slot_a_value < slot_b_value`). This prevents duplicate pairs.

6. **No destructive actions without logging** — every pause, budget change, and retirement must be recorded in `cycle_actions` with the full context in the `details` JSONB column.
