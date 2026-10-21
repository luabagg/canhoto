"""Local JSON API. Calls ``canhoto.service`` only. Does not serve the page."""

from canhoto.api.app import create_api

__all__ = ["create_api"]
