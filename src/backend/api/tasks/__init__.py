"""Procrastinate task package."""

from .procrastinate_app import procrastinate_app

# Side-effect imports: register tasks on the app singleton.
from . import fetch_greenhouse_company  # noqa: F401  (registers task on app)
from . import enqueue_greenhouse_fan_out  # noqa: F401  (registers periodic task on app)
from . import fetch_ashby_company  # noqa: F401  (registers task on app)
from . import enqueue_ashby_fan_out  # noqa: F401  (registers periodic task on app)
from . import fetch_lever_company  # noqa: F401  (registers task on app)
from . import enqueue_lever_fan_out  # noqa: F401  (registers periodic task on app)
from . import fetch_gem_company  # noqa: F401  (registers task on app)
from . import enqueue_gem_fan_out  # noqa: F401  (registers periodic task on app)
from . import fetch_workday_company  # noqa: F401  (registers task on app)
from . import enqueue_workday_fan_out  # noqa: F401  (registers periodic task on app)

__all__ = ["procrastinate_app"]
