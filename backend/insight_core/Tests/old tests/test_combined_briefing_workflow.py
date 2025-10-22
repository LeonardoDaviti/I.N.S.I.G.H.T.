"""
I.N.S.I.G.H.T. Combined Briefing Workflow Test
Tests both Telegram and RSS connector tools together for unified briefing functionality.

This test script:
1. Loads config and sets up both Telegram and RSS connectors
2. Tests individual connector methods from both platforms
3. Gets 4-day briefing from both Telegram channels and RSS feeds
4. Combines and sorts posts by date in descending order (most recent first)
5. Outputs in Console, HTML, and JSON formats
6. Provides detailed logging and error reporting for unified workflow
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.telegram_connector import TelegramConnector
from connectors.rss_connector import RssConnector
from connectors.tool_registry import discover_tools, tool_registry
from config.config_manager import ConfigManager
from output.console_output import ConsoleOutput
from output.html_output import HTMLOutput
from output.json_output import JSONOutput
from logs.core.logger_config import get_component_logger

class CombinedBriefingWorkflowTest:
    """
    Comprehensive test for the unified briefing workflow using both Telegram and RSS connectors.
    Tests integration of multiple data sources and unified content processing.
    """
    
    def __init__(self):
        self.logger = get_component_logger('combined_briefing_test')
        self.config_manager = ConfigManager()
        self.telegram_connector = None
        self.rss_connector = None
        self.test_results = {
            "setup_success": False,
            "telegram_setup_success": False,
            "rss_setup_success": False,
            "telegram_tools_discovered": 0,
            "rss_tools_discovered": 0,
            "telegram_channels_tested": 0,
            "rss_feeds_tested": 0,
            "telegram_posts_fetched": 0,
            "rss_posts_fetched": 0,
            "total_posts_fetched": 0,
            "successful_telegram_channels": 0,
            "failed_telegram_channels": 0,
            "successful_rss_feeds": 0,
            "failed_rss_feeds": 0,
            "output_formats_generated": [],
            "errors": [],
            "start_time": None,
            "end_time": None
        }
        
    async def setup_test_environment(self) -> bool:
        """Set up the test environment for both connectors and validate everything is ready."""
        self.logger.info("🔧 Setting up combined briefing workflow test environment...")
        self.test_results["start_time"] = datetime.now()
        
        try:
            # Load and validate config
            config = self.config_manager.load_config()
            if not config:
                self.logger.error("❌ Failed to load configuration")
                return False
            
            is_valid, validation_errors = self.config_manager.validate_config(config)
            if not is_valid:
                self.logger.error(f"❌ Configuration validation failed: {validation_errors}")
                return False
            
            # Setup Telegram connector
            telegram_success = await self.setup_telegram_connector()
            self.test_results["telegram_setup_success"] = telegram_success
            
            # Setup RSS connector
            rss_success = await self.setup_rss_connector()
            self.test_results["rss_setup_success"] = rss_success
            
            # Overall setup success if at least one connector works
            overall_success = telegram_success or rss_success
            self.test_results["setup_success"] = overall_success
            
            if not overall_success:
                self.logger.error("❌ Both connectors failed to setup")
                return False
            
            if telegram_success and rss_success:
                self.logger.info("✅ Both Telegram and RSS connectors setup successfully")
            elif telegram_success:
                self.logger.info("✅ Telegram connector setup successfully (RSS failed)")
            else:
                self.logger.info("✅ RSS connector setup successfully (Telegram failed)")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Setup failed: {e}")
            self.test_results["errors"].append(f"Setup error: {str(e)}")
            return False
    
    async def setup_telegram_connector(self) -> bool:
        """Setup Telegram connector specifically."""
        try:
            self.logger.info("🔧 Setting up Telegram connector...")
            
            config = self.config_manager.get_config()
            telegram_config = self.config_manager.get_platform_config(config, 'telegram')
            
            if not telegram_config or not telegram_config.get('enabled', False):
                self.logger.warning("⚠️ Telegram is not enabled in configuration")
                return False
            
            channels = telegram_config.get('channels', [])
            if not channels:
                self.logger.warning("⚠️ No telegram channels configured")
                return False
            
            self.logger.info(f"📡 Found {len(channels)} telegram channels in config")
            
            # Setup telegram connector
            self.telegram_connector = TelegramConnector()
            
            if not self.telegram_connector.setup_connector():
                self.logger.warning("⚠️ Failed to setup telegram connector")
                return False
            
            # Connect to telegram
            await self.telegram_connector.connect()
            
            # Discover telegram tools
            telegram_tools = discover_tools(self.telegram_connector)
            self.test_results["telegram_tools_discovered"] = len(telegram_tools)
            
            self.logger.info(f"✅ Telegram connector ready: {len(telegram_tools)} tools discovered")
            for tool in telegram_tools:
                self.logger.info(f"   - {tool.name}: {tool.description}")
            
            return True
            
        except Exception as e:
            self.logger.warning(f"⚠️ Telegram setup failed: {e}")
            self.test_results["errors"].append(f"Telegram setup: {str(e)}")
            return False
    
    async def setup_rss_connector(self) -> bool:
        """Setup RSS connector specifically."""
        try:
            self.logger.info("🔧 Setting up RSS connector...")
            
            config = self.config_manager.get_config()
            rss_config = self.config_manager.get_platform_config(config, 'rss')
            
            if not rss_config or not rss_config.get('enabled', False):
                self.logger.warning("⚠️ RSS is not enabled in configuration")
                return False
            
            feeds = rss_config.get('feeds', [])
            if not feeds:
                self.logger.warning("⚠️ No RSS feeds configured")
                return False
            
            self.logger.info(f"📡 Found {len(feeds)} RSS feeds in config")
            
            # Setup RSS connector
            self.rss_connector = RssConnector()
            
            if not self.rss_connector.setup_connector():
                self.logger.warning("⚠️ Failed to setup RSS connector")
                return False
            
            # Connect to RSS
            await self.rss_connector.connect()
            
            # Discover RSS tools
            rss_tools = discover_tools(self.rss_connector)
            self.test_results["rss_tools_discovered"] = len(rss_tools)
            
            self.logger.info(f"✅ RSS connector ready: {len(rss_tools)} tools discovered")
            for tool in rss_tools:
                self.logger.info(f"   - {tool.name}: {tool.description}")
            
            return True
            
        except Exception as e:
            self.logger.warning(f"⚠️ RSS setup failed: {e}")
            self.test_results["errors"].append(f"RSS setup: {str(e)}")
            return False
    
    async def test_individual_connectors(self) -> Dict[str, Any]:
        """Test individual methods from both connectors."""
        self.logger.info("🔧 Testing individual connector methods...")
        
        connector_test_results = {
            "telegram": {},
            "rss": {}
        }
        
        # Test Telegram connector
        if self.telegram_connector:
            connector_test_results["telegram"] = await self.test_telegram_methods()
        else:
            self.logger.info("⚠️ Skipping Telegram tests (connector not available)")
        
        # Test RSS connector
        if self.rss_connector:
            connector_test_results["rss"] = await self.test_rss_methods()
        else:
            self.logger.info("⚠️ Skipping RSS tests (connector not available)")
        
        return connector_test_results
    
    async def test_telegram_methods(self) -> Dict[str, Any]:
        """Test Telegram connector methods."""
        self.logger.info("🧪 Testing Telegram connector methods...")
        
        telegram_results = {}
        config = self.config_manager.get_config()
        telegram_config = self.config_manager.get_platform_config(config, 'telegram')
        channels = telegram_config.get('channels', [])
        
        if channels:
            test_channel = channels[0]
            self.logger.info(f"🧪 Testing fetch_posts with channel: {test_channel}")
            
            try:
                recent_posts = await self.telegram_connector.fetch_posts(test_channel, 3)
                
                telegram_results["fetch_posts"] = {
                    "success": True,
                    "posts_fetched": len(recent_posts),
                    "test_channel": test_channel,
                    "sample_post": recent_posts[0] if recent_posts else None
                }
                
                self.logger.info(f"✅ Telegram fetch_posts: {len(recent_posts)} posts from {test_channel}")
                
            except Exception as e:
                telegram_results["fetch_posts"] = {
                    "success": False,
                    "error": str(e),
                    "test_channel": test_channel
                }
                self.logger.error(f"❌ Telegram fetch_posts failed: {e}")
        
        return telegram_results
    
    async def test_rss_methods(self) -> Dict[str, Any]:
        """Test RSS connector methods."""
        self.logger.info("🧪 Testing RSS connector methods...")
        
        rss_results = {}
        config = self.config_manager.get_config()
        rss_config = self.config_manager.get_platform_config(config, 'rss')
        feeds = rss_config.get('feeds', [])
        
        if feeds:
            test_feed = feeds[0]
            self.logger.info(f"🧪 Testing get_feed_info with feed: {test_feed}")
            
            try:
                feed_info = await self.rss_connector.get_feed_info(test_feed)
                
                rss_results["get_feed_info"] = {
                    "success": True,
                    "test_feed": test_feed,
                    "feed_info": feed_info,
                    "total_entries": feed_info.get('total_entries', 0)
                }
                
                self.logger.info(f"✅ RSS get_feed_info: {feed_info.get('total_entries', 0)} entries in {test_feed}")
                
            except Exception as e:
                rss_results["get_feed_info"] = {
                    "success": False,
                    "error": str(e),
                    "test_feed": test_feed
                }
                self.logger.error(f"❌ RSS get_feed_info failed: {e}")
            
            # Test fetch_posts
            self.logger.info(f"🧪 Testing RSS fetch_posts with feed: {test_feed}")
            
            try:
                recent_posts = await self.rss_connector.fetch_posts(test_feed, 3)
                
                rss_results["fetch_posts"] = {
                    "success": True,
                    "posts_fetched": len(recent_posts),
                    "test_feed": test_feed,
                    "sample_post": recent_posts[0] if recent_posts else None
                }
                
                self.logger.info(f"✅ RSS fetch_posts: {len(recent_posts)} posts from {test_feed}")
                
            except Exception as e:
                rss_results["fetch_posts"] = {
                    "success": False,
                    "error": str(e),
                    "test_feed": test_feed
                }
                self.logger.error(f"❌ RSS fetch_posts failed: {e}")
        
        return rss_results
    
    async def run_combined_briefing_workflow(self) -> List[Dict[str, Any]]:
        """Run the main combined briefing workflow to get 4-day briefing from both sources."""
        self.logger.info("📋 Running 4-day combined briefing workflow...")
        
        all_posts = []
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=4)
        
        # Collect posts from Telegram
        if self.telegram_connector:
            telegram_posts = await self.collect_telegram_posts(cutoff_date)
            all_posts.extend(telegram_posts)
            self.test_results["telegram_posts_fetched"] = len(telegram_posts)
            self.logger.info(f"📡 Telegram: {len(telegram_posts)} posts collected")
        else:
            self.logger.info("⚠️ Skipping Telegram collection (connector not available)")
        
        # Collect posts from RSS
        if self.rss_connector:
            rss_posts = await self.collect_rss_posts(cutoff_date)
            all_posts.extend(rss_posts)
            self.test_results["rss_posts_fetched"] = len(rss_posts)
            self.logger.info(f"📡 RSS: {len(rss_posts)} posts collected")
        else:
            self.logger.info("⚠️ Skipping RSS collection (connector not available)")
        
        # Sort all posts by date in descending order (most recent first)
        combined_posts = sorted(
            all_posts,
            key=lambda p: p.get('date', datetime.min.replace(tzinfo=timezone.utc)),
            reverse=True  # Descending order - most recent first
        )
        
        self.test_results["total_posts_fetched"] = len(combined_posts)
        
        self.logger.info(f"✅ Combined workflow: {len(combined_posts)} total posts collected and sorted by date (descending)")
        
        return combined_posts
    
    async def collect_telegram_posts(self, cutoff_date: datetime) -> List[Dict[str, Any]]:
        """Collect posts from all Telegram channels."""
        telegram_posts = []
        
        config = self.config_manager.get_config()
        telegram_config = self.config_manager.get_platform_config(config, 'telegram')
        channels = telegram_config.get('channels', [])
        
        self.test_results["telegram_channels_tested"] = len(channels)
        
        for channel in channels:
            try:
                self.logger.info(f"📡 Fetching from Telegram channel: {channel}")
                
                # Fetch recent posts from each channel
                channel_posts = await self.telegram_connector.fetch_posts(channel, 50)
                
                if channel_posts:
                    # Filter to last 4 days and add source info
                    filtered_posts = []
                    for post in channel_posts:
                        if post.get('date') and post['date'] >= cutoff_date:
                            post['connector_type'] = 'telegram'
                            post['source_type'] = 'telegram_channel'
                            filtered_posts.append(post)
                    
                    telegram_posts.extend(filtered_posts)
                    self.test_results["successful_telegram_channels"] += 1
                    self.logger.info(f"   ✅ {channel}: {len(filtered_posts)} posts from last 4 days")
                else:
                    self.test_results["failed_telegram_channels"] += 1
                    self.logger.warning(f"   ⚠️ {channel}: No posts retrieved")
                    
            except Exception as e:
                self.test_results["failed_telegram_channels"] += 1
                self.logger.error(f"   ❌ Failed to fetch from {channel}: {e}")
                self.test_results["errors"].append(f"Telegram channel {channel}: {str(e)}")
                continue
        
        return telegram_posts
    
    async def collect_rss_posts(self, cutoff_date: datetime) -> List[Dict[str, Any]]:
        """Collect posts from all RSS feeds."""
        rss_posts = []
        
        config = self.config_manager.get_config()
        rss_config = self.config_manager.get_platform_config(config, 'rss')
        feeds = rss_config.get('feeds', [])
        
        self.test_results["rss_feeds_tested"] = len(feeds)
        
        for feed_url in feeds:
            try:
                self.logger.info(f"📡 Fetching from RSS feed: {feed_url}")
                
                # Fetch recent posts from each feed
                feed_posts = await self.rss_connector.fetch_posts(feed_url, 50)
                
                if feed_posts:
                    # Filter to last 4 days and add source info
                    filtered_posts = []
                    for post in feed_posts:
                        if post.get('date') and post['date'] >= cutoff_date:
                            post['connector_type'] = 'rss'
                            post['source_type'] = 'rss_feed'
                            filtered_posts.append(post)
                    
                    rss_posts.extend(filtered_posts)
                    self.test_results["successful_rss_feeds"] += 1
                    self.logger.info(f"   ✅ {feed_url}: {len(filtered_posts)} posts from last 4 days")
                else:
                    self.test_results["failed_rss_feeds"] += 1
                    self.logger.warning(f"   ⚠️ {feed_url}: No posts retrieved")
                    
            except Exception as e:
                self.test_results["failed_rss_feeds"] += 1
                self.logger.error(f"   ❌ Failed to fetch from {feed_url}: {e}")
                self.test_results["errors"].append(f"RSS feed {feed_url}: {str(e)}")
                continue
        
        return rss_posts
    
    def generate_outputs(self, posts: List[Dict[str, Any]]) -> Dict[str, str]:
        """Generate outputs in Console, HTML, and JSON formats."""
        self.logger.info("📄 Generating outputs in multiple formats...")
        
        output_files = {}
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        try:
            # 1. Console Output
            self.logger.info("🖥️ Generating console output...")
            title = f"I.N.S.I.G.H.T. Combined 4-Day Briefing Test ({len(posts)} posts)"
            ConsoleOutput.render_briefing_to_console(posts, title)
            self.test_results["output_formats_generated"].append("console")
            
            # 2. HTML Output
            self.logger.info("🌐 Generating HTML output...")
            html_output = HTMLOutput(f"I.N.S.I.G.H.T. Combined Briefing Test - {timestamp}")
            
            # Organize posts by source for HTML rendering
            posts_by_source = {}
            for post in posts:
                source = post.get('source', 'unknown')
                if source not in posts_by_source:
                    posts_by_source[source] = []
                posts_by_source[source].append(post)
            
            html_output.render_briefing(posts_by_source, days=3)
            html_filename = f"Tests/output/combined_briefing_test_{timestamp}.html"
            html_output.save_to_file(html_filename)
            output_files["html"] = html_filename
            self.test_results["output_formats_generated"].append("html")
            self.logger.info(f"✅ HTML saved: {html_filename}")
            
            # 3. JSON Output
            self.logger.info("📋 Generating JSON output...")
            json_output = JSONOutput()
            
            # Create mission summary with combined sources
            all_sources = list(posts_by_source.keys())
            mission_context = json_output.create_mission_summary(
                posts, 
                "4-Day Combined Briefing Workflow Test", 
                all_sources
            )
            
            json_filename = f"Tests/output/combined_briefing_test_{timestamp}.json"
            json_output.export_to_file(posts, json_filename, mission_context=mission_context)
            output_files["json"] = json_filename
            self.test_results["output_formats_generated"].append("json")
            self.logger.info(f"✅ JSON saved: {json_filename}")
            
        except Exception as e:
            self.logger.error(f"❌ Output generation failed: {e}")
            self.test_results["errors"].append(f"Output generation: {str(e)}")
        
        return output_files
    
    def generate_test_report(self, connector_results: Dict, output_files: Dict) -> None:
        """Generate comprehensive test report."""
        self.test_results["end_time"] = datetime.now()
        duration = (self.test_results["end_time"] - self.test_results["start_time"]).total_seconds()
        
        print("\n" + "="*80)
        print("🧪 I.N.S.I.G.H.T. COMBINED BRIEFING WORKFLOW TEST REPORT")
        print("="*80)
        
        print(f"\n📊 Test Summary:")
        print(f"   Duration: {duration:.1f} seconds")
        print(f"   Overall Setup Success: {'✅' if self.test_results['setup_success'] else '❌'}")
        print(f"   Telegram Setup: {'✅' if self.test_results['telegram_setup_success'] else '❌'}")
        print(f"   RSS Setup: {'✅' if self.test_results['rss_setup_success'] else '❌'}")
        print(f"   Telegram Tools Discovered: {self.test_results['telegram_tools_discovered']}")
        print(f"   RSS Tools Discovered: {self.test_results['rss_tools_discovered']}")
        print(f"   Total Posts Fetched: {self.test_results['total_posts_fetched']}")
        print(f"   Output Formats Generated: {', '.join(self.test_results['output_formats_generated'])}")
        
        print(f"\n📡 Telegram Results:")
        print(f"   Channels Tested: {self.test_results['telegram_channels_tested']}")
        print(f"   Posts Fetched: {self.test_results['telegram_posts_fetched']}")
        print(f"   Successful Channels: {self.test_results['successful_telegram_channels']}")
        print(f"   Failed Channels: {self.test_results['failed_telegram_channels']}")
        
        print(f"\n📡 RSS Results:")
        print(f"   Feeds Tested: {self.test_results['rss_feeds_tested']}")
        print(f"   Posts Fetched: {self.test_results['rss_posts_fetched']}")
        print(f"   Successful Feeds: {self.test_results['successful_rss_feeds']}")
        print(f"   Failed Feeds: {self.test_results['failed_rss_feeds']}")
        
        print(f"\n🔧 Connector Test Results:")
        for connector_type, results in connector_results.items():
            print(f"   {connector_type.upper()}:")
            for method_name, result in results.items():
                status = "✅" if result.get("success", False) else "❌"
                print(f"     {status} {method_name}: {result}")
        
        print(f"\n📄 Generated Files:")
        for format_type, filename in output_files.items():
            print(f"   📁 {format_type.upper()}: {filename}")
        
        if self.test_results["errors"]:
            print(f"\n❌ Errors Encountered ({len(self.test_results['errors'])}):")
            for error in self.test_results["errors"]:
                print(f"   - {error}")
        else:
            print(f"\n✅ No errors encountered!")
        
        # Success criteria
        success_criteria = [
            self.test_results["setup_success"],
            self.test_results["total_posts_fetched"] > 0,
            len(self.test_results["output_formats_generated"]) >= 2,
            (self.test_results["successful_telegram_channels"] + self.test_results["successful_rss_feeds"]) > 0
        ]
        
        overall_success = all(success_criteria)
        
        # Calculate success rates
        if self.test_results["telegram_channels_tested"] > 0:
            telegram_success_rate = (self.test_results["successful_telegram_channels"] / self.test_results["telegram_channels_tested"]) * 100
            print(f"\n📈 Telegram Success Rate: {telegram_success_rate:.1f}% ({self.test_results['successful_telegram_channels']}/{self.test_results['telegram_channels_tested']})")
        
        if self.test_results["rss_feeds_tested"] > 0:
            rss_success_rate = (self.test_results["successful_rss_feeds"] / self.test_results["rss_feeds_tested"]) * 100
            print(f"📈 RSS Success Rate: {rss_success_rate:.1f}% ({self.test_results['successful_rss_feeds']}/{self.test_results['rss_feeds_tested']})")
        
        print(f"\n🎯 Overall Test Result: {'✅ SUCCESS' if overall_success else '❌ PARTIAL SUCCESS'}")
        
        if overall_success:
            print("🎉 All combined briefing test objectives completed successfully!")
            print("📋 Posts have been sorted by date in descending order (most recent first)")
        else:
            print("⚠️ Some test objectives were not met, but basic functionality works.")
            if self.test_results["failed_telegram_channels"] > 0 or self.test_results["failed_rss_feeds"] > 0:
                print("💡 Note: Some sources failed - this may indicate connectivity or configuration issues.")
        
        print("="*80)
    
    async def cleanup(self):
        """Clean up test resources."""
        if self.telegram_connector:
            try:
                await self.telegram_connector.disconnect()
                self.logger.info("✅ Telegram connector disconnected")
            except Exception as e:
                self.logger.error(f"❌ Telegram cleanup error: {e}")
        
        if self.rss_connector:
            try:
                await self.rss_connector.disconnect()
                self.logger.info("✅ RSS connector disconnected")
            except Exception as e:
                self.logger.error(f"❌ RSS cleanup error: {e}")

async def main():
    """Main test execution function."""
    print("🚀 Starting I.N.S.I.G.H.T. Combined Briefing Workflow Test...")
    print("🔗 Testing both Telegram and RSS connectors together")
    
    # Create output directory if it doesn't exist
    os.makedirs("Tests/output", exist_ok=True)
    
    test = CombinedBriefingWorkflowTest()
    
    try:
        # Setup test environment for both connectors
        if not await test.setup_test_environment():
            print("❌ Test setup failed. Exiting.")
            return
        
        # Test individual connector methods
        connector_results = await test.test_individual_connectors()
        
        # Run main combined briefing workflow
        briefing_posts = await test.run_combined_briefing_workflow()
        
        if not briefing_posts:
            print("⚠️ No posts retrieved from either source. This could be due to:")
            print("   - Network connectivity issues")
            print("   - Invalid channel/feed URLs")
            print("   - Sources with no recent content")
            print("   - Authentication or parsing errors")
            print("Proceeding with empty dataset for output format testing...")
        
        # Generate outputs in all formats (even with empty data to test format generation)
        output_files = test.generate_outputs(briefing_posts)
        
        # Generate comprehensive test report
        test.generate_test_report(connector_results, output_files)
        
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        test.test_results["errors"].append(f"Main execution: {str(e)}")
        
    finally:
        # Cleanup
        await test.cleanup()

if __name__ == "__main__":
    # Run the combined briefing test
    asyncio.run(main())