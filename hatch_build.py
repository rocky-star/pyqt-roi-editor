"""Compile the Qt forms, resources and translations before a build.

Hatchling calls `initialize` once per build, before it collects the
files to package, so a wheel never goes out without the modules
generated from the `.ui`, `.qrc` and `.ts` files that the application
imports.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import PySide6
from hatchling.builders.hooks.plugin.interface import BuildHookInterface

# `project.py` imports its siblings by bare name, so it has to be run
# as a script rather than through `python -m PySide6.scripts.project`.
PROJECT_TOOL = (
    Path(PySide6.__file__).resolve().parent / "scripts" / "project.py"
)


class Pyside6ProjectHook(BuildHookInterface):
    """Run `pyside6-project build` in the build environment."""

    PLUGIN_NAME = 'custom'

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        # The tool shells out to `pyside6-uic` and friends by name,
        # which only exist on the path of the environment running the
        # backend if the frontend put them there.
        env = os.environ.copy()
        scripts = str(Path(sys.executable).parent)
        env['PATH'] = os.pathsep.join([scripts, env.get('PATH', '')])
        subprocess.run(
            [sys.executable, str(PROJECT_TOOL), 'build'],
            cwd=self.root,
            env=env,
            check=True,
        )
