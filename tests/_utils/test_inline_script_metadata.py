from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from marimo._utils.inline_script_metadata import (
    PyProjectReader,
    _apply_marimo_tool_updates,
    _pyproject_toml_to_requirements_txt,
    has_marimo_in_script_metadata,
    is_marimo_dependency,
    script_metadata_hash_from_filename,
    update_marimo_tool_in_script,
)
from marimo._utils.platform import is_windows
from marimo._utils.scripts import read_pyproject_from_script

if TYPE_CHECKING:
    from pathlib import Path


def test_get_dependencies():
    SCRIPT = """
# Copyright 2026 Marimo. All rights reserved.
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "polars",
#     "marimo>=0.8.0",
#     "quak",
#     "vega-datasets",
# ]
# ///

import marimo

__generated_with = "0.8.2"
app = marimo.App(width="medium")
"""
    assert PyProjectReader.from_script(SCRIPT).dependencies == [
        "polars",
        "marimo>=0.8.0",
        "quak",
        "vega-datasets",
    ]


def test_get_dependencies_github():
    url = "https://github.com/marimo-team/marimo/blob/a1e1be3190023a86650904249f911b2e6ffb8fac/examples/third_party/leafmap/leafmap_example.py"
    assert PyProjectReader.from_filename(url).dependencies == [
        "leafmap==0.41.0",
        "marimo",
    ]


def test_no_dependencies():
    SCRIPT = """
import marimo

__generated_with = "0.8.2"
app = marimo.App(width="medium")
"""
    assert PyProjectReader.from_script(SCRIPT).dependencies == []


def test_windows_line_endings_from_url():
    """Test that script metadata from URL with Windows line endings is parsed correctly."""
    from unittest.mock import patch

    from marimo._utils.requests import Response

    # Script content as it would come from a Windows server with CRLF line endings
    SCRIPT_WITH_CRLF = b"""# /// script\r
# requires-python = ">=3.11"\r
# dependencies = [\r
#     "polars",\r
#     "marimo>=0.8.0",\r
# ]\r
# ///\r
\r
import marimo\r
\r
__generated_with = "0.8.2"\r
app = marimo.App(width="medium")\r
"""

    url = "https://example.com/notebook.py"

    with patch("marimo._utils.requests.get") as mock_get:
        # Mock the response to return content with Windows line endings
        mock_get.return_value = Response(
            200,
            SCRIPT_WITH_CRLF,
            {},
        )

        # This should now work correctly with the line ending normalization in response.text()
        reader = PyProjectReader.from_filename(url)
        assert reader.dependencies == ["polars", "marimo>=0.8.0"]
        assert reader.python_version == ">=3.11"


def test_pyproject_toml_to_requirements_txt_git_sources():
    pyproject = {
        "dependencies": [
            "marimo",
            "numpy",
            "polars",
            "altair",
        ],
        "tool": {
            "uv": {
                "sources": {
                    "marimo": {
                        "git": "https://github.com/marimo-team/marimo.git",
                        "rev": "main",
                    },
                    "numpy": {
                        "git": "https://github.com/numpy/numpy.git",
                        "branch": "main",
                    },
                    "polars": {
                        "git": "https://github.com/pola/polars.git",
                        "branch": "dev",
                    },
                }
            }
        },
    }
    assert _pyproject_toml_to_requirements_txt(pyproject) == [
        "marimo @ git+https://github.com/marimo-team/marimo.git@main",
        "numpy @ git+https://github.com/numpy/numpy.git@main",
        "polars @ git+https://github.com/pola/polars.git@dev",
        "altair",
    ]


def test_pyproject_toml_to_requirements_txt_with_marker():
    pyproject = {
        "dependencies": [
            "marimo",
            "polars",
        ],
        "tool": {
            "uv": {
                "sources": {
                    "marimo": {
                        "git": "https://github.com/marimo-team/marimo.git",
                        "tag": "0.1.0",
                        "marker": "python_version >= '3.12'",
                    }
                }
            }
        },
    }
    assert _pyproject_toml_to_requirements_txt(pyproject) == [
        "marimo @ git+https://github.com/marimo-team/marimo.git@0.1.0; python_version >= '3.12'",
        "polars",
    ]


def test_pyproject_toml_to_requirements_txt_with_url_sources():
    pyproject = {
        "dependencies": [
            "marimo",
            "polars",
        ],
        "tool": {
            "uv": {
                "sources": {
                    "marimo": {
                        "url": "https://github.com/marimo-team/marimo/archive/refs/heads/main.zip",
                    }
                }
            }
        },
    }
    assert _pyproject_toml_to_requirements_txt(pyproject) == [
        "marimo @ https://github.com/marimo-team/marimo/archive/refs/heads/main.zip",
        "polars",
    ]


@pytest.mark.skipif(is_windows(), reason="only testing posix paths")
def test_pyproject_toml_to_requirements_txt_with_local_path():
    pyproject = {
        "dependencies": [
            "marimo",
            "polars",
        ],
        "tool": {
            "uv": {
                "sources": {
                    "marimo": {
                        "path": "/Users/me/work/marimo",
                    }
                }
            }
        },
    }
    assert _pyproject_toml_to_requirements_txt(pyproject) == [
        "marimo @ /Users/me/work/marimo",
        "polars",
    ]


@pytest.mark.skipif(is_windows(), reason="only testing posix paths")
def test_pyproject_toml_to_requirements_txt_with_relative_path():
    pyproject = {
        "dependencies": [
            "marimo",
            "polars",
        ],
        "tool": {
            "uv": {
                "sources": {
                    "marimo": {
                        "path": "../local/marimo",
                    }
                }
            }
        },
    }
    # Test with a config path to verify relative path resolution
    config_path = "/Users/me/project/script.py"
    assert _pyproject_toml_to_requirements_txt(pyproject, config_path) == [
        "marimo @ /Users/me/local/marimo",
        "polars",
    ]


@pytest.mark.parametrize(
    "version_spec",
    [
        "marimo>=0.1.0",
        "marimo==0.1.0",
        "marimo<=0.1.0",
        "marimo>0.1.0",
        "marimo<0.1.0",
        "marimo~=0.1.0",
    ],
)
def test_pyproject_toml_to_requirements_txt_with_versioned_dependencies(
    version_spec: str,
):
    pyproject = {
        "dependencies": [
            version_spec,
        ],
        "tool": {
            "uv": {
                "sources": {
                    "marimo": {
                        "git": "https://github.com/marimo-team/marimo.git",
                        "rev": "main",
                    },
                }
            }
        },
    }
    assert _pyproject_toml_to_requirements_txt(pyproject) == [
        "marimo @ git+https://github.com/marimo-team/marimo.git@main",
    ]


def test_get_python_version_requirement():
    pyproject = {"requires-python": ">=3.11"}
    assert (
        PyProjectReader(pyproject, config_path=None).python_version == ">=3.11"
    )

    pyproject = {"dependencies": ["polars"]}
    assert PyProjectReader(pyproject, config_path=None).python_version is None

    assert PyProjectReader({}, config_path=None).python_version is None

    pyproject = {"requires-python": {"invalid": "type"}}
    assert PyProjectReader(pyproject, config_path=None).python_version is None


def test_get_dependencies_with_python_version():
    SCRIPT = """
# /// script
# requires-python = ">=3.11"
# dependencies = ["polars"]
# ///

import marimo
"""
    assert PyProjectReader.from_script(SCRIPT).dependencies == ["polars"]

    pyproject = read_pyproject_from_script(SCRIPT)
    assert pyproject is not None
    assert (
        PyProjectReader(pyproject, config_path=None).python_version == ">=3.11"
    )

    SCRIPT_NO_PYTHON = """
# /// script
# dependencies = ["polars"]
# ///

import marimo
"""
    pyproject_no_python = read_pyproject_from_script(SCRIPT_NO_PYTHON)
    assert pyproject_no_python is not None
    assert (
        PyProjectReader(pyproject_no_python, config_path=None).python_version
        is None
    )
    assert PyProjectReader.from_script(SCRIPT_NO_PYTHON).dependencies == [
        "polars"
    ]


def test_get_dependencies_with_nonexistent_file():
    # Test with a non-existent file
    assert (
        PyProjectReader.from_filename("nonexistent_file.py").dependencies == []
    )

    # Test with empty
    assert PyProjectReader.from_filename("").dependencies == []


def test_is_marimo_dependency():
    assert is_marimo_dependency("marimo")
    assert is_marimo_dependency("marimo[extras]")
    assert not is_marimo_dependency("marimo-extras")
    assert not is_marimo_dependency("marimo-ai")

    # With version specifiers
    assert is_marimo_dependency("marimo==0.1.0")
    assert is_marimo_dependency("marimo[extras]>=0.1.0")
    assert is_marimo_dependency("marimo[extras]==0.1.0")
    assert is_marimo_dependency("marimo[extras]~=0.1.0")
    assert is_marimo_dependency("marimo[extras]<=0.1.0")
    assert is_marimo_dependency("marimo[extras]>=0.1.0")
    assert is_marimo_dependency("marimo[extras]<=0.1.0")

    # With other packages
    assert not is_marimo_dependency("numpy")
    assert not is_marimo_dependency("pandas")
    assert not is_marimo_dependency("marimo-ai")
    assert not is_marimo_dependency("marimo-ai==0.1.0")


def test_has_marimo_in_script_metadata(tmp_path):
    """Test has_marimo_in_script_metadata returns correct values."""
    # True: marimo present
    with_marimo = tmp_path / "with_marimo.py"
    with_marimo.write_text(
        "# /// script\n# dependencies = ['marimo']\n# ///\n"
    )
    assert has_marimo_in_script_metadata(str(with_marimo)) is True

    # False: metadata exists but no marimo
    without_marimo = tmp_path / "without_marimo.py"
    without_marimo.write_text(
        "# /// script\n# dependencies = ['numpy']\n# ///\n"
    )
    assert has_marimo_in_script_metadata(str(without_marimo)) is False

    # None: no metadata
    no_metadata = tmp_path / "no_metadata.py"
    no_metadata.write_text("import marimo\n")
    assert has_marimo_in_script_metadata(str(no_metadata)) is None

    # None: non-.py file
    assert has_marimo_in_script_metadata(str(tmp_path / "test.md")) is None


def test_script_metadata_hash_from_filename_none_without_metadata(
    tmp_path: Path,
) -> None:
    notebook = tmp_path / "no_metadata.py"
    notebook.write_text("import marimo\n", encoding="utf-8")
    assert script_metadata_hash_from_filename(str(notebook)) is None


def test_script_metadata_hash_from_filename_ignores_formatting(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.py"
    first.write_text(
        """
# /// script
# dependencies = [
#   "numpy",
#   "marimo>=0.20.0",
# ]
# requires-python = ">=3.11"
# ///
""",
        encoding="utf-8",
    )
    second = tmp_path / "second.py"
    second.write_text(
        """
# /// script
# requires-python   =   ">=3.11"
# dependencies = ["numpy", "marimo>=0.20.0"]
# ///
""",
        encoding="utf-8",
    )
    assert script_metadata_hash_from_filename(
        str(first)
    ) == script_metadata_hash_from_filename(str(second))


def test_script_metadata_hash_from_filename_changes_with_dependencies(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.py"
    first.write_text(
        """
# /// script
# dependencies = ["numpy"]
# ///
""",
        encoding="utf-8",
    )
    second = tmp_path / "second.py"
    second.write_text(
        """
# /// script
# dependencies = ["pandas"]
# ///
""",
        encoding="utf-8",
    )
    assert script_metadata_hash_from_filename(
        str(first)
    ) != script_metadata_hash_from_filename(str(second))


# ---- PyProjectReader: [tool.marimo] reads ------------------------------------


def test_reader_exposes_conda_environment() -> None:
    script = """
# /// script
# [tool.marimo]
# conda_environment = "marimo-qa"
# conda_channels = ["conda-forge", "nvidia"]
# ///

import marimo as mo
"""
    reader = PyProjectReader.from_script(script)
    assert reader.conda_environment == "marimo-qa"
    assert reader.conda_channels == ["conda-forge", "nvidia"]
    assert reader.marimo_tool == {
        "conda_environment": "marimo-qa",
        "conda_channels": ["conda-forge", "nvidia"],
    }


def test_reader_defaults_when_tool_marimo_absent() -> None:
    reader = PyProjectReader.from_script(
        """
# /// script
# dependencies = ["polars"]
# ///
"""
    )
    assert reader.conda_environment is None
    assert reader.conda_channels == []
    assert reader.marimo_tool == {}


def test_reader_ignores_non_string_conda_environment() -> None:
    reader = PyProjectReader.from_script(
        """
# /// script
# [tool.marimo]
# conda_environment = 42
# ///
"""
    )
    assert reader.conda_environment is None


def test_reader_filters_non_string_channels() -> None:
    reader = PyProjectReader.from_script(
        """
# /// script
# [tool.marimo]
# conda_channels = ["conda-forge", 42, "nvidia"]
# ///
"""
    )
    assert reader.conda_channels == ["conda-forge", "nvidia"]


# ---- _apply_marimo_tool_updates: in-memory transformation --------------------


def _read_after(updated: str) -> PyProjectReader:
    return PyProjectReader.from_script(updated)


def test_apply_sets_keys_in_existing_block() -> None:
    original = """# /// script
# dependencies = ["polars"]
# ///

import polars as pl
"""
    updated = _apply_marimo_tool_updates(
        original,
        {"conda_environment": "marimo-qa", "conda_channels": ["conda-forge"]},
    )
    assert "import polars as pl" in updated
    reader = _read_after(updated)
    assert reader.conda_environment == "marimo-qa"
    assert reader.conda_channels == ["conda-forge"]
    assert reader.dependencies == ["polars"]


def test_apply_creates_block_when_absent() -> None:
    original = "import marimo as mo\n"
    updated = _apply_marimo_tool_updates(
        original, {"conda_environment": "marimo-qa"}
    )
    assert updated.startswith("# /// script\n")
    assert "import marimo as mo" in updated
    assert _read_after(updated).conda_environment == "marimo-qa"


def test_apply_deletes_key_when_set_to_none() -> None:
    original = """# /// script
# [tool.marimo]
# conda_environment = "marimo-qa"
# conda_channels = ["conda-forge"]
# ///
"""
    updated = _apply_marimo_tool_updates(original, {"conda_environment": None})
    reader = _read_after(updated)
    assert reader.conda_environment is None
    assert reader.conda_channels == ["conda-forge"]


def test_apply_drops_empty_script_block_when_no_keys_remain() -> None:
    original = """# /// script
# [tool.marimo]
# conda_environment = "marimo-qa"
# ///

import marimo as mo
"""
    updated = _apply_marimo_tool_updates(original, {"conda_environment": None})
    # The empty block should be removed entirely; no `# /// script` husk.
    assert "# /// script" not in updated
    assert "tool.marimo" not in updated
    assert "import marimo as mo" in updated


def test_apply_keeps_block_when_other_keys_remain() -> None:
    original = """# /// script
# dependencies = ["polars"]
# [tool.marimo]
# conda_environment = "marimo-qa"
# ///

import polars as pl
"""
    updated = _apply_marimo_tool_updates(original, {"conda_environment": None})
    # Block stays — `dependencies` is still there.
    assert "# /// script" in updated
    assert 'dependencies = ["polars"]' in updated
    assert "tool.marimo" not in updated
    assert "conda_environment" not in updated


def test_apply_preserves_other_tool_subtables() -> None:
    original = """# /// script
# dependencies = ["polars"]
# [tool.uv]
# index-url = "https://example.com/simple"
# ///
"""
    updated = _apply_marimo_tool_updates(
        original, {"conda_environment": "marimo-qa"}
    )
    reader = _read_after(updated)
    assert reader.conda_environment == "marimo-qa"
    assert reader.dependencies == ["polars"]
    assert reader.index_url == "https://example.com/simple"


def test_apply_rejects_multiple_script_blocks() -> None:
    original = """# /// script
# dependencies = []
# ///

# /// script
# dependencies = ["x"]
# ///
"""
    with pytest.raises(ValueError, match="Multiple script blocks"):
        _apply_marimo_tool_updates(original, {"conda_environment": "qa"})


# ---- update_marimo_tool_in_script: end-to-end file mutation ------------------


def test_update_marimo_tool_in_script_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "nb.py"
    f.write_text(
        """# /// script
# dependencies = ["polars"]
# ///

import polars as pl
""",
        encoding="utf-8",
    )

    assert update_marimo_tool_in_script(
        str(f),
        conda_environment="marimo-qa",
        conda_channels=["conda-forge", "nvidia"],
    )
    reader = PyProjectReader.from_filename(str(f))
    assert reader.conda_environment == "marimo-qa"
    assert reader.conda_channels == ["conda-forge", "nvidia"]
    assert reader.dependencies == ["polars"]


def test_update_marimo_tool_creates_block_when_missing(tmp_path: Path) -> None:
    f = tmp_path / "nb.py"
    f.write_text("import marimo as mo\n", encoding="utf-8")

    assert update_marimo_tool_in_script(str(f), conda_environment="marimo-qa")
    contents = f.read_text(encoding="utf-8")
    assert contents.startswith("# /// script\n")
    assert (
        PyProjectReader.from_filename(str(f)).conda_environment == "marimo-qa"
    )


def test_update_marimo_tool_noop_when_no_kwargs_given(tmp_path: Path) -> None:
    f = tmp_path / "nb.py"
    f.write_text("import marimo as mo\n", encoding="utf-8")

    assert update_marimo_tool_in_script(str(f))
    assert f.read_text(encoding="utf-8") == "import marimo as mo\n"


def test_update_marimo_tool_returns_false_for_missing_file(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "does-not-exist.py"
    assert (
        update_marimo_tool_in_script(
            str(missing), conda_environment="marimo-qa"
        )
        is False
    )
