"""
Tests for source settings functionality.

Tests:
- Get platform defaults
- Get source settings (merged with platform defaults)
- Update source settings
- Update platform defaults
- Settings merging logic
"""
import os
import pytest
import psycopg
from insight_core.db.repo_sources import SourcesRepository
from insight_core.services.sources_service import SourcesService

# Use test database or fallback to dev database
DATABASE_URL = os.getenv('TEST_DATABASE_URL') or os.getenv('DATABASE_URL')

if not DATABASE_URL:
    pytest.skip("No DATABASE_URL found, skipping database tests", allow_module_level=True)


class TestSourceSettings:
    """Test source settings CRUD operations."""
    
    def setup_method(self):
        """Initialize repository before each test."""
        self.repo = SourcesRepository(DATABASE_URL)
        self.service = SourcesService(DATABASE_URL)
        
        # Create a test source
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Insert test source
                cur.execute("""
                    INSERT INTO sources (platform, handle_or_url, enabled, settings)
                    VALUES ('rss', 'https://test-settings.example.com/feed', TRUE, '{}')
                    RETURNING id
                """)
                self.test_source_id = str(cur.fetchone()[0])
                conn.commit()
    
    def teardown_method(self):
        """Clean up after each test."""
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Delete test source
                cur.execute("DELETE FROM sources WHERE id = %s", (self.test_source_id,))
                conn.commit()
    
    def test_get_source_settings_empty(self):
        """Test getting settings for source with no custom settings (should get hardcoded defaults)."""
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                settings = self.repo.get_source_settings(cur, self.test_source_id)
                
                assert isinstance(settings, dict)
                # Should have at least the default fields
                assert 'fetch_delay_seconds' in settings or 'priority' in settings
    
    def test_update_source_settings(self):
        """Test updating source settings."""
        new_settings = {
            "display_name": "Test Feed",
            "fetch_delay_seconds": 10,
            "priority": 5,
            "max_posts_per_fetch": 100
        }
        
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                success = self.repo.update_source_settings(cur, self.test_source_id, new_settings)
                conn.commit()
                
                assert success is True
                
                # Verify settings were updated
                settings = self.repo.get_source_settings(cur, self.test_source_id)
                assert settings["display_name"] == "Test Feed"
                assert settings["fetch_delay_seconds"] == 10
                assert settings["priority"] == 5
                assert settings["max_posts_per_fetch"] == 100
    
    def test_settings_override_defaults(self):
        """Test that source settings override hardcoded defaults."""
        # Set custom priority
        custom_settings = {"priority": 1}
        
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                self.repo.update_source_settings(cur, self.test_source_id, custom_settings)
                conn.commit()
                
                # Get merged settings
                settings = self.repo.get_source_settings(cur, self.test_source_id)
                
                # Custom priority should override default
                assert settings["priority"] == 1
                # Other fields should come from platform defaults
                assert "fetch_delay_seconds" in settings
    
    def test_service_update_validation(self):
        """Test that service validates settings before updating."""
        settings = {
            "display_name": "Valid Feed",
            "fetch_delay_seconds": "5",  # String should be converted to int
            "invalid_field": "should be ignored"  # Invalid field should be filtered
        }
        
        result = self.service.update_source_settings(self.test_source_id, settings)
        
        assert result["source_id"] == self.test_source_id
        assert result["settings"]["display_name"] == "Valid Feed"
        assert result["settings"]["fetch_delay_seconds"] == 5
        assert "invalid_field" not in result["settings"]
    
    def test_get_all_sources_with_settings(self):
        """Test getting all sources with their merged settings."""
        sources = self.service.get_all_sources_with_settings()
        
        assert isinstance(sources, list)
        # Find our test source
        test_source = next((s for s in sources if s["id"] == self.test_source_id), None)
        assert test_source is not None
        assert "settings" in test_source
        assert isinstance(test_source["settings"], dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

