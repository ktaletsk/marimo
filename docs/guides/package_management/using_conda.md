# Using conda environments

marimo notebooks can run inside an existing [conda](https://docs.conda.io/) /
[mamba](https://github.com/mamba-org/mamba) /
[micromamba](https://mamba.readthedocs.io/en/latest/user_guide/micromamba.html)
environment. There are three ways to wire this up — pick whichever
matches how you launch marimo.

> Note: this is the **opposite** trade-off from
> [inlining dependencies](inlining_dependencies.md). Conda envs are
> shared, heavy, and managed externally; the notebook doesn't carry the
> packages with it. The env *name* may travel with the notebook (see
> [Way 2](#way-2-declare-the-env-inside-the-notebook)), but the env
> itself is created and maintained by you.

## Way 1: activate, then launch

The simplest pattern and the one most conda users already know.

```bash
mamba activate marimo-qa
marimo edit notebook.py
```

The marimo kernel inherits ``CONDA_DEFAULT_ENV``, ``CONDA_PREFIX``, and
``PATH`` from your shell. Imports resolve from the env's
``site-packages``; the kernel's ``sys.executable`` points at the env's
Python; packages installed through marimo's missing-package banner land
in the active env.

In Settings → Package management, pick **conda**, **mamba**, or
**micromamba** to match the binary on your PATH. Picking ``conda`` will
auto-fall-back to ``mamba`` or ``micromamba`` if a real ``conda`` binary
isn't present (common with [mambaforge](https://github.com/conda-forge/miniforge)
installs where ``conda`` is a shell alias).

## Way 2: declare the env inside the notebook

Put the env name in the notebook's PEP 723 metadata block:

```python
# /// script
# [tool.marimo]
# conda_environment = "marimo-qa"
# ///

import marimo as mo
import polars as pl
```

When you launch `marimo edit notebook.py` (from any shell), marimo
reads the declaration, looks the env up on the machine, and spawns the
kernel inside it. You don't need to activate the env yourself.

Sharing a notebook then implies "open this in env ``marimo-qa``,
please" — a small, conda-native form of reproducibility hint. The
recipient runs:

```bash
mamba env create -f environment.yml  # creates marimo-qa
marimo edit notebook.py              # marimo picks up the binding
```

If the declared env doesn't exist on the machine, marimo logs a
warning and falls back to the default kernel python. You can also
combine this with [Way 1](#way-1-activate-then-launch) — activation
takes precedence over the declaration.

## Way 3: launcher integration (JupyterHub, Anaconda Desktop, …)

When marimo is launched by a launcher (not by the user typing a
command), the launcher decides which env to spawn into. The contract
the launcher follows is:

1. If you want the notebook to run in a specific conda env, set
   ``CONDA_DEFAULT_ENV``, ``CONDA_PREFIX``, ``CONDA_PYTHON_EXE`` and
   prepend ``$CONDA_PREFIX/bin`` to ``PATH`` in the marimo subprocess
   environment before spawning. Functionally equivalent to running
   ``mamba activate <env>`` in a wrapper script.

2. Alternatively, read ``[tool.marimo].conda_environment`` from the
   notebook's PEP 723 block via
   ``marimo._utils.inline_script_metadata.PyProjectReader`` and use it
   to pre-fill the env picker in your launcher's UI, or pass it
   straight through as the env to activate.

marimo itself does not surface an env-picker UI. The launcher owns
that question — the user already picked the env when they chose the
launcher's button. This avoids the awkward case of two env pickers
(the launcher's and marimo's) racing for the same decision.

## Installing packages from inside a notebook

Regardless of which way you launched, marimo's missing-package banner
respects the active conda-family manager:

- For a real ``conda`` install: ``conda install -n <env> -y <pkg>``
- For mamba: ``mamba install -n <env> -y <pkg>``
- For micromamba: ``micromamba install -n <env> -y <pkg>``

Channels come from your ``~/.condarc`` (or per-env ``condarc``).
marimo does not currently surface a per-notebook channel selector —
configure channels through conda's native mechanisms.

For private channels (e.g. ``https://repo.anaconda.cloud/repo/...``),
[set up the token via
conda](https://docs.anaconda.com/anacondaorg/user-guide/tasks/work-with-private-channels/)
once and marimo's installs will use it automatically.

## What about pixi?

Pixi has its own project layout (``pixi.toml``) and is a different
manager rather than a conda variant. Picking **pixi** in Settings runs
``pixi add`` / ``pixi remove``. There is no ``conda_environment``
binding equivalent for pixi today; the recommended pattern is the
sibling guide [Inlining dependencies](inlining_dependencies.md) (uv)
or a pixi project directory next to the notebook.
