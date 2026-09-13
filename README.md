# hermes-sway-plugin

A native [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin for
**Sway 1.9**: bounded desktop inspection, verified runtime control, best-effort
application launching, and plugin-owned persistent configuration that keeps
working when Hermes is not running.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Sway](https://img.shields.io/badge/sway-1.9-informational)

Standard library only — no runtime dependencies. Linux/Wayland only.

## Supported versions and scope

| | |
|---|---|
| Sway | **1.9** (enforced). Any other major/minor fails closed with `unsupported_sway_version`. |
| Python | 3.10 or newer |
| Hermes | current native plugin API (`plugin.yaml` v1-compatible manifest, `ctx.register_tool`, `ctx.register_skill`) |
| Platforms | Linux/Wayland |

The plugin targets Sway 1.9 deliberately: it renders only commands and
configuration statements that Sway 1.9 implements, and it refuses to
opportunistically use newer syntax. It is not an i3 plugin, and it is not a
generic `swaymsg` passthrough — there is no raw-command parameter anywhere.

## Installation

```bash
# From GitHub (recommended)
hermes plugins install lessucettes/hermes-sway-plugin --enable

# Or validate a local checkout first
git clone https://github.com/lessucettes/hermes-sway-plugin
cd hermes-sway-plugin
hermes plugins validate .
hermes plugins doctor . --ci
hermes plugins install lessucettes/hermes-sway-plugin --ref <commit-sha> --no-enable
hermes plugins enable sway
```

Then confirm the toolset is available:

```bash
hermes plugins list
hermes tools
```

The plugin registers the `sway` toolset (seven tools) and the bundled
`sway:sway` skill. Load the skill in a session with `skill_view("sway:sway")`;
it is not auto-loaded.

## Tools

| Tool | Scope | Purpose |
|---|---|---|
| `sway_inspect` | read-only | Sway version, focused window/workspace/output, windows, workspaces, outputs, marks, or a compact normalized tree. |
| `sway_window` | runtime | Focus, move to an exact workspace/output, directional move, float/fullscreen, resize, position, scratchpad, sticky, marks, and a guarded close. |
| `sway_workspace` | runtime | Focus or create, rename, or move an existing workspace to an exact output. |
| `sway_layout` | runtime | Set a container's parent layout, split at a container, or exactly swap two containers. |
| `sway_launch` | runtime | Launch one argv process without a shell and report best-effort window correlation. |
| `sway_rule` | persistent | Managed window and workspace-to-output rules in Sway configuration. |
| `sway_startup` | persistent | Managed `exec` / explicitly acknowledged `exec_always` startup entries. |

Every handler returns exactly one JSON string:

```json
{"ok": true, "scope": "runtime", "data": { }, "warnings": []}
{"ok": false, "error": {"code": "target_not_found", "message": "…", "details": {}}, "recoverable": true}
```

### Working style

1. Inspect first, then mutate a **fresh** `con_id` from that inspection.
2. A singular mutation must resolve to **exactly one** target; zero or multiple
   matches are an error, never a first-match guess.
3. Every runtime mutation is verified against a freshly fetched tree, and the
   observed result is reported. Sway command batches are not transactional, so
   the plugin sends the smallest possible command instead of pretending to roll
   back.
4. Runtime changes are session state. Use `sway_rule` / `sway_startup` for
   behavior that must survive a restart.

## Persistent configuration

Persistent tools write **only** plugin-owned files and never edit your Sway
configuration for you.

Add the owned include to your Sway configuration once:

```sway
include ~/.config/sway/hermes/*.conf
```

| File | Contents |
|---|---|
| `hermes-sway-plugin-rules.conf` | Window and workspace-to-output rules |
| `hermes-sway-plugin-startup.conf` | Startup commands |

Default location: `${XDG_CONFIG_HOME:-~/.config}/sway/hermes` with the main
configuration at `${XDG_CONFIG_HOME:-~/.config}/sway/config`. Set the plugin's
`config_dir` to manage a different configuration directory. Every persistent
result returns the resolved `include` path, so the location is never implicit.

```bash
chmod 700 ~/.config/sway/hermes   # recommended; generated files are mode 0600
```

### Ownership boundaries and safety

- Each generated file carries deterministic metadata headers and a SHA-256
  digest of its body. Hand edits are **refused** (`manual_edit_refused`) instead
  of being silently absorbed or overwritten.
- Writes are serialized with `flock`, staged in the same directory, validated
  with `sway -C -c`, and only then replaced atomically. A timestamped backup is
  kept (`backup_keep`, default 10).
- Reload happens only when the running configuration contains the exact include
  line. Otherwise the validated write succeeds with an `include_not_configured`
  warning and no reload. Pending reload confirmation restores the backup; that
  rollback is **configuration rollback only** and cannot terminate a process
  that `exec_always` already started.
- Overlapping external `assign` / `for_window` / `workspace … output` statements
  are detected conservatively and block writes unless explicitly acknowledged
  with `allow_external_conflicts`. The plugin never edits or reorders your rules.
- New persistent rules apply to **new windows only**; they are not retroactive.

Manual recovery:

```bash
cp ~/.config/sway/hermes/hermes-sway-plugin-rules.conf.bak.1 \
   ~/.config/sway/hermes/hermes-sway-plugin-rules.conf && swaymsg reload
```

### Example: place a chat client

```jsonc
// sway_rule add
{
  "action": "add",
  "rule_id": "telegram",
  "kind": "window",
  "match": {"app_id": {"value": "org.telegram.desktop", "mode": "exact"}},
  "intended_cardinality": "one",
  "destination": {"workspace": "4"},
  "effects": {"floating": true, "width_px": 800, "height_px": 600, "center": true}
}
```

Two otherwise identical windows cannot be separated by Sway rules. Give each
application a stable identity first (for example `kitty --app-id kitty.chat` and
`kitty --app-id kitty.build`, or distinct XWayland `--class` values) and match
that exact value.

## Configuration keys

| Key | Default | Meaning |
|---|---|---|
| `ipc_timeout_seconds` | 3.0 | Sway IPC request timeout. |
| `reload_timeout_seconds` | 5.0 | Wait for a finished reload. |
| `launch_timeout_seconds` | 10.0 | Window-correlation window after a launch. |
| `config_dir` | `""` | Managed directory; empty uses the XDG default above. |
| `backup_keep` | 10 | Backups retained after a successful write. |

## Limitations

- **Sway 1.9 only.** Other versions are rejected rather than partially
  supported.
- **No raw commands** and no arbitrary relative insertion ("place A immediately
  right of B"), saved-tree restore, placeholder/layout import, or complete
  historical topology restore. Sway 1.9 does not offer a reliable API for those.
- **Launch correlation is best-effort.** It reports `matched`, `timeout`, or
  `ambiguous` plus the evidence used. Process reuse, daemonizing applications,
  and identical identities remain limitations; a successful process start is
  never reported as a successful window match.
- **`sway_window close` terminates the client, not just one view.** Sway's `kill`
  signals the owning process, so closing one window of a multi-window client
  (single-instance terminal emulator, IDE, browser) can close its other windows
  as well. Check that the client owns no other window before closing it.
- **Persistent geometry is applied at map time.** `width_px` / `height_px`
  effects are issued by Sway's `for_window`; a window assigned to a workspace
  that is not visible may keep the size its client requested. Verify the geometry
  after the workspace is shown rather than assuming the rule won.
- **Directional moves and centered positions are compositor-dependent.** The
  observed result is reported, and the plugin tells you to inspect the layout.
- **Geometry and sticky actions require an explicit floating, non-fullscreen
  window.** The plugin does not enable floating implicitly to satisfy a request.
- **No cross-restart container identity.** `con_id` values do not survive a
  restart; re-inspect.
- **External conflicts are reported, not resolved.** There is no include
  ordering that universally wins for both first-match `assign` and later-effect
  `for_window` rules, so overlap is yours to settle.

## Testing and validation

```bash
uv venv .venv && uv pip install --python .venv/bin/python -e '.[dev]'
uv run pytest -q                       # full suite, no compositor required
hermes plugins validate .
hermes plugins doctor . --ci
SWAYSOCK="$SWAYSOCK" uv run python scripts/live_smoke.py
```

The test suite drives the real i3-ipc framing over a scripted Unix socket, so
nothing touches your desktop. `tests/test_hermes_discovery.py` loads the plugin
through the real Hermes discovery path and needs a current checkout:

```bash
HERMES_REPO=/path/to/hermes-agent uv run pytest tests/test_hermes_discovery.py -q
```

`scripts/live_smoke.py` is the only test that talks to a running compositor. It
sends `GET_VERSION`, `GET_TREE`, `GET_WORKSPACES`, and `GET_OUTPUTS` only — never
`RUN_COMMAND` — and prints a bounded summary:

```
Sway 1.9; outputs=1; workspaces=2; windows=3
```

Behaviors that cannot be asserted headlessly (real placement after a session
restart, reload-timeout recovery on a disposable configuration) are described
under *Limitations* rather than claimed by the automated suite.

## License

[MIT](LICENSE) © 2026 lessucettes.

## Development notes

This project was developed with AI coding assistance. Implementation, tests, and
documentation were authored in a human-directed workflow with contributions from
the following models:

- GPT-5.6 Sol
- GPT-5.6 Terra
- GLM-5.3 Flash
- DeepSeek V4.1 Flash

These models and their providers are credited as development tools only. They do
not own, endorse, sponsor, or maintain this project, and they provide no warranty
or support for it. All design decisions, review, and responsibility for the
published code rest with the repository maintainer.
