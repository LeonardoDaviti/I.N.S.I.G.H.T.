#!/usr/bin/env python3
"""
sources.json and the database (issue 0071): the database is the truth.

  json-to-db         import the file now: adds sources and sets their on/off, never deletes
  json-to-db --once  the same, only if no start imported a file into this database before
                     (what the containers run at start)
  db-to-json         export the database's sources to the file

Exits 1 when the file could not be read or an entry was skipped; the start scripts go on.
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
    parser = argparse.ArgumentParser(description="Import sources.json into the database (add-only), or export it")
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
        "--once",
        action="store_true",
        help="Import only if no start imported a file into this database before",
    )
    return parser.parse_args()


def main() -> None:
    setup_logging(debug_mode=False)
    logger = get_component_logger("sync_sources_json")
    args = parse_args()

    db_url = ensure_database()
    os.environ["DATABASE_URL"] = db_url
    service = SourceConfigSyncService(db_url, config_path=args.config)

    if args.direction == "db-to-json":
        logger.info("Exported: %s", service.export_db_to_json())
        return
    result = service.import_once() if args.once else service.import_json()
    if result.get("imported_before") or (result["read"] and not result["skipped"]):
        return
    sys.exit(1)


if __name__ == "__main__":
    main()
