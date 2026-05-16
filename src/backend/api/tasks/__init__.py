"""Procrastinate task package.

Tasks are registered on a single ``procrastinate.App`` instance defined in
``procrastinate_app``. Importing this package re-exports the app object so
callers don't have to remember the submodule path.
"""

from .procrastinate_app import procrastinate_app

__all__ = ["procrastinate_app"]
