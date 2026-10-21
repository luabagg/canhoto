"""Local page. Serves static files and an API origin. Does not call the ledger."""

from canhoto.page.app import create_page

__all__ = ["create_page"]
