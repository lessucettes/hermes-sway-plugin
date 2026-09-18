# hermes-sway-plugin

A native [Hermes Agent](https://github.com/NousResearch/hermes-agent) plugin for
**Sway 1.9**. It gives Hermes typed tools for inspecting and controlling the
current desktop, launching applications, and maintaining plugin-owned Sway rules
and startup entries.

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Sway](https://img.shields.io/badge/sway-1.9-informational)

The runtime uses only the Python standard library. The plugin is for
Linux/Wayland and supports Sway 1.9 only.

## Installation

```bash
# Install and enable from GitHub. Review the security-scan findings first;
# --force acknowledges a CAUTION verdict for this community source.
hermes plugins install lessucettes/hermes-sway-plugin --force --enable

# Or inspect and validate a checkout before installing a pinned revision
git clone https://github.com/lessucettes/hermes-sway-plugin
cd hermes-sway-plugin
hermes plugins validate .
hermes plugins doctor . --ci
hermes plugins install lessucettes/hermes-sway-plugin --force --ref <40-character-commit-sha> --no-enable
hermes plugins enable sway
```

Hermes still blocks a `DANGEROUS` scan verdict; `--force` only confirms that you
reviewed and accept an overridable `CAUTION` verdict or replaces an existing
installation.

Confirm registration with:

```bash
hermes plugins list
hermes tools
```

The plugin registers the `sway` toolset with seven tools and the optional
`sway:sway` skill. Load the skill with `skill_view("sway:sway")` when you want
its Sway-specific operating guidance; the skill is not auto-loaded.

## Use it through Hermes

Ask for the desktop outcome in ordinary language. Hermes can select the tool and
arguments from the request, for example:

- “Move Firefox to workspace 3.”
- “Make the focused terminal floating, resize it to 1000 by 700, and center it.”
- “Put Telegram on workspace 4 whenever it opens.”
- “Start kanshi when Sway starts, but not after every reload.”
- “Launch foot and tell me whether a new window can be correlated with it.”
- “Show me the current Sway workspaces and outputs.”

An inspection is useful when the requested window is ambiguous or when a fresh
container ID is needed. It is not a mandatory first step when an exact target is
already known. Persistent window rules affect future matching windows; if a
request also means “change the already-open window now,” Hermes must use a
runtime window action as well.

## Tools

| Tool | Scope | Purpose |
|---|---|---|
| `sway_inspect` | read-only | Return Sway version and focused state, or bounded views of windows, workspaces, outputs, marks, and the normalized tree. The default view is a compact summary. |
| `sway_window` | runtime | Focus or move one window; change floating, fullscreen, scratchpad, sticky, marks, size, or position; request that Sway close it. |
| `sway_workspace` | runtime | Focus or create an exact workspace, rename one, or move one to an exact output. |
| `sway_layout` | runtime | Set the selected container's parent layout, split at a container, or swap two containers. |
| `sway_launch` | runtime | Start one argv-based process without a shell and optionally observe possible new windows. |
| `sway_rule` | persistent | Manage plugin-owned window rules and workspace-to-output declarations. |
| `sway_startup` | persistent | Manage plugin-owned `exec` and explicitly acknowledged `exec_always` entries. |

There is no raw Sway command argument. Every handler returns one JSON string in
a stable success or error envelope:

```json
{"ok": true, "scope": "runtime", "data": {}, "warnings": []}
{"ok": false, "error": {"code": "target_not_found", "message": "…", "details": {}}, "recoverable": true}
```

### Runtime behavior

- Singular window and layout operations resolve exactly one target by `con_id`,
  mark, or conjunctive exact fields. Zero or multiple matches are errors rather
  than first-match guesses. A `con_id` is session-local and should be recent.
- Exact workspace focus and move operations use Sway's
  `--no-auto-back-and-forth`, so requesting a named workspace does not toggle to
  the previous workspace.
- Runtime operations query fresh state after the command when there is an
  observable postcondition. Sway command batches are not transactional.
- `set_parent_layout` selects the requested container because Sway's `layout`
  command changes that selected container's parent layout.
- `split_at` creates a split at the selected container. When one current sibling
  needs its own nested group, split at that sibling first; use
  `set_parent_layout` only when the existing parent—and therefore the current
  sibling group—should change layout.
- Floating-window coordinates support workspace-relative and global absolute
  positioning. Resize accepts floating or tiled non-fullscreen windows and one
  or both dimensions. If `unit` is omitted, the contextual Sway default is used:
  pixels for floating windows and percentage points for tiled windows. Tiled
  resize changes the selected container's share in the relevant ancestor split;
  the requested value is not an exact final pixel-rectangle postcondition.
  Results return the requested axes, resolved unit, before/fresh rectangles, and
  per-axis changed status. A successful Sway reply that leaves every requested
  axis unchanged is reported with a warning rather than as an attained size.
- `close` requires `confirm_close: true` and sends Sway's `kill` command. The
  result distinguishes `close_requested` from `closed_observed`; it does not
  infer which process signal or client-side shutdown behavior occurred.
- Directional movement, centering, splitting, and automatic container
  flattening remain Sway-controlled. Results and warnings describe what the
  plugin can observe rather than promising a complete topology.

### Runtime socket discovery

Runtime tools need a connectable Sway IPC socket. Automatic discovery checks, in
order, the process `SWAYSOCK`/`SWAYSOCK_WLR`, `sway --get-socketpath`, the
process `I3SOCK`, and then the same socket variables in the optional systemd user
environment. A dead automatic candidate is skipped, including an inherited path
left stale after a compositor restart. The systemd fallback is used only when a
user manager is reachable and the Sway session has imported its socket variable.

Launching Hermes from a terminal inside Sway is supported through inherited
environment variables. Launching it from a TTY or another process tree is also
supported when either `sway --get-socketpath` succeeds there or the current
socket was imported into the systemd user environment. The plugin does not glob
runtime directories for sockets because multiple Sway sessions would make that
selection unsafe. Programmatic callers that give `SwayIPC` an explicit socket
path get strict behavior: an unreachable explicit path is reported rather than
silently attaching to a different session.

## Persistent configuration

Persistent tools write only these plugin-owned files:

| File | Contents |
|---|---|
| `hermes-sway-plugin-rules.conf` | Window rules and workspace-to-output declarations |
| `hermes-sway-plugin-startup.conf` | Startup commands |

The plugin **does not edit the main Sway config**. Add the include yourself once:

```sway
include ~/.config/sway/hermes/*.conf
```

The documented glob is recognized when deciding whether the active config loads
the managed file. An explicit matching include, including a relative or `~`
path, is also recognized.

By default, managed files live in
`${XDG_CONFIG_HOME:-~/.config}/sway/hermes`, while the main configuration is
`${XDG_CONFIG_HOME:-~/.config}/sway/config`. If `config_dir` is set, it must be
an absolute Sway configuration directory; managed files and its `config` file
are resolved there. Persistent results report the resolved include path.

```bash
chmod 700 ~/.config/sway/hermes   # recommended; generated files are mode 0600
```

### What a persistent write does

- Managed documents contain canonical metadata and a SHA-256 digest of the Sway
  body. If their content is edited by hand, later management is refused with
  `manual_edit_refused`.
- Writes are serialized with `flock`. A candidate in the same directory and the
  current main config are checked with `sway -C -c` before replacement.
- Existing files are copied to numeric backups (`.bak.1`, `.bak.2`, …), up to
  `backup_keep`. The live target remains in place while the backup is made; the
  candidate then replaces it with `os.replace`.
- Reload is attempted only when the running configuration can be observed and
  contains an include that resolves to the managed file. Otherwise the write
  remains on disk and returns `include_not_configured` or
  `reload_not_attempted`.
- If a requested reload is not confirmed, the previous file is restored (or a
  newly created file is removed) and that state is reloaded. This is file/config
  rollback only; it cannot undo effects that Sway or an `exec_always` process
  already performed.
- A conservative scan reports external `assign`, `for_window`, workspace-output,
  unreadable, or unscannable include statements. These findings are warnings;
  they do not block a valid write, and the plugin does not edit or reorder those
  statements.

Manual recovery from the newest retained backup is straightforward:

```bash
cp ~/.config/sway/hermes/hermes-sway-plugin-rules.conf.bak.1 \
   ~/.config/sway/hermes/hermes-sway-plugin-rules.conf
swaymsg reload
```

### Rule semantics

- Window placement to either a workspace or an output is rendered with Sway's
  `assign`. Other mapped-window effects use `for_window`; `no_focus` is emitted
  as its own top-level statement.
- A window rule can match `app_id`, XWayland `class`/`instance`, `title`,
  `window_role`, `shell`, or `con_mark` with exact or regex criteria.
  `window_type` is a literal Sway 1.9 enum and does not accept regex mode.
- `intended_cardinality` is advisory and defaults to `many`. When a live tree is
  available, the result includes the current audit and warns if it does not meet
  the stated intent; the audit does not prevent the rule from being written.
- Window rules are not retroactively applied to unchanged existing windows.
  `workspace_output` is a separate workspace declaration, not a window rule.
- A workspace-output rule renders one `workspace "…" output "…" …` statement;
  its output list is preference order.
- Normal startup entries render as `exec` (`sway_start_only`).
  `sway_start_and_every_reload` renders as `exec_always` and requires
  `acknowledge_reload_relaunch: true` because every reload may start another
  process.

For future one-window placement, prefer a stable Wayland `app_id`. For XWayland,
use a stable class and instance. Two otherwise identical windows cannot be
reliably separated by a Sway rule; configure distinct application identities
first, such as `kitty --app-id kitty.chat` and `kitty --app-id kitty.build`.

## Launch correlation

`sway_launch` starts exactly one argv process with `shell=False`. When window
observation is requested, it subscribes before launch, compares new containers
to a baseline, waits 250 ms after a tentative match for competing candidates,
and performs a final tree query at the deadline.

Correlation reports one of:

- `matched` — one strongest candidate;
- `ambiguous` — more than one strongest candidate;
- `timeout` — no candidate met the available evidence;
- `observation_failed` — the process started, but Sway observation failed;
- `not_requested` — `wait_for_window` was false.

Evidence is ranked as `pid_exact`, `descendant`, then `identity_only`.
`identity_only` requires an exact caller-supplied identity. All tiers are
best-effort evidence, not proof of a process-to-window relationship. Spawned
children are reaped asynchronously when the process object supports waiting.

## Configuration keys

| Key | Default | Meaning |
|---|---:|---|
| `ipc_timeout_seconds` | `3.0` | Sway IPC request timeout. |
| `reload_timeout_seconds` | `5.0` | Wait for a reload event before rollback. |
| `launch_timeout_seconds` | `10.0` | Default window-correlation period. |
| `config_dir` | `""` | Managed Sway directory; empty uses the XDG paths above. |
| `backup_keep` | `10` | Number of numeric managed-file backups to retain. |

## Limits and authority

- Sway 1.9 is enforced. Other major/minor versions return
  `unsupported_sway_version` for live operations.
- This is not an i3 plugin or a generic `swaymsg` passthrough. It does not offer
  arbitrary relative insertion, saved-tree import, placeholder restoration, or
  complete historical topology restore.
- Runtime window/container identity does not survive a Sway restart.
- Persistent rule effects, geometry, external statement ordering, application
  daemonization, and client reuse are ultimately governed by Sway and the
  application. The plugin reports bounded observations and warnings where it
  cannot establish stronger facts.
- Upstream Sway 1.9 source and behavior are the authority for command and config
  semantics. This README describes the plugin's interface, not an independent
  guarantee about compositor internals.

## Testing and validation

Create the development environment and run the suite without contacting the
active Sway session:

```bash
uv sync --extra dev
uv run pytest -q
uv run pytest tests/ -q
```

The tests use fixtures, injected clients, and scripted Unix sockets. The real
Hermes discovery test needs a current Hermes checkout (the default lookup is
`~/.hermes/hermes-agent`):

```bash
HERMES_REPO=/path/to/hermes-agent uv run pytest tests/test_hermes_discovery.py -q
```

Validate the plugin package with Hermes:

```bash
hermes plugins validate . --json
hermes plugins doctor . --ci
```

An optional read-only check against the current compositor is available:

```bash
SWAYSOCK="$SWAYSOCK" uv run python scripts/live_smoke.py
```

`live_smoke.py` sends only `GET_VERSION`, `GET_TREE`, `GET_WORKSPACES`, and
`GET_OUTPUTS`; it does not send `RUN_COMMAND`.

For destructive integration coverage, run the isolated headless harness. It
creates a temporary Sway 1.9 session and XWayland test windows, exercises runtime
mutations, persistent placement, reload, and file rollback, then removes the
session. It never connects to the active desktop:

```bash
uv run python tests/integration/headless_sway.py
```

This optional check requires the `sway` and `xmessage` executables. A missing
prerequisite exits with status 77 and a JSON skip result.

## License

[MIT](LICENSE) © 2026 lessucettes.

## Acknowledgements

This project was developed with AI coding assistance in a human-directed
implementation, test, and documentation workflow. Development tools included:

- GPT-5.6 Sol
- GPT-5.6 Terra
- GLM-5.3 Flash
- DeepSeek V4.1 Flash

These models and their providers do not own, endorse, sponsor, or maintain the
project and provide no warranty or support. Design decisions, review, and
responsibility for the published code remain with the repository maintainer.
