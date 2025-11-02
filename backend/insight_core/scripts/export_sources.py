#!/usr/bin/env python3
"""
Export sources to CSV.

Usage: python backend/insight_core/scripts/export_sources.py

This script will:
1. Fetch all sources from the database
2. Export to CSV file named sources.csv in the scripts folder
"""
import sys
from pathlib import Path
import csv
from datetime import datetime

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from insight_core.db.ensure_db import ensure_database
from insight_core.db.repo_sources import SourcesRepository
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

setup_logging(debug_mode=True)
logger = get_component_logger("export_sources")


def export_sources_to_csv(output_dir: Path):
    """
    Export all sources to CSV with post counts.
    
    Args:
        output_dir: Directory to save the CSV file
    """
    logger.info("📋 Fetching sources from database")
    
    # Get database connection
    db_url = ensure_database()
    repo = SourcesRepository(db_url)
    
    # Fetch sources with post counts
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            sources = repo.get_sources_with_post_counts(cur)
    
    if not sources:
        logger.warning("⚠️  No sources found in database")
        return False
    
    logger.info(f"✅ Found {len(sources)} sources")
    
    # Prepare CSV file path
    csv_filename = "sources.csv"
    csv_path = output_dir / csv_filename
    
    # Define CSV columns
    fieldnames = [
        'id',
        'platform',
        'handle_or_url',
        'enabled',
        'post_count',
        'created_at',
        'updated_at'
    ]
    
    # Write to CSV
    logger.info(f"💾 Writing to: {csv_path}")
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for source in sources:
            row = {
                'id': source.get('id', ''),
                'platform': source.get('platform', ''),
                'handle_or_url': source.get('handle_or_url', ''),
                'enabled': source.get('enabled', False),
                'post_count': source.get('post_count', 0),
                'created_at': str(source.get('created_at', '')),
                'updated_at': str(source.get('updated_at', ''))
            }
            
            writer.writerow(row)
    
    # Print summary statistics
    enabled_count = sum(1 for s in sources if s.get('enabled'))
    total_posts = sum(s.get('post_count', 0) for s in sources)
    
    logger.info(f"✅ Successfully exported {len(sources)} sources to {csv_filename}")
    logger.info(f"📊 File location: {csv_path.absolute()}")
    logger.info(f"\n📈 Summary Statistics:")
    logger.info(f"   Total sources: {len(sources)}")
    logger.info(f"   Enabled sources: {enabled_count}")
    logger.info(f"   Disabled sources: {len(sources) - enabled_count}")
    logger.info(f"   Total posts: {total_posts}")
    
    # Group by platform
    by_platform = {}
    for source in sources:
        platform = source.get('platform', 'unknown')
        if platform not in by_platform:
            by_platform[platform] = {'count': 0, 'posts': 0}
        by_platform[platform]['count'] += 1
        by_platform[platform]['posts'] += source.get('post_count', 0)
    
    logger.info(f"\n📊 By Platform:")
    for platform, stats in sorted(by_platform.items()):
        logger.info(f"   {platform}: {stats['count']} sources, {stats['posts']} posts")
    
    logger.info(f"\n💡 To load in Python:")
    logger.info(f"   import pandas as pd")
    logger.info(f"   df = pd.read_csv('{csv_path.absolute()}')")
    
    return True


def main():
    """Main function to run the export script."""
    print("=" * 60)
    print("📤 I.N.S.I.G.H.T. Sources Export Tool")
    print("=" * 60)
    print("\nExport all sources to CSV\n")
    
    # Get output directory (same as script location)
    output_dir = Path(__file__).resolve().parent
    
    # Export sources
    success = export_sources_to_csv(output_dir)
    
    if success:
        print("\n" + "=" * 60)
        print("✅ Export completed successfully!")
        print("=" * 60)
    else:
        print("\n" + "=" * 60)
        print("❌ Export failed. Check logs for details.")
        print("=" * 60)


if __name__ == "__main__":
    main()