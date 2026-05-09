from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from marimo._config.packages import (
    _preferred_conda_family_manager,
    infer_package_manager,
    infer_package_manager_from_lockfile,
    infer_package_manager_from_pyproject,
)


@pytest.fixture
def mock_cwd(tmp_path: Path):
    """Creates a temporary directory and sets it as CWD"""
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(old_cwd)


def test_infer_package_manager_from_pyproject():
    # Test poetry detection
    with patch(
        "marimo._config.packages.toml_reader.read",
        return_value={"tool": {"poetry": {}}},
    ):
        assert (
            infer_package_manager_from_pyproject(Path("pyproject.toml"))
            == "poetry"
        )

    # Test no tool section
    with patch("marimo._config.packages.toml_reader.read", return_value={}):
        assert (
            infer_package_manager_from_pyproject(Path("pyproject.toml"))
            is None
        )

    # Test exception handling
    with patch(
        "marimo._config.packages.toml_reader.read", side_effect=Exception
    ):
        assert (
            infer_package_manager_from_pyproject(Path("pyproject.toml"))
            is None
        )


def test_infer_package_manager_from_lockfile(mock_cwd: Path):
    # Test poetry.lock
    (mock_cwd / "poetry.lock").touch()
    assert infer_package_manager_from_lockfile(mock_cwd) == "poetry"
    (mock_cwd / "poetry.lock").unlink()

    # Test pixi.lock
    (mock_cwd / "pixi.lock").touch()
    assert infer_package_manager_from_lockfile(mock_cwd) == "pixi"
    (mock_cwd / "pixi.lock").unlink()

    # Test no lockfile
    for f in mock_cwd.iterdir():
        f.unlink()
    assert infer_package_manager_from_lockfile(mock_cwd) is None


TEST_CASES: list[
    tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]
] = [
    # Test pyproject.toml with poetry
    ({"pyproject.toml": {"tool": {"poetry": {}}}}, {}, {}, "poetry"),
    # Test lockfile detection
    ({"poetry.lock": ""}, {}, {}, "poetry"),
    # Test pixi.toml
    ({"pixi.toml": ""}, {}, {}, "pixi"),
    # Test environment.yml -> conda
    ({"environment.yml": ""}, {}, {}, "conda"),
    # Test environment.yaml -> conda
    ({"environment.yaml": ""}, {}, {}, "conda"),
    # Test active conda env -> conda
    ({}, {"CONDA_DEFAULT_ENV": "myenv"}, {}, "conda"),
    # Test fallback to pip
    ({}, {}, {}, "pip"),
    # Test fallback to uv when running inside `uv run` / `uvx`
    ({}, {"UV": "/usr/bin/uv"}, {}, "uv"),
]

if sys.platform != "win32":
    TEST_CASES.extend(
        [
            # Test uv virtualenv
            ({}, {"VIRTUAL_ENV": "/path/uv/env"}, {}, "uv"),
            # Test regular virtualenv
            ({}, {}, {"base_prefix": "/usr", "prefix": "/venv"}, "pip"),
        ]
    )


@pytest.mark.parametrize(
    ("files", "env_vars", "sys_attrs", "expected"),
    TEST_CASES,
)
def test_infer_package_manager(
    mock_cwd: Path,
    files: dict[str, Any],
    env_vars: dict[str, Any],
    sys_attrs: dict[str, Any],
    expected: str,
):
    # Write a default pyproject.toml file
    (mock_cwd / "pyproject.toml").write_text(
        """
        [project]
        name = "test"
        """
    )

    # Create test files
    for filename, content in files.items():
        if isinstance(content, dict):
            import tomlkit

            with open(mock_cwd / filename, "w") as f:
                tomlkit.dump(content, f)
        else:
            (mock_cwd / filename).write_text(content)

    # Ensure CI env vars (e.g. UV set by uv-based runners) don't leak
    # into the test. Start from a clean slate for the keys that
    # infer_package_manager inspects, then layer on env_vars.
    sanitized = {
        k: v
        for k, v in os.environ.items()
        if k not in ("UV", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV")
    }
    sanitized.update(env_vars)

    # Mock environment variables. Also force the conda-family preference
    # helper to return "conda" so test outcomes don't depend on whether
    # conda/mamba/micromamba happens to be on PATH on the test runner.
    with (
        patch.dict(os.environ, sanitized, clear=True),
        patch(
            "marimo._config.packages._preferred_conda_family_manager",
            return_value="conda",
        ),
    ):
        # Mock sys attributes
        if sys_attrs:
            with patch.multiple(sys, **sys_attrs):
                assert infer_package_manager() == expected
        else:
            assert infer_package_manager() == expected


@pytest.mark.parametrize(
    ("marker_filename", "expected"),
    [
        ("pixi.toml", "pixi"),
        ("environment.yml", "conda"),
        ("environment.yaml", "conda"),
    ],
)
def test_infer_package_manager_without_pyproject(
    mock_cwd: Path, marker_filename: str, expected: str
):
    """A project root with only a non-pyproject manifest must still be
    detected. Regression: previously the upward walk only anchored on
    pyproject.toml/requirements.txt, so root_dir ended at filesystem root
    and the manifest in CWD was missed."""
    (mock_cwd / marker_filename).touch()

    sanitized = {
        k: v
        for k, v in os.environ.items()
        if k not in ("UV", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV")
    }
    with (
        patch.dict(os.environ, sanitized, clear=True),
        patch(
            "marimo._config.packages._preferred_conda_family_manager",
            return_value="conda",
        ),
    ):
        assert infer_package_manager() == expected


def test_preferred_conda_family_prefers_conda() -> None:
    with patch(
        "marimo._config.packages.shutil.which",
        side_effect=lambda name: f"/fake/{name}",
    ):
        assert _preferred_conda_family_manager() == "conda"


def test_preferred_conda_family_falls_back_to_mamba() -> None:
    def which(name: str) -> str | None:
        return f"/fake/{name}" if name == "mamba" else None

    with patch("marimo._config.packages.shutil.which", side_effect=which):
        assert _preferred_conda_family_manager() == "mamba"


def test_preferred_conda_family_falls_back_to_micromamba() -> None:
    def which(name: str) -> str | None:
        return f"/fake/{name}" if name == "micromamba" else None

    with patch("marimo._config.packages.shutil.which", side_effect=which):
        assert _preferred_conda_family_manager() == "micromamba"


def test_preferred_conda_family_defaults_to_conda_when_none_installed() -> (
    None
):
    with patch("marimo._config.packages.shutil.which", return_value=None):
        assert _preferred_conda_family_manager() == "conda"


def test_infer_picks_mamba_when_only_mamba_installed(mock_cwd: Path) -> None:
    """User scenario: CONDA_DEFAULT_ENV set by `mamba activate`, and
    only `mamba` is on PATH (no real `conda` binary). Inference must
    pick `mamba` rather than the unusable `conda`."""
    (mock_cwd / "environment.yml").touch()

    def which(name: str) -> str | None:
        return f"/fake/{name}" if name == "mamba" else None

    sanitized = {
        k: v
        for k, v in os.environ.items()
        if k not in ("UV", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV")
    }
    with (
        patch.dict(os.environ, sanitized, clear=True),
        patch("marimo._config.packages.shutil.which", side_effect=which),
    ):
        assert infer_package_manager() == "mamba"
