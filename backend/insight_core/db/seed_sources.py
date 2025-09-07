import os, sys, json
from pathlib import Path
from typing import Dict, Any, List, Tuple

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
import psycopg
from psycopg import Connection, Cursor

load_dotenv()

from insight_core.logs.core.logger_config import setup_logging, get_component_logger
from insight_core.db.ensure_db import ensure_database


def load_sources_json(path: Path) -> Dict[str, Any]:
    """
    Read the sources.json file and parse it into a dict.
    """
    with open(path, 'r', encoding='utf-8') as file:
        return json.load(file)

def flatten_sources(doc: Dict[str, Any]) -> List[Tuple[str, str, bool]]:
    """
    Convert hierarchical platforms to a flat list: (platform, handle_or_url, enabled_bool).
    """
    flat = []
    for platform_name, platform_data in doc['platforms'].items():
        sources = platform_data.get('sources', [])
        for source in sources:
            handle_or_url = source.get('id')
            if not handle_or_url:
                continue
            enabled = source.get('state', 'disabled') == 'enabled'
            flat.append((platform_name, handle_or_url, enabled))
    return flat

def upsert_sources(cur: Cursor, rows: List[Tuple[str, str, bool]]) -> Tuple[int, int]:
    """
    Insert missing sources and update changed ones.
    Returns (inserted_count, updated_count).
    """
    inserted_count = 0
    updated_count = 0
    for row in rows:
        platform, handle_or_url, enabled = row
        cur.execute("""
            SELECT id, enabled FROM sources WHERE platform = %s AND handle_or_url = %s
        """, (platform, handle_or_url))
        existing = cur.fetchone()
        if existing:
            if existing[1] != enabled:
                cur.execute("""
                    UPDATE sources SET enabled = %s, updated_at = now() WHERE id = %s
                """, (enabled, existing[0]))
                updated_count += 1
                
        else:
            cur.execute("""
                INSERT INTO sources (platform, handle_or_url, enabled) VALUES (%s, %s, %s)
            """, (platform, handle_or_url, enabled))
            inserted_count += 1
            
    return inserted_count, updated_count

def main() -> None:
    """
    Bootstrap DB/URL, connect, seed sources and log counts.
    """ 
    setup_logging(debug_mode=False)
    logger = get_component_logger("db_seed_sources")

    try:
        db_url = ensure_database()
        os.environ["DATABASE_URL"] = db_url
        logger.info("Database was ensured and using")
    except Exception as e:
        logger.exception("Database bootstrap failed: %s", e)
        sys.exit(1)

    try:
        with psycopg.connect(db_url) as conn:
            with conn.cursor() as cur:
                doc = load_sources_json(Path(__file__).resolve().parent.parent / "config" / "sources.json")
                rows = flatten_sources(doc)
                inserted, updated = upsert_sources(cur, rows)
            conn.commit()
        logger.info("Inserted %s sources, updated %s", inserted, updated)
    except Exception as e:
        logger.exception("Sources seeding failed: %s", e)
        sys.exit(1)

if __name__ == "__main__":
    main()

# doc = load_sources_json(Path(__file__).resolve().parent.parent / "config" / "sources.json")
# print(flatten_sources(doc))