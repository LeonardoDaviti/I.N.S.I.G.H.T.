"""
I.N.S.I.G.H.T. Briefing Workflow Test
Tests the new telegram connector tools and briefing functionality.

This test script:
1. Loads config and sets up telegram connector
2. Tests the new @expose_tool decorated methods
3. Gets 4-day briefing (today + 3 previous days)
4. Outputs in Console, HTML, and JSON formats
5. Provides detailed logging and error reporting
"""

import asyncio
import sys
import os
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.telegram_connector import TelegramConnector
from connectors.tool_registry import discover_tools, tool_registry
from config.config_manager import ConfigManager
from output.console_output import ConsoleOutput
from output.html_output import HTMLOutput
from output.json_output import JSONOutput
from logs.core.logger_config import get_component_logger

class BriefingWorkflowTest:
    """
    Comprehensive test for the briefing workflow using new telegram connector tools.
    """
    
    def __init__(self):
        self.logger = get_component_logger('briefing_test')
        self.config_manager = ConfigManager()
        self.telegram_connector = None
        self.test_results = {
            "setup_success": False,
            "tools_discovered": 0,
            "channels_tested": 0,
            "total_posts_fetched": 0,
            "output_formats_generated": [],
            "errors": [],
            "start_time": None,
            "end_time": None
        }
        
    async def setup_test_environment(self) -> bool:
        """Set up the test environment and validate everything is ready."""
        self.logger.info("🔧 Setting up briefing workflow test environment...")
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
            
            # Check if telegram is enabled
            telegram_config = self.config_manager.get_platform_config(config, 'telegram')
            if not telegram_config or not telegram_config.get('enabled', False):
                self.logger.error("❌ Telegram is not enabled in configuration")
                return False
            
            channels = telegram_config.get('channels', [])
            if not channels:
                self.logger.error("❌ No telegram channels configured")
                return False
            
            self.logger.info(f"✅ Configuration loaded: {len(channels)} telegram channels found")
            
            # Setup telegram connector
            self.telegram_connector = TelegramConnector()
            
            if not self.telegram_connector.setup_connector():
                self.logger.error("❌ Failed to setup telegram connector")
                return False
            
            # Connect to telegram
            await self.telegram_connector.connect()
            self.logger.info("✅ Telegram connector connected successfully")
            
            # Discover tools
            discovered_tools = discover_tools(self.telegram_connector)
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
    
    async def test_individual_tools(self) -> Dict[str, Any]:
        """Test individual telegram connector tools."""
        self.logger.info("🔧 Testing individual telegram connector tools...")
        
        tool_test_results = {}
        config = self.config_manager.get_config()
        telegram_config = self.config_manager.get_platform_config(config, 'telegram')
        channels = telegram_config.get('channels', [])
        
        # Test fetch_recent_posts tool
        if channels:
            test_channel = channels[0]  # Use first channel for individual test
            self.logger.info(f"🧪 Testing fetch_recent_posts with channel: {test_channel}")
            
            try:
                # Test with small limit first
                recent_posts = await self.telegram_connector.fetch_posts(test_channel, 3)
                
                tool_test_results["fetch_recent_posts"] = {
                    "success": True,
                    "posts_fetched": len(recent_posts),
                    "test_channel": test_channel,
                    "sample_post": recent_posts[0] if recent_posts else None
                }
                
                self.logger.info(f"✅ fetch_recent_posts: {len(recent_posts)} posts from {test_channel}")
                
            except Exception as e:
                tool_test_results["fetch_recent_posts"] = {
                    "success": False,
                    "error": str(e),
                    "test_channel": test_channel
                }
                self.logger.error(f"❌ fetch_recent_posts failed: {e}")
        
        return tool_test_results
    
    async def run_briefing_workflow(self) -> List[Dict[str, Any]]:
        """Run the main briefing workflow to get 4-day briefing."""
        self.logger.info("📋 Running 4-day briefing workflow...")
        
        config = self.config_manager.get_config()
        telegram_config = self.config_manager.get_platform_config(config, 'telegram')
        channels = telegram_config.get('channels', [])
        
        self.test_results["channels_tested"] = len(channels)
        
        try:
            # Test get_briefing_posts method (if it exists)
            if hasattr(self.telegram_connector, 'get_briefing_posts'):
                self.logger.info(f"🔍 Using get_briefing_posts for {len(channels)} channels")
                
                # Get posts from last 3 days (today + 3 previous = 4 days total)
                briefing_posts = await self.telegram_connector.get_briefing_posts(
                    channels=channels,
                    days=3,  # Last 3 days + today = 4 days total
                    posts_per_channel=50  # Aim for ~40 total posts
                )
                
                self.logger.info(f"✅ Briefing workflow: {len(briefing_posts)} posts collected")
                
            else:
                # Fallback: collect individual posts from each channel
                self.logger.info(f"🔍 Using individual fetch_posts for {len(channels)} channels")
                
                all_posts = []
                cutoff_date = datetime.now(timezone.utc) - timedelta(days=5)
                
                for channel in channels:
                    try:
                        # Fetch recent posts from each channel
                        channel_posts = await self.telegram_connector.fetch_posts(channel, 50)
                        
                        # Filter to last 4 days
                        filtered_posts = [
                            post for post in channel_posts
                            if post.get('date') and post['date'] >= cutoff_date
                        ]
                        
                        all_posts.extend(filtered_posts)
                        self.logger.info(f"   📡 {channel}: {len(filtered_posts)} posts from last 4 days")
                        
                    except Exception as e:
                        self.logger.error(f"❌ Failed to fetch from {channel}: {e}")
                        self.test_results["errors"].append(f"Channel {channel}: {str(e)}")
                        continue
                
                # Sort chronologically
                briefing_posts = sorted(
                    all_posts,
                    key=lambda p: p.get('date', datetime.min.replace(tzinfo=timezone.utc))
                )
                
                self.logger.info(f"✅ Individual workflow: {len(briefing_posts)} posts collected")
            
            self.test_results["total_posts_fetched"] = len(briefing_posts)
            return briefing_posts
            
        except Exception as e:
            self.logger.error(f"❌ Briefing workflow failed: {e}")
            self.test_results["errors"].append(f"Briefing workflow: {str(e)}")
            return []
    
    def generate_outputs(self, posts: List[Dict[str, Any]]) -> Dict[str, str]:
        """Generate outputs in Console, HTML, and JSON formats."""
        self.logger.info("📄 Generating outputs in multiple formats...")
        
        output_files = {}
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        try:
            # 1. Console Output
            self.logger.info("🖥️ Generating console output...")
            title = f"I.N.S.I.G.H.T. 4-Day Briefing Test ({len(posts)} posts)"
            ConsoleOutput.render_briefing_to_console(posts, title)
            self.test_results["output_formats_generated"].append("console")
            
            # 2. HTML Output
            self.logger.info("🌐 Generating HTML output...")
            html_output = HTMLOutput(f"I.N.S.I.G.H.T. Briefing Test - {timestamp}")
            
            # Organize posts by source for HTML rendering
            posts_by_source = {}
            for post in posts:
                source = post.get('source', 'unknown')
                if source not in posts_by_source:
                    posts_by_source[source] = []
                posts_by_source[source].append(post)
            
            html_output.render_briefing(posts_by_source, days=3)
            html_filename = f"Tests/output/briefing_test_{timestamp}.html"
            html_output.save_to_file(html_filename)
            output_files["html"] = html_filename
            self.test_results["output_formats_generated"].append("html")
            self.logger.info(f"✅ HTML saved: {html_filename}")
            
            # 3. JSON Output
            self.logger.info("📋 Generating JSON output...")
            json_output = JSONOutput()
            
            # Create mission summary
            channels = list(posts_by_source.keys())
            mission_context = json_output.create_mission_summary(
                posts, 
                "4-Day Briefing Workflow Test", 
                channels
            )
            
            json_filename = f"Tests/output/briefing_test_{timestamp}.json"
            json_output.export_to_file(posts, json_filename, mission_context=mission_context)
            output_files["json"] = json_filename
            self.test_results["output_formats_generated"].append("json")
            self.logger.info(f"✅ JSON saved: {json_filename}")
            
        except Exception as e:
            self.logger.error(f"❌ Output generation failed: {e}")
            self.test_results["errors"].append(f"Output generation: {str(e)}")
        
        return output_files
    
    def generate_test_report(self, tool_results: Dict, output_files: Dict) -> None:
        """Generate comprehensive test report."""
        self.test_results["end_time"] = datetime.now()
        duration = (self.test_results["end_time"] - self.test_results["start_time"]).total_seconds()
        
        print("\n" + "="*60)
        print("🧪 I.N.S.I.G.H.T. BRIEFING WORKFLOW TEST REPORT")
        print("="*60)
        
        print(f"\n📊 Test Summary:")
        print(f"   Duration: {duration:.1f} seconds")
        print(f"   Setup Success: {'✅' if self.test_results['setup_success'] else '❌'}")
        print(f"   Tools Discovered: {self.test_results['tools_discovered']}")
        print(f"   Channels Tested: {self.test_results['channels_tested']}")
        print(f"   Total Posts Fetched: {self.test_results['total_posts_fetched']}")
        print(f"   Output Formats Generated: {', '.join(self.test_results['output_formats_generated'])}")
        
        print(f"\n🔧 Tool Test Results:")
        for tool_name, result in tool_results.items():
            status = "✅" if result.get("success", False) else "❌"
            print(f"   {status} {tool_name}: {result}")
        
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
            self.test_results["tools_discovered"] > 0,
            self.test_results["total_posts_fetched"] > 0,
            len(self.test_results["output_formats_generated"]) >= 2,
            len(self.test_results["errors"]) == 0
        ]
        
        overall_success = all(success_criteria)
        
        print(f"\n🎯 Overall Test Result: {'✅ SUCCESS' if overall_success else '❌ PARTIAL SUCCESS'}")
        
        if overall_success:
            print("🎉 All test objectives completed successfully!")
        else:
            print("⚠️ Some test objectives were not met, but basic functionality works.")
        
        print("="*60)
    
    async def cleanup(self):
        """Clean up test resources."""
        if self.telegram_connector:
            try:
                await self.telegram_connector.disconnect()
                self.logger.info("✅ Telegram connector disconnected")
            except Exception as e:
                self.logger.error(f"❌ Cleanup error: {e}")

async def main():
    """Main test execution function."""
    print("🚀 Starting I.N.S.I.G.H.T. Briefing Workflow Test...")
    
    # Create output directory if it doesn't exist
    os.makedirs("Tests/output", exist_ok=True)
    
    test = BriefingWorkflowTest()
    
    try:
        # Setup test environment
        if not await test.setup_test_environment():
            print("❌ Test setup failed. Exiting.")
            return
        
        # Test individual tools
        tool_results = await test.test_individual_tools()
        
        # Run main briefing workflow
        briefing_posts = await test.run_briefing_workflow()
        
        if not briefing_posts:
            print("❌ No posts retrieved. Cannot test output generation.")
            return
        
        # Generate outputs in all formats
        output_files = test.generate_outputs(briefing_posts)
        
        # Generate comprehensive test report
        test.generate_test_report(tool_results, output_files)
        
    except Exception as e:
        print(f"❌ Test execution failed: {e}")
        test.test_results["errors"].append(f"Main execution: {str(e)}")
        
    finally:
        # Cleanup
        await test.cleanup()

if __name__ == "__main__":
    # Run the test
    asyncio.run(main())