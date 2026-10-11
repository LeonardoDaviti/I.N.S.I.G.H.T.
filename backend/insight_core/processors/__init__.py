"""
INSIGHT Processors - Modular Processing System
============================================

Main processing modules for INSIGHT platform
- ai: AI processing modules
"""

from .ai.gemini_processor import GeminiProcessor

__all__ = [
    'GeminiProcessor'
]