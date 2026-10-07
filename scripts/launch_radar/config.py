"""Environment configuration for the loop.

Secrets are only ever checked for presence. A missing variable is reported by
its NAME only, never by value.
"""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

DEFAULT_STATE_DIR = "~/Library/Application Support/jvn-launch-radar"


class ConfigError(Exception):
    """A required environment variable is missing or malformed. ``str()`` is the variable name."""

    def __init__(self, name: str, problem: str = "is not set") -> None:
        super().__init__(name)
        self.name = name
        self.problem = problem

    def message(self) -> str:
        return f"{self.name} {self.problem}"


@dataclass(frozen=True)
class Config:
    backend_url: str
    internal_api_key: str | None
    state_dir: Path


def is_loopback_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def state_dir_from(env: Mapping[str, str]) -> Path:
    return Path(env.get("LAUNCH_RADAR_STATE_DIR") or DEFAULT_STATE_DIR).expanduser()


def load_config(env: Mapping[str, str] | None = None, *, need_parallel: bool) -> Config:
    env = os.environ if env is None else env
    backend_url = (env.get("BACKEND_URL") or "").strip().rstrip("/")
    if not backend_url:
        raise ConfigError("BACKEND_URL")
    scheme = urlparse(backend_url).scheme
    if scheme not in ("http", "https"):
        raise ConfigError("BACKEND_URL", "must be an http(s) URL")
    if scheme != "https" and not is_loopback_url(backend_url):
        # X-Internal-Key rides on every request: never send it in cleartext off this machine.
        raise ConfigError("BACKEND_URL", "must be https unless loopback")
    key = env.get("INTERNAL_API_KEY") or None
    if key is None and not is_loopback_url(backend_url):
        raise ConfigError("INTERNAL_API_KEY", "is not set (required unless BACKEND_URL is a loopback URL)")
    if need_parallel and not env.get("PARALLEL_API_KEY"):
        raise ConfigError("PARALLEL_API_KEY")
    return Config(backend_url=backend_url, internal_api_key=key, state_dir=state_dir_from(env))
