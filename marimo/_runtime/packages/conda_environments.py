# Copyright 2026 Marimo. All rights reserved.
"""Discover conda-family environments on the user's machine.

Lists envs by shelling out to whichever conda/mamba/micromamba binary is
available; all three share the same env directories so the result is
identical regardless of which one we call.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import msgspec

from marimo import _loggers
from marimo._config.packages import _preferred_conda_family_manager

LOGGER = _loggers.marimo_logger()

_CACHE_TTL_SECONDS = 30.0
_cache: dict[str, tuple[float, list[CondaEnvironment]]] = {}


class CondaEnvironment(msgspec.Struct, rename="camel"):
    name: str
    path: str
    is_active: bool


def _env_name_from_path(env_path: Path) -> str:
    """Derive a display name from an env path.

    Standard layout puts named envs under ``<root>/envs/<name>``; root
    envs are labeled ``base`` to match the ``conda env list`` text view.
    """
    if env_path.parent.name == "envs":
        return env_path.name
    return "base"


def _active_env_path() -> str | None:
    """Path of the currently-active conda env, if any."""
    prefix = os.environ.get("CONDA_PREFIX")
    if not prefix:
        return None
    try:
        return str(Path(prefix).resolve())
    except OSError:
        return prefix


def list_conda_environments(
    *, refresh: bool = False
) -> list[CondaEnvironment]:
    """Enumerate conda-family environments on the machine.

    Cached for ``_CACHE_TTL_SECONDS`` seconds. Pass ``refresh=True`` to
    bypass the cache. Returns an empty list if no conda-family binary is
    on PATH or the command fails.
    """
    cache_key = _preferred_conda_family_manager()
    now = time.monotonic()
    if not refresh:
        cached = _cache.get(cache_key)
        if cached is not None and (now - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    envs = _list_environments_uncached(cache_key)
    _cache[cache_key] = (now, envs)
    return envs


def _list_environments_uncached(binary: str) -> list[CondaEnvironment]:
    try:
        proc = subprocess.run(
            [binary, "env", "list", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        LOGGER.debug("conda env discovery failed: %s", e)
        return []

    if proc.returncode != 0:
        LOGGER.debug(
            "conda env discovery returned %d: %s",
            proc.returncode,
            proc.stderr.strip(),
        )
        return []

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        LOGGER.debug("conda env discovery: malformed JSON: %s", e)
        return []

    raw_paths = data.get("envs", [])
    if not isinstance(raw_paths, list):
        return []

    active = _active_env_path()
    out: list[CondaEnvironment] = []
    for raw_path in raw_paths:
        if not isinstance(raw_path, str):
            continue
        path = Path(raw_path)
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = raw_path
        out.append(
            CondaEnvironment(
                name=_env_name_from_path(path),
                path=resolved,
                is_active=active is not None and resolved == active,
            )
        )
    return out


def clear_cache() -> None:
    """Drop any cached env list; the next call re-queries the binary."""
    _cache.clear()


def find_environment_by_name(name: str) -> CondaEnvironment | None:
    """Return the env with the given name, or ``None`` if not on this machine.

    Note: when two envs share a display name (e.g. two ``base`` envs from a
    coexisting mambaforge + anaconda install), the first match wins. The
    notebook picker prevents this case in practice by writing only what
    the user selected; the disambiguation happens in the UI.
    """
    for env in list_conda_environments():
        if env.name == name:
            return env
    return None


def conda_env_python_path(env: CondaEnvironment) -> str:
    """Return the path to ``python`` inside the given env."""
    # Cross-platform: Windows puts the interpreter at <env>/python.exe,
    # POSIX at <env>/bin/python.
    base = Path(env.path)
    posix = base / "bin" / "python"
    if posix.exists():
        return str(posix)
    windows = base / "python.exe"
    if windows.exists():
        return str(windows)
    return str(posix)  # best-effort fallback for missing envs
