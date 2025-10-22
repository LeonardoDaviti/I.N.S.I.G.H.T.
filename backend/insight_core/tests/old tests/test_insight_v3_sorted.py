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

class InsightV3Sorted:

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
    
    async def display_posts(self, posts: List[Dict[str, Any]], title: str):
        """Display posts in the console"""
        ConsoleOutput.render_report_to_console(posts, title)
        
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
        sorted_posts = self.sort_posts_by_date(all_posts)
        
        # Display sorted results
        title = f"Telegram Posts from {len(channels)} channels ({len(sorted_posts)} total, sorted by date)"
        await self.display_posts(sorted_posts, title)
        
        await self.telegram_connector.disconnect()

if __name__ == "__main__":
    test_v3 = InsightV3Sorted()
    asyncio.run(test_v3.run())