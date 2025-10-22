"""
INSIGHT Express Test - Version 14: Enhanced Topics with Token Tracking
=====================================================================

Purpose: Enhanced version with topic-based daily briefings and fallback strategy
Scope: All configured channels and RSS feeds with timezone-aware date handling
Focus: Topic extraction, deep-dive analysis, and enhanced HTML output
New Features: 
- Enhanced daily briefing with topic extraction
- Table of Contents generation
- Topic-based deep-dive summaries
- Post references for each topic
- Enhanced HTML rendering with topic sections
- Fallback to standard briefing if enhanced processing fails
- Token usage tracking for cost monitoring
"""

import asyncio
import os
import sys
import json
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

class InsightV14EnhancedTopics:

    def __init__(self, user_timezone_offset: int = 4):
        """
        Initialize with user timezone configuration and enhanced topic processing
        
        Args:
            user_timezone_offset: User's timezone offset from UTC (e.g., +4 for GMT+4)
        """
        self.config_manager = ConfigManager()
        self.limit = 30
        # User timezone configuration - default +4 GMT as requested
        self.user_timezone_offset = user_timezone_offset
        self.user_timezone = timezone(timedelta(hours=user_timezone_offset))
        
        # Token tracking
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_api_calls = 0
        self.token_stats = []
        
        # Enhanced processing stats
        self.enhanced_success_count = 0
        self.fallback_count = 0
        
        # Gemini 2.0 Flash pricing (example rates - update with actual pricing)
        self.input_token_rate = 0.00015 / 1000  # $0.15 per 1M input tokens
        self.output_token_rate = 0.0006 / 1000  # $0.60 per 1M output tokens
        
        print(f"🕐 Configured user timezone: GMT{'+' if user_timezone_offset >= 0 else ''}{user_timezone_offset}")
        print(f"📊 Enhanced topic processing enabled with fallback strategy")
        print(f"🔢 Token tracking enabled with cost estimation")
    
    def track_token_usage(self, operation: str, token_info: Dict[str, Any]):
        """
        Track token usage for an operation
        
        Args:
            operation: Name of the operation (e.g., "enhanced_briefing", "standard_briefing")
            token_info: Token usage information from Gemini
        """
        try:
            prompt_tokens = token_info.get('prompt_tokens', 0) or 0
            response_tokens = token_info.get('response_tokens', 0) or 0
            total_tokens = token_info.get('total_tokens', 0) or 0
            
            # Update totals
            self.total_input_tokens += prompt_tokens
            self.total_output_tokens += response_tokens
            self.total_api_calls += 1
            
            # Calculate costs
            input_cost = prompt_tokens * self.input_token_rate
            output_cost = response_tokens * self.output_token_rate
            total_cost = input_cost + output_cost
            
            # Store stats
            stats = {
                'operation': operation,
                'prompt_tokens': prompt_tokens,
                'response_tokens': response_tokens,
                'total_tokens': total_tokens,
                'input_cost': input_cost,
                'output_cost': output_cost,
                'total_cost': total_cost,
                'timestamp': datetime.now(self.user_timezone)
            }
            
            self.token_stats.append(stats)
            
            print(f"🔢 {operation}: {prompt_tokens} in + {response_tokens} out = {total_tokens} tokens (${total_cost:.6f})")
            
        except Exception as e:
            print(f"Warning: Failed to track tokens for {operation}: {e}")
    
    def get_token_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive token usage summary with enhanced processing stats
        
        Returns:
            Dict with token usage statistics and processing information
        """
        total_cost = (self.total_input_tokens * self.input_token_rate) + (self.total_output_tokens * self.output_token_rate)
        
        return {
            'total_api_calls': self.total_api_calls,
            'total_input_tokens': self.total_input_tokens,
            'total_output_tokens': self.total_output_tokens,
            'total_tokens': self.total_input_tokens + self.total_output_tokens,
            'total_cost': total_cost,
            'average_tokens_per_call': (self.total_input_tokens + self.total_output_tokens) / max(self.total_api_calls, 1),
            'input_output_ratio': self.total_input_tokens / max(self.total_output_tokens, 1),
            'enhanced_success_count': self.enhanced_success_count,
            'fallback_count': self.fallback_count,
            'enhanced_success_rate': self.enhanced_success_count / max(self.enhanced_success_count + self.fallback_count, 1) * 100,
            'detailed_stats': self.token_stats
        }
    
    def display_token_summary(self):
        """Display comprehensive token usage summary with enhanced processing info"""
        summary = self.get_token_summary()
        
        print(f"\n📊 TOKEN USAGE & PROCESSING SUMMARY")
        print(f"=" * 60)
        print(f"🔄 Total API Calls: {summary['total_api_calls']}")
        print(f"📥 Total Input Tokens: {summary['total_input_tokens']:,}")
        print(f"📤 Total Output Tokens: {summary['total_output_tokens']:,}")
        print(f"🔢 Total Tokens: {summary['total_tokens']:,}")
        print(f"💰 Estimated Cost: ${summary['total_cost']:.6f}")
        print(f"📈 Avg Tokens/Call: {summary['average_tokens_per_call']:.1f}")
        print(f"📊 Input/Output Ratio: {summary['input_output_ratio']:.2f}:1")
        print(f"\n🎯 ENHANCED PROCESSING STATS:")
        print(f"✅ Enhanced Success: {summary['enhanced_success_count']} briefings")
        print(f"🔄 Fallback Used: {summary['fallback_count']} briefings")
        print(f"📈 Success Rate: {summary['enhanced_success_rate']:.1f}%")
        
        if summary['detailed_stats']:
            print(f"\n📋 DETAILED OPERATION BREAKDOWN:")
            operations = defaultdict(list)
            for stat in summary['detailed_stats']:
                operations[stat['operation']].append(stat)
            
            for operation, stats in operations.items():
                total_op_tokens = sum(s['total_tokens'] for s in stats)
                total_op_cost = sum(s['total_cost'] for s in stats)
                avg_tokens = total_op_tokens / len(stats)
                
                print(f"  {operation}: {len(stats)} calls, {total_op_tokens:,} tokens, ${total_op_cost:.6f} (avg: {avg_tokens:.1f} tokens/call)")

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
    
    async def process_enhanced_daily_briefing(self, day: datetime, day_posts: List[Dict[str, Any]]) -> tuple:
        """
        Process daily briefing with enhanced topic extraction and fallback strategy
        Includes both enhanced and traditional briefings in one file for comparison
        
        Returns:
            tuple: (html_output, enhanced_success: bool)
        """
        day_formatted = day.strftime('%B %d, %Y')
        
        # Try enhanced topic-based processing first
        try:
            print(f"🎯 Attempting enhanced topic-based briefing for {day_formatted}...")
            enhanced_result = await self.gemini_processor.enhanced_daily_briefing_with_topics(day_posts)
            
            if "error" not in enhanced_result and enhanced_result.get('daily_briefing'):
                print(f"✅ Enhanced processing successful for {day_formatted}")
                
                # Track token usage for enhanced
                enhanced_token_info = enhanced_result.get('token_usage', {})
                self.track_token_usage("enhanced_briefing", enhanced_token_info)
                
                # Generate traditional briefing for comparison
                print(f"📊 Generating traditional briefing for comparison...")
                standard_result = await self.gemini_processor.daily_briefing_with_tokens(day_posts)
                
                if "error" not in standard_result:
                    # Track token usage for traditional
                    standard_token_info = standard_result.get('token_usage', {})
                    self.track_token_usage("traditional_briefing", standard_token_info)
                    
                    # Create combined HTML output
                    html_title = f"Dual Briefing Comparison for {day_formatted} (GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset})"
                    html_output = HTMLOutput(html_title)
                    
                    # Render enhanced briefing first
                    html_output.render_topic_based_daily_briefing(day, enhanced_result, day_posts)
                    
                    # Add comparison section with traditional briefing
                    html_output.body_content += f'''
                    <!-- COMPARISON SECTION: Traditional vs Enhanced -->
                    <div class="comparison-section" style="margin-top: 50px; border-top: 3px solid #3498db; padding-top: 30px;">
                        <div class="comparison-header" style="text-align: center; margin-bottom: 30px;">
                            <h2 style="color: #2c3e50; font-size: 24px; margin: 0;">🔄 Traditional Briefing Comparison</h2>
                            <p style="color: #7f8c8d; margin: 10px 0 0 0;">Standard daily briefing format with all posts for debugging and analysis</p>
                            <div style="background: #ecf0f1; padding: 10px; margin: 15px 0; border-radius: 5px; font-size: 14px;">
                                <strong>Enhanced:</strong> {enhanced_token_info.get('total_tokens', 'N/A')} tokens | 
                                <strong>Traditional:</strong> {standard_token_info.get('total_tokens', 'N/A')} tokens | 
                                <strong>Efficiency:</strong> {len(enhanced_result.get('topics', []))} topics identified
                            </div>
                        </div>
                        
                        <!-- Traditional Daily Briefing -->
                        <div class="traditional-briefing-card" style="background: white; border: 1px solid #bdc3c7; border-radius: 8px; margin-bottom: 30px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                            <div class="traditional-briefing-header" style="background: #34495e; color: white; padding: 15px; border-radius: 8px 8px 0 0;">
                                <h3 style="margin: 0; font-size: 18px;">📋 Traditional Daily Briefing</h3>
                                <p style="margin: 5px 0 0 0; opacity: 0.8; font-size: 14px;">Generated using standard daily_briefing_with_tokens method</p>
                            </div>
                            <div class="traditional-briefing-content" style="padding: 20px;">
                                {html_output._format_briefing_content(standard_result['briefing'])}
                            </div>
                        </div>
                        
                        <!-- All Posts in Traditional Format -->
                        <div class="all-posts-section">
                            <div class="posts-header" style="background: #95a5a6; color: white; padding: 15px; border-radius: 8px 8px 0 0; margin-bottom: 0;">
                                <h3 style="margin: 0; font-size: 18px;">📑 All Posts ({len(day_posts)} items)</h3>
                                <p style="margin: 5px 0 0 0; opacity: 0.9; font-size: 14px;">Complete chronological listing for detailed analysis</p>
                            </div>
                            <div class="posts-container" style="border: 1px solid #95a5a6; border-top: none; border-radius: 0 0 8px 8px; background: white;">
                    '''
                    
                    # Add all posts using traditional format
                    for post in day_posts:
                        html_output.body_content += html_output._format_post(post)
                    
                    # Close the sections
                    html_output.body_content += '''
                            </div>
                        </div>
                    </div>
                    '''
                    
                    # Display enhanced briefing info
                    print(f"\n📊 Enhanced Daily Briefing (GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset}):")
                    print(f"📋 Topics identified: {len(enhanced_result.get('topics', []))}")
                    for topic in enhanced_result.get('topics', []):
                        print(f"  • {topic.get('title', 'Unknown Topic')} ({len(topic.get('post_references', []))} posts)")
                    
                    print(f"🔄 Traditional briefing also generated for comparison")
                    print(f"🔢 Enhanced: {enhanced_token_info.get('total_tokens', 'N/A')} tokens | Traditional: {standard_token_info.get('total_tokens', 'N/A')} tokens")
                    
                    return html_output, True
                else:
                    print(f"⚠️ Traditional briefing failed, using enhanced only")
                    # Fall back to enhanced only
                    html_title = f"Enhanced Daily Briefing for {day_formatted} (GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset})"
                    html_output = HTMLOutput(html_title)
                    html_output.render_topic_based_daily_briefing(day, enhanced_result, day_posts)
                    return html_output, True
                
        except Exception as e:
            print(f"⚠️ Enhanced processing failed for {day_formatted}: {e}")
        
        # Fallback to standard processing
        print(f"🔄 Falling back to standard briefing for {day_formatted}...")
        self.fallback_count += 1
        
        try:
            standard_result = await self.gemini_processor.daily_briefing_with_tokens(day_posts)
            
            if "error" not in standard_result:
                print(f"✅ Standard processing successful for {day_formatted}")
                
                # Track token usage
                token_info = standard_result.get('token_usage', {})
                self.track_token_usage("standard_briefing", token_info)
                
                # Create standard HTML output
                html_title = f"Daily Briefing for {day_formatted} (GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset})"
                html_output = HTMLOutput(html_title)
                html_output.render_daily_briefing(day, standard_result['briefing'], day_posts)
                
                # Add fallback indicator
                html_output.body_content += '''
                <div class="fallback-indicator" style="position: fixed; top: 10px; right: 10px; background: #e67e22; color: white; padding: 8px 12px; border-radius: 5px; font-size: 12px; z-index: 1000; box-shadow: 0 2px 4px rgba(0,0,0,0.2);">
                    ⚠️ FALLBACK: Enhanced processing failed
                </div>
                '''
                
                # Display standard briefing
                print(f"\n📋 Standard Daily Briefing (GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset}):")
                print(standard_result['briefing'])
                
                return html_output, False
                
        except Exception as e:
            print(f"❌ Standard processing also failed for {day_formatted}: {e}")
            
        # Both failed - create error output
        print(f"💥 All processing methods failed for {day_formatted}")
        html_title = f"Error - {day_formatted}"
        html_output = HTMLOutput(html_title)
        html_output.body_content = f"<div class='error'><h1>Error</h1><p>Failed to generate briefing for {day_formatted}</p></div>"
        
        return html_output, False
    
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
        """Main execution loop with enhanced topic processing and fallback strategy"""
        
        # Optional: Ask user for timezone preference
        print("\n🔧 Enhanced Topic Processing v14")
        print("=" * 60)
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
        target_days = ['2025-07-11', '2025-07-10', '2025-07-09']  # Update this to current date for testing

        for day, day_posts in posts_by_days.items():
            # Only show posts for target days (optional filter)
            if target_days and day.strftime('%Y-%m-%d') not in target_days:
                continue
                
            print(f"\n📅 {day.strftime('%B %d, %Y')} - {len(day_posts)} posts (GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset})")
            title = f"Posts for {day.strftime('%B %d, %Y')} ({len(day_posts)} posts)"
            await self.display_posts(day_posts, title)
            
            # Process with enhanced briefing and fallback
            html_output, enhanced_success = await self.process_enhanced_daily_briefing(day, day_posts)
            
            # Save HTML file with appropriate naming
            if enhanced_success:
                filename = f"daily_briefing_{day.strftime('%Y_%m_%d')}_GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset}_enhanced.html"
                html_content = html_output._get_enhanced_html_template()
            else:
                filename = f"daily_briefing_{day.strftime('%Y_%m_%d')}_GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset}_standard.html"
                html_content = html_output._get_html_template()
            
            # Save the HTML file
            try:
                with open(filename, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                print(f"💾 Generated HTML briefing: {filename}")
            except Exception as e:
                print(f"❌ Error saving HTML file: {e}")
            
            print("-" * 60)

        # Display final comprehensive summary
        self.display_token_summary()

        await self.telegram_connector.disconnect()
        await self.gemini_processor.disconnect()
        
        print(f"\n✅ V14 Enhanced Topic Processing Complete!")
        print(f"🕐 All times displayed in GMT{'+' if self.user_timezone_offset >= 0 else ''}{self.user_timezone_offset}")
        print(f"🔢 Total API cost: ${self.get_token_summary()['total_cost']:.6f}")
        print(f"🎯 Enhanced success rate: {self.get_token_summary()['enhanced_success_rate']:.1f}%")

if __name__ == "__main__":
    # Initialize with +4 GMT as requested (you can change this default)
    test_v14 = InsightV14EnhancedTopics(user_timezone_offset=4)
    asyncio.run(test_v14.run())