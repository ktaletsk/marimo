# Spec: First-class conda env support in marimo

**Status:** in development on branch `claude/conda-pixi-environments-aUSUg`
**Driver:** Anaconda x marimo launch collab (CoreWeave GPU beta for molab)
**Stakeholders:** Konstantin (marimo), Sarah Tsai (Anaconda DevRel), Jack Evans (Anaconda PM)

## Goal

Make conda (and mamba/micromamba) a first-class option in marimo by targeting **existing environments on the user's machine**. Users pick an environment per notebook; marimo runs the kernel inside it and installs packages into it through the normal missing-package flow.

## Non-goals

We are explicitly **not** building:

- **Single-file reproducibility** for conda notebooks. Sharing a `.py` requires also sharing an `environment.yml` or a README — accepted as the conda-native trade-off.
- **Sandboxing / env provisioning.** Marimo does not create or destroy conda envs. Users continue to use `conda create` / `mamba create` in their shell.
- **Sidecar manifest mutation.** Marimo does not write to `environment.yml` or `pixi.toml`. Users edit those with their existing tooling.
- **Inline `conda-script` block.** Defer until / unless [the draft pixi/conda CEP](https://github.com/prefix-dev/pixi/discussions/3751) lands.
- **Lockfile management.** `conda-lock` / `pixi.lock` already exist for users who want this.

## User experience

### Picking an env

A new control in the notebook header (next to the cell-run toolbar) shows:
**Environment: `marimo-qa` ▾**

Clicking it opens a dropdown listing every conda env on the machine — `base`, plus everything under `~/miniconda3/envs/` or `~/mamba/envs/`. Selecting one persists the choice into the notebook file (see Storage). Selecting "None / system Python" clears the binding.

If the notebook declares an env that doesn't exist on this machine, the header shows a warning state ("`marimo-qa` not found — pick another env") and offers the dropdown.

### Installing packages

Behavior already shipped in Phase 1 — confirming for completeness:

1. Cell runs `import requests`, fails with `ModuleNotFoundError`.
2. Marimo shows the missing-package banner with package name, extras selector, and version dropdown.
3. User clicks **Install**.
4. Marimo runs `conda install -n <selected-env> -c <channels...> -y requests` (or `mamba install ...` / `micromamba install ...`, depending on the manager selected in Settings).
5. Cell re-runs; import succeeds.

**No silent auto-install.** Conda installs can take 10–30 seconds; one-click consent is the right ergonomic.

### Channels

The single most important Anaconda hook.

- **Settings → Package management → Default channels**: ordered list with conda-forge first by default; user can add any channel URL or token URL (the latter handles private/paid channels).
- **Per-notebook channel override**: persisted in the same header block as the env selection (see Storage). Lets a private-channel-using notebook ship with its channel declaration intact even if the global default differs.
- Channels are passed to every conda/mamba/micromamba invocation via `-c <channel>` flags in declaration order.
- Auth for private channels defers entirely to conda's existing mechanisms (token URLs, `~/.condarc`). Marimo does not store credentials.

## Storage format

Use the existing PEP 723 `# /// script` block with a `[tool.marimo]` extension. uv ignores tables under `[tool.X]`, so the same block can hold both PEP 723 dependencies (for uv-mode notebooks) and marimo's env hint (for conda-mode notebooks).

```python
# /// script
# [tool.marimo]
# conda_environment = "marimo-qa"
# conda_channels = ["conda-forge", "nvidia"]
# ///

import marimo as mo
...
```

Properties:

- **Discoverable.** Lives at the top of the file, alongside any other inline metadata. No new convention.
- **Forward-compatible.** When the draft `conda-script` block ships, we can add inline dependencies to the same notebook without breaking the env hint.
- **uv-compatible.** uv reads only `requires-python` and `dependencies` at the top level plus its own `[tool.uv]` — it ignores `[tool.marimo]`.
- **Writable from the UI.** Reuse the existing PEP 723 block parser/writer in `marimo/_utils/inline_script_metadata.py`. Adding/removing `[tool.marimo]` is a small extension.

If a notebook has no block at all, we add one when the user picks an env from the dropdown.

## Implementation plan

### Phase 1 — DONE (shipped on this branch)

- `CondaPackageManager` base + `CondaCliPackageManager` / `MambaPackageManager` / `MicromambaPackageManager` subclasses, each honoring `CONDA_DEFAULT_ENV` via `-n <env>`.
- Inference picks the conda-family binary actually on PATH (`conda` → `mamba` → `micromamba` → `conda` fallback).
- `[tool.marimo.package_management]` recognizes `conda`/`mamba`/`micromamba` as valid managers.
- Frontend dropdown includes all three.
- Install hints, project-marker walk fix, regression tests.

### Phase 2.A — Env discovery

- New helper: `list_conda_environments()` → calls `conda env list --json` (or whichever binary `_preferred_conda_family_manager()` picks).
- Returns `[{"name": str, "path": str, "is_active": bool}, ...]`.
- New API endpoint `GET /api/conda/envs` that returns the list.
- Cached for 30s server-side (env list is slow; new envs are rare).
- Tests: mocked subprocess output.

### Phase 2.B — Read `[tool.marimo]` from the script block

- Extend `inline_script_metadata.py` parser to expose the `[tool.marimo]` sub-table when present.
- Extract `conda_environment` and `conda_channels` keys; ignore unknown keys.
- Surface the values to the kernel manager and the frontend (via the existing notebook open handshake).
- Tests: round-trip read/write of the block.

### Phase 2.C — Header UI: env selector

- New React component: an env-picker control in the notebook header.
- Lists available envs from `/api/conda/envs`, marks the currently-selected one.
- On change: mutates `[tool.marimo.conda_environment]` in the file (server-side, via existing PEP 723 writer pattern) and triggers a kernel restart.
- Warning state when the declared env doesn't exist on this machine.

### Phase 2.D — Kernel launch into selected env

- Today: the kernel inherits `CONDA_DEFAULT_ENV` from the parent shell.
- Phase 2.D: the session manager wraps the kernel spawn with `conda run -n <env> --no-capture-output python -m marimo._kernel ...` (or mamba/micromamba equivalent).
- Activates env vars (`PATH`, `LD_LIBRARY_PATH`, `CONDA_DEFAULT_ENV`) so packages with native libs (MKL, CUDA) work.
- Fallback: if `conda run` fails, set env vars manually and spawn directly.
- Tests: spawn a kernel in a fresh conda env, verify `sys.executable` matches `<env>/bin/python`.

### Phase 2.E — Channel support

- Settings UI: ordered list of default channels (multi-input with chip display).
- Per-notebook override stored in `[tool.marimo.conda_channels]`.
- Plumb to `CondaCliPackageManager.install_command()` / `uninstall()` / `list_packages()` — add `-c <channel>` for each.
- Symmetric to existing `_env_args()` — add `_channel_args()` on the base class.
- Tests: command construction with single channel, multiple channels, no channels.

### Phase 2.F — Demo + docs

- New guide: `docs/guides/package_management/conda_environments.md` covering env picking, channels, private channel auth.
- Anaconda launch demo notebook in `examples/gpu/` — a credible GPU workload (PyTorch + CUDA via conda-forge/nvidia channels) that wouldn't be possible with uv.

## Commit order (suggested)

Each independently mergeable on this branch:

1. Env discovery + `/api/conda/envs` endpoint.
2. `[tool.marimo]` parser extension + tests.
3. Header env-picker UI (read-only first, then writes).
4. Kernel launch via `conda run -n <env>`.
5. Channel selector + plumb-through.
6. Demo notebook + docs.

## Open questions

- **Private channel UX.** Beyond passing `-c <url>`, do we surface anything in the marimo UI for token entry, or fully defer to `~/.condarc`? Defaulting to "fully defer" unless Anaconda has a strong preference.
- **Restart semantics.** Changing the env mid-session requires a kernel restart. Should the picker prompt before restarting, or do it silently? Lean prompt.
- **`base` env**. Should we hide it by default in the picker (since installing into `base` is generally discouraged)? Probably show with a subtle "not recommended" hint.

## Future plans (deferred — was the old Phase 2/3/4/5)

Filed for later, after the launch:

- **Single-file reproducibility via inline conda-script block.** Wait for [prefix-dev/pixi#3751](https://github.com/prefix-dev/pixi/discussions/3751) to ship. When it does, marimo extends `inline_script_metadata.py` to also recognize `# /// conda-script`, mirrors what we already do for PEP 723.
- **`--sandbox` for conda/pixi.** An `EnvironmentProvisioner` abstraction in `marimo/_cli/sandbox.py` so `marimo edit --sandbox` can create/reuse a pixi env from a sidecar `pixi.toml`. Larger refactor; not on the critical path for the Anaconda launch.
- **Sidecar manifest mutation.** Marimo writes to `environment.yml` / `pixi.toml` when packages are installed. Skipped because conda users edit these by hand and a tool-driven write loses comments/ordering. Revisit if user demand surfaces.
- **Lockfile awareness.** Surface `pixi.lock` / `conda-lock` drift in the UI. Not needed for v1.
- **Env creation from the UI.** "Create new env" button in the picker that wraps `conda create -n <name> python=<v>`. Defer — users can run one shell command. Worth adding if telemetry shows friction.
- **Pixi-mode env targeting parity.** Same UI for pixi project envs (`pixi shell` style). Pixi case is rarer in the conda-user audience; defer until demand justifies.

## References

- [PEP 723 — Inline script metadata](https://peps.python.org/pep-0723/)
- [Draft CEP for pixi conda-script block](https://github.com/prefix-dev/pixi/discussions/3751)
- [conda env list documentation](https://docs.conda.io/projects/conda/en/latest/commands/env/list.html)
- [conda run documentation](https://docs.conda.io/projects/conda/en/latest/commands/run.html)
- Prior conversation: branch `claude/conda-pixi-environments-aUSUg`, commits `dd48d24` (Phase 1), `c14a1cd` (inference fix), `98b063d` (mamba/micromamba)
