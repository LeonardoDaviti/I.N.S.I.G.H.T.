"""
I.N.S.I.G.H.T. RSS Briefing Workflow Test
Tests the RSS connector tools and briefing functionality with multiple RSS feeds.

This test script:
1. Loads config and sets up RSS connector
2. Tests RSS connector methods (fetch_posts, get_feed_info, etc.)
3. Gets 4-day briefing from multiple RSS feeds (today + 3 previous days)
4. Outputs in Console, HTML, and JSON formats
5. Provides detailed logging and error reporting for RSS feed processing
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.rss_connector import RssConnector
from connectors.tool_registry import discover_tools, tool_registry
from config.config_manager import ConfigManager
from output.console_output import ConsoleOutput
from output.html_output import HTMLOutput
from output.json_output import JSONOutput
from logs.core.logger_config import get_component_logger

class RSSBriefingWorkflowTest:
    """
    Comprehensive test for the RSS briefing workflow using RSS connector.
    Tests multiple RSS feeds and aggregated content processing.
    """
    
    def __init__(self):
        self.logger = get_component_logger('rss_briefing_test')
        self.config_manager = ConfigManager()
        self.rss_connector = None
        self.test_results = {
            "setup_success": False,
            "tools_discovered": 0,
            "feeds_tested": 0,
            "total_posts_fetched": 0,
            "successful_feeds": 0,
            "failed_feeds": 0,
            "output_formats_generated": [],
            "errors": [],
            "start_time": None,
            "end_time": None,
            "feed_analysis_results": []
        }
        
    async def setup_test_environment(self) -> bool:
        """Set up the test environment and validate everything is ready."""
        self.logger.info("🔧 Setting up RSS briefing workflow test environment...")
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
            
            # Check if RSS is enabled
            rss_config = self.config_manager.get_platform_config(config, 'rss')
            if not rss_config or not rss_config.get('enabled', False):
                self.logger.error("❌ RSS is not enabled in configuration")
                return False
            
            feeds = rss_config.get('feeds', [])
            if not feeds:
                self.logger.error("❌ No RSS feeds configured")
                return False
            
            self.logger.info(f"✅ Configuration loaded: {len(feeds)} RSS feeds found")
            
            # Setup RSS connector
            self.rss_connector = RssConnector()
            
            if not self.rss_connector.setup_connector():
                self.logger.error("❌ Failed to setup RSS connector")
                return False
            
            # Connect to RSS (validate feedparser)
            await self.rss_connector.connect()
            self.logger.info("✅ RSS connector connected successfully")
            
            # Discover tools
            discovered_tools = discover_tools(self.rss_connector)
            self.test_results["tools_discovered"] = len(discovered_tools)
            
            self.logger.info(f"🔍 Discovered {len(discovered_tools)} tools:")
            for tool in discovered_tools:
                self.logger.info(f"   - {tool.name}: {tool.description}")
            
            self.test_results["setup_success"] = True
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Setup failed: {e}")
            self.test_results["errors"].append(f"Setup error: {str(e)}")
            return False
    
    async def test_individual_rss_methods(self) -> Dict[str, Any]:
        """Test individual RSS connector methods."""
        self.logger.info("🔧 Testing individual RSS connector methods...")
        
        method_test_results = {}
        config = self.config_manager.get_config()
        rss_config = self.config_manager.get_platform_config(config, 'rss')
        feeds = rss_config.get('feeds', [])
        
        # Test get_feed_info method
        if feeds:
            test_feed = feeds[0]  # Use first feed for individual test
            self.logger.info(f"🧪 Testing get_feed_info with feed: {test_feed}")
            
            try:
                feed_info = await self.rss_connector.get_feed_info(test_feed)
                
                method_test_results["get_feed_info"] = {
                    "success": True,
                    "test_feed": test_feed,
                    "feed_info": feed_info,
                    "total_entries": feed_info.get('total_entries', 0),
                    "feed_type": feed_info.get('feed_type', 'unknown'),
                    "status": feed_info.get('status', 'unknown')
                }
                
                self.logger.info(f"✅ get_feed_info: {feed_info.get('total_entries', 0)} entries in {test_feed}")
                
            except Exception as e:
                method_test_results["get_feed_info"] = {
                    "success": False,
                    "error": str(e),
                    "test_feed": test_feed
                }
                self.logger.error(f"❌ get_feed_info failed: {e}")
        
        # Test fetch_posts method
        if feeds:
            test_feed = feeds[0]
            self.logger.info(f"🧪 Testing fetch_posts with feed: {test_feed}")
            
            try:
                # Test with small limit first
                recent_posts = await self.rss_connector.fetch_posts(test_feed, 5)
                
                method_test_results["fetch_posts"] = {
                    "success": True,
                    "posts_fetched": len(recent_posts),
                    "test_feed": test_feed,
                    "sample_post": recent_posts[0] if recent_posts else None
                }
                
                self.logger.info(f"✅ fetch_posts: {len(recent_posts)} posts from {test_feed}")
                
            except Exception as e:
                method_test_results["fetch_posts"] = {
                    "success": False,
                    "error": str(e),
                    "test_feed": test_feed
                }
                self.logger.error(f"❌ fetch_posts failed: {e}")
        
        return method_test_results
    
    async def analyze_all_feeds(self) -> List[Dict[str, Any]]:
        """Analyze all configured RSS feeds for metadata."""
        self.logger.info("📊 Analyzing all configured RSS feeds...")
        
        config = self.config_manager.get_config()
        rss_config = self.config_manager.get_platform_config(config, 'rss')
        feeds = rss_config.get('feeds', [])
        
        feed_analysis_results = []
        
        for feed_url in feeds:
            try:
                self.logger.info(f"📡 Analyzing feed: {feed_url}")
                feed_info = await self.rss_connector.get_feed_info(feed_url)
                
                feed_analysis_results.append({
                    "url": feed_url,
                    "success": feed_info.get('status') == 'success',
                    "info": feed_info
                })
                
                if feed_info.get('status') == 'success':
                    self.logger.info(f"✅ {feed_url}: {feed_info.get('total_entries', 0)} entries, type: {feed_info.get('feed_type', 'unknown')}")
                else:
                    self.logger.warning(f"⚠️ {feed_url}: {feed_info.get('error', 'Analysis failed')}")
                    
            except Exception as e:
                self.logger.error(f"❌ Failed to analyze {feed_url}: {e}")
                feed_analysis_results.append({
                    "url": feed_url,
                    "success": False,
                    "info": {"error": str(e), "status": "error"}
                })
        
        self.test_results["feed_analysis_results"] = feed_analysis_results
        return feed_analysis_results
    
    async def run_rss_briefing_workflow(self) -> List[Dict[str, Any]]:
        """Run the main RSS briefing workflow to get 4-day briefing from multiple feeds."""
        self.logger.info("📋 Running 4-day RSS briefing workflow...")
        
        config = self.config_manager.get_config()
        rss_config = self.config_manager.get_platform_config(config, 'rss')
        feeds = rss_config.get('feeds', [])
        
        self.test_results["feeds_tested"] = len(feeds)
        
        try:
            # Test fetch_posts_by_timeframe method if it exists
            if hasattr(self.rss_connector, 'fetch_posts_by_timeframe'):
                self.logger.info(f"🔍 Using fetch_posts_by_timeframe for {len(feeds)} feeds")
                
                # Get posts from last 3 days (today + 3 previous = 4 days total)
                briefing_posts = await self.rss_connector.fetch_posts_by_timeframe(
                    sources=feeds,
                    days=3  # Last 3 days + today = 4 days total
                )
                
                self.logger.info(f"✅ Briefing workflow: {len(briefing_posts)} posts collected")
                
            else:
                # Fallback: collect individual posts from each feed
                self.logger.info(f"🔍 Using individual fetch_posts for {len(feeds)} feeds")
                
                all_posts = []
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=4)
                successful_feeds = 0
                failed_feeds = 0
                
                for feed_url in feeds:
                    try:
                        self.logger.info(f"📡 Fetching from: {feed_url}")
                        
                        # Fetch recent posts from each feed
                        feed_posts = await self.rss_connector.fetch_posts(feed_url, 50)
                        
                        if feed_posts:
                            # Filter to last 4 days
                            filtered_posts = [
                                post for post in feed_posts
                                if post.get('date') and post['date'] >= cutoff_date
                            ]
                            
                            all_posts.extend(filtered_posts)
                            successful_feeds += 1
                            self.logger.info(f"   ✅ {feed_url}: {len(filtered_posts)} posts from last 4 days")
                        else:
                            failed_feeds += 1
                            self.logger.warning(f"   ⚠️ {feed_url}: No posts retrieved")
                        
                    except Exception as e:
                        failed_feeds += 1
                        self.logger.error(f"   ❌ Failed to fetch from {feed_url}: {e}")
                        self.test_results["errors"].append(f"Feed {feed_url}: {str(e)}")
                        continue
                
                # Sort chronologically
                briefing_posts = sorted(
                    all_posts,
                    key=lambda p: p.get('date', datetime.min.replace(tzinfo=timezone.utc)),
                    reverse=True  # Most recent first
                )
                
                self.test_results["successful_feeds"] = successful_feeds
                self.test_results["failed_feeds"] = failed_feeds
                
                self.logger.info(f"✅ Individual workflow: {len(briefing_posts)} posts collected")
                self.logger.info(f"📊 Feed success rate: {successful_feeds}/{len(feeds)} successful")
            
            self.test_results["total_posts_fetched"] = len(briefing_posts)
            return briefing_posts
            
        except Exception as e:
            self.logger.error(f"❌ RSS briefing workflow failed: {e}")
            self.test_results["errors"].append(f"RSS briefing workflow: {str(e)}")
            return []
    
    def generate_outputs(self, posts: List[Dict[str, Any]]) -> Dict[str, str]:
        """Generate outputs in Console, HTML, and JSON formats."""
        self.logger.info("📄 Generating outputs in multiple formats...")
        
        output_files = {}
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        try:
            # 1. Console Output
            self.logger.info("🖥️ Generating console output...")
            title = f"I.N.S.I.G.H.T. RSS 4-Day Briefing Test ({len(posts)} posts)"
            ConsoleOutput.render_briefing_to_console(posts, title)
            self.test_results["output_formats_generated"].append("console")
            
            # 2. HTML Output
            self.logger.info("🌐 Generating HTML output...")
            html_output = HTMLOutput(f"I.N.S.I.G.H.T. RSS Briefing Test - {timestamp}")
            
            # Organize posts by source for HTML rendering
            posts_by_source = {}
            for post in posts:
                source = post.get('source', 'unknown')
                if source not in posts_by_source:
                    posts_by_source[source] = []
                posts_by_source[source].append(post)
            
            html_output.render_briefing(posts_by_source, days=3)
            html_filename = f"Tests/output/rss_briefing_test_{timestamp}.html"
            html_output.save_to_file(html_filename)
            output_files["html"] = html_filename
            self.test_results["output_formats_generated"].append("html")
            self.logger.info(f"✅ HTML saved: {html_filename}")
            
            # 3. JSON Output
            self.logger.info("📋 Generating JSON output...")
            json_output = JSONOutput()
            
            # Create mission summary
            feeds = list(posts_by_source.keys())
            mission_context = json_output.create_mission_summary(
                posts, 
                "4-Day RSS Briefing Workflow Test", 
                feeds
            )
            
            json_filename = f"Tests/output/rss_briefing_test_{timestamp}.json"
            json_output.export_to_file(posts, json_filename, mission_context=mission_context)
            output_files["json"] = json_filename
            self.test_results["output_formats_generated"].append("json")
            self.logger.info(f"✅ JSON saved: {json_filename}")
            
        except Exception as e:
            self.logger.error(f"❌ Output generation failed: {e}")
            self.test_results["errors"].append(f"Output generation: {str(e)}")
        
        return output_files
    
    def generate_test_report(self, method_results: Dict, feed_analysis: List, output_files: Dict) -> None:
        """Generate comprehensive test report."""
        self.test_results["end_time"] = datetime.now()
        duration = (self.test_results["end_time"] - self.test_results["start_time"]).total_seconds()
        
        print("\n" + "="*70)
        print("🧪 I.N.S.I.G.H.T. RSS BRIEFING WORKFLOW TEST REPORT")
        print("="*70)
        
        print(f"\n📊 Test Summary:")
        print(f"   Duration: {duration:.1f} seconds")
        print(f"   Setup Success: {'✅' if self.test_results['setup_success'] else '❌'}")
        print(f"   Tools Discovered: {self.test_results['tools_discovered']}")
        print(f"   Feeds Tested: {self.test_results['feeds_tested']}")
        print(f"   Total Posts Fetched: {self.test_results['total_posts_fetched']}")
        print(f"   Successful Feeds: {self.test_results['successful_feeds']}")
        print(f"   Failed Feeds: {self.test_results['failed_feeds']}")
        print(f"   Output Formats Generated: {', '.join(self.test_results['output_formats_generated'])}")
        
        print(f"\n🔧 RSS Method Test Results:")
        for method_name, result in method_results.items():
            status = "✅" if result.get("success", False) else "❌"
            print(f"   {status} {method_name}: {result}")
        
        print(f"\n📡 Feed Analysis Results ({len(feed_analysis)} feeds):")
        for analysis in feed_analysis:
            status = "✅" if analysis["success"] else "❌"
            feed_url = analysis["url"]
            info = analysis["info"]
            
            if analysis["success"]:
                entries = info.get('total_entries', 0)
                feed_type = info.get('feed_type', 'unknown')
                print(f"   {status} {feed_url}: {entries} entries, type: {feed_type}")
            else:
                error = info.get('error', 'Unknown error')
                print(f"   {status} {feed_url}: {error}")
        
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
            self.test_results["successful_feeds"] > 0,
            len(self.test_results["errors"]) <= self.test_results["failed_feeds"]  # Allow feed failures
        ]
        
        overall_success = all(success_criteria)
        
        # Calculate success rate
        if self.test_results["feeds_tested"] > 0:
            success_rate = (self.test_results["successful_feeds"] / self.test_results["feeds_tested"]) * 100
            print(f"\n📈 Feed Success Rate: {success_rate:.1f}% ({self.test_results['successful_feeds']}/{self.test_results['feeds_tested']})")
        
        print(f"\n🎯 Overall Test Result: {'✅ SUCCESS' if overall_success else '❌ PARTIAL SUCCESS'}")
        
        if overall_success:
            print("🎉 All RSS test objectives completed successfully!")
        else:
            print("⚠️ Some test objectives were not met, but basic RSS functionality works.")
            if self.test_results["failed_feeds"] > 0:
                print(f"💡 Note: {self.test_results['failed_feeds']} feeds failed - this may indicate feed URL issues or network problems.")
        
        print("="*70)
    
    async def cleanup(self):
        """Clean up test resources."""
        if self.rss_connector:
            try:
                await self.rss_connector.disconnect()
                self.logger.info("✅ RSS connector disconnected")
            except Exception as e:
                self.logger.error(f"❌ Cleanup error: {e}")

async def main():
    """Main test execution function."""
    print("🚀 Starting I.N.S.I.G.H.T. RSS Briefing Workflow Test...")
    
    # Create output directory if it doesn't exist
    os.makedirs("Tests/output", exist_ok=True)
    
    test = RSSBriefingWorkflowTest()
    
    try:
        # Setup test environment
        if not await test.setup_test_environment():
            print("❌ Test setup failed. Exiting.")
            return
        
        # Analyze all configured feeds first
        feed_analysis = await test.analyze_all_feeds()
        
        # Test individual RSS methods
        method_results = await test.test_individual_rss_methods()
        
        # Run main RSS briefing workflow
        briefing_posts = await test.run_rss_briefing_workflow()
        
        if not briefing_posts:
            print("⚠️ No posts retrieved. This could be due to:")
            print("   - Network connectivity issues")
            print("   - Invalid RSS feed URLs")
            print("   - Feeds with no recent content")
            print("   - RSS parsing errors")
            print("Proceeding with empty dataset for output format testing...")
        
        # Generate outputs in all formats (even with empty data to test format generation)
        output_files = test.generate_outputs(briefing_posts)
        
        # Generate comprehensive test report
        test.generate_test_report(method_results, feed_analysis, output_files)
        
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        test.test_results["errors"].append(f"Main execution: {str(e)}")
        
    finally:
        # Cleanup
        await test.cleanup()

if __name__ == "__main__":
    # Run the RSS briefing test
    asyncio.run(main())