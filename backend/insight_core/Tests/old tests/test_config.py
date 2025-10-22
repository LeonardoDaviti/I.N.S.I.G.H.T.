"""
Test Configuration for I.N.S.I.G.H.T. Mark II Testing Suite
"""

class TestConfiguration:
    """Configuration settings for the testing suite"""
    
    # Rate limiting and performance thresholds
    RATE_LIMIT_THRESHOLD = 30.0  # seconds - if test takes longer, consider rate limiting
    INTER_TEST_DELAY = 3.0  # seconds between tests
    TELEGRAM_REQUEST_DELAY = 2.0  # seconds between Telegram requests
    
    # Expected performance benchmarks
    EXPECTED_POSTS_PER_SECOND = {
        'telegram': 5.0,
        'rss': 10.0,
        'youtube': 1.0,  # Slower due to transcript processing
        'reddit': 3.0
    }
    
    # Output format validation
    REQUIRED_OUTPUT_FORMATS = ['Console', 'HTML', 'JSON']
    
    # Test data limits
    MAX_POSTS_PER_TEST = 100
    MIN_POSTS_FOR_SUCCESS = 1
    
    # File paths
    TEST_OUTPUT_DIR = "Tests/output"
    TEST_LOGS_DIR = "Tests/logs"
    TEST_REPORTS_DIR = "Tests/reports"