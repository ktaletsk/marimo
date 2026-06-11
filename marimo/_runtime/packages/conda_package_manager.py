# Copyright 2026 Marimo. All rights reserved.
from __future__ import annotations

import json
import os
import subprocess

from marimo._runtime.packages.module_name_to_conda_name import (
    module_name_to_conda_name,
)
from marimo._runtime.packages.package_manager import (
    CanonicalizingPackageManager,
    PackageDescription,
)
from marimo._runtime.packages.utils import split_packages


class CondaPackageManager(CanonicalizingPackageManager):
    """Base class for conda-family package managers (conda, pixi).

    Subclasses provide the concrete CLI invocations.
    """

    docs_url = "https://docs.conda.io/projects/conda/"

    def _construct_module_name_mapping(self) -> dict[str, str]:
        return module_name_to_conda_name()


class CondaCliPackageManager(CondaPackageManager):
    """Manages packages with a ``conda``-family CLI.

    Operates on the currently active conda environment (as inferred from
    ``CONDA_DEFAULT_ENV``); does not provision new environments.

    The user-visible ``name`` is the manager selected in settings; the
    *binary* actually executed is resolved at call-time from the
    conda-family candidates that subclasses declare. This lets a user
    pick "conda" on a mambaforge install where ``conda`` is only a shell
    alias and have things still work — mamba is API-compatible for the
    subcommands marimo uses.
    """

    name = "conda"

    # Binaries to try in order. Subclasses constrain this list to enforce
    # a specific binary (e.g. MambaPackageManager forces mamba only).
    _binary_candidates: tuple[str, ...] = ("conda", "mamba", "micromamba")

    def _resolve_binary(self) -> str | None:
        """First available binary in ``_binary_candidates``, or ``None``."""
        from marimo._dependencies.dependencies import DependencyManager

        for candidate in self._binary_candidates:
            if DependencyManager.which(candidate):
                return candidate
        return None

    def is_manager_installed(self) -> bool:
        if self._resolve_binary() is not None:
            return True
        from marimo._dependencies.dependencies import DependencyManager

        # Avoid the misleading "{name} is not available" log when none of
        # the candidates are installed — the alert UI carries a clearer
        # message. Keep the standard path for single-binary subclasses.
        if len(self._binary_candidates) == 1:
            return bool(DependencyManager.which(self._binary_candidates[0]))
        return False

    def _env_args(self) -> list[str]:
        env = os.environ.get("CONDA_DEFAULT_ENV")
        return ["-n", env] if env else []

    def install_command(
        self, package: str, *, upgrade: bool, group: str | None = None
    ) -> list[str]:
        # The `group` parameter is accepted for interface compatibility, but is ignored.
        del group
        binary = self._resolve_binary() or self._binary_candidates[0]
        subcommand = "update" if upgrade else "install"
        return [
            binary,
            subcommand,
            *self._env_args(),
            "-y",
            *split_packages(package),
        ]

    async def uninstall(self, package: str, group: str | None = None) -> bool:
        # The `group` parameter is accepted for interface compatibility, but is ignored.
        del group
        binary = self._resolve_binary() or self._binary_candidates[0]
        return await self.run(
            [
                binary,
                "remove",
                *self._env_args(),
                "-y",
                *split_packages(package),
            ],
            log_callback=None,
        )

    def list_packages(self) -> list[PackageDescription]:
        binary = self._resolve_binary()
        if binary is None:
            return []

        try:
            proc = subprocess.run(
                [binary, "list", *self._env_args(), "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            packages = json.loads(proc.stdout)
            return [
                PackageDescription(name=pkg["name"], version=pkg["version"])
                for pkg in packages
            ]
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return []


class MambaPackageManager(CondaCliPackageManager):
    """Manages packages with the ``mamba`` CLI.

    mamba is conda-CLI-compatible for the subcommands marimo uses.
    """

    name = "mamba"
    _binary_candidates = ("mamba",)


class MicromambaPackageManager(CondaCliPackageManager):
    """Manages packages with the ``micromamba`` CLI."""

    name = "micromamba"
    _binary_candidates = ("micromamba",)


class PixiPackageManager(CondaPackageManager):
    name = "pixi"

    def install_command(
        self, package: str, *, upgrade: bool, group: str | None = None
    ) -> list[str]:
        # The `group` parameter is accepted for interface compatibility, but is ignored.
        del group
        return [
            "pixi",
            "upgrade" if upgrade else "add",
            *split_packages(package),
        ]

    async def uninstall(self, package: str, group: str | None = None) -> bool:
        # The `group` parameter is accepted for interface compatibility, but is ignored.
        del group
        return await self.run(
            ["pixi", "remove", *split_packages(package)], log_callback=None
        )

    def list_packages(self) -> list[PackageDescription]:
        if not self.is_manager_installed():
            return []

        try:
            proc = subprocess.run(
                ["pixi", "list", "--json"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=True,
            )
            packages = json.loads(proc.stdout)
            return [
                PackageDescription(name=pkg["name"], version=pkg["version"])
                for pkg in packages
            ]
        except (subprocess.CalledProcessError, json.JSONDecodeError):
            return []
