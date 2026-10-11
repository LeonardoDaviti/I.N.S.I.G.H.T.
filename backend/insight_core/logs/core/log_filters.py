import logging

class OperationFilter(logging.Filter):
    """Filter for operation-specific logs."""

    def __init__(self, operation_type):
        super().__init__()
        self.operation_type = operation_type.lower()

    def filter(self, record):
        message = record.getMessage().lower()
        logger_name = record.name.lower()
        return self.operation_type in message or self.operation_type in logger_name
    
class ErrorOnlyFilter(logging.Filter):
    """Filter to only allow ERROR and CRITICAL messages."""
    
    def filter(self, record):
        return record.levelno >= logging.ERROR
    
class PlatformFilter(logging.Filter):
    """Filter for specific platform logs (telegram, rss, youtube, reddit)."""
    
    def __init__(self, platform):
        super().__init__()
        self.platform = platform.lower()
    
    def filter(self, record):
        # Check if the message is related to the specific platform
        logger_name = record.name.lower()
        module_name = record.module.lower() 
        return self.platform in logger_name or self.platform in module_name