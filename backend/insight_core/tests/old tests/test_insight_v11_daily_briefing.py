"""
INSIGHT Express Test - Version 3: Config Manager + Multiple Channels + Date Sorting
==================================================================================

Purpose: Use ConfigManager to load all Telegram channels and sort posts by date
Scope: All configured channels, 10 posts each, sorted by date, console output
Focus: Configuration management, multi-channel processing, and chronological sorting
"""

import asyncio
import os
import sys
from typing import List, Dict, Any
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.telegram_connector import TelegramConnector
from connectors.rss_connector import RssConnector

from config.config_manager import ConfigManager
from output.console_output import ConsoleOutput
from output.html_output import HTMLOutput
from processors.ai.gemini_processor import GeminiProcessor

class InsightV4DaySorting:

    def __init__(self):
        self.config_manager = ConfigManager()
        self.limit = 10
    
    def sort_posts_by_date(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort posts by date (newest first)"""
        return sorted(
            posts, 
            key=lambda post: post.get('date', datetime.min), 
            reverse=True
        )
    
    def sort_posts_by_day(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort posts by day (newest first)"""
        posts_by_day = defaultdict(list)

        # Adding posts by the day
        for post in posts:
            post_date = post.get('date', datetime.min)
            if isinstance(post_date, datetime):
                day_key = post_date.date()
                posts_by_day[day_key].append(post)
        
        # Sorting days
        sorted_by_days = {}
        for day in sorted(posts_by_day.keys(), reverse=True):
            sorted_by_days[day] = sorted(
                posts_by_day[day],
                key = lambda p: p.get('date', datetime.min),
                reverse=True
            )
        
        return sorted_by_days

    async def display_posts(self, posts: List[Dict[str, Any]], title: str):
        """Display posts in the console"""
        ConsoleOutput.render_report_to_console(posts, title)
        
    
    async def run(self):
        """Main execution loop with date sorting"""
        # Load config
        config = self.config_manager.load_config()
        telegram_config = self.config_manager.get_platform_config(config, 'telegram')
        rss_config = self.config_manager.get_platform_config(config, 'rss')
        
        channels = telegram_config.get('channels', [])
        feeds = rss_config.get('feeds', [])
        
        # Setup connector
        self.telegram_connector = TelegramConnector()
        self.rss_connector = RssConnector()
        
        self.gemini_processor = GeminiProcessor()

        self.telegram_connector.setup_connector()
        self.rss_connector.setup_connector()

        self.gemini_processor.setup_processor()

        await self.rss_connector.connect()
        await self.telegram_connector.connect()
        await self.gemini_processor.connect()

        # Collect posts from all channels
        all_posts = []
        
        for channel in channels:
            try:
                posts = await self.telegram_connector.fetch_posts(channel, self.limit)
                all_posts.extend(posts)
                print(f"Fetched {len(posts)} posts from @{channel}")
            except Exception as e:
                print(f"Error fetching from @{channel}: {e}")
        
        for feed in feeds:
            try:
                posts = await self.rss_connector.fetch_posts(feed, self.limit)
                all_posts.extend(posts)
                print(f"Fetched {len(posts)} posts from {feed}")
            except Exception as e:
                print(f"Error fetching from {feed}: {e}")


        # Sorted by Day
        posts_by_days = self.sort_posts_by_day(all_posts)

        target_days = ['2025-07-08']

        for day, day_posts in posts_by_days.items():
            # Only show posts for target days (optional filter)
            if target_days and day.strftime('%Y-%m-%d') not in target_days:
                continue
                
            print(f"\n📅 {day.strftime('%B %d, %Y')} - {len(day_posts)} posts")
            title = f"Posts for {day.strftime('%B %d, %Y')} ({len(day_posts)} posts)"
            ConsoleOutput.render_report_to_console(day_posts, title)
            # Generate daily briefing
            briefing = await self.gemini_processor.daily_briefing(day_posts)
            print("\nDaily Briefing:")
            print(briefing)
            print("-" * 60)

            html_output = HTMLOutput(f"Daily Briefing for {day.strftime('%B %d, %Y')}")
            html_output.render_daily_briefing(day, briefing, day_posts)

            filename = f"daily_briefing_{day.strftime('%Y_%m_%d')}.html"
            html_output.save_to_file(filename)
            print(f"Generated HTML briefing: {filename}")
            print("-" * 60)

        # print(posts_by_days)

        # print(posts_by_days.keys())

        # for day, day_posts in posts_by_days.items():
        #     print(day)
            # title = f"Posts for {day.strftime('%B %d, %Y')} ({len(day_posts)} posts)"
            # await self.display_posts(day_posts, title)
            
        
        # Display sorted results
        # title = f"Telegram Posts from {len(channels)} channels ({len(sorted_posts)} total, sorted by date)"
        # await self.display_posts(sorted_posts, title)
        
        await self.telegram_connector.disconnect()
        await self.gemini_processor.disconnect()

if __name__ == "__main__":
    test_v4 = InsightV4DaySorting()
    asyncio.run(test_v4.run())