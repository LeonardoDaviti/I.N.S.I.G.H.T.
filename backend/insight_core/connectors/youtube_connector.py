from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs
import os

import yt_dlp
try:
    from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
    from youtube_transcript_api.formatters import TextFormatter
    TRANSCRIPT_API_AVAILABLE = True
except ImportError:
    TRANSCRIPT_API_AVAILABLE = False

    class NoTranscriptFound(Exception):
        pass

    class TranscriptsDisabled(Exception):
        pass

    class TextFormatter:
        def format_transcript(self, transcript_data):
            return "\n".join(item.get("text", "") for item in transcript_data if item.get("text"))

    class _YouTubeTranscriptApiFallback:
        @staticmethod
        def list_transcripts(video_id):
            raise NoTranscriptFound("youtube_transcript_api is not installed")

    YouTubeTranscriptApi = _YouTubeTranscriptApiFallback

from .base_connector import BaseConnector
from .tool_registry import expose_tool

class YouTubeConnector(BaseConnector):
    """
    I.N.S.I.G.H.T. YouTube Connector v3.1 - "The Liberated Spymaster" - Grand Marshal Edition
    
    Now FREE from Google API dependencies! Uses yt-dlp for metadata extraction
    and youtube_transcript_api for transcripts.
    
    Features:
    - Single video transcript extraction by URL
    - Channel-based transcript collection (latest N videos)
    - Playlist transcript extraction
    - Search-based transcript collection
    - Language preference system with fallbacks
    - HARDENED: Bulletproof error handling for all failure scenarios
    - NO API KEY REQUIRED: Complete freedom from Google's API quotas
    
    This connector treats transcript failures as expected battlefield conditions
    and continues operations despite individual video failures.
    
    Updated with two-phase initialization for automatic discovery support.
    """
    
    def __init__(self):
        """
        Phase 1: Create blank YouTube connector object.
        Configuration will be handled by setup_connector().
        """
        super().__init__("youtube")
        
        # Default values - will be set in setup_connector()
        self.preferred_languages = None
        self.transcript_formatter = None
        self.prefer_manual = None
        self.ydl_opts = None
        
        self.logger.info("YouTube Connector object created (pending setup)")
    
    def setup_connector(self) -> bool:
        """
        Phase 2: Configure the YouTube connector with language preferences and settings.
        
        Returns:
            bool: True if setup was successful
        """
        try:
            self.logger.info("Setting up YouTube connector...")
            
            # Load language preferences from environment or use defaults
            languages_env = os.getenv('YOUTUBE_PREFERRED_LANGUAGES', 'en,ru,ka')
            self.preferred_languages = [lang.strip() for lang in languages_env.split(',')]
            
            # Initialize transcript formatter
            self.transcript_formatter = TextFormatter()
            
            # Quality preferences - prefer manual transcripts over auto-generated
            self.prefer_manual = os.getenv('YOUTUBE_PREFER_MANUAL', 'true').lower() == 'true'
            
            # yt-dlp configuration
            self.ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,  # We need full info for metadata
                'writesubtitles': False,  # We use youtube_transcript_api instead
                'writeautomaticsub': False,
            }
            
            # Test that yt-dlp is available
            try:
                with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                    pass  # Just test that it works
            except Exception as e:
                self.logger.error(f"❌ yt-dlp not available: {e}")
                return False
            
            self.logger.info("✅ YouTube connector setup successful")
            self.logger.info(f"   Preferred languages: {self.preferred_languages}")
            self.logger.info(f"   Prefer manual transcripts: {self.prefer_manual}")
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Failed to setup YouTube connector: {e}")
            return False
    
    async def connect(self) -> None:
        """
        No connection needed - yt-dlp works directly without authentication.
        """
        try:
            # Test yt-dlp functionality with a simple call
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                # Just test that yt-dlp is working
                pass
            self.logger.info("Connected to YouTube via yt-dlp - Ready for intelligence gathering!")
        except Exception as e:
            self.logger.error(f"Failed to initialize yt-dlp: {str(e)}")
            raise ConnectionError(f"yt-dlp initialization failed: {str(e)}")
    
    async def disconnect(self) -> None:
        """
        Gracefully disconnects (nothing to disconnect with yt-dlp).
        """
        self.logger.info("YouTube connector disconnected")
    
    def _extract_video_id(self, video_url: str) -> Optional[str]:
        """
        Extracts video ID from various YouTube URL formats.
        Supports youtu.be, youtube.com/watch, youtube.com/embed formats.
        
        Args:
            video_url: YouTube video URL
            
        Returns:
            Extracted video ID or None if invalid
        """
        try:
            # Handle youtu.be short URLs
            if "youtu.be" in video_url:
                return video_url.split("/")[-1].split("?")[0]
            
            # Handle youtube.com URLs
            elif "youtube.com" in video_url:
                # Standard watch URLs
                if "v=" in video_url:
                    return video_url.split("v=")[1].split("&")[0]
                # Embed URLs
                elif "embed/" in video_url:
                    return video_url.split("embed/")[1].split("?")[0]
            
            return None
            
        except Exception as e:
            self.logger.warning(f"Failed to extract video ID from URL {video_url}: {e}")
            return None
    
    def _extract_channel_id(self, channel_identifier: str) -> str:
        """
        Processes channel identifier to determine if it's a channel ID or username.
        
        Args:
            channel_identifier: Channel ID, username, or channel URL
            
        Returns:
            Processed channel identifier for yt-dlp calls
        """
        # If it's a full URL, return as-is for yt-dlp
        if "youtube.com" in channel_identifier:
            return channel_identifier
        
        # If it's just a channel ID or username, construct the URL
        if channel_identifier.startswith('UC') and len(channel_identifier) == 24:
            # It's a channel ID
            return f"https://www.youtube.com/channel/{channel_identifier}"
        elif channel_identifier.startswith('@'):
            # It's a handle
            return f"https://www.youtube.com/{channel_identifier}"
        else:
            # Assume it's a username or handle without @
            return f"https://www.youtube.com/@{channel_identifier}"
    
    def _get_best_transcript(self, video_id: str) -> Optional[str]:
        """
        Fetches the best available transcript for a video using language preferences.
        
        Args:
            video_id: YouTube video ID
            
        Returns:
            Formatted transcript text or None if no transcript available
        """
        try:
            # Get available transcripts
            transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
            
            # Try preferred languages first
            for lang_code in self.preferred_languages:
                try:
                    # Try manual transcript first
                    if self.prefer_manual:
                        try:
                            transcript = transcript_list.find_manually_created_transcript([lang_code])
                            transcript_data = transcript.fetch()
                            return self.transcript_formatter.format_transcript(transcript_data)
                        except NoTranscriptFound:
                            pass  # Fall back to auto-generated
                    
                    # Try any transcript (manual or auto) in preferred language
                    transcript = transcript_list.find_transcript([lang_code])
                    transcript_data = transcript.fetch()
                    return self.transcript_formatter.format_transcript(transcript_data)
                    
                except NoTranscriptFound:
                    continue
            
            # If no preferred language found, try any available transcript
            try:
                # Get first available transcript
                available_transcripts = list(transcript_list)
                if available_transcripts:
                    first_transcript = available_transcripts[0]
                    transcript_data = first_transcript.fetch()
                    return self.transcript_formatter.format_transcript(transcript_data)
            except Exception:
                pass
            
            return None
            
        except (NoTranscriptFound, TranscriptsDisabled) as e:
            self.logger.warning(f"No transcript available for video {video_id}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Unexpected error fetching transcript for video {video_id}: {e}")
            return None
    
    def _get_video_metadata_ytdlp(self, video_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetches video metadata using yt-dlp.
        
        Args:
            video_id: YouTube video ID
            
        Returns:
            Video metadata dictionary or None if failed
        """
        try:
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            
            with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                
                if not info:
                    self.logger.warning(f"No metadata found for video {video_id}")
                    return None
                
                # Convert yt-dlp format to Google API-like format for compatibility
                return {
                    'snippet': {
                        'title': info.get('title', ''),
                        'description': info.get('description', ''),
                        'publishedAt': info.get('upload_date', ''),
                        'channelTitle': info.get('uploader', ''),
                        'channelId': info.get('uploader_id', ''),
                    },
                    'statistics': {
                        'viewCount': info.get('view_count', 0),
                        'likeCount': info.get('like_count', 0),
                    }
                }
            
        except Exception as e:
            self.logger.error(f"yt-dlp error fetching metadata for video {video_id}: {e}")
            return None
    
    def _get_channel_videos_ytdlp(self, channel_identifier: str, limit: int) -> List[str]:
        """
        Fetches latest video IDs from a YouTube channel using yt-dlp.
        This version correctly parses the nested structure returned for channel pages.
        """
        try:
            channel_url = self._extract_channel_id(channel_identifier)
            
            opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': 'in_playlist',
                'playlistend': limit, # This limit applies to each tab, so we'll enforce the total limit in our code.
                'cachedir': False,
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                self.logger.info(f"Extracting video list from channel URL: {channel_url}")
                info = ydl.extract_info(channel_url, download=False)

                if not info or 'entries' not in info:
                    self.logger.error(f"Channel {channel_identifier} not found or has no videos")
                    return []

                # --- THE CORRECT PARSING LOGIC ---
                all_video_ids = []
                # Loop through the main entries, which are the channel's TABS (Videos, Live, Shorts)
                for tab_playlist in info['entries']:
                    # Check if this tab has its own list of video entries
                    if tab_playlist and 'entries' in tab_playlist and tab_playlist['entries']:
                        # Loop through the actual videos inside the tab
                        for video_entry in tab_playlist['entries']:
                            if video_entry and 'id' in video_entry:
                                all_video_ids.append(video_entry['id'])
                                # Stop once we have collected enough videos to meet the limit
                                if len(all_video_ids) >= limit:
                                    break
                    
                    # Break the outer loop as well if the limit is reached
                    if len(all_video_ids) >= limit:
                        break
                
                # Return the final list, ensuring it's not longer than the requested limit
                return all_video_ids[:limit]

        except Exception as e:
            self.logger.error(f"yt-dlp error fetching videos from channel {channel_identifier}: {e}")
            return []
    
    def _search_videos_ytdlp(self, search_query: str, limit: int) -> List[str]:
        """
        Searches for videos using yt-dlp.
        
        Args:
            search_query: Search query
            limit: Maximum number of video IDs to return
            
        Returns:
            List of video IDs
        """
        try:
            search_url = f"ytsearch{limit}:{search_query}"
            
            opts = {
                **self.ydl_opts,
                'extract_flat': True,
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(search_url, download=False)
                
                if not info or 'entries' not in info:
                    self.logger.warning(f"No videos found for search query: {search_query}")
                    return []
                
                # Extract video IDs from entries
                video_ids = []
                for entry in info['entries']:
                    if entry and 'id' in entry:
                        video_ids.append(entry['id'])
                
                return video_ids[:limit]
            
        except Exception as e:
            self.logger.error(f"yt-dlp error searching for videos with query '{search_query}': {e}")
            return []
    
    def _get_playlist_videos_ytdlp(self, playlist_url: str, limit: int) -> List[str]:
        """
        Fetches video IDs from a YouTube playlist using yt-dlp.
        
        Args:
            playlist_url: YouTube playlist URL
            limit: Maximum number of videos to fetch
            
        Returns:
            List of video IDs
        """
        try:
            opts = {
                **self.ydl_opts,
                'extract_flat': True,
                'playlistend': limit,
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
                
                if not info or 'entries' not in info:
                    self.logger.error(f"Playlist not found or has no videos: {playlist_url}")
                    return []
                
                # Extract video IDs from entries
                video_ids = []
                for entry in info['entries']:
                    if entry and 'id' in entry:
                        video_ids.append(entry['id'])
                        if len(video_ids) >= limit:
                            break
                
                return video_ids
            
        except Exception as e:
            self.logger.error(f"yt-dlp error fetching playlist {playlist_url}: {e}")
            return []

    async def fetch_posts(self, source_identifier: str, limit: int) -> List[Dict[str, Any]]:
        """
        Fetches transcripts from YouTube videos.
        
        Supports two modes:
        1. Single video URL - extracts transcript from one video
        2. Channel identifier - extracts transcripts from latest N videos
        
        HARDENED: Individual video failures do not affect other videos.
        
        Args:
            source_identifier: YouTube video URL or channel identifier
            limit: Maximum number of transcripts to fetch (ignored for single video)
            
        Returns:
            List of posts in unified format with transcript content
        """
        # Determine if this is a video URL or channel identifier
        video_id = self._extract_video_id(source_identifier)
        
        if video_id:
            # Single video mode
            return await self._fetch_single_video_transcript(video_id, source_identifier)
        else:
            # Channel mode
            return await self._fetch_channel_transcripts(source_identifier, limit)
    
    @expose_tool(
        name="fetch_single_video_transcript",
        description="Extract transcript from a single YouTube video with detailed metadata",
        parameters={
            "video_url": {
                "type": "str",
                "description": "YouTube video URL (https://youtube.com/watch?v=..., https://youtu.be/..., or https://youtube.com/embed/...)",
                "required": True
            }
        },
        category="youtube",
        examples=[
            "fetch_single_video_transcript('https://www.youtube.com/watch?v=dQw4w9WgXcQ')",
            "fetch_single_video_transcript('https://youtu.be/dQw4w9WgXcQ')",
            "fetch_single_video_transcript('https://www.youtube.com/embed/dQw4w9WgXcQ')"
        ],
        returns="List containing single post with video transcript, title, description, and metadata",
        notes="Only accepts single video URLs. Use fetch_video_transcripts for channels. Returns empty list if no transcript available."
    )
    async def fetch_single_video_transcript(self, video_url: str) -> List[Dict[str, Any]]:
        """
        Extract transcript from a single YouTube video.
        
        This tool is specifically designed for single video transcript extraction
        with strict URL validation to ensure only video URLs are accepted.
        
        Args:
            video_url: YouTube video URL in any supported format
            
        Returns:
            List containing single post with transcript or empty list if failed
        """
        # Validate that this is actually a video URL
        video_id = self._extract_video_id(video_url)
        if not video_id:
            self.logger.error(f"Invalid YouTube video URL: {video_url}")
            return []
        
        self.logger.info(f"🎥 Extracting transcript from single video: {video_id}")
        
        try:
            # Use the existing internal method
            result = await self._fetch_single_video_transcript(video_id, video_url)
            
            if result:
                self.logger.info(f"✅ Successfully extracted transcript from video {video_id}")
            else:
                self.logger.warning(f"⚠️ No transcript available for video {video_id}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Failed to extract transcript from video {video_id}: {str(e)}")
            return []

    async def _fetch_single_video_transcript(self, video_id: str, source_identifier: str) -> List[Dict[str, Any]]:
        """
        Fetches transcript from a single YouTube video.
        
        Args:
            video_id: YouTube video ID
            source_identifier: Original source as entered by user
            
        Returns:
            List containing single post with transcript or empty list if failed
        """
        self.logger.info(f"Extracting intelligence from video {video_id}...")
        
        try:
            # Get video metadata using yt-dlp
            metadata = self._get_video_metadata_ytdlp(video_id)
            if not metadata:
                self.logger.error(f"ERROR: Failed to fetch metadata for video {video_id}")
                return []
            
            # Get transcript
            transcript = self._get_best_transcript(video_id)
            if not transcript:
                self.logger.warning(f"WARNING: Could not retrieve transcript for video {video_id}. Skipping.")
                return []
            
            # Create unified post
            snippet = metadata['snippet']
            
            # Parse publish date from yt-dlp format (YYYYMMDD)
            upload_date_str = snippet.get('publishedAt', '')
            try:
                if upload_date_str and len(upload_date_str) == 8:
                    # Convert YYYYMMDD to datetime
                    year = int(upload_date_str[:4])
                    month = int(upload_date_str[4:6])
                    day = int(upload_date_str[6:8])
                    publish_date = datetime(year, month, day, tzinfo=timezone.utc)
                else:
                    publish_date = datetime.now(timezone.utc)
            except:
                publish_date = datetime.now(timezone.utc)
            
            unified_post = self._create_unified_post(
                platform="youtube",
                source=source_identifier,  # Exactly as user enters
                url=f"https://www.youtube.com/watch?v={video_id}",
                content=transcript,
                date=publish_date,
                media_urls=[f"https://www.youtube.com/watch?v={video_id}"],
                categories=[],  # YouTube tags could be extracted here in future
                metadata={}  # Empty for Mark II
            )
            
            # # Add YouTube-specific metadata
            # unified_post['video_title'] = snippet['title']
            # unified_post['video_description'] = snippet.get('description', '')
            # unified_post['channel_id'] = snippet['channelId']
            # unified_post['view_count'] = metadata.get('statistics', {}).get('viewCount', 0)
            
            self.logger.info(f"Successfully extracted transcript from video {video_id}")
            return [unified_post]
            
        except Exception as e:
            self.logger.error(f"ERROR: Failed to process video {video_id} - Reason: {str(e)}")
            return []
    
    @expose_tool(
        name="fetch_video_transcripts",
        description="Extract transcripts from the latest N videos in a YouTube channel",
        parameters={
            "channel_identifier": {
                "type": "str",
                "description": "YouTube channel ID (UC...), username (@username), or channel URL (https://youtube.com/...)",
                "required": True
            },
            "limit": {
                "type": "int",
                "description": "Number of latest videos to fetch transcripts from (1-50)",
                "required": True
            }
        },
        category="youtube",
        examples=[
            "fetch_video_transcripts('UCHnyfMqiRRG1u-2MsSQLbXA', 10)",
            "fetch_video_transcripts('@veritasium', 5)",
            "fetch_video_transcripts('https://youtube.com/@mkbhd', 15)"
        ],
        returns="List of posts with video transcripts, titles, descriptions, and metadata",
        notes="Large channels may take several minutes. Individual video failures won't stop the process. Use reasonable limits to avoid timeouts."
    )
    async def fetch_channel_transcripts(self, channel_identifier: str, limit: int) -> List[Dict[str, Any]]:
        """
        Extract transcripts from the latest N videos in a YouTube channel.
        
        This tool fetches the most recent videos from a channel and extracts their
        transcripts using yt-dlp for metadata and youtube_transcript_api for transcripts.
        Individual video failures are handled gracefully.
        
        Args:
            channel_identifier: Channel ID, username, or full channel URL
            limit: Number of videos to process (1-50 recommended)
            
        Returns:
            List of posts with transcripts in unified format, sorted by publish date
        """
        # Validate inputs
        if limit <= 0 or limit > 50:
            self.logger.error("Limit must be between 1 and 50 for performance reasons")
            return []
        
        if not channel_identifier.strip():
            self.logger.error("Channel identifier cannot be empty")
            return []
        
        self.logger.info(f"🎬 Extracting transcripts from {limit} videos in channel: {channel_identifier}")
        
        try:
            # Use the existing internal method
            result = await self._fetch_channel_transcripts(channel_identifier, limit)
            
            if result:
                self.logger.info(f"✅ Successfully extracted {len(result)} transcripts from channel {channel_identifier}")
            else:
                self.logger.warning(f"⚠️ No transcripts available for channel {channel_identifier}")
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Failed to extract transcripts from channel {channel_identifier}: {str(e)}")
            return []
    

    async def _fetch_channel_transcripts(self, channel_identifier: str, limit: int) -> List[Dict[str, Any]]:
        """
        Fetches transcripts from latest videos in a YouTube channel.
        
        HARDENED: Individual video failures do not affect the overall operation.
        
        Args:
            channel_identifier: Channel ID or username
            limit: Maximum number of video transcripts to fetch
            
        Returns:
            List of posts with transcripts in unified format
        """
        self.logger.info(f"Starting intelligence extraction from channel {channel_identifier} (limit: {limit})...")
        
        try:
            # Get video IDs from channel using yt-dlp
            video_ids = self._get_channel_videos_ytdlp(channel_identifier, limit)
            if not video_ids:
                self.logger.error(f"ERROR: No videos found for channel {channel_identifier}")
                return []
            
            self.logger.info(f"Found {len(video_ids)} videos in channel {channel_identifier}")
            
            # Process each video with individual error handling
            all_posts = []
            successful_extractions = 0
            failed_extractions = 0
            
            for i, video_id in enumerate(video_ids):
                self.logger.info(f"Processing video {i+1}/{len(video_ids)}: {video_id}")
                
                try:
                    video_posts = await self._fetch_single_video_transcript(video_id, channel_identifier)
                    
                    if video_posts:
                        all_posts.extend(video_posts)
                        successful_extractions += 1
                    
                except Exception as e:
                    # If the specialist fails on one video, we log it and continue to the next one.
                    self.logger.error(f"Failed to process video {video_id} from channel {channel_identifier}: {e}")
                    failed_extractions += 1
                    continue
            
            # Sort by publish date (newest first)
            all_posts.sort(key=lambda p: p.get('date', datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
            
            self.logger.info(f"Channel processing complete: {successful_extractions} successful, {failed_extractions} failed extractions")
            return all_posts
            
        except Exception as e:
            self.logger.error(f"ERROR: Failed to process channel {channel_identifier} - Reason: Critical error: {str(e)}")
            return []
    
    async def fetch_posts_by_timeframe(self, sources: List[str], days: int) -> List[Dict[str, Any]]:
        """
        Fetches YouTube transcripts from multiple sources within a specific timeframe.
        
        HARDENED: Individual source failures do not affect other sources.
        
        Args:
            sources: List of YouTube video URLs or channel identifiers
            days: Number of days to look back (0 for "today only")
            
        Returns:
            List of posts with transcripts in unified format, sorted chronologically
        """
        if days == 0:
            self.logger.info("Starting 'End of Day' YouTube intelligence briefing for today...")
            cutoff_date = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            self.logger.info(f"Starting Historical YouTube intelligence briefing for the last {days} days...")
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=days)
        
        all_posts = []
        successful_sources = 0
        failed_sources = 0
        
        for source in sources:
            self.logger.info(f"Processing YouTube source: {source}")
            
            try:
                # Fetch posts from this source (use high limit for timeframe filtering)
                source_posts = await self.fetch_posts(source, 50)  # Get more videos to filter by date
                
                # Filter by timeframe
                filtered_posts = [
                    post for post in source_posts
                    if post.get('date') and post['date'] >= cutoff_date
                ]
                
                if filtered_posts:
                    all_posts.extend(filtered_posts)
                    successful_sources += 1
                    self.logger.info(f"Successfully collected {len(filtered_posts)} transcripts from {source}")
                else:
                    self.logger.warning(f"No transcripts found in timeframe for {source}")
                    
            except Exception as e:
                self.logger.error(f"ERROR: Failed to process YouTube source {source} - Reason: {str(e)}")
                failed_sources += 1
                continue
        
        self.logger.info(f"Multi-source YouTube processing complete: {successful_sources} successful, {failed_sources} failed sources")
        
        # Sort chronologically
        try:
            return sorted(all_posts, key=lambda p: p.get('date', datetime.min.replace(tzinfo=timezone.utc)))
        except Exception as e:
            self.logger.error(f"Error sorting YouTube posts chronologically: {e}")
            return all_posts
    
    async def fetch_playlist_transcripts(self, playlist_url: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        BONUS FEATURE: Fetches transcripts from all videos in a YouTube playlist.
        
        Args:
            playlist_url: YouTube playlist URL
            limit: Maximum number of videos to process
            
        Returns:
            List of posts with transcripts in unified format
        """
        try:
            self.logger.info(f"Extracting intelligence from playlist {playlist_url}...")
            
            # Get videos from playlist using yt-dlp
            video_ids = self._get_playlist_videos_ytdlp(playlist_url, limit)
            
            if not video_ids:
                self.logger.error(f"No videos found in playlist: {playlist_url}")
                return []
            
            # Process each video
            all_posts = []
            for video_id in video_ids:
                video_posts = await self._fetch_single_video_transcript(video_id, playlist_url)
                if video_posts:
                    # Update source_id to indicate playlist
                    video_posts[0]['source_id'] = f"playlist:{playlist_url}"
                    all_posts.extend(video_posts)
            
            self.logger.info(f"Successfully extracted {len(all_posts)} transcripts from playlist")
            return all_posts
            
        except Exception as e:
            self.logger.error(f"ERROR: Failed to process playlist {playlist_url} - Reason: {str(e)}")
            return []
    
    async def search_video_transcripts(self, search_query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        BONUS FEATURE: Searches for videos and extracts their transcripts.
        
        Args:
            search_query: YouTube search query
            limit: Maximum number of videos to process
            
        Returns:
            List of posts with transcripts in unified format
        """
        try:
            self.logger.info(f"Searching for videos matching: '{search_query}'")
            
            # Search for videos using yt-dlp
            video_ids = self._search_videos_ytdlp(search_query, limit)
            
            if not video_ids:
                self.logger.warning(f"No videos found for search query: {search_query}")
                return []
            
            # Process each video
            all_posts = []
            for video_id in video_ids:
                video_posts = await self._fetch_single_video_transcript(video_id, search_query)
                if video_posts:
                    # Update source_id to indicate search
                    video_posts[0]['source_id'] = f"search:{search_query}"
                    all_posts.extend(video_posts)
            
            self.logger.info(f"Successfully extracted {len(all_posts)} transcripts from search '{search_query}'")
            return all_posts
            
        except Exception as e:
            self.logger.error(f"ERROR: Failed to search for videos with query '{search_query}' - Reason: {str(e)}")
            return [] 
