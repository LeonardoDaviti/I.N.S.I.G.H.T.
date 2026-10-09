"""Legacy connector package: re-exports only.

Mark IX B5 deleted the RSS, Reddit and YouTube connectors, the tool registry and the
connector discovery (every fetch goes through insight_core.ingestion). TelegramConnector
stays as the basis for B8, which moves its logic into ingestion/kinds/telegram_mtproto.py
and deletes this package. No ingestion path imports it.
"""

from .base_connector import BaseConnector
from .telegram_connector import TelegramConnector

__all__ = ["BaseConnector", "TelegramConnector"]
