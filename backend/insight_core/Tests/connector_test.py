import sys
import os
from typing import List, Dict, Any
import asyncio

# Add backend directory to path (one level higher than before)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from insight_core.connectors.base_connector import BaseConnector
from insight_core.connectors.telegram_connector import TelegramConnector
from insight_core.output.console_output import ConsoleOutput

    
async def display_posts(posts: List[Dict[str, Any]]):
    """Render posts in the console"""
    ConsoleOutput.render_report_to_console(posts, "Telegram Posts")


class TestConnector:
    def __init__(self, connector: BaseConnector):
        self.source = "durov"
        self.limit = 10
        self.connector = connector()

    async def connect_connector(self):
        self.connector.setup_connector()
        await self.connector.connect()

        try:
            posts = await self.connector.fetch_posts(self.source, self.limit)
        except Exception as e:
            print(f"Error fetching posts: {e}")
            return
        
        await display_posts(posts)
        
        await self.connector.disconnect()


if __name__ == "__main__":
    test_connector = TestConnector(TelegramConnector)
    asyncio.run(test_connector.connect_connector())