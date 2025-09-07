import logging
import logging.handlers
import os
from .log_formatters import LogFormatters
from .log_filters import *

class LoggerConfig:
    """Configuration for logging system."""

    def __init__(self, debug_mode=False):
        self.debug_mode = debug_mode
        self.log_level = logging.DEBUG if debug_mode else logging.INFO
        self._ensure_log_directories()

    def _ensure_log_directories(self):
        """Create log directories if they don't exist."""
        directories = [
            "logs/core",
            "logs/connectors",
            "logs/operations"
        ]
        
        for directory in directories:
            os.makedirs(directory, exist_ok=True)

    def _setup_logging(self):

        # Clear any existing handlers
        logging.getLogger().handlers.clear()

        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(self.log_level)

        # Set up different types of handlers
        self._setup_console_handler()
        self._setup_application_handler()
        self._setup_error_handler()
        self._setup_connector_handlers()
        self._setup_operation_handlers()
        
        # Configure specific loggers
        self._configure_component_loggers()
        
        logging.info("Logging system initialized successfully")

    def _setup_console_handler(self):
        """Set up console output handler with Unicode support."""
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO if not self.debug_mode else logging.WARNING)
        
        # Create a formatter that avoids emoji characters
        console_formatter = logging.Formatter(
            fmt='%(levelname)s - %(name)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        
        # Add to root logger
        logging.getLogger().addHandler(console_handler)

    def _setup_application_handler(self):
        """Set up main application log handler."""
        app_handler = logging.FileHandler('logs/core/application.log')
        app_handler.setLevel(self.log_level)
        app_handler.setFormatter(LogFormatters.get_file_formatter())
        
        # Add to root logger
        logging.getLogger().addHandler(app_handler)
    
    def _setup_error_handler(self):
        """Set up error-only log handler."""
        error_handler = logging.FileHandler('logs/core/errors.log')
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(LogFormatters.get_error_formatter())
        error_handler.addFilter(ErrorOnlyFilter())
        
        # Add to root logger
        logging.getLogger().addHandler(error_handler)
    
    def _setup_connector_handlers(self):
        """Set up individual handlers for each connector."""
        connectors = ['telegram', 'rss', 'youtube', 'reddit']
        
        for connector in connectors:
            handler = logging.FileHandler(f'logs/connectors/{connector}.log')
            handler.setLevel(self.log_level)
            handler.setFormatter(LogFormatters.get_file_formatter())
            handler.addFilter(PlatformFilter(connector))
            
            # Add to root logger
            logging.getLogger().addHandler(handler)
    
    def _setup_operation_handlers(self):
        """Set up handlers for different operation types."""
        operations = ['automated', 'interactive', 'recovery']
        
        for operation in operations:
            handler = logging.FileHandler(f'logs/operations/{operation}.log')
            handler.setLevel(self.log_level)
            handler.setFormatter(LogFormatters.get_file_formatter())
            handler.addFilter(OperationFilter(operation))
            
            # Add to root logger  
            logging.getLogger().addHandler(handler)

    def _configure_component_loggers(self):
        """Configure loggers for specific components."""
        # Connector loggers
        for connector in ['telegram', 'rss', 'youtube', 'reddit']:
            logger = logging.getLogger(f'{connector}_connector')
            logger.setLevel(self.log_level)
        
        # Operation loggers
        for operation in ['automated', 'interactive', 'recovery']:
            logger = logging.getLogger(f'{operation}_operation')
            logger.setLevel(self.log_level)
        
        # Core loggers
        core_components = ['config_manager', 'async_gatherer', 'insight_operator']
        for component in core_components:
            logger = logging.getLogger(component)
            logger.setLevel(self.log_level)

def setup_logging(debug_mode=False):
    """Convenience function to set up logging."""
    config = LoggerConfig(debug_mode=debug_mode)
    config._setup_logging()
    return config

def get_connector_logger(connector_name):
    """Get a logger for a specific connector."""
    return logging.getLogger(f'{connector_name}_connector')

def get_operation_logger(operation_type):
    """Get a logger for a specific operation type."""
    return logging.getLogger(f'{operation_type}_operation')

def get_component_logger(component_name):
    """Get a logger for a specific component."""
    return logging.getLogger(component_name)
