"""Procrastinate task package.

Tasks are registered on a single ``procrastinate.App`` instance defined in
``procrastinate_app``. Importing this package re-exports the app object and
**also** imports every task module so the ``@procrastinate_app.task``
decorators run before the worker starts.
"""

from .procrastinate_app import procrastinate_app

# Side-effect imports: register tasks on the app singleton.
from . import fetch_greenhouse_company  # noqa: F401  (registers task on app)

__all__ = ["procrastinate_app"]
