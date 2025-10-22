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
from config.config_manager import ConfigManager
from output.console_output import ConsoleOutput
from output.html_output import HTMLOutput

class InsightV4DaySorting:

    def __init__(self):
        self.config_manager = ConfigManager()
        self.limit = 20
    
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
        
    # async def render_html_report(self, posts: List[Dict[str, Any]]):
    #     """Render HTML report"""
    #     html_output = HTMLOutput()
    #     html_output.render_report(posts)

    async def run(self):
        """Main execution loop with date sorting"""
        # Load config
        config = self.config_manager.load_config()
        telegram_config = self.config_manager.get_platform_config(config, 'telegram')
        
        if not telegram_config or not telegram_config.get('enabled', False):
            print("Telegram not enabled in config")
            return
        
        channels = telegram_config.get('channels', [])
        if not channels:
            print("No telegram channels configured")
            return
        
        # Setup connector
        self.telegram_connector = TelegramConnector()
        self.telegram_connector.setup_connector()
        await self.telegram_connector.connect()

        
        
        # Collect posts from all channels
        all_posts = []
        
        for channel in channels:
            try:
                posts = await self.telegram_connector.fetch_posts(channel, self.limit)
                all_posts.extend(posts)
                print(f"Fetched {len(posts)} posts from @{channel}")
            except Exception as e:
                print(f"Error fetching from @{channel}: {e}")
        
        # Sort posts by date (newest first)
        # sorted_posts = self.sort_posts_by_date(all_posts)

        # Sorted by Day
        posts_by_days = self.sort_posts_by_day(all_posts)

        for day, day_posts in posts_by_days.items():
            title = f"Posts for {day.strftime('%B %d, %Y')} ({len(day_posts)} posts)"
            await self.display_posts(day_posts, title)
            filename = f"insight_test_v4_{day.strftime('%B %d, %Y')}.html"
            html_output = HTMLOutput("I.N.S.I.G.H.T. Report")
            html_output.render_report(day_posts)
            html_output.save_to_file(filename)
            
        
        # Display sorted results
        # title = f"Telegram Posts from {len(channels)} channels ({len(sorted_posts)} total, sorted by date)"
        # await self.display_posts(sorted_posts, title)
        
        await self.telegram_connector.disconnect()

if __name__ == "__main__":
    test_v4 = InsightV4DaySorting()
    asyncio.run(test_v4.run())