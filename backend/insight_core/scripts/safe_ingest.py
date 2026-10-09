"""CLI over the ingestion module: one fetch run, the report printed as JSON.

    python -m insight_core.scripts.safe_ingest [--force] [--folder ID | --source ID]

Without a selector every enabled source is considered and only the due ones are fetched
(the scheduler tick's run). --force ignores cadence and backoff, never unavailability.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Sequence

BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

from insight_core.ingestion import FetchRequest, SourceSelector, Trigger, run_ingestion  # noqa: E402


def parse_args(argv: Sequence[str] | None = None) -> FetchRequest:
    parser = argparse.ArgumentParser(description="Run one ingestion fetch run.")
    parser.add_argument("--force", action="store_true", help="ignore cadence and backoff")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--folder", metavar="ID", help="only the enabled sources of this folder/track")
    target.add_argument("--source", metavar="ID", help="only this source (even when disabled)")
    args = parser.parse_args(argv)
    if args.folder:
        selector = SourceSelector.folder(args.folder)
    elif args.source:
        selector = SourceSelector.source(args.source)
    else:
        selector = SourceSelector.all()
    return FetchRequest(selector, Trigger.CLI, force=args.force)


def main(argv: Sequence[str] | None = None) -> int:
    from insight_core.logs.core.logger_config import setup_logging

    setup_logging(debug_mode=False)
    report = asyncio.run(run_ingestion(parse_args(argv)))
    print(json.dumps(report.to_payload(), indent=2))
    return 0 if report.job_status == "success" else 1


if __name__ == "__main__":
    sys.exit(main())
