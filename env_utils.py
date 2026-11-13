"""Shared environment helpers for Hermes runtime modules.

Guards against empty values and unexpanded Zerops template placeholders (e.g. ``${VAR}``)
so optional Vault variables never leak literal placeholder strings into runtime logic.
"""

import os
import re
from typing import Iterable

_UNEXPANDED_PLACEHOLDER_RE = re.compile(r"\$\{[A-Za-z0-9_.]+\}")


def clean_env(name: str, default: str = "") -> str:
    """Return stripped env var value, or ``default`` when empty or containing ``${...}``."""
    raw = os.getenv(name)
    if raw is None:
        return default
    stripped = raw.strip()
    if not stripped or _UNEXPANDED_PLACEHOLDER_RE.search(stripped):
        return default
    return stripped


def load_runtime_env(candidate_paths: Iterable[str]) -> None:
    """Load key=value overrides from the first existing ``runtime.env`` file.

    Respects already-configured valid environment variables while replacing
    missing, blank, or unexpanded ``${...}`` placeholder values.
    """
    for env_path in candidate_paths:
        if not env_path or not os.path.exists(env_path):
            continue
        try:
            with open(env_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    ls = line.strip()
                    if not ls or ls.startswith("#") or "=" not in ls:
                        continue
                    key, val = ls.split("=", 1)
                    k = key.strip()
                    v = val.strip("'\" ")
                    if k and v and not clean_env(k):
                        os.environ[k] = v
            return
        except Exception:
            return
