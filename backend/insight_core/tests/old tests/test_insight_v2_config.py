"""
INSIGHT Express Test - Version 2: Config Manager + Multiple Channels
===================================================================

Purpose: Use ConfigManager to load all Telegram channels from sources.json
Scope: All configured channels, 10 posts each, console output
Focus: Configuration management and multi-channel processing
"""

import asyncio
import os
import sys
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.telegram_connector import TelegramConnector
from config.config_manager import ConfigManager
from output.console_output import ConsoleOutput

class InsightV2Config:

    def __init__(self):
        self.config_manager = ConfigManager()
        self.limit = 10
    
    async def display_posts(self, posts: List[Dict[str, Any]], title: str):
        """Display posts in the console"""
        ConsoleOutput.render_report_to_console(posts, title)
        
    async def run(self):
        """Main execution loop with config management"""
        # Load config
        config = self.config_manager.load_config()
        telegram_config = self.config_manager.get_platform_config(config, 'telegram')
        
        channels = telegram_config.get('channels', [])
        
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
        
        # Display combined results
        title = f"Telegram Posts from {len(channels)} channels ({len(all_posts)} total)"
        await self.display_posts(all_posts, title)
        
        await self.telegram_connector.disconnect()

if __name__ == "__main__":
    test_v2 = InsightV2Config()
    asyncio.run(test_v2.run())