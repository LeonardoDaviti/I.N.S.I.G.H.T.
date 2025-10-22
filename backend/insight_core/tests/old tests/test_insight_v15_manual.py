import asyncio
import os
import sys
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta, date
from collections import defaultdict
from time import sleep
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.telegram_connector import TelegramConnector
from connectors.rss_connector import RssConnector
from config.config_manager import ConfigManager
from output.html_output import HTMLOutput
from processors.ai.gemini_processor import GeminiProcessor
from processors.utils.post_utils import PostSorter

class SimpleEnhancedInsight:
    
    def __init__(self, user_timezone_offset: int = 4):
        self.config_manager = ConfigManager()
        self.limit = 10
        self.user_timezone_offset = user_timezone_offset
        self.user_timezone = timezone(timedelta(hours=user_timezone_offset))
        self.post_sorter = PostSorter()
    

    async def fetch_all_posts(self) -> List[Dict[str, Any]]:
        config = self.config_manager.load_config()
        telegram_config = self.config_manager.get_platform_config(config, 'telegram')
        rss_config = self.config_manager.get_platform_config(config, 'rss')
        
        channels = telegram_config.get('channels', [])
        feeds = rss_config.get('feeds', [])
        
        all_posts = []
        
        # Fetch Telegram posts
        if channels:
            telegram_connector = TelegramConnector()
            telegram_connector.setup_connector()
            await telegram_connector.connect()
            
            for channel in channels:
                try:
                    posts = await telegram_connector.fetch_posts(channel, self.limit)
                    all_posts.extend(posts)
                except Exception:
                    pass
                    
            await telegram_connector.disconnect()
        
        # Fetch RSS posts
        if feeds:
            rss_connector = RssConnector()
            rss_connector.setup_connector()
            await rss_connector.connect()
            
            for feed in feeds:
                try:
                    posts = await rss_connector.fetch_posts(feed, self.limit)
                    all_posts.extend(posts)
                except Exception:
                    pass
                    
            await rss_connector.disconnect()
        
        return all_posts

    async def generate_enhanced_html(self, target_date: str = None) -> str:
        """
        Generate enhanced HTML for a specific date or the latest available date
        
        Args:
            target_date: Date string in format 'YYYY-MM-DD' or None for latest
            
        Returns:
            HTML content as string
        """
        # Fetch all posts
        all_posts = await self.fetch_all_posts()
        
        
        # Sort posts by day
        posts_by_days = self.post_sorter.sort_posts_by_day(all_posts, self.user_timezone)
        
        target_date = '2025-07-12'

        target_date_obj = datetime.strptime(target_date, '%Y-%m-%d').date()
        day_posts = posts_by_days.get(target_date_obj, [])
        day = target_date_obj
        
        gemini_processor = GeminiProcessor()
        gemini_processor.setup_processor()
        await gemini_processor.connect()

        filename2 = f"simple_standart_briefing_1.html"
        briefing = await gemini_processor.daily_briefing(day_posts)
        html_output2 = HTMLOutput(f"Daily Briefing for {day.strftime('%B %d, %Y')}")
        html_output2.render_daily_briefing(day, briefing, day_posts)
        html_output2.save_to_file(filename2, html_output2._get_html_template())
        sleep(60)
        
        try:
            enhanced_result = await gemini_processor.enhanced_daily_briefing_with_topics(day_posts)
            
            # Generate HTML
            day_datetime = datetime.combine(day, datetime.min.time())
            html_title = f"Enhanced Daily Briefing for {day.strftime('%B %d, %Y')}"
            html_output = HTMLOutput(html_title)
            html_output.render_topic_based_daily_briefing(day_datetime, enhanced_result, day_posts)
            
            return html_output._get_enhanced_html_template()
        
        except Exception:
            return "<html><body><h1>Error processing enhanced briefing</h1></body></html>"
        finally:
            await gemini_processor.disconnect()

    async def run(self, target_date: str = None) -> str:
        """
        Simple run method that returns HTML string
        
        Args:
            target_date: Optional date string in format 'YYYY-MM-DD'
            
        Returns:
            HTML content as string
        """
        return await self.generate_enhanced_html(target_date)

# Simple usage functions
async def get_enhanced_briefing_html(target_date: str = None, timezone_offset: int = 4) -> str:
    """
    Simple function to get enhanced briefing HTML
    
    Args:
        target_date: Date string in format 'YYYY-MM-DD' or None for latest
        timezone_offset: User timezone offset from UTC
        
    Returns:
        HTML content as string
    """
    insight = SimpleEnhancedInsight(timezone_offset)
    html_content = await insight.run(target_date)

    html_output = HTMLOutput()
    html_output.save_to_file(filename="simple_enhanced_briefing_4.html", template=html_content)
    

if __name__ == "__main__":
    
    asyncio.run(get_enhanced_briefing_html())