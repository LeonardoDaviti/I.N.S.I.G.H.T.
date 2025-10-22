"""
INSIGHT Express Test - Version 8: Interactive YouTube Transcript App
====================================================================

Purpose: Interactive application for YouTube transcript extraction
Scope: User enters URLs, gets transcripts, can quit with 'q'
Focus: User-driven transcript extraction workflow

This version provides:
1. Interactive URL input from user
2. Real-time transcript extraction
3. Simple quit mechanism with 'q'
4. Clean connector lifecycle management

Educational Goals:
- Understand interactive application flow
- See how to handle user input in async context
- Learn proper resource cleanup
- Experience real-time transcript processing
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

class InsightV8YouTubeInteractive:

    def __init__(self):
        self.youtube_connector = None
        self.gemini_processor = None
    
    async def setup_connectors(self):
        """Initialize and setup all connectors"""
        print("🚀 Setting up INSIGHT YouTube Transcript App...")
        
        self.youtube_connector = YouTubeConnector()
        self.gemini_processor = GeminiProcessor()

        self.youtube_connector.setup_connector()
        self.gemini_processor.setup_processor()
        
        await self.youtube_connector.connect()
        await self.gemini_processor.connect()
        
        print("✅ Connectors ready!")
    
    async def cleanup_connectors(self):
        """Clean up all connectors"""
        print("\n🧹 Cleaning up connectors...")
        
        if self.youtube_connector:
            await self.youtube_connector.disconnect()
        if self.gemini_processor:
            await self.gemini_processor.disconnect()
            
        print("✅ Cleanup complete!")

    async def handle_questions(self, transcript_post: Dict[str, Any]):
        """Handle question-asking loop for the current video"""
        print("\n" + "="*50)
        print("💬 ASK QUESTIONS ABOUT THIS VIDEO")
        print("="*50)
        print("❓ Ask any question about the content")
        print("⏭️  Type 'next' to go to next video")
        print("❌ Type 'q' to quit application")
        print("="*50)
        
        while True:
            try:
                print("\n💭 Your question (or 'next'/'q'):")
                user_question = input("> ").strip()
                
                # Check for commands
                if user_question.lower() == 'q':
                    return 'quit'
                
                if user_question.lower() == 'next':
                    return 'next'
                
                # Validate question
                if not user_question:
                    print("⚠️  Please enter a question or 'next'/'q'")
                    continue
                
                # Ask Gemini the question
                print("🤖 Thinking...")
                result = await self.gemini_processor.ask_single_post(transcript_post, user_question)
                
                if "error" in result:
                    print(f"❌ Error: {result['error']}")
                    continue
                
                print("\n🧠 AI ANSWER:")
                print("-" * 40)
                print(result.get('answer', 'No answer provided'))
                print("-" * 40)
                
            except Exception as e:
                print(f"❌ Error processing question: {str(e)}")
    
    async def process_video_url(self, url: str):
        """Process a single video URL and display results"""
        try:
            print(f"\n📺 Processing: {url}")
            print("⏳ Fetching transcript...")
            
            # Get transcript
            transcript = await self.youtube_connector.fetch_single_video_transcript(url)
            
            if not transcript:
                print("❌ No transcript found for this video")
                return
            
            print("\n📄 TRANSCRIPT:")
            print("=" * 50)
            print(transcript)
            print("=" * 50)
            
            # Analyze with Gemini
            print("\n🤖 Analyzing with AI...")
            result = await self.gemini_processor.analyze_single_post(transcript[0])
            
            print("\n🧠 AI ANALYSIS:")
            print("=" * 50)
            print(result)
            print("=" * 50)

            # Handle questions
            question_result = await self.handle_questions(transcript[0])
            return question_result
            
        except Exception as e:
            print(f"❌ Error processing video: {str(e)}")
    
    async def run(self):
        """Main interactive loop"""
        await self.setup_connectors()
        
        print("\n" + "="*60)
        print("🎬 INSIGHT YouTube Transcript Extractor")
        print("="*60)
        print("📝 Enter YouTube URLs to get transcripts")
        print("❌ Type 'q' to quit")
        print("="*60)
        
        while True:
            try:
                # Get user input
                print("\n🔗 Enter YouTube URL (or 'q' to quit):")
                user_input = input("> ").strip()
                
                # Check for quit command
                if user_input.lower() == 'q':
                    print("\n👋 Thanks for using INSIGHT! Goodbye!")
                    break
                
                # Validate input
                if not user_input:
                    print("⚠️  Please enter a valid URL or 'q' to quit")
                    continue
                
                if "youtube.com" not in user_input and "youtu.be" not in user_input:
                    print("⚠️  Please enter a valid YouTube URL")
                    continue
                
                # Process the URL
                await self.process_video_url(user_input)
                
            except KeyboardInterrupt:
                print("\n\n👋 Keyboard interrupt received. Goodbye!")
                break
            except Exception as e:
                print(f"❌ Unexpected error: {str(e)}")
                print("🔄 Continuing with next input...")
        
        await self.cleanup_connectors()

if __name__ == "__main__":
    app = InsightV8YouTubeInteractive()
    asyncio.run(app.run())