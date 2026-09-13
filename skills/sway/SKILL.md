---
name: sway
description: Control Sway 1.9 windows, workspaces, layouts, and rules.
version: 0.1.0
author: Izen, Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [sway, wayland, linux, desktop]
---

# Sway 1.9 Operating Skill

Use the `sway` toolset for Sway 1.9 desktop work. It supports bounded inspection, verified runtime changes, best-effort argv launches, and persistent configuration; it never accepts raw Sway command text.

## When to Use

- Use for requests about Sway windows, workspaces, outputs, layouts, startup behavior, or durable window placement.
- Do not use for arbitrary `swaymsg` command execution, restoring an arbitrary historical tree, or assuming a container ID survives a restart.

## Procedure

1. Call `sway_inspect` first. For a singular runtime change, use the returned fresh `con_id` as `target`; do not select the first matching window. Completion: exactly one intended target is identified.
2. Map “now”, “this session”, and “currently open” to `sway_window`, `sway_workspace`, `sway_layout`, or `sway_launch`. Runtime changes do not persist across restart.
3. Map “always”, “after restart”, “on Sway start”, and “every time this opens” to `sway_rule` or `sway_startup`. Persistent rules affect new windows only; use a separate runtime action when the request also means “now”.
4. Prefer an exact Wayland `app_id`. For XWayland, use class plus instance. Use titles only for stable application-defined roles. Completion: the matcher distinguishes the intended future window(s).
5. For a one-window persistent rule, require current cardinality evidence or explicit acknowledgement when it cannot be verified. Use `intended_cardinality: "many"` only when applying to every matching window is intended.
6. Use `sway_start_only` for normal application startup. Use `sway_start_and_every_reload` only after explicit `acknowledge_reload_relaunch: true`; `exec_always` can relaunch applications on every reload.

## Examples

Persist a Telegram placement rule, then separately move an already-open matching window if requested:

```json
{"action":"add","kind":"window","match":{"app_id":{"value":"org.telegram.desktop","mode":"exact"}},"intended_cardinality":"one","destination":{"workspace":"4"},"effects":{"floating":true,"width_px":800,"height_px":600,"center":true}}
```

Two Kitty roles need application-defined identities rather than two indistinguishable Kitty windows. Launch each with a distinct supported identifier, for example `kitty --app-id kitty.chat` and `kitty --app-id kitty.build`; then match the exact `app_id` in separate rules. For XWayland programs, configure distinct `--class` values and match class plus instance.

## Pitfalls

- `sway_launch` process success is not window correlation success. Correlation can return `matched`, `timeout`, or `ambiguous` and is never guaranteed.
- Directional moves and centered floating positions are compositor-dependent; inspect the returned state afterward.
- Position, resize, and sticky require an explicit floating non-fullscreen window. Do not enable floating implicitly to satisfy them.
- Sway 1.9 cannot reliably represent arbitrary relative insertion, saved-tree import, placeholder restoration, or a complete historical topology restore.
- Do not manually edit plugin-owned generated configuration. Use `sway_rule` or `sway_startup` to update/remove it; manual changes are refused to prevent accidental overwrite.

## Verification

After a runtime mutation, inspect the result or use the handler's verified postcondition. After a persistent update, check the generated lines, validation/reload state, warnings about external conflicts or a missing include, and the explicit `applies_to_new_windows_only` result.
