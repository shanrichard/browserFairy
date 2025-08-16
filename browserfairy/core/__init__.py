"""Core functionality for Chrome DevTools Protocol connection."""

from .connector import ChromeConnector, ChromeConnectionError
from .chrome_instance import ChromeInstanceManager, ChromeInstanceError, ChromeStartupError

__all__ = [
    'ChromeConnector',
    'ChromeConnectionError', 
    'ChromeInstanceManager',
    'ChromeInstanceError',
    'ChromeStartupError'
]