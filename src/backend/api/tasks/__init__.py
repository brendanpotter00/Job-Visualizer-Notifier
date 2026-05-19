"""Procrastinate task package."""

from .procrastinate_app import procrastinate_app

# Side-effect imports: register tasks on the app singleton.
from . import fetch_greenhouse_company  # noqa: F401  (registers task on app)
from . import enqueue_greenhouse_fan_out  # noqa: F401  (registers periodic task on app)
from . import fetch_ashby_company  # noqa: F401  (registers task on app)
from . import enqueue_ashby_fan_out  # noqa: F401  (registers periodic task on app)
from . import fetch_eightfold_company  # noqa: F401  (registers task on app)
# enqueue_eightfold_fan_out is registered in Unit 5 (this file's next edit).

__all__ = ["procrastinate_app"]
