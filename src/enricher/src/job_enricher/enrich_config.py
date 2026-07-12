"""Meta-backed runtime knobs, read fresh each tick.

Port of job-watcher's match_config pattern: tolerate bad/missing values (return
the default, never crash a tick); write helpers validate/clamp then persist.
These are the dials the /enrich-tick command reads at Step 0.6 and the
CLI subcommands expose (model, batch, fan-out, judge on/off + floor).
"""

from __future__ import annotations

from typing import Protocol


class _MetaStore(Protocol):
    def get_meta(self, key: str) -> str | None: ...
    def set_meta(self, key: str, value: str, ts: str | None = ...) -> None: ...
    def delete_meta(self, key: str) -> None: ...


# classify model
CLASSIFY_MODEL_DEFAULT = "haiku"
CLASSIFY_MODEL_META_KEY = "classify:model"
MODEL_CHOICES: tuple[str, ...] = ("haiku", "sonnet", "opus")

# classify batch (jobs per sub-agent) + fan-out (parallel agents per wave)
CLASSIFY_BATCH_DEFAULT = 3
CLASSIFY_BATCH_META_KEY = "classify:batch_size"
CLASSIFY_BATCH_BOUNDS = (1, 10)

CLASSIFY_FANOUT_DEFAULT = 12
CLASSIFY_FANOUT_META_KEY = "classify:fan_out"
CLASSIFY_FANOUT_BOUNDS = (1, 20)

# judge — Sonnet, globally toggleable. Default scope is LOW-CONFIDENCE rows only:
# the measured lift of judging every row was NEGATIVE (all of the judge's level
# changes on confident rows moved away from gold), so the judge concentrates on
# rows classify itself was unsure about (confidence below the ceiling), rows
# whose facets were nulled at ingest, and rows already flagged needs_human.
JUDGE_ENABLED_DEFAULT = True
JUDGE_ENABLED_META_KEY = "judge:enabled"

JUDGE_MODEL_DEFAULT = "sonnet"
JUDGE_MODEL_META_KEY = "judge:model"

# below this judge self-confidence, flag needs_human instead of trusting the fix
JUDGE_HUMAN_FLOOR_DEFAULT = 0.60
JUDGE_HUMAN_FLOOR_META_KEY = "judge:human_floor"

# which rows the judge sees: 'low_confidence' (default) or 'all'
JUDGE_SCOPE_DEFAULT = "low_confidence"
JUDGE_SCOPE_META_KEY = "judge:scope"
JUDGE_SCOPE_CHOICES: tuple[str, ...] = ("all", "low_confidence")

# under scope=low_confidence, judge rows with classify_confidence below this
JUDGE_CONFIDENCE_CEILING_DEFAULT = 0.85
JUDGE_CONFIDENCE_CEILING_META_KEY = "judge:confidence_ceiling"

# inference engine — WHICH harness runs classify/judge, independent of the model
# tier. 'claude-code' = the sandboxed Claude sub-agent fan-out (subscription, the
# default and the only path used for untrusted production text); 'ollama' = the
# local open model over Ollama's HTTP API; 'opencode' = the same local weights
# driven through the OpenCode CLI harness. The open engines read `opencode:model`
# for the Ollama tag (e.g. qwen3:32b). See docs/LOCAL-OPEN-MODEL.md.
ENGINE_CHOICES: tuple[str, ...] = ("claude-code", "ollama", "opencode")

# Default engine for both stages is the fully-local, subscription-free open model
# (qwen3:32b via Ollama). Chosen for $0 marginal cost; the tradeoff is throughput
# (a single GPU serializes — no fan-out — so run OFF the 10-min tick as a
# continuous worker) and ~a few points of accuracy vs Claude. See
# docs/handoffs/2026-07-12-local-ollama-cutover.md. An explicit `classify:engine`/
# `judge:engine` knob still overrides this per-deployment.
CLASSIFY_ENGINE_DEFAULT = "ollama"
CLASSIFY_ENGINE_META_KEY = "classify:engine"

JUDGE_ENGINE_DEFAULT = "ollama"
JUDGE_ENGINE_META_KEY = "judge:engine"

# Ollama model tag the open engines classify/judge with (free-form; whatever is
# pulled locally). Not a fixed choice set — `ollama list` is the source of truth.
OPENCODE_MODEL_DEFAULT = "qwen3:32b"
OPENCODE_MODEL_META_KEY = "opencode:model"


def _get_choice(store: _MetaStore, key: str, default: str, choices: tuple[str, ...]) -> str:
    raw = store.get_meta(key)
    return raw if raw in choices else default


def _get_str(store: _MetaStore, key: str, default: str) -> str:
    """Free-form string knob (no fixed choice set): return the stored value if
    present and non-blank, else the committed default."""
    raw = store.get_meta(key)
    return raw if raw not in (None, "") else default


def _get_bounded_int(store: _MetaStore, key: str, default: int, bounds: tuple[int, int]) -> int:
    raw = store.get_meta(key)
    if raw is None:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    lo, hi = bounds
    return default if parsed < lo or parsed > hi else parsed


def get_classify_model(store: _MetaStore) -> str:
    return _get_choice(store, CLASSIFY_MODEL_META_KEY, CLASSIFY_MODEL_DEFAULT, MODEL_CHOICES)


def get_classify_batch_size(store: _MetaStore) -> int:
    return _get_bounded_int(store, CLASSIFY_BATCH_META_KEY, CLASSIFY_BATCH_DEFAULT, CLASSIFY_BATCH_BOUNDS)


def get_classify_fan_out(store: _MetaStore) -> int:
    return _get_bounded_int(store, CLASSIFY_FANOUT_META_KEY, CLASSIFY_FANOUT_DEFAULT, CLASSIFY_FANOUT_BOUNDS)


def get_judge_enabled(store: _MetaStore) -> bool:
    raw = store.get_meta(JUDGE_ENABLED_META_KEY)
    if raw is None:
        return JUDGE_ENABLED_DEFAULT
    return raw.strip().lower() in ("1", "true", "on", "yes")


def get_judge_model(store: _MetaStore) -> str:
    return _get_choice(store, JUDGE_MODEL_META_KEY, JUDGE_MODEL_DEFAULT, MODEL_CHOICES)


def get_judge_human_floor(store: _MetaStore) -> float:
    raw = store.get_meta(JUDGE_HUMAN_FLOOR_META_KEY)
    if raw is None:
        return JUDGE_HUMAN_FLOOR_DEFAULT
    try:
        v = float(raw)
    except ValueError:
        return JUDGE_HUMAN_FLOOR_DEFAULT
    return v if 0.0 <= v <= 1.0 else JUDGE_HUMAN_FLOOR_DEFAULT


def get_judge_scope(store: _MetaStore) -> str:
    return _get_choice(store, JUDGE_SCOPE_META_KEY, JUDGE_SCOPE_DEFAULT, JUDGE_SCOPE_CHOICES)


def get_judge_confidence_ceiling(store: _MetaStore) -> float:
    raw = store.get_meta(JUDGE_CONFIDENCE_CEILING_META_KEY)
    if raw is None:
        return JUDGE_CONFIDENCE_CEILING_DEFAULT
    try:
        v = float(raw)
    except ValueError:
        return JUDGE_CONFIDENCE_CEILING_DEFAULT
    return v if 0.0 <= v <= 1.0 else JUDGE_CONFIDENCE_CEILING_DEFAULT


def get_classify_engine(store: _MetaStore) -> str:
    return _get_choice(store, CLASSIFY_ENGINE_META_KEY, CLASSIFY_ENGINE_DEFAULT, ENGINE_CHOICES)


def get_judge_engine(store: _MetaStore) -> str:
    return _get_choice(store, JUDGE_ENGINE_META_KEY, JUDGE_ENGINE_DEFAULT, ENGINE_CHOICES)


def get_opencode_model(store: _MetaStore) -> str:
    return _get_str(store, OPENCODE_MODEL_META_KEY, OPENCODE_MODEL_DEFAULT)


def set_classify_model(store: _MetaStore, value: str) -> str:
    if value not in MODEL_CHOICES:
        raise ValueError(f"invalid model {value!r}; expected one of {MODEL_CHOICES}")
    store.set_meta(CLASSIFY_MODEL_META_KEY, value)
    return value


def set_classify_batch_size(store: _MetaStore, value: int) -> int:
    lo, hi = CLASSIFY_BATCH_BOUNDS
    clamped = max(lo, min(hi, int(value)))
    store.set_meta(CLASSIFY_BATCH_META_KEY, str(clamped))
    return clamped


def set_classify_fan_out(store: _MetaStore, value: int) -> int:
    lo, hi = CLASSIFY_FANOUT_BOUNDS
    clamped = max(lo, min(hi, int(value)))
    store.set_meta(CLASSIFY_FANOUT_META_KEY, str(clamped))
    return clamped


def set_judge_enabled(store: _MetaStore, value: bool) -> bool:
    store.set_meta(JUDGE_ENABLED_META_KEY, "on" if value else "off")
    return value


def set_judge_model(store: _MetaStore, value: str) -> str:
    if value not in MODEL_CHOICES:
        raise ValueError(f"invalid model {value!r}; expected one of {MODEL_CHOICES}")
    store.set_meta(JUDGE_MODEL_META_KEY, value)
    return value


def set_judge_human_floor(store: _MetaStore, value: float) -> float:
    clamped = max(0.0, min(1.0, float(value)))
    store.set_meta(JUDGE_HUMAN_FLOOR_META_KEY, str(clamped))
    return clamped


def set_judge_scope(store: _MetaStore, value: str) -> str:
    if value not in JUDGE_SCOPE_CHOICES:
        raise ValueError(f"invalid judge scope {value!r}; expected one of {JUDGE_SCOPE_CHOICES}")
    store.set_meta(JUDGE_SCOPE_META_KEY, value)
    return value


def set_judge_confidence_ceiling(store: _MetaStore, value: float) -> float:
    clamped = max(0.0, min(1.0, float(value)))
    store.set_meta(JUDGE_CONFIDENCE_CEILING_META_KEY, str(clamped))
    return clamped


def set_classify_engine(store: _MetaStore, value: str) -> str:
    if value not in ENGINE_CHOICES:
        raise ValueError(f"invalid engine {value!r}; expected one of {ENGINE_CHOICES}")
    store.set_meta(CLASSIFY_ENGINE_META_KEY, value)
    return value


def set_judge_engine(store: _MetaStore, value: str) -> str:
    if value not in ENGINE_CHOICES:
        raise ValueError(f"invalid engine {value!r}; expected one of {ENGINE_CHOICES}")
    store.set_meta(JUDGE_ENGINE_META_KEY, value)
    return value


def set_opencode_model(store: _MetaStore, value: str) -> str:
    value = str(value).strip()
    if not value:
        raise ValueError("opencode model must be a non-empty Ollama tag (e.g. qwen3:32b)")
    store.set_meta(OPENCODE_MODEL_META_KEY, value)
    return value


def config_snapshot(store: _MetaStore) -> dict[str, object]:
    """The JSON the /enrich-tick command reads at Step 0.6."""
    return {
        "classify_engine": get_classify_engine(store),
        "classify_model": get_classify_model(store),
        "classify_batch_size": get_classify_batch_size(store),
        "classify_fan_out": get_classify_fan_out(store),
        "judge_enabled": get_judge_enabled(store),
        "judge_engine": get_judge_engine(store),
        "judge_model": get_judge_model(store),
        "judge_human_floor": get_judge_human_floor(store),
        "judge_scope": get_judge_scope(store),
        "judge_confidence_ceiling": get_judge_confidence_ceiling(store),
        "opencode_model": get_opencode_model(store),
    }


# The full set of runtime-knob meta keys. `reset_knob` deletes one of these so its
# getter falls back to the committed default — the way to make an already-running
# prod follow a newly-deployed default instead of a stale explicit override.
KNOB_META_KEYS: frozenset[str] = frozenset(
    {
        CLASSIFY_ENGINE_META_KEY,
        CLASSIFY_MODEL_META_KEY,
        CLASSIFY_BATCH_META_KEY,
        CLASSIFY_FANOUT_META_KEY,
        JUDGE_ENABLED_META_KEY,
        JUDGE_ENGINE_META_KEY,
        JUDGE_MODEL_META_KEY,
        JUDGE_HUMAN_FLOOR_META_KEY,
        JUDGE_SCOPE_META_KEY,
        JUDGE_CONFIDENCE_CEILING_META_KEY,
        OPENCODE_MODEL_META_KEY,
    }
)


def reset_knob(store: _MetaStore, key: str) -> str:
    """Clear an explicit knob override so its getter returns the committed default."""
    if key not in KNOB_META_KEYS:
        raise ValueError(f"unknown knob {key!r}; expected one of {sorted(KNOB_META_KEYS)}")
    store.delete_meta(key)
    return key
