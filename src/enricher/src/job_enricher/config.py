"""Runtime configuration (pydantic-settings).

Env is mapped implicitly (field_name -> FIELD_NAME), mirroring JVN's config.py.
The laptop only ever makes OUTBOUND calls to JVN (pull model), so the required
secrets are the JVN base URL + the internal key. HMAC/tunnel settings are only
needed for the OPTIONAL inbound edge (server.py); they default off.
"""

from __future__ import annotations

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- JVN pull target (required for real runs) ---
    jvn_base_url: str = "http://localhost:8080"   # JVN_BASE_URL (Railway backend URL)
    internal_api_key: str | None = None           # INTERNAL_API_KEY (shared with JVN)

    # --- pull cadence / batch ---
    pull_limit: int = Field(default=60, gt=0, le=500)   # jobs claimed per tick
    writeback_batch_size: int = Field(default=50, gt=0, le=200)
    http_timeout_seconds: float = Field(default=30.0, gt=0)

    # --- optional inbound edge (server.py) — OFF by default in pull mode ---
    edge_enabled: bool = False                    # EDGE_ENABLED
    edge_port: int = Field(default=8787, gt=0)    # EDGE_PORT
    edge_hmac_secret: str | None = None           # EDGE_HMAC_SECRET
    tunnel_name: str | None = None                # TUNNEL_NAME (e.g. "jobnorm")

    # --- local dashboard (separate app; defaults to 127.0.0.1, and a non-loopback
    #     --host is refused unless --allow-remote — it edits knobs unauthenticated) ---
    dashboard_port: int = Field(default=8788, gt=0)   # DASHBOARD_PORT

    # --- local open-model engines (opencode/ollama) — process-level infra, not a
    #     per-tick dial. The Ollama tag itself is the `opencode:model` runtime knob. ---
    ollama_base_url: str = "http://localhost:11434"   # OLLAMA_BASE_URL
    opencode_binary: str = "opencode"                 # OPENCODE_BINARY (PATH name or abs path)
    claude_binary: str = "claude"                     # CLAUDE_BINARY (headless `claude -p`)
    engine_timeout_seconds: float = Field(default=300.0, gt=0)  # ENGINE_TIMEOUT_SECONDS

    @model_validator(mode="after")
    def _validate_edge(self) -> "Settings":
        if self.edge_enabled and not self.edge_hmac_secret:
            raise ValueError("edge_enabled=True requires edge_hmac_secret")
        return self

    model_config = {"env_file": (".env", ".env.local"), "extra": "ignore"}


settings = Settings()
