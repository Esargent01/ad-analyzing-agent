"""Gene pool seeder that reads gene_pool_seed.json and upserts into the gene_pool table."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.engine import get_session
from src.db.tables import GenePoolEntry

logger = logging.getLogger(__name__)

DEFAULT_SEED_FILE = Path(__file__).resolve().parent.parent.parent / "gene_pool_seed.json"


def _load_seed_data(file_path: Path) -> list[dict[str, str | None]]:
    """Parse the seed JSON file into a flat list of gene pool records.

    Expected JSON format::

        {
          "slots": {
            "headline": [
              {"value": "...", "description": "..."},
              ...
            ],
            ...
          }
        }
    """
    with open(file_path) as f:
        data = json.load(f)

    records: list[dict[str, str | None]] = []
    # Support both flat format {"headline": [...]} and wrapped {"slots": {"headline": [...]}}
    slots = data.get("slots", data)
    for slot_name, entries in slots.items():
        for entry in entries:
            records.append({
                "slot_name": slot_name,
                "slot_value": entry["value"],
                "description": entry.get("description"),
            })
    return records


async def seed_gene_pool(
    session: AsyncSession,
    file_path: Path = DEFAULT_SEED_FILE,
) -> int:
    """Upsert gene pool entries from a seed JSON file.

    Returns the number of rows upserted.
    """
    records = _load_seed_data(file_path)

    if not records:
        logger.warning("No gene pool entries found in %s", file_path)
        return 0

    upserted = 0
    for record in records:
        stmt = (
            pg_insert(GenePoolEntry)
            .values(
                slot_name=record["slot_name"],
                slot_value=record["slot_value"],
                description=record["description"],
                is_active=True,
            )
            .on_conflict_do_update(
                constraint="uq_gene_pool_slot_value",
                set_={
                    "description": record["description"],
                    "is_active": True,
                    "retired_at": None,
                },
            )
        )
        await session.execute(stmt)
        upserted += 1

    await session.flush()
    logger.info("Upserted %d gene pool entries from %s", upserted, file_path)
    return upserted


async def run_seeder(file_path: Path = DEFAULT_SEED_FILE) -> int:
    """Standalone entry point: open a session and seed the gene pool.

    Usage from CLI::

        python -m src.db.seed
    """
    async with get_session() as session:
        count = await seed_gene_pool(session, file_path)
    return count


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO)
    count = asyncio.run(run_seeder())
    print(f"Seeded {count} gene pool entries.")
