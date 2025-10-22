#!/usr/bin/env python3
"""
I.N.S.I.G.H.T. Mark II - Comprehensive Testing Suite
Version: 2.4.0 - "The Validator"

This testing suite validates all functionality of the I.N.S.I.G.H.T. platform
including all missions, output formats, rate limiting, and error handling.

Features:
- Manual and Automatic testing modes
- Performance benchmarking
- Rate limiting validation
- Output format verification
- Comprehensive reporting
- Error detection and recovery testing
"""

import os
import sys
import asyncio
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path to import main modules
sys.path.append(str(Path(__file__).parent.parent))

from main import InsightOperator
from test_config import TestConfiguration
from test_cases import TestCases
from test_reporter import TestReporter

class TestRunner:
    """
    Comprehensive test runner for I.N.S.I.G.H.T. Mark II
    
    Supports both manual and automatic testing modes with
    detailed performance metrics and validation.
    """
    
    def __init__(self, mode='manual'):
        self.mode = mode  # 'manual' or 'automatic'
        self.config = TestConfiguration()
        self.test_cases = TestCases()
        self.reporter = TestReporter()
        self.insight = None
        
        # Setup test logging
        self.setup_test_logging()
        
        print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                    I.N.S.I.G.H.T. Mark II Testing Suite                    ║
║                         "The Validator" - v2.4.0                           ║
║                                                                              ║
║  Mode: {mode.upper():^10}                                                    ║
║  Test Cases: {len(self.test_cases.get_all_tests()):^3}                                                        ║
║  Output Formats: 7 (Console, HTML, JSON, Combinations)                      ║
╚══════════════════════════════════════════════════════════════════════════════╝
        """)
    
    def setup_test_logging(self):
        """Setup dedicated test logging"""
        log_dir = Path("Tests/logs")
        log_dir.mkdir(exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        log_file = log_dir / f"test_run_{timestamp}.log"
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - TEST - %(message)s',
            handlers=[
                logging.FileHandler(log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )
        
        self.log_file = log_file
        logging.info(f"Test logging initialized: {log_file}")
    
    async def initialize_insight(self):
        """Initialize and connect the I.N.S.I.G.H.T. operator"""
        logging.info("Initializing I.N.S.I.G.H.T. operator for testing...")
        self.insight = InsightOperator()
        await self.insight.connect_all()
        
        available_connectors = list(self.insight.connectors.keys())
        logging.info(f"Available connectors: {available_connectors}")
        
        if not available_connectors:
            raise Exception("No connectors available for testing!")
        
        return available_connectors
    
    async def run_test_case(self, test_case):
        """Execute a single test case with performance monitoring"""
        test_name = test_case['name']
        mission_type = test_case['mission']
        test_data = test_case['data']
        expected_behavior = test_case['expected']
        
        logging.info(f"Starting test: {test_name}")
        print(f"\n🧪 Testing: {test_name}")
        print(f"📋 Mission: {mission_type}")
        print(f"🎯 Expected: {expected_behavior}")
        
        start_time = time.time()
        test_result = {
            'name': test_name,
            'mission': mission_type,
            'start_time': start_time,
            'success': False,
            'posts_fetched': 0,
            'execution_time': 0,
            'output_formats_tested': [],
            'rate_limiting_detected': False,
            'errors': [],
            'performance_metrics': {}
        }
        
        try:
            # Execute the specific mission based on type
            posts = await self.execute_mission(mission_type, test_data)
            
            end_time = time.time()
            execution_time = end_time - start_time
            
            test_result.update({
                'success': True,
                'posts_fetched': len(posts),
                'execution_time': execution_time,
                'performance_metrics': {
                    'posts_per_second': len(posts) / execution_time if execution_time > 0 else 0,
                    'avg_time_per_post': execution_time / len(posts) if len(posts) > 0 else 0
                }
            })
            
            # Test output formats if in automatic mode
            if self.mode == 'automatic':
                await self.test_output_formats(posts, test_case, test_result)
            
            # Check for rate limiting indicators
            if execution_time > self.config.RATE_LIMIT_THRESHOLD:
                test_result['rate_limiting_detected'] = True
                logging.warning(f"Possible rate limiting detected - execution time: {execution_time:.2f}s")
            
            print(f"✅ Test passed: {len(posts)} posts in {execution_time:.2f}s")
            logging.info(f"Test completed successfully: {test_name}")
            
        except Exception as e:
            end_time = time.time()
            test_result.update({
                'success': False,
                'execution_time': end_time - start_time,
                'errors': [str(e)]
            })
            
            print(f"❌ Test failed: {str(e)}")
            logging.error(f"Test failed: {test_name} - {str(e)}")
        
        # Manual mode: Ask user for validation
        if self.mode == 'manual':
            await self.manual_validation(test_result)
        
        return test_result
    
    async def execute_mission(self, mission_type, test_data):
        """Execute specific mission based on type"""
        posts = []
        
        if mission_type == 'telegram_deep_scan':
            posts = await self.insight.get_n_posts(test_data['channel'], test_data['limit'])
        
        elif mission_type == 'telegram_briefing':
            posts = await self.insight.get_briefing_posts(test_data['channels'], test_data['days'])
        
        elif mission_type == 'telegram_eod':
            posts = await self.insight.get_briefing_posts(test_data['channels'], 0)
        
        elif mission_type == 'rss_analysis':
            feed_info = await self.insight.analyze_rss_feed(test_data['feed_url'])
            # Convert feed_info to posts format for consistency
            posts = [{'title': 'RSS Analysis', 'content': json.dumps(feed_info, indent=2), 'platform': 'rss'}]
        
        elif mission_type == 'rss_single':
            posts = await self.insight.get_rss_posts(test_data['feed_url'], test_data['limit'])
        
        elif mission_type == 'rss_multi':
            posts = await self.insight.get_multi_rss_posts(test_data['feed_urls'], test_data['limit_per_feed'])
        
        elif mission_type == 'youtube_transcript':
            posts = await self.insight.get_youtube_transcript(test_data['video_url'])
        
        elif mission_type == 'youtube_channel':
            posts = await self.insight.get_youtube_channel_transcripts(test_data['channel_id'], test_data['limit'])
        
        elif mission_type == 'youtube_playlist':
            posts = await self.insight.get_youtube_playlist_transcripts(test_data['playlist_url'], test_data['limit'])
        
        elif mission_type == 'reddit_post':
            posts = await self.insight.get_reddit_post_with_comments(test_data['post_url'])
        
        elif mission_type == 'reddit_subreddit':
            posts = await self.insight.get_posts_from_subreddit(test_data['subreddit'], test_data['limit'])
        
        elif mission_type == 'reddit_multi':
            posts = await self.insight.get_posts_from_multiple_subreddits(test_data['subreddits'], test_data['limit_per_subreddit'])
        
        else:
            raise ValueError(f"Unknown mission type: {mission_type}")
        
        return posts
    
    async def test_output_formats(self, posts, test_case, test_result):
        """Test all output formats for the given posts"""
        from output import HTMLOutput, JSONOutput
        
        formats_tested = []
        
        try:
            # Test JSON output
            json_output = JSONOutput()
            mission_context = json_output.create_mission_summary(
                posts, 
                test_case['name'], 
                [test_case['data'].get('channel', 'test')]
            )
            json_filename = f"test_output_{test_case['name'].replace(' ', '_')}.json"
            json_output.export_to_file(posts, f"Tests/output/{json_filename}", mission_context=mission_context)
            formats_tested.append('JSON')
            
            # Test HTML output
            html_output = HTMLOutput(f"Test: {test_case['name']}")
            html_output.render_report(posts)
            html_filename = f"test_output_{test_case['name'].replace(' ', '_')}.html"
            html_output.save_to_file(f"Tests/output/{html_filename}")
            formats_tested.append('HTML')
            
            # Console output is tested implicitly during execution
            formats_tested.append('Console')
            
        except Exception as e:
            test_result['errors'].append(f"Output format testing failed: {str(e)}")
        
        test_result['output_formats_tested'] = formats_tested
    
    async def manual_validation(self, test_result):
        """Manual validation by user input"""
        print(f"\n📊 Test Results for: {test_result['name']}")
        print(f"   Posts fetched: {test_result['posts_fetched']}")
        print(f"   Execution time: {test_result['execution_time']:.2f}s")
        print(f"   Technical success: {'✅' if test_result['success'] else '❌'}")
        
        while True:
            user_input = input("\n👤 Did this test meet your expectations? (y/n/s for skip): ").lower()
            if user_input in ['y', 'yes']:
                test_result['user_validation'] = 'passed'
                break
            elif user_input in ['n', 'no']:
                test_result['user_validation'] = 'failed'
                reason = input("   Please describe what went wrong: ")
                test_result['user_feedback'] = reason
                break
            elif user_input in ['s', 'skip']:
                test_result['user_validation'] = 'skipped'
                break
            else:
                print("   Please enter 'y' for yes, 'n' for no, or 's' to skip")
    
    async def run_all_tests(self):
        """Run all test cases based on mode"""
        # Create output directories
        Path("Tests/output").mkdir(parents=True, exist_ok=True)
        Path("Tests/logs").mkdir(parents=True, exist_ok=True)
        
        # Initialize I.N.S.I.G.H.T.
        available_connectors = await self.initialize_insight()
        
        # Get test cases
        all_tests = self.test_cases.get_all_tests()
        
        # Filter tests based on available connectors
        filtered_tests = self.test_cases.filter_tests_by_connectors(all_tests, available_connectors)
        
        print(f"\n🎯 Running {len(filtered_tests)} tests (filtered from {len(all_tests)} total)")
        
        if self.mode == 'manual':
            print("\n⚠️  Manual mode: You'll be asked to validate each test result")
        
        # Execute tests
        results = []
        for i, test_case in enumerate(filtered_tests, 1):
            print(f"\n{'='*80}")
            print(f"Test {i}/{len(filtered_tests)}")
            print(f"{'='*80}")
            
            result = await self.run_test_case(test_case)
            results.append(result)
            
            # Add delay between tests to avoid rate limiting
            if i < len(filtered_tests):
                delay = self.config.INTER_TEST_DELAY
                print(f"\n⏳ Waiting {delay}s before next test...")
                await asyncio.sleep(delay)
        
        # Generate comprehensive report
        report = self.reporter.generate_report(results, available_connectors)
        
        # Save report
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = Path(f"Tests/reports/test_report_{timestamp}.json")
        report_file.parent.mkdir(exist_ok=True)
        
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        
        # Display summary
        self.display_test_summary(report)
        
        print(f"\n📄 Detailed report saved to: {report_file}")
        print(f"📄 Test logs saved to: {self.log_file}")
        
        # Cleanup
        await self.insight.disconnect_all()
        
        return report
    
    def display_test_summary(self, report):
        """Display a summary of test results"""
        stats = report['summary']['statistics']
        
        print(f"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                               TEST SUMMARY                                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  Total Tests: {stats['total_tests']:^3}                                                         ║
║  Passed: {stats['passed']:^3}  │  Failed: {stats['failed']:^3}  │  Skipped: {stats.get('skipped', 0):^3}                   ║
║  Success Rate: {stats['success_rate']:.1f}%                                                    ║
║                                                                              ║
║  Total Posts Fetched: {stats['total_posts']:^6}                                              ║
║  Total Execution Time: {stats['total_execution_time']:.1f}s                                             ║
║  Average Time per Test: {stats['avg_execution_time']:.1f}s                                           ║
║                                                                              ║
║  Connectors Tested: {', '.join(report['summary']['connectors_tested']):^20}                              ║
║  Rate Limiting Detected: {stats['rate_limiting_incidents']:^3} incidents                                ║
╚══════════════════════════════════════════════════════════════════════════════╝
        """)
        
        if stats['failed'] > 0:
            print("\n❌ FAILED TESTS:")
            for result in report['results']:
                if not result['success']:
                    print(f"   • {result['name']}: {result['errors'][0] if result['errors'] else 'Unknown error'}")
        
        if stats.get('skipped', 0) > 0:
            print(f"\n⏭️  SKIPPED TESTS: {stats['skipped']}")

async def main():
    """Main entry point for test runner"""
    print("I.N.S.I.G.H.T. Mark II - Testing Suite")
    print("Select testing mode:")
    print("1. Manual Testing (interactive validation)")
    print("2. Automatic Testing (silent execution)")
    
    while True:
        choice = input("\nEnter your choice (1 or 2): ").strip()
        if choice == '1':
            mode = 'manual'
            break
        elif choice == '2':
            mode = 'automatic'
            break
        else:
            print("Please enter 1 or 2")
    
    runner = TestRunner(mode=mode)
    
    try:
        report = await runner.run_all_tests()
        
        # Ask if user wants to see detailed results
        if input("\n🔍 View detailed test results? (y/n): ").lower() in ['y', 'yes']:
            print(json.dumps(report, indent=2))
        
    except KeyboardInterrupt:
        print("\n\n⚠️  Testing interrupted by user")
    except Exception as e:
        print(f"\n💥 Testing failed with critical error: {e}")
        logging.critical(f"Critical testing error: {e}", exc_info=True)

if __name__ == "__main__":
    asyncio.run(main())