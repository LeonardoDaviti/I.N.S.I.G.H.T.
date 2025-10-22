"""
Test Cases Definition for I.N.S.I.G.H.T. Mark II Testing Suite
"""

class TestCases:
    """Defines all test cases for the I.N.S.I.G.H.T. platform"""
    
    def __init__(self):
        self.telegram_channels = ['seeallochnaya', 'durov', 'denissexy', 'ai_newz']
        self.rss_feeds = [
            'https://simonwillison.net/atom/everything/',
            'https://www.seangoedecke.com/rss.xml',
            'https://toska.bearblog.dev/feed/?type=rss'
        ]
        self.youtube_videos = [
            'https://youtu.be/JIYtAnlzMfw',
            'https://youtu.be/CQywdSdi5iA'
        ]
        self.reddit_subreddits = ['PixelArtTutorials', 'LocalLLaMA']
    
    def get_all_tests(self):
        """Return all test cases"""
        tests = []
        
        # Mission 1: Telegram Deep Scan Tests
        tests.extend(self._get_telegram_deep_scan_tests())
        
        # Mission 2: Historical Briefing Tests
        tests.extend(self._get_telegram_briefing_tests())
        
        # Mission 3: End of Day Report Tests
        tests.extend(self._get_telegram_eod_tests())
        
        # Mission 4: RSS Analysis Tests
        tests.extend(self._get_rss_analysis_tests())
        
        # Mission 5: RSS Single Feed Tests
        tests.extend(self._get_rss_single_tests())
        
        # Mission 6: RSS Multi-Feed Tests
        tests.extend(self._get_rss_multi_tests())
        
        # Mission 7: YouTube Transcript Tests
        tests.extend(self._get_youtube_transcript_tests())
        
        # Mission 8: YouTube Channel Tests
        tests.extend(self._get_youtube_channel_tests())
        
        # Mission 9: YouTube Playlist Tests
        tests.extend(self._get_youtube_playlist_tests())
        
        # Mission 12: Reddit Post Tests
        tests.extend(self._get_reddit_post_tests())
        
        # Mission 13: Reddit Subreddit Tests
        tests.extend(self._get_reddit_subreddit_tests())
        
        # Mission 14: Reddit Multi-Source Tests
        tests.extend(self._get_reddit_multi_tests())
        
        return tests
    
    def _get_telegram_deep_scan_tests(self):
        """Telegram Deep Scan test cases"""
        return [
            {
                'name': 'Telegram Deep Scan - seeallochnaya (5 posts)',
                'mission': 'telegram_deep_scan',
                'data': {'channel': 'seeallochnaya', 'limit': 5},
                'expected': 'Should fetch 5 recent posts, test all output formats',
                'connectors_required': ['telegram']
            },
            {
                'name': 'Telegram Deep Scan - durov (5 posts)',
                'mission': 'telegram_deep_scan',
                'data': {'channel': 'durov', 'limit': 5},
                'expected': 'Should fetch 5 recent posts, test all output formats',
                'connectors_required': ['telegram']
            },
            {
                'name': 'Telegram Deep Scan - denissexy (10 posts)',
                'mission': 'telegram_deep_scan',
                'data': {'channel': 'denissexy', 'limit': 10},
                'expected': 'Should fetch 10 recent posts, test all output formats',
                'connectors_required': ['telegram']
            },
            {
                'name': 'Telegram Rate Limiting Test - ai_newz (40 posts)',
                'mission': 'telegram_deep_scan',
                'data': {'channel': 'ai_newz', 'limit': 40},
                'expected': 'Should implement automatic delays, measure time, avoid rate limiting',
                'connectors_required': ['telegram'],
                'performance_test': True
            },
            {
                'name': 'Telegram Rate Limiting Test - denissexy (100 posts)',
                'mission': 'telegram_deep_scan',
                'data': {'channel': 'denissexy', 'limit': 100},
                'expected': 'Should implement automatic delays, measure time, avoid rate limiting',
                'connectors_required': ['telegram'],
                'performance_test': True
            }
        ]
    
    def _get_telegram_briefing_tests(self):
        """Telegram Historical Briefing test cases"""
        return [
            {
                'name': 'Telegram Briefing - All channels (4 days)',
                'mission': 'telegram_briefing',
                'data': {'channels': self.telegram_channels, 'days': 4},
                'expected': 'Should fetch posts from all channels within 4-day timeframe',
                'connectors_required': ['telegram']
            },
            {
                'name': 'Telegram Briefing - All channels (10 days)',
                'mission': 'telegram_briefing',
                'data': {'channels': self.telegram_channels, 'days': 10},
                'expected': 'Should fetch posts from all channels within 10-day timeframe',
                'connectors_required': ['telegram']
            },
            {
                'name': 'Telegram Briefing - All channels (20 days)',
                'mission': 'telegram_briefing',
                'data': {'channels': self.telegram_channels, 'days': 20},
                'expected': 'Should fetch posts from all channels within 20-day timeframe',
                'connectors_required': ['telegram']
            }
        ]
    
    def _get_telegram_eod_tests(self):
        """Telegram End of Day Report test cases"""
        return [
            {
                'name': 'Telegram End of Day - All channels',
                'mission': 'telegram_eod',
                'data': {'channels': self.telegram_channels},
                'expected': 'Should fetch recent posts from all specified channels',
                'connectors_required': ['telegram']
            }
        ]
    
    def _get_rss_analysis_tests(self):
        """RSS Analysis test cases"""
        return [
            {
                'name': f'RSS Analysis - {feed.split("/")[-2] if "/" in feed else feed}',
                'mission': 'rss_analysis',
                'data': {'feed_url': feed},
                'expected': 'Should return feed metadata, entry counts, categories',
                'connectors_required': ['rss']
            }
            for feed in self.rss_feeds
        ]
    
    def _get_rss_single_tests(self):
        """RSS Single Feed test cases"""
        return [
            {
                'name': f'RSS Single Feed - {feed.split("/")[-2] if "/" in feed else feed} (20 posts)',
                'mission': 'rss_single',
                'data': {'feed_url': feed, 'limit': 20},
                'expected': 'Should fetch 20 posts, handle different RSS formats',
                'connectors_required': ['rss']
            }
            for feed in self.rss_feeds
        ]
    
    def _get_rss_multi_tests(self):
        """RSS Multi-Feed test cases"""
        return [
            {
                'name': 'RSS Multi-Feed - All feeds (20 posts each)',
                'mission': 'rss_multi',
                'data': {'feed_urls': self.rss_feeds, 'limit_per_feed': 20},
                'expected': 'Should fetch 20 posts per feed, combine into unified timeline',
                'connectors_required': ['rss']
            }
        ]
    
    def _get_youtube_transcript_tests(self):
        """YouTube Transcript test cases"""
        return [
            {
                'name': f'YouTube Transcript - {video.split("/")[-1]}',
                'mission': 'youtube_transcript',
                'data': {'video_url': video},
                'expected': 'Should extract video transcript in multiple languages',
                'connectors_required': ['youtube']
            }
            for video in self.youtube_videos
        ]
    
    def _get_youtube_channel_tests(self):
        """YouTube Channel test cases"""
        return [
            {
                'name': 'YouTube Channel - UCrDwWp7EBBv4NwvScIpBDOA (5 videos)',
                'mission': 'youtube_channel',
                'data': {'channel_id': 'UCrDwWp7EBBv4NwvScIpBDOA', 'limit': 5},
                'expected': 'Should process 5 latest videos, extract metadata and transcripts',
                'connectors_required': ['youtube']
            }
        ]
    
    def _get_youtube_playlist_tests(self):
        """YouTube Playlist test cases"""
        return [
            {
                'name': 'YouTube Playlist - PLf2m23nhTg1NjL3-jL3s0qZCYzO07ZQPv',
                'mission': 'youtube_playlist',
                'data': {
                    'playlist_url': 'https://youtube.com/playlist?list=PLf2m23nhTg1NjL3-jL3s0qZCYzO07ZQPv',
                    'limit': 5
                },
                'expected': 'Should process playlist videos, extract transcripts',
                'connectors_required': ['youtube']
            }
        ]
    
    def _get_reddit_post_tests(self):
        """Reddit Post test cases"""
        return [
            {
                'name': 'Reddit Post Analysis - PixelArtTutorials post with comments',
                'mission': 'reddit_post',
                'data': {
                    'post_url': 'https://www.reddit.com/r/PixelArtTutorials/comments/1c2vhu6/how_do_i_start_my_journey_in_pixel_art/'
                },
                'expected': 'Should fetch post with all comments, proper threading',
                'connectors_required': ['reddit']
            }
        ]
    
    def _get_reddit_subreddit_tests(self):
        """Reddit Subreddit test cases"""
        return [
            {
                'name': 'Reddit Subreddit - PixelArtTutorials (5 posts with comments)',
                'mission': 'reddit_subreddit',
                'data': {'subreddit': 'PixelArtTutorials', 'limit': 5},
                'expected': 'Should fetch 5 posts with comments, handle pagination',
                'connectors_required': ['reddit']
            }
        ]
    
    def _get_reddit_multi_tests(self):
        """Reddit Multi-Source test cases"""
        return [
            {
                'name': 'Reddit Multi-Source - PixelArtTutorials + LocalLLaMA',
                'mission': 'reddit_multi',
                'data': {'subreddits': self.reddit_subreddits, 'limit_per_subreddit': 5},
                'expected': 'Should fetch posts from multiple subreddits, combine results',
                'connectors_required': ['reddit']
            }
        ]
    
    def filter_tests_by_connectors(self, tests, available_connectors):
        """Filter tests based on available connectors"""
        filtered_tests = []
        
        for test in tests:
            required = test.get('connectors_required', [])
            if all(connector in available_connectors for connector in required):
                filtered_tests.append(test)
            else:
                missing = [c for c in required if c not in available_connectors]
                print(f"⏭️  Skipping test '{test['name']}' - missing connectors: {missing}")
        
        return filtered_tests