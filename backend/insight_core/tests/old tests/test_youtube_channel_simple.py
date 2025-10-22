import asyncio
import sys
import os
from typing import List

# Add the parent directory to the path so we can import the connector
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from connectors.youtube_connector import YouTubeConnector

async def simple_test():
    connector = YouTubeConnector()
    connector.setup_connector()
    await connector.connect()
    
    # Test with a well-known channel
    video_ids = connector._get_channel_videos_ytdlp("UC4tyylntl2l2-lA5N8GTddg", 5)
    
    print(video_ids)
    
    await connector.disconnect()
    
    return len(video_ids) > 0

if __name__ == "__main__":
    success = asyncio.run(simple_test())
    print("✅ Test passed!" if success else "❌ Test failed!")