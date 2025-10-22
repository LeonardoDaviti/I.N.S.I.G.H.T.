#!/usr/bin/env python3
"""
Simple test script for YouTube channel video fetching functionality.
Tests the _get_channel_videos_ytdlp method with real YouTube channels.
"""

import asyncio
import sys
import os
from typing import List

# Add the parent directory to the path so we can import the connector
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.youtube_connector import YouTubeConnector


async def test_channel_video_fetching():
    """Test the _get_channel_videos_ytdlp method with various inputs."""
    
    print("🧪 Starting YouTube Channel Video Fetching Tests\n")
    
    # Initialize connector
    connector = YouTubeConnector()
    
    # Setup the connector
    if not connector.setup_connector():
        print("❌ Failed to setup YouTube connector")
        return False
    
    # Connect
    try:
        await connector.connect()
        print("✅ Connected to YouTube connector\n")
    except Exception as e:
        print(f"❌ Failed to connect: {e}")
        return False
    
    # Test cases
    test_cases = [
        {
            "name": "Channel ID (Veritasium)",
            "identifier": "UCHnyfMqiRRG1u-2MsSQLbXA",
            "limit": 5,
            "expected_min": 1  # Expect at least 1 video
        },
        {
            "name": "Username with @ (MKBHD)",
            "identifier": "@MKBHD",
            "limit": 3,
            "expected_min": 1
        },
        {
            "name": "Channel URL (3Blue1Brown)",
            "identifier": "https://www.youtube.com/@3blue1brown",
            "limit": 4,
            "expected_min": 1
        },
        {
            "name": "Large limit test",
            "identifier": "UCHnyfMqiRRG1u-2MsSQLbXA",
            "limit": 20,
            "expected_min": 10  # Expect at least 10 videos
        },
        {
            "name": "Invalid channel",
            "identifier": "ThisChannelDoesNotExist12345",
            "limit": 5,
            "expected_min": 0  # Expect no videos
        }
    ]
    
    results = []
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test {i}: {test_case['name']}")
        print(f"  Channel: {test_case['identifier']}")
        print(f"  Limit: {test_case['limit']}")
        
        try:
            # Call the method we're testing
            video_ids = connector._get_channel_videos_ytdlp(
                test_case['identifier'], 
                test_case['limit']
            )
            
            # Validate results
            if isinstance(video_ids, list):
                print(f"  ✅ Returned list with {len(video_ids)} video IDs")
                
                # Check if we got expected minimum number of videos
                if len(video_ids) >= test_case['expected_min']:
                    print(f"  ✅ Got expected minimum videos ({test_case['expected_min']})")
                    
                    # Validate video IDs format (should be 11 characters)
                    valid_ids = all(isinstance(vid_id, str) and len(vid_id) == 11 for vid_id in video_ids)
                    if valid_ids and video_ids:
                        print(f"  ✅ All video IDs have valid format")
                        print(f"  📝 Sample video IDs: {video_ids[:3]}")
                    elif not video_ids:
                        print(f"  ⚠️ No videos returned (expected for invalid channels)")
                    else:
                        print(f"  ❌ Some video IDs have invalid format")
                        
                    # Check limit is respected
                    if len(video_ids) <= test_case['limit']:
                        print(f"  ✅ Limit respected ({len(video_ids)} ≤ {test_case['limit']})")
                    else:
                        print(f"  ❌ Limit exceeded ({len(video_ids)} > {test_case['limit']})")
                        
                else:
                    if test_case['expected_min'] == 0:
                        print(f"  ✅ No videos returned as expected for invalid channel")
                    else:
                        print(f"  ❌ Got fewer videos than expected ({len(video_ids)} < {test_case['expected_min']})")
                
                results.append({
                    "test": test_case['name'],
                    "success": len(video_ids) >= test_case['expected_min'],
                    "video_count": len(video_ids)
                })
                
            else:
                print(f"  ❌ Did not return a list: {type(video_ids)}")
                results.append({
                    "test": test_case['name'],
                    "success": False,
                    "video_count": 0
                })
                
        except Exception as e:
            print(f"  ❌ Exception occurred: {e}")
            results.append({
                "test": test_case['name'],
                "success": False,
                "video_count": 0
            })
        
        print()  # Empty line for readability
    
    # Disconnect
    await connector.disconnect()
    
    # Summary
    print("=" * 50)
    print("📊 TEST SUMMARY")
    print("=" * 50)
    
    successful_tests = sum(1 for r in results if r['success'])
    total_tests = len(results)
    
    for result in results:
        status = "✅ PASS" if result['success'] else "❌ FAIL"
        print(f"{status} - {result['test']} ({result['video_count']} videos)")
    
    print(f"\nOverall: {successful_tests}/{total_tests} tests passed")
    
    if successful_tests == total_tests:
        print("🎉 All tests passed! The function is working correctly.")
        return True
    else:
        print("⚠️ Some tests failed. Check the implementation.")
        return False


async def test_helper_method():
    """Test the _extract_channel_id helper method."""
    print("🧪 Testing _extract_channel_id helper method\n")
    
    connector = YouTubeConnector()
    connector.setup_connector()
    
    test_cases = [
        {
            "input": "UCHnyfMqiRRG1u-2MsSQLbXA",
            "expected_contains": "channel/UCHnyfMqiRRG1u-2MsSQLbXA"
        },
        {
            "input": "@MKBHD", 
            "expected_contains": "@MKBHD"
        },
        {
            "input": "veritasium",
            "expected_contains": "@veritasium"
        },
        {
            "input": "https://www.youtube.com/@3blue1brown",
            "expected_contains": "@3blue1brown"
        }
    ]
    
    for test in test_cases:
        result = connector._extract_channel_id(test['input'])
        if test['expected_contains'] in result:
            print(f"✅ {test['input']} → {result}")
        else:
            print(f"❌ {test['input']} → {result} (expected to contain: {test['expected_contains']})")
    
    print()


if __name__ == "__main__":
    async def main():
        print("🚀 YouTube Connector Channel Video Fetching Test\n")
        
        # Test helper method first
        await test_helper_method()
        
        # Test main functionality
        success = await test_channel_video_fetching()
        
        if success:
            print("\n🎯 All tests completed successfully!")
            sys.exit(0)
        else:
            print("\n💥 Some tests failed!")
            sys.exit(1)
    
    # Run the tests
    asyncio.run(main())