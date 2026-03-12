import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.db.ensure_db import ensure_database
from insight_core.logs.core.logger_config import get_component_logger, setup_logging
from insight_core.services.source_config_sync_service import SourceConfigSyncService


def main() -> None:
    setup_logging(debug_mode=False)
    logger = get_component_logger("db_seed_sources")

    db_url = ensure_database()
    os.environ["DATABASE_URL"] = db_url

    service = SourceConfigSyncService(db_url)
    result = service.sync_json_to_db(mirror=True)
    if not result.get("success"):
        logger.error("Sources seeding failed: %s", result)
        sys.exit(1)

    logger.info("Inserted %s sources, updated %s, deleted %s",
                result["stats"]["added"],
                result["stats"]["updated"],
                result["stats"]["deleted"])


if __name__ == "__main__":
    main()
