"""
INSIGHT Express Test - Version 1: Basic YouTube Connector  
==========================================================

Purpose: Test the most basic functionality - direct YouTube connector usage
Scope: Single video transcript extraction, console output only
Focus: Understanding the core YouTube connector workflow

This version teaches us:
1. How to setup a YouTube connector from scratch
2. How to connect to YouTube (no auth needed)
3. How to extract transcript from a single video
4. How to display results in console

Educational Goals:
- Understand the connector lifecycle (setup -> connect -> fetch -> disconnect)
- See the raw transcript data structure from YouTube
- Verify yt-dlp and transcript API is working
- Test basic error handling for videos without transcripts
"""

import asyncio
import os
import sys
from datetime import datetime
from typing import List, Dict, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.youtube_connector import YouTubeConnector
from processors.ai.gemini_processor import GeminiProcessor
from output.console_output import ConsoleOutput

class InsightV1YouTubeBasic:

    def __init__(self):
        # Using a popular educational video that likely has transcripts
        self.test_video_url = "https://youtu.be/HIkBIfst8oA"  # 3Blue1Brown: Neural Networks
        # Alternative test URLs (uncomment to try different videos):
        # self.test_video_url = "https://youtu.be/aircAruvnKk"  # Short URL format
        # self.test_video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"  # Rick Roll (classic test)
    
    async def display_posts(self, posts: List[Dict[str, Any]]):
        """Display transcript posts in the console"""
        
        
    async def run(self):
        """Main execution loop"""
        self.youtube_connector = YouTubeConnector()
        self.gemini_processor = GeminiProcessor()

        self.youtube_connector.setup_connector()
        self.gemini_processor.setup_processor()
        
        await self.youtube_connector.connect()
        await self.gemini_processor.connect()

        transcript = await self.youtube_connector.fetch_single_video_transcript(self.test_video_url)

        # print(transcript)
        result = await self.gemini_processor.analyze_single_post(transcript[0]) # input dict?
            
        # ConsoleOutput.render_report_to_console(transcript, "YouTube Video Transcript")
        print(result)
        # ConsoleOutput.render_report_to_console(result, "YouTube Video Analysis")
        
        await self.youtube_connector.disconnect()
        await self.gemini_processor.disconnect()

if __name__ == "__main__":
    test_youtube_basic = InsightV1YouTubeBasic()
    asyncio.run(test_youtube_basic.run())