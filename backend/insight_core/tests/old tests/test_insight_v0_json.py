"""
INSIGHT Express Test - Version 1: Basic Telegram Connector
==========================================================

Purpose: Test the most basic functionality - direct Telegram connector usage
Scope: Single channel, 10 posts, console output only
Focus: Understanding the core Telegram connector workflow

This version teaches us:
1. How to setup a Telegram connector from scratch
2. How to authenticate and connect
3. How to fetch posts from a single channel
4. How to display results in console

Educational Goals:
- Understand the connector lifecycle (setup -> connect -> fetch -> disconnect)
- See the raw data structure from Telegram
- Verify authentication is working
- Test basic error handling
"""

import asyncio
import os
import sys
import json
import pprint
from datetime import datetime
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.telegram_connector import TelegramConnector
from output.console_output import ConsoleOutput

class InsightV1TelegramBasic:

    def __init__(self):
        self.test_channel = "durov"
        self.limit = 10
    
    async def display_posts(self, posts: List[Dict[str, Any]]):
        """Display posts in the console"""
        ConsoleOutput.render_report_to_console(posts, "Telegram Posts")
        
    async def run(self):
        """Main execution loop"""
        self.telegram_connector = TelegramConnector()

        self.telegram_connector.setup_connector()
        await self.telegram_connector.connect()

        try:
            posts = await self.telegram_connector.fetch_posts(self.test_channel, self.limit)
            for post in posts:
                post['date'] = post['date'].isoformat()
                pretty_post = json.dumps(post, indent = 4)
                print(pretty_post)
                # pprint.pprint(post)
        except Exception as e:
            print(f"Error fetching posts: {e}")
            return
        
        # await self.display_posts(posts)
        
        await self.telegram_connector.disconnect()

if __name__ == "__main__":
    test_telegram_basic = InsightV1TelegramBasic()
    asyncio.run(test_telegram_basic.run())
