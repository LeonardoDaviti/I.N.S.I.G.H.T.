import fcntl
import logging
import logging.handlers
import os
from .log_formatters import LogFormatters
from .log_filters import *


class SharedRotatingFileHandler(logging.handlers.WatchedFileHandler):
    """A log file many processes append to, rotated by size by whichever of them finds it full.

    Every process of both containers writes these files (RotatingFileHandler let each rotate the file under the
    others). Each write goes to the file now at the path (WatchedFileHandler, O_APPEND), and the rotation runs under
    an flock on `<path>.lock` after re-reading the size, so it happens once. The Ingestion tab's log view and the API
    watchdog read these files."""

    def __init__(self, filename, maxBytes=0, backupCount=0, encoding=None, delay=False):
        super().__init__(filename, mode="a", encoding=encoding, delay=delay)
        self.maxBytes, self.backupCount = maxBytes, backupCount

    def emit(self, record):
        try:
            if self.maxBytes > 0 and self.stream is not None and os.fstat(self.stream.fileno()).st_size >= self.maxBytes:
                self._rotate()
        except Exception:   # noqa: BLE001 - logging never raises into the caller
            self.handleError(record)
        super().emit(record)

    def _rotate(self) -> None:
        path = self.baseFilename
        with open(path + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if os.path.exists(path) and os.stat(path).st_size >= self.maxBytes:   # not rotated meanwhile
                    if self.backupCount > 0:
                        for i in range(self.backupCount - 1, 0, -1):
                            if os.path.exists(f"{path}.{i}"):
                                os.replace(f"{path}.{i}", f"{path}.{i + 1}")
                        os.replace(path, f"{path}.1")
                    else:
                        open(path, "w").close()
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
        self.reopenIfNeeded()

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

        logging.getLogger().handlers.clear()

        root_logger = logging.getLogger()
        root_logger.setLevel(self.log_level)

        self._setup_console_handler()
        self._setup_application_handler()
        self._setup_error_handler()
        self._setup_connector_handlers()
        self._setup_operation_handlers()
        
        logging.info("Logging system initialized successfully")

    def _setup_console_handler(self):
        """Set up console output handler with Unicode support."""
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO if not self.debug_mode else logging.WARNING)

        console_formatter = logging.Formatter(
            fmt='%(levelname)s - %(name)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(console_formatter)
        logging.getLogger().addHandler(console_handler)

    def _setup_application_handler(self):
        """Set up main application log handler."""
        app_handler = SharedRotatingFileHandler(
            'logs/core/application.log', maxBytes=10_000_000, backupCount=3)
        app_handler.setLevel(self.log_level)
        app_handler.setFormatter(LogFormatters.get_file_formatter())
        logging.getLogger().addHandler(app_handler)
    
    def _setup_error_handler(self):
        """Set up error-only log handler."""
        error_handler = SharedRotatingFileHandler(
            'logs/core/errors.log', maxBytes=10_000_000, backupCount=3)
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(LogFormatters.get_error_formatter())
        error_handler.addFilter(ErrorOnlyFilter())
        logging.getLogger().addHandler(error_handler)
    
    def _setup_connector_handlers(self):
        """Set up individual handlers for each connector."""
        connectors = ['telegram', 'rss', 'youtube', 'reddit']
        
        for connector in connectors:
            handler = SharedRotatingFileHandler(
                f'logs/connectors/{connector}.log', maxBytes=10_000_000, backupCount=3)
            handler.setLevel(self.log_level)
            handler.setFormatter(LogFormatters.get_file_formatter())
            handler.addFilter(PlatformFilter(connector))
            logging.getLogger().addHandler(handler)
    
    def _setup_operation_handlers(self):
        """Set up handlers for different operation types."""
        operations = ['automated', 'interactive', 'recovery']
        
        for operation in operations:
            handler = SharedRotatingFileHandler(
                f'logs/operations/{operation}.log', maxBytes=10_000_000, backupCount=3)
            handler.setLevel(self.log_level)
            handler.setFormatter(LogFormatters.get_file_formatter())
            handler.addFilter(OperationFilter(operation))
            logging.getLogger().addHandler(handler)

def setup_logging(debug_mode=False):
    """Convenience function to set up logging."""
    config = LoggerConfig(debug_mode=debug_mode)
    config._setup_logging()
    return config

def get_component_logger(component_name):
    """Get a logger for a specific component."""
    return logging.getLogger(component_name)
