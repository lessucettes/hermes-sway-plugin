# hermes-sway-plugin

Native Hermes Agent plugin for **Sway 1.9** (Wayland): bounded inspection, verified
runtime control, best-effort argv launching, and plugin-owned persistent
configuration. Python 3.10+ standard library only — no runtime dependencies.

## Install

```bash
hermes plugins validate /path/to/hermes-sway-plugin
hermes plugins doctor /path/to/hermes-sway-plugin --ci
hermes plugins install OWNER/hermes-sway-plugin --ref v0.1.0 --no-enable
hermes plugins enable sway
hermes tools
```

The plugin registers the `sway` toolset with seven tools and the bundled
`sway:sway` skill.

## Tools

| Tool | Scope | Purpose |
|---|---|---|
| `sway_inspect` | read-only | Version, focus, windows, workspaces, outputs, marks, compact tree. |
| `sway_window` | runtime | Focus, move, float, fullscreen, resize, position, scratchpad, sticky, marks, guarded close. |
| `sway_workspace` | runtime | Focus or create, rename, move an existing workspace to an exact output. |
| `sway_layout` | runtime | Set a parent layout, split at a container, or exactly swap two containers. |
| `sway_launch` | runtime | Launch one argv process and report best-effort window correlation. |
| `sway_rule` | persistent | Managed window and workspace-output rules in Sway configuration. |
| `sway_startup` | persistent | Managed `exec` / acknowledged `exec_always` startup entries. |

Every tool returns one JSON string: `{"ok":true,"scope":...,"data":...,"warnings":[...]}`
or `{"ok":false,"error":{"code","message","details"},"recoverable":...}`.

Inspect first, then mutate a fresh `con_id`. Runtime changes do not survive a
restart; use `sway_rule` / `sway_startup` for durable behavior.

## Persistent configuration

Enable the owned include once in your Sway configuration (the plugin never edits
it for you):

```sway
include ~/.config/sway/hermes/*.conf
```

Generated files (mode `0600`, directory `0700`):

- `hermes-sway-plugin-rules.conf` — window / workspace-output rules
- `hermes-sway-plugin-startup.conf` — startup commands

```bash
chmod 700 ~/.config/sway/hermes
```

An empty `config_dir` resolves to `${XDG_CONFIG_HOME:-~/.config}/sway/hermes`
with the main configuration at `${XDG_CONFIG_HOME:-~/.config}/sway/config`.
Every persistent result returns the resolved `include` path.

Each file starts with deterministic metadata headers plus a SHA-256 digest of its
body. Hand edits are refused (`manual_edit_refused`) rather than silently
overwritten; recover by re-adding the entry through the tool or by restoring a
backup. Writes are serialized with `flock`, staged in the same directory, and
replaced atomically after `sway -C -c` validation; timestamped backups are
pruned to `backup_keep`.

Manual recovery:

```bash
cp ~/.config/sway/hermes/hermes-sway-plugin-rules.conf.bak.1 \
   ~/.config/sway/hermes/hermes-sway-plugin-rules.conf && swaymsg reload
```

Reload happens only when the running configuration contains the exact include
line. Otherwise the validated write succeeds with an `include_not_configured`
warning and no reload. Pending reload confirmation restores the backup and
reports rollback state; rollback is configuration rollback only.

## Configuration keys

| Key | Default | Meaning |
|---|---|---|
| `ipc_timeout_seconds` | 3.0 | Sway IPC request timeout. |
| `reload_timeout_seconds` | 5.0 | Wait for a finished reload. |
| `launch_timeout_seconds` | 10.0 | Window-correlation window after launch. |
| `config_dir` | `""` | Managed directory; empty uses the XDG default above. |
| `backup_keep` | 10 | Backups retained after a successful write. |

## Verification

```bash
uv run pytest -q
hermes plugins validate .
hermes plugins doctor . --ci
SWAYSOCK="$SWAYSOCK" uv run python scripts/live_smoke.py   # read-only
```

`scripts/live_smoke.py` sends only `GET_VERSION`, `GET_TREE`, `GET_WORKSPACES`,
and `GET_OUTPUTS`; it never sends `RUN_COMMAND`. Expected output pattern:
`Sway 1.9; outputs=<N>; workspaces=<N>; windows=<N>`.

To use the bundled skill: `skill_view("sway:sway")`. It is not auto-loaded.

## Not supported

- Sway versions other than 1.9 — the plugin fails closed with `unsupported_sway_version`.
- Raw Sway command text, arbitrary relative insertion ("place A right of B"),
  saved-tree restore, placeholder/layout import, or complete topology restore.
- Guaranteed process-to-window association after `sway_launch`; correlation
  returns `matched`, `timeout`, or `ambiguous` and never proves the link.
- Editing your main Sway configuration, or resolving overlapping external
  `assign` / `for_window` rules for you.
- Retroactive application: new persistent rules apply to new windows only.
  Rollback cannot terminate a process already started by `exec_always`.
