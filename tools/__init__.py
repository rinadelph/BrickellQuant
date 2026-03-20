"""
BrickellQuant Tools
===================
Agent-first financial data library.

Quick start:
    from tools.sec import SECClient
    from tools.market import MarketClient
    from tools.news import NewsClient
    from tools.Yodel import YodelClient

See AGENT_README.md for full documentation.
"""

from tools.sec import SECClient
from tools.market import MarketClient
from tools.news import NewsClient
from tools.Yodel import YodelClient

__version__ = "0.1.0"
__all__ = ["SECClient", "MarketClient", "NewsClient", "YodelClient"]
