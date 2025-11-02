#!/usr/bin/env python3
"""
Export posts to CSV for BERTopic analysis.

Usage: python backend/insight_core/scripts/export.py

This script will:
1. Ask for export type (single date or date range)
2. Fetch posts from the database
3. Export to CSV file in the scripts folder
"""
import sys
from pathlib import Path
import csv
from datetime import datetime, timedelta

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND_DIR))

import psycopg
from insight_core.db.ensure_db import ensure_database
from insight_core.db.repo_posts import PostsRepository
from insight_core.logs.core.logger_config import setup_logging, get_component_logger

setup_logging(debug_mode=True)
logger = get_component_logger("export_posts")


def export_posts_to_csv(start_date_str: str, end_date_str: str, output_dir: Path):
    """
    Export posts for a date range to CSV.
    
    Args:
        start_date_str: Start date in YYYY-MM-DD format
        end_date_str: End date in YYYY-MM-DD format (same as start for single date)
        output_dir: Directory to save the CSV file
    """
    try:
        # Validate date formats
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        
        if end_date < start_date:
            logger.error(f"❌ End date ({end_date_str}) must be after or equal to start date ({start_date_str})")
            return False
        
        logger.info(f"📅 Fetching posts from {start_date_str} to {end_date_str}")
        
    except ValueError as e:
        logger.error(f"❌ Invalid date format. Expected YYYY-MM-DD. Error: {e}")
        return False
    
    # Get database connection
    db_url = ensure_database()
    repo = PostsRepository(db_url)
    
    # Fetch posts for each date in the range
    all_posts = []
    current_date = start_date
    
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            while current_date <= end_date:
                date_str = current_date.strftime("%Y-%m-%d")
                logger.info(f"   Fetching posts for {date_str}...")
                posts = repo.get_posts_by_date(cur, current_date)
                
                if posts:
                    logger.info(f"   ✅ Found {len(posts)} posts for {date_str}")
                    all_posts.extend(posts)
                else:
                    logger.info(f"   ⚠️  No posts found for {date_str}")
                
                current_date += timedelta(days=1)
    
    if not all_posts:
        logger.warning(f"⚠️  No posts found in date range: {start_date_str} to {end_date_str}")
        return False
    
    logger.info(f"✅ Total posts collected: {len(all_posts)}")
    
    # Prepare CSV file path
    if start_date_str == end_date_str:
        csv_filename = f"{start_date_str}.csv"
    else:
        csv_filename = f"{start_date_str}_to_{end_date_str}.csv"
    
    csv_path = output_dir / csv_filename
    
    # Define CSV columns (optimized for BERTopic)
    fieldnames = [
        'id',
        'title',
        'content',
        'text',  # Combined title + content for BERTopic
        'url',
        'platform',
        'source',
        'published_at',
        'categories',
        'media_urls'
    ]
    
    # Write to CSV
    logger.info(f"💾 Writing to: {csv_path}")
    
    with open(csv_path, 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()
        
        for post in all_posts:
            # Combine title and content for BERTopic analysis
            title = post.get('title', '')
            content = post.get('content', '')
            combined_text = f"{title} {content}".strip()
            
            # Convert lists to strings for CSV
            categories = ', '.join(post.get('categories', [])) if post.get('categories') else ''
            media_urls = ', '.join(post.get('media_urls', [])) if post.get('media_urls') else ''
            
            row = {
                'id': post.get('id', ''),
                'title': title,
                'content': content,
                'text': combined_text,  # This is what BERTopic will use
                'url': post.get('url', ''),
                'platform': post.get('platform', ''),
                'source': post.get('source', ''),
                'published_at': str(post.get('published_at', '')),
                'categories': categories,
                'media_urls': media_urls
            }
            
            writer.writerow(row)
    
    logger.info(f"✅ Successfully exported {len(all_posts)} posts to {csv_filename}")
    logger.info(f"📊 File location: {csv_path.absolute()}")
    
    # Show summary statistics
    by_platform = {}
    by_date = {}
    
    for post in all_posts:
        platform = post.get('platform', 'unknown')
        by_platform[platform] = by_platform.get(platform, 0) + 1
        
        pub_date = str(post.get('published_at', ''))[:10]  # Get YYYY-MM-DD part
        by_date[pub_date] = by_date.get(pub_date, 0) + 1
    
    logger.info(f"\n📊 Summary:")
    logger.info(f"   Total posts: {len(all_posts)}")
    logger.info(f"   Date range: {start_date_str} to {end_date_str}")
    logger.info(f"   Days covered: {(end_date - start_date).days + 1}")
    logger.info(f"\n   By platform:")
    for platform, count in sorted(by_platform.items()):
        logger.info(f"      {platform}: {count}")
    
    logger.info(f"\n💡 To use with BERTopic:")
    logger.info(f"   import pandas as pd")
    logger.info(f"   df = pd.read_csv('{csv_path.absolute()}')")
    logger.info(f"   docs = df['text'].tolist()")
    logger.info(f"   # Then use docs with BERTopic")
    
    return True


def main():
    """Main function to run the export script."""
    print("=" * 60)
    print("📤 I.N.S.I.G.H.T. Posts Export Tool")
    print("=" * 60)
    print("\nExport posts to CSV for BERTopic analysis\n")
    
    # Ask for export type
    print("Export options:")
    print("  1. Single date")
    print("  2. Date range")
    
    choice = input("\nSelect option (1 or 2) [default: 1]: ").strip()
    
    if choice == "2":
        # Date range export
        print("\n📅 Date Range Export")
        start_date_str = input("Enter start date (YYYY-MM-DD): ").strip()
        end_date_str = input("Enter end date (YYYY-MM-DD): ").strip()
        
        if not start_date_str or not end_date_str:
            print("❌ Both start and end dates are required. Exiting.")
            return
        
        print(f"\n📊 Exporting posts from {start_date_str} to {end_date_str}...")
        print("This may take a moment for large date ranges...\n")
        
    else:
        # Single date export
        print("\n📅 Single Date Export")
        date_str = input("Enter date (YYYY-MM-DD): ").strip()
        
        if not date_str:
            print("❌ No date provided. Exiting.")
            return
        
        start_date_str = date_str
        end_date_str = date_str
    
    # Get output directory (same as script location)
    output_dir = Path(__file__).resolve().parent
    
    # Export posts
    success = export_posts_to_csv(start_date_str, end_date_str, output_dir)
    
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

