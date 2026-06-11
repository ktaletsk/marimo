# Copyright 2026 Marimo. All rights reserved.
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, cast

from marimo import _loggers
from marimo._cli.files.file_path import FileContentReader
from marimo._utils.code import hash_code
from marimo._utils.paths import normalize_path
from marimo._utils.scripts import (
    REGEX as _SCRIPT_BLOCK_REGEX,
    read_pyproject_from_script,
)

LOGGER = _loggers.marimo_logger()

# Sentinel used by update_marimo_tool_in_script to distinguish
# "leave unchanged" from "delete this key" (which is signaled by None).
_UNSET = object()


class PyProjectReader:
    def __init__(
        self,
        project: dict[str, Any],
        *,
        config_path: str | None,
        name: str | None = None,
    ):
        self.project = project
        self.config_path = config_path
        self.name = name

    @staticmethod
    def from_filename(name: str) -> PyProjectReader:
        return PyProjectReader(
            name=name,
            project=_get_pyproject_from_filename(name) or {},
            config_path=name,
        )

    @staticmethod
    def from_script(script: str) -> PyProjectReader:
        return PyProjectReader(
            project=read_pyproject_from_script(script) or {},
            config_path=None,
            name=None,
        )

    @property
    def extra_index_urls(self) -> list[str]:
        # See https://docs.astral.sh/uv/reference/settings/#pip_extra-index-url
        return (  # type: ignore[no-any-return]
            self.project.get("tool", {})
            .get("uv", {})
            .get("extra-index-url", [])
        )

    @property
    def index_configs(self) -> list[dict[str, str]]:
        # See https://docs.astral.sh/uv/reference/settings/#index
        return self.project.get("tool", {}).get("uv", {}).get("index", [])  # type: ignore[no-any-return]

    @property
    def index_url(self) -> str | None:
        # See https://docs.astral.sh/uv/reference/settings/#pip_index-url
        return (  # type: ignore[no-any-return]
            self.project.get("tool", {}).get("uv", {}).get("index-url", None)
        )

    @property
    def python_version(self) -> str | None:
        try:
            version = self.project.get("requires-python")
            # Only return string version requirements
            if not isinstance(version, str):
                return None
            return version
        except Exception as e:
            LOGGER.warning(f"Failed to parse Python version requirement: {e}")
            return None

    @property
    def dependencies(self) -> list[str]:
        return self.project.get("dependencies", [])  # type: ignore[no-any-return]

    @property
    def marimo_tool(self) -> dict[str, Any]:
        """The ``[tool.marimo]`` sub-table from the inline script metadata."""
        tool = self.project.get("tool", {})
        marimo = tool.get("marimo", {})
        return marimo if isinstance(marimo, dict) else {}

    @property
    def conda_environment(self) -> str | None:
        """Name of the conda env this notebook is bound to, if any."""
        val = self.marimo_tool.get("conda_environment")
        return val if isinstance(val, str) and val else None

    @property
    def conda_channels(self) -> list[str]:
        """Per-notebook conda channel overrides. Empty list when unset."""
        val = self.marimo_tool.get("conda_channels", [])
        if not isinstance(val, list):
            return []
        return [c for c in val if isinstance(c, str)]

    @property
    def requirements_txt_lines(self) -> list[str]:
        """Get dependencies from string representation of script."""
        try:
            return _pyproject_toml_to_requirements_txt(
                self.project, self.config_path
            )
        except Exception as e:
            LOGGER.warning(f"Failed to parse dependencies: {e}")
            return []


def _get_pyproject_from_filename(name: str) -> dict[str, Any] | None:
    try:
        contents, _ = FileContentReader().read_file(name)
        if name.endswith(".py"):
            return read_pyproject_from_script(contents)

        if not (name.endswith((".md", ".qmd"))):
            raise ValueError(
                f"Unsupported file type: {name}. Only .py and .md files are supported."
            )

        headers = get_headers_from_markdown(contents)
        header = headers["pyproject"]
        if not header:
            header = headers["header"]
        elif headers["header"]:
            pyproject = PyProjectReader.from_script(headers["header"])
            if pyproject.dependencies or pyproject.python_version:
                LOGGER.warning(
                    "Both header and pyproject provide dependencies. "
                    "Preferring pyproject."
                )
        return read_pyproject_from_script(header)
    except FileNotFoundError:
        return None
    except Exception:
        LOGGER.warning(f"Failed to read pyproject.toml from {name}")
        return None


def _pyproject_toml_to_requirements_txt(
    pyproject: dict[str, Any],
    config_path: str | None = None,
) -> list[str]:
    """
    Convert a pyproject.toml file to a requirements.txt file.

    If there is a `[tool.uv.sources]` section, we resolve the dependencies
    to their corresponding source.

    # dependencies = [
    #     "python-gcode",
    # ]
    #
    # [tool.uv.sources]
    # python-gcode = { git = "https://github.com/fetlab/python_gcode", rev = "new" }

    Args:
        pyproject: A dict containing the pyproject.toml contents.
        config_path: The path to the pyproject.toml or inline script metadata. This
            is used to resolve relative paths used in the dependencies.
    """
    dependencies = cast(list[str], pyproject.get("dependencies", []))
    if not dependencies:
        return []

    uv_sources = pyproject.get("tool", {}).get("uv", {}).get("sources", {})

    for dependency, source in uv_sources.items():
        # Find the index of the dependency. This may have a version
        # attached, so we cannot do .index()
        dep_index: int | None = None
        for i, dep in enumerate(dependencies):
            if dep == dependency or dep.startswith(
                (
                    f"{dependency}==",
                    f"{dependency}<",
                    f"{dependency}>",
                    f"{dependency}~",
                )
            ):
                dep_index = i
                break

        if dep_index is None:
            continue

        new_dependency = None

        # Handle git dependencies
        if "git" in source:
            git_url = f"git+{source['git']}"
            ref = (
                source.get("rev") or source.get("branch") or source.get("tag")
            )
            new_dependency = (
                f"{dependency} @ {git_url}@{ref}"
                if ref
                else f"{dependency} @ {git_url}"
            )
        # Handle local paths
        elif "path" in source:
            source_path = Path(source["path"])
            # If path is relative and we have a config path, resolve it relative to the config path
            if not source_path.is_absolute() and config_path:
                config_dir = Path(config_path).parent
                source_path = normalize_path(config_dir / source_path)
            new_dependency = f"{dependency} @ {source_path!s}"

        # Handle URLs
        elif "url" in source:
            new_dependency = f"{dependency} @ {source['url']}"

        if new_dependency:
            if source.get("marker"):
                new_dependency += f"; {source['marker']}"

            dependencies[dep_index] = new_dependency

    return dependencies


def is_marimo_dependency(dependency: str) -> bool:
    # Split on any version specifier
    without_version = re.split(r"[=<>~]+", dependency)[0]
    # Match marimo and marimo[extras], but not marimo-<something-else>
    return without_version == "marimo" or without_version.startswith("marimo[")


def get_headers_from_markdown(contents: str) -> dict[str, str]:
    from marimo._convert.markdown.to_ir import extract_frontmatter

    frontmatter, _ = extract_frontmatter(contents)
    return get_headers_from_frontmatter(frontmatter)


def get_headers_from_frontmatter(
    frontmatter: dict[str, Any],
) -> dict[str, str]:
    from marimo._utils.scripts import wrap_script_metadata

    headers = {"pyproject": "", "header": ""}

    pyproject = frontmatter.get("pyproject", "")
    if pyproject:
        if not pyproject.startswith("#"):
            # Wrap raw TOML content in PEP 723 format
            pyproject = wrap_script_metadata(pyproject)
        headers["pyproject"] = pyproject
    headers["header"] = frontmatter.get("header", "")
    return headers


def has_marimo_in_script_metadata(filepath: str) -> bool | None:
    """Check if marimo is in the file's PEP 723 script metadata dependencies.

    Returns:
        True if marimo is in dependencies
        False if script metadata exists but marimo is not in dependencies
        None if file has no script metadata
    """

    project = _get_pyproject_from_filename(filepath)
    if project is None:
        return None

    dependencies = project.get("dependencies", [])
    return any(is_marimo_dependency(dep) for dep in dependencies)


def script_metadata_hash_from_filename(name: str) -> str | None:
    project = _get_pyproject_from_filename(name)
    if project is None:
        return None
    serialized = json.dumps(
        project,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hash_code(serialized)


def update_marimo_tool_in_script(
    filepath: str,
    *,
    conda_environment: str | None | Any = _UNSET,
    conda_channels: list[str] | None | Any = _UNSET,
) -> bool:
    """Set or clear ``[tool.marimo]`` keys in a notebook's PEP 723 block.

    For each keyword: pass a value to set it, pass ``None`` to delete the
    key, omit the kwarg to leave it untouched. Returns ``True`` on
    success, ``False`` if the file cannot be read or rewritten.

    If the file has no ``# /// script`` block and at least one key is
    being set, a new block is prepended at the top of the file.
    """
    updates: dict[str, Any] = {}
    if conda_environment is not _UNSET:
        updates["conda_environment"] = conda_environment
    if conda_channels is not _UNSET:
        updates["conda_channels"] = conda_channels
    if not updates:
        return True

    try:
        path = Path(filepath)
        original = path.read_text(encoding="utf-8")
    except OSError as e:
        LOGGER.warning(
            "Failed to read %s for marimo-tool update: %s", filepath, e
        )
        return False

    try:
        new_contents = _apply_marimo_tool_updates(original, updates)
    except Exception as e:
        LOGGER.warning("Failed to update [tool.marimo] in %s: %s", filepath, e)
        return False

    if new_contents == original:
        return True

    try:
        path.write_text(new_contents, encoding="utf-8")
    except OSError as e:
        LOGGER.warning(
            "Failed to write %s after marimo-tool update: %s", filepath, e
        )
        return False
    return True


def _apply_marimo_tool_updates(contents: str, updates: dict[str, Any]) -> str:
    """Pure-function core of :func:`update_marimo_tool_in_script`.

    Splits out for testability — takes file contents, returns new contents.
    """
    import tomlkit

    script_matches = [
        m
        for m in re.finditer(_SCRIPT_BLOCK_REGEX, contents)
        if m.group("type") == "script"
    ]
    if len(script_matches) > 1:
        raise ValueError("Multiple script blocks found")
    match = script_matches[0] if script_matches else None

    if match is None:
        # No script block yet — create one if there is anything to write.
        toml_doc = tomlkit.document()
    else:
        # Strip the leading "# " / "#" from each metadata line.
        raw_lines = match.group("content").splitlines(keepends=True)
        stripped = "".join(
            line[2:] if line.startswith("# ") else line[1:]
            for line in raw_lines
        )
        toml_doc = tomlkit.parse(stripped)

    tool_table = toml_doc.get("tool")
    if tool_table is None:
        tool_table = tomlkit.table()
        toml_doc["tool"] = tool_table

    marimo_table = tool_table.get("marimo")
    if marimo_table is None:
        marimo_table = tomlkit.table()
        tool_table["marimo"] = marimo_table

    changed = False
    for key, value in updates.items():
        if value is None:
            if key in marimo_table:
                del marimo_table[key]
                changed = True
        else:
            marimo_table[key] = value
            changed = True

    # Tidy up: drop [tool.marimo] / [tool] if they end up empty.
    if not marimo_table:
        del tool_table["marimo"]
    if not tool_table:
        del toml_doc["tool"]

    if not changed:
        return contents

    rendered_toml = tomlkit.dumps(toml_doc).rstrip()

    if not rendered_toml:
        # The block ends up empty (last key was deleted). Drop the entire
        # `# /// script ... # ///` block rather than leaving an empty husk.
        if match is None:
            return contents
        # Eat one trailing newline after `# ///` if present, so we don't
        # leave a stray blank line at the top of the file.
        end = match.end()
        if end < len(contents) and contents[end] == "\n":
            end += 1
        return contents[: match.start()] + contents[end:]

    rendered_block_lines = ["# /// script"]
    for line in rendered_toml.split("\n"):
        rendered_block_lines.append(f"# {line}" if line else "#")
    rendered_block_lines.append("# ///")
    rendered_block = "\n".join(rendered_block_lines)

    if match is None:
        # Prepend new block.
        if contents and not contents.startswith("\n"):
            return rendered_block + "\n\n" + contents
        return rendered_block + contents

    # Replace existing block in place.
    start, end = match.start(), match.end()
    return contents[:start] + rendered_block + contents[end:]
