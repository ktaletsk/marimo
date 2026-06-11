# Copyright 2026 Marimo. All rights reserved.
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from marimo._runtime.packages.conda_environments import (
    CondaEnvironment,
    _env_name_from_path,
    clear_cache,
    list_conda_environments,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Module-level cache leaks across tests; reset between each one."""
    clear_cache()
    yield
    clear_cache()


def test_env_name_from_path_uses_envs_dir_layout() -> None:
    from pathlib import Path

    assert _env_name_from_path(Path("/home/u/miniconda3/envs/qa")) == "qa"


def test_env_name_from_path_labels_root_as_base() -> None:
    from pathlib import Path

    assert _env_name_from_path(Path("/home/u/miniconda3")) == "base"
    assert _env_name_from_path(Path("/opt/anaconda3")) == "base"


def _patch_subprocess(stdout: str, returncode: int = 0):
    proc = MagicMock()
    proc.stdout = stdout
    proc.returncode = returncode
    proc.stderr = ""
    return patch(
        "marimo._runtime.packages.conda_environments.subprocess.run",
        return_value=proc,
    )


def _patch_preferred(binary: str = "conda"):
    return patch(
        "marimo._runtime.packages.conda_environments._preferred_conda_family_manager",
        return_value=binary,
    )


def test_list_envs_parses_paths_and_labels_active(monkeypatch) -> None:
    output = json.dumps(
        {
            "envs": [
                "/Users/me/miniconda3",
                "/Users/me/miniconda3/envs/marimo-qa",
                "/Users/me/miniconda3/envs/data-sci",
            ]
        }
    )
    monkeypatch.setenv("CONDA_PREFIX", "/Users/me/miniconda3/envs/marimo-qa")

    with _patch_preferred(), _patch_subprocess(output):
        envs = list_conda_environments()

    assert envs == [
        CondaEnvironment(
            name="base",
            path="/Users/me/miniconda3",
            is_active=False,
        ),
        CondaEnvironment(
            name="marimo-qa",
            path="/Users/me/miniconda3/envs/marimo-qa",
            is_active=True,
        ),
        CondaEnvironment(
            name="data-sci",
            path="/Users/me/miniconda3/envs/data-sci",
            is_active=False,
        ),
    ]


def test_list_envs_returns_empty_when_binary_missing(monkeypatch) -> None:
    monkeypatch.delenv("CONDA_PREFIX", raising=False)

    with (
        _patch_preferred(),
        patch(
            "marimo._runtime.packages.conda_environments.subprocess.run",
            side_effect=FileNotFoundError,
        ),
    ):
        assert list_conda_environments() == []


def test_list_envs_returns_empty_on_nonzero_exit(monkeypatch) -> None:
    monkeypatch.delenv("CONDA_PREFIX", raising=False)

    with _patch_preferred(), _patch_subprocess("", returncode=1):
        assert list_conda_environments() == []


def test_list_envs_returns_empty_on_malformed_json(monkeypatch) -> None:
    monkeypatch.delenv("CONDA_PREFIX", raising=False)

    with _patch_preferred(), _patch_subprocess("not json {{"):
        assert list_conda_environments() == []


def test_list_envs_uses_cache(monkeypatch) -> None:
    output = json.dumps({"envs": ["/opt/conda"]})
    monkeypatch.delenv("CONDA_PREFIX", raising=False)

    with _patch_preferred(), _patch_subprocess(output) as mock_run:
        list_conda_environments()
        list_conda_environments()
        list_conda_environments()
        # Only one subprocess call despite three list_conda_environments calls.
        assert mock_run.return_value is mock_run.return_value
        # Verify subprocess.run was invoked exactly once.
        from marimo._runtime.packages import conda_environments as _mod

        assert _mod.subprocess.run.call_count == 1  # type: ignore[attr-defined]


def test_list_envs_refresh_bypasses_cache(monkeypatch) -> None:
    output = json.dumps({"envs": ["/opt/conda"]})
    monkeypatch.delenv("CONDA_PREFIX", raising=False)

    with _patch_preferred(), _patch_subprocess(output):
        list_conda_environments()
        list_conda_environments(refresh=True)

        from marimo._runtime.packages import conda_environments as _mod

        assert _mod.subprocess.run.call_count == 2  # type: ignore[attr-defined]


def test_list_envs_uses_preferred_binary(monkeypatch) -> None:
    """Helper shells out to whatever _preferred_conda_family_manager picks."""
    monkeypatch.delenv("CONDA_PREFIX", raising=False)

    with (
        _patch_preferred(binary="mamba"),
        _patch_subprocess(json.dumps({"envs": []})) as mock_run,
    ):
        list_conda_environments()

    args, _ = mock_run.call_args
    assert args[0][0] == "mamba"
    assert args[0][1:] == ["env", "list", "--json"]


def test_find_environment_by_name_returns_match(monkeypatch) -> None:
    from marimo._runtime.packages.conda_environments import (
        find_environment_by_name,
    )

    output = json.dumps(
        {
            "envs": [
                "/Users/me/mamba",
                "/Users/me/mamba/envs/marimo-qa",
            ]
        }
    )
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    with _patch_preferred(), _patch_subprocess(output):
        match = find_environment_by_name("marimo-qa")
    assert match is not None
    assert match.name == "marimo-qa"
    assert match.path == "/Users/me/mamba/envs/marimo-qa"


def test_find_environment_by_name_returns_none_when_absent(
    monkeypatch,
) -> None:
    from marimo._runtime.packages.conda_environments import (
        find_environment_by_name,
    )

    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    with _patch_preferred(), _patch_subprocess(json.dumps({"envs": []})):
        assert find_environment_by_name("nonexistent") is None


def test_conda_env_python_path_posix(tmp_path) -> None:
    from marimo._runtime.packages.conda_environments import (
        CondaEnvironment,
        conda_env_python_path,
    )

    env_dir = tmp_path / "myenv"
    bin_dir = env_dir / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "python").touch()

    env = CondaEnvironment(name="myenv", path=str(env_dir), is_active=False)
    assert conda_env_python_path(env) == str(bin_dir / "python")
