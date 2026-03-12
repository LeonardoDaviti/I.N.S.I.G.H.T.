#!/usr/bin/env python3
"""
Sync sources.json and the database source registry in either direction.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.ensure_db import ensure_database
from insight_core.logs.core.logger_config import get_component_logger, setup_logging
from insight_core.services.source_config_sync_service import SourceConfigSyncService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync sources.json and database sources")
    parser.add_argument(
        "direction",
        choices=("json-to-db", "db-to-json"),
        help="Sync direction",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="Optional path to sources.json",
    )
    parser.add_argument(
        "--no-mirror",
        action="store_true",
        help="Do not delete DB sources that are missing from sources.json when importing",
    )
    return parser.parse_args()


def main() -> None:
    setup_logging(debug_mode=False)
    logger = get_component_logger("sync_sources_json")
    args = parse_args()

    db_url = ensure_database()
    os.environ["DATABASE_URL"] = db_url
    service = SourceConfigSyncService(db_url, config_path=args.config)

    if args.direction == "json-to-db":
        result = service.sync_json_to_db(mirror=not args.no_mirror)
    else:
        result = service.sync_db_to_json()

    if result.get("success"):
        logger.info("Source sync completed: %s", result)
        return

    logger.error("Source sync failed: %s", result)
    sys.exit(1)


if __name__ == "__main__":
    main()
