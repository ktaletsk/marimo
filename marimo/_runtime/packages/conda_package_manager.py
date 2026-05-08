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
    """Manages packages with the ``conda`` CLI.

    Operates on the currently active conda environment (as inferred from
    ``CONDA_DEFAULT_ENV``); does not provision new environments.
    """

    name = "conda"

    def _env_args(self) -> list[str]:
        env = os.environ.get("CONDA_DEFAULT_ENV")
        return ["-n", env] if env else []

    def install_command(
        self, package: str, *, upgrade: bool, group: str | None = None
    ) -> list[str]:
        # The `group` parameter is accepted for interface compatibility, but is ignored.
        del group
        subcommand = "update" if upgrade else "install"
        return [
            "conda",
            subcommand,
            *self._env_args(),
            "-y",
            *split_packages(package),
        ]

    async def uninstall(self, package: str, group: str | None = None) -> bool:
        # The `group` parameter is accepted for interface compatibility, but is ignored.
        del group
        return await self.run(
            [
                "conda",
                "remove",
                *self._env_args(),
                "-y",
                *split_packages(package),
            ],
            log_callback=None,
        )

    def list_packages(self) -> list[PackageDescription]:
        if not self.is_manager_installed():
            return []

        try:
            proc = subprocess.run(
                ["conda", "list", *self._env_args(), "--json"],
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
