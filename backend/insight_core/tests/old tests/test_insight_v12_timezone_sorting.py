"""
INSIGHT Express Test - Version 12: Timezone-Aware Date Sorting
==============================================================

Purpose: Enhanced version of V11 with user timezone configuration for accurate time sorting
Scope: All configured channels and RSS feeds with timezone-aware date handling
Focus: User timezone conversion, accurate sorting, and localized time display
New Features: 
- User timezone configuration (+4 GMT support)
- Timezone-aware date conversion for all posts
- Accurate local time sorting and display
- Timezone information in console and HTML output
"""

import asyncio
import os
import sys
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.telegram_connector import TelegramConnector
from connectors.rss_connector import RssConnector

from config.config_manager import ConfigManager
from output.console_output import ConsoleOutput
from output.html_output import HTMLOutput
from processors.ai.gemini_processor import GeminiProcessor

class InsightV12TimezoneAware:

    def __init__(self, user_timezone_offset: int = 4):
        """
        Initialize with user timezone configuration
        
        Args:
            user_timezone_offset: User's timezone offset from UTC (e.g., +4 for GMT+4)
        """
        self.config_manager = ConfigManager()
        self.limit = 10
        # User timezone configuration - default +4 GMT as requested
        self.user_timezone_offset = user_timezone_offset
        self.user_timezone = timezone(timedelta(hours=user_timezone_offset))
        
        print(f"🕐 Configured user timezone: GMT{'+' if user_timezone_offset >= 0 else ''}{user_timezone_offset}")
    
    def convert_to_user_timezone(self, dt: datetime) -> datetime:
        """
        Convert a datetime object to user's timezone
        
        Args:
            dt: Datetime object (assumed UTC if no timezone info)
            
        Returns:
            Datetime object converted to user's timezone
        """
        if dt == datetime.min:
            return dt
            
        try:
            # If datetime is naive (no timezone), assume it's UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            
            # Convert to user's timezone
            return dt.astimezone(self.user_timezone)
        except Exception as e:
            print(f"Warning: Failed to convert timezone for {dt}: {e}")
            return dt
    
    def convert_posts_timezone(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Convert all post timestamps to user's timezone
        
        Args:
            posts: List of posts with potentially UTC timestamps
            
        Returns:
            Posts with timestamps converted to user's timezone
        """
        converted_posts = []
        
        for post in posts:
            if not isinstance(post, dict):
                continue
                
            # Create a copy to avoid modifying original
            converted_post = post.copy()
            
            # Convert the main date field
            if 'date' in converted_post:
                original_date = converted_post['date']
                converted_date = self.convert_to_user_timezone(original_date)
                converted_post['date'] = converted_date
                
                # Add timezone information for debugging
                converted_post['timezone_info'] = {
                    'original_utc': original_date.isoformat() if isinstance(original_date, datetime) else str(original_date),
                    'user_local': converted_date.isoformat() if isinstance(converted_date, datetime) else str(converted_date),
                    'user_timezone': f"GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset}"
                }
            
            converted_posts.append(converted_post)
        
        return converted_posts
    
    def sort_posts_by_date(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sort posts by date (newest first) using user's timezone
        """
        # Convert posts to user timezone first
        timezone_posts = self.convert_posts_timezone(posts)
        
        return sorted(
            timezone_posts, 
            key=lambda post: post.get('date', datetime.min), 
            reverse=True
        )
    
    def sort_posts_by_day(self, posts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Sort posts by day (newest first) using user's timezone
        """
        # Convert posts to user timezone first
        timezone_posts = self.convert_posts_timezone(posts)
        posts_by_day = defaultdict(list)

        # Adding posts by the day (using user's timezone)
        for post in timezone_posts:
            post_date = post.get('date', datetime.min)
            if isinstance(post_date, datetime):
                # Use the converted timezone date for day grouping
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
        """Display posts in the console with timezone information"""
        # Add timezone info to title
        timezone_title = f"{title} (Times in GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset})"
        ConsoleOutput.render_report_to_console(posts, timezone_title)
        
    def get_user_timezone_input(self) -> int:
        """
        Interactive method to get user's timezone preference
        
        Returns:
            User's timezone offset from UTC
        """
        print("\n🌍 Timezone Configuration")
        print("=" * 50)
        print("Examples:")
        print("  • GMT+4 (Gulf/UAE): Enter 4")
        print("  • GMT+3 (Moscow): Enter 3") 
        print("  • GMT-5 (Eastern US): Enter -5")
        print("  • GMT+0 (London/UTC): Enter 0")
        
        while True:
            try:
                user_input = input(f"\nEnter your timezone offset (current: GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset}): ").strip()
                
                if not user_input:  # Use current default
                    return self.user_timezone_offset
                    
                offset = int(user_input)
                if -12 <= offset <= 14:  # Valid timezone range
                    return offset
                else:
                    print("❌ Invalid timezone offset. Please enter a value between -12 and +14.")
            except ValueError:
                print("❌ Invalid input. Please enter a number (e.g., 4 for GMT+4).")
    
    async def run(self):
        """Main execution loop with timezone-aware date sorting"""
        
        # Optional: Ask user for timezone preference
        print("\n🔧 Timezone Configuration")
        use_interactive = input("Configure timezone interactively? (y/n, default=n): ").strip().lower()
        
        if use_interactive == 'y':
            self.user_timezone_offset = self.get_user_timezone_input()
            self.user_timezone = timezone(timedelta(hours=self.user_timezone_offset))
            print(f"✅ Timezone set to: GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset}")
        
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
        
        print(f"\n📡 Fetching data with timezone GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset}")
        print("=" * 60)
        
        for channel in channels:
            try:
                posts = await self.telegram_connector.fetch_posts(channel, self.limit)
                all_posts.extend(posts)
                print(f"✅ Fetched {len(posts)} posts from @{channel}")
            except Exception as e:
                print(f"❌ Error fetching from @{channel}: {e}")
        
        for feed in feeds:
            try:
                posts = await self.rss_connector.fetch_posts(feed, self.limit)
                all_posts.extend(posts)
                print(f"✅ Fetched {len(posts)} posts from {feed}")
            except Exception as e:
                print(f"❌ Error fetching from {feed}: {e}")

        print(f"\n📊 Total posts collected: {len(all_posts)}")

        # Sort by Day with timezone conversion
        posts_by_days = self.sort_posts_by_day(all_posts)

        # Show timezone conversion summary
        if all_posts:
            sample_post = all_posts[0]
            if 'timezone_info' in sample_post:
                print(f"\n🕐 Timezone Conversion Example:")
                print(f"   Original UTC: {sample_post['timezone_info']['original_utc']}")
                print(f"   Your Local:   {sample_post['timezone_info']['user_local']}")

        # You can modify target_days or remove the filter entirely
        target_days = ['2025-07-08']  # Remove this filter or modify as needed

        for day, day_posts in posts_by_days.items():
            # Only show posts for target days (optional filter)
            if target_days and day.strftime('%Y-%m-%d') not in target_days:
                continue
                
            print(f"\n📅 {day.strftime('%B %d, %Y')} - {len(day_posts)} posts (GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset})")
            title = f"Posts for {day.strftime('%B %d, %Y')} ({len(day_posts)} posts)"
            await self.display_posts(day_posts, title)
            
            # Generate daily briefing
            briefing = await self.gemini_processor.daily_briefing(day_posts)
            print(f"\n📋 Daily Briefing (GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset}):")
            print(briefing)
            print("-" * 60)

            # Generate HTML with timezone info
            html_title = f"Daily Briefing for {day.strftime('%B %d, %Y')} (GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset})"
            html_output = HTMLOutput(html_title)
            html_output.render_daily_briefing(day, briefing, day_posts)

            filename = f"daily_briefing_{day.strftime('%Y_%m_%d')}_GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset}.html"
            html_output.save_to_file(filename)
            print(f"💾 Generated HTML briefing: {filename}")
            print("-" * 60)

        await self.telegram_connector.disconnect()
        await self.gemini_processor.disconnect()
        
        print(f"\n✅ V12 Timezone-Aware Processing Complete!")
        print(f"🕐 All times displayed in GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset}")

if __name__ == "__main__":
    # Initialize with +4 GMT as requested (you can change this default)
    test_v12 = InsightV12TimezoneAware(user_timezone_offset=4)
    asyncio.run(test_v12.run())