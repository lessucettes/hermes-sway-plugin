---
name: sway
description: Control Sway windows, workspaces, layouts, and rules.
version: 0.2.0
author: lessucettes, Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [sway, wayland, linux, desktop]
---

# Sway 1.9 Operating Skill

Translate the user's desktop intent into the smallest of the seven structured `sway` tools. Do not turn a simple request into an audit: inspect only when the live target, destination, or layout topology is uncertain. The tools do not accept raw Sway command text.

## Intent Map

| What the user means | Tool and scope |
|---|---|
| “What is focused?”, “What is open?”, “Which output is active?” | `sway_inspect`, using the smallest useful view |
| “Move/focus/float/resize/mark/close this open window” | `sway_window`; current session only |
| “Go to workspace 4”, “rename 4”, “move workspace 4 to DP-1” | `sway_workspace`; current session only |
| “Make these tabs”, “split here”, “swap these two” | `sway_layout`; current session only |
| “Open Firefox”, “run this application” | `sway_launch` with an argv array, never a shell command string |
| “Always open this app on 4”, “make it float every time” | `sway_rule` with `kind: "window"` |
| “Workspace 9 belongs on HDMI-A-1” | `sway_rule` with `kind: "workspace_output"` |
| “Start this when Sway starts” | `sway_startup` |

Words such as **now**, **currently open**, **this window**, and **this session** imply a runtime action. Words such as **always**, **after restart**, **every time it opens**, and **on Sway start** imply persistent configuration. **Now and always** requires both: mutate the current object and create the persistent rule or startup entry. A reload alone is not the runtime half.

## Inspect Only to Resolve Uncertainty

Do not call `sway_inspect` first by habit.

- If a fresh `con_id` already identifies the window, act on it directly. Refresh only after an intervening event or action could have destroyed or recreated that window.
- If the user supplied an exact workspace or output and the operation can accept it directly, do not inspect merely to repeat the name.
- When current focus or broad desktop state is needed, omit `view` and use the default `summary`.
- When live window identity or uniqueness is uncertain, use `view: "windows"` with the narrowest known filter. This is the normal way to obtain a fresh `con_id`, `app_id`, XWayland class/instance, and title.
- Use `view: "tree"` only when parent/child topology matters for `sway_layout`. Ordinary focus, move, resize, and identity questions do not need the tree.
- Use `workspaces`, `outputs`, or `marks` when the user asks for that list or the summary lacks the required destination detail.

A singular runtime operation must resolve to exactly one live object. Prefer the fresh `con_id` returned by inspection. An exact runtime `match` is acceptable only when it resolves one match; zero is `target_not_found`, multiple is `target_ambiguous`. Never pick the first result.

## Choose Identity for the Scope

Live and persistent identities solve different problems.

**For a live window:** prefer a fresh `con_id`. A session mark or an exact conjunctive matcher can be useful, but still must identify exactly one object. A PID is evidence about a running process, not a durable window identity.

**For a persistent window rule:**

1. For native Wayland, prefer exact `app_id`.
2. For XWayland, prefer exact class; add exact instance only when class alone is too broad.
3. Add an application-defined stable role when the application exposes one and the rule needs it.
4. Use title only as a last resort. Titles are often document-, page-, locale-, or state-dependent.

Never persist `con_id` or PID: both are runtime values and change when the client or session is recreated. If two windows expose no stable distinguishing property, configure distinct application identities at launch when the application supports that, rather than inventing a fragile title rule.

Persistent match fields default to exact mode. Use regex only when the user actually wants a family of identities, not as a shortcut around discovering the exact one.

## Runtime Actions

Pass only fields relevant to the selected action.

- `sway_window` changes exactly one open window. Position, sticky state, and resize are meaningful only where Sway permits them; do not silently enable floating to force a request through.
- `sway_workspace` can focus or create an exact workspace without prior inspection. Rename and move-to-output require an existing workspace.
- `sway_layout` operates relative to containers: `set_parent_layout` changes the target's parent layout, `split_at` changes the split at the target, and `swap` needs two unique targets. Inspect the tree first when that relationship is not already known.
- `sway_window` action `close` is a Sway client-close request, not a POSIX signal sent to a PID. Set `confirm_close: true`. Treat `close_requested` and `closed_observed` separately; a client may delay or refuse closure.

Trust the tool's verified postcondition when it succeeds. Inspect again only when the returned observation is insufficient or an error says the observed state differs.

## Launch Once, Then Interpret Correlation

Use `sway_launch` with exact `argv`; add `expected_identity` when a stable Wayland `app_id` or XWayland class/instance is known. Correlation is best-effort because launchers may daemonize, reuse an existing process, or open several windows.

Read `status`, `candidates`, and `match_basis` together. `match_basis` explains the strongest evidence used, such as direct PID relation or a newly observed matching identity; it is not a persistence key.

`observation_failed` means the process **did start** but Sway observation failed afterward. Do not retry the launch blindly or the application may start twice. The same caution applies when a started process returns `timeout` or `ambiguous`: resolve the live windows with `sway_inspect` instead of launching again.

## Persistence Without Pretending It Is Runtime

`sway_rule` and `sway_startup` own generated configuration files. Do not manually edit those files. The user's main Sway config must include the returned managed include path once; after that, the plugin can validate, write, reload, and roll back its own files without taking ownership of the main config.

For window rules:

- Current cardinality is advisory, not permission. `intended_cardinality` defaults to `many`; set it to `one` only to describe the user's intent and improve diagnostics.
- The application does not need to be running. Zero current matches may produce an unverified-cardinality warning, but must not prevent a future-window rule.
- External `assign`, `for_window`, or workspace statements may produce conflict warnings. Surface the warning and its source, but do not treat it as a blocker.
- Reloading a rule does not retrofit an unchanged open window. If the user wants the behavior now and later, call `sway_window` for the current window and `sway_rule` for future evaluations.
- `workspace_output` is a workspace-to-output rule, not a new-window rule. Do not describe it as waiting for an application window to open.

For startup entries, use `sway_start_only` for ordinary applications. Use `sway_start_and_every_reload` only when the user explicitly wants every reload to relaunch it, and set `acknowledge_reload_relaunch: true`.

## Recover From the Error, Not From a Checklist

- **`target_not_found`:** the selector is stale or no current object matches. Inspect `windows` with a narrow filter, obtain a fresh identity, and retry only if the intended window now resolves uniquely.
- **`target_ambiguous`:** inspect the returned candidates or a filtered `windows` view. Use a distinguishing field or fresh `con_id`; ask the user only when their wording does not distinguish the candidates. Never select the first.
- **`include_not_configured`:** the managed file was written and validated, but it was not loaded. Report the exact returned include path and have the user add it to the main config once. Do not duplicate the rule or startup entry; after setup, reload or update that existing resource.
- **Reload not attempted or not confirmed:** distinguish “file written but not live” from rollback. If `rolled_back` is true, the prior generated file was restored and the requested persistent change must be reissued only after the reload problem is fixed. If reload and rollback reload both fail, stop and report the uncertain live state rather than claiming success.
- **`postcondition_failed`:** the command was accepted or attempted, but fresh observation did not match the request. Inspect the smallest relevant view—`tree` only for layout, otherwise usually `windows` or `summary`—and report the observed state. Retry only when the evidence identifies a stale target or transient race; do not loop against compositor constraints.
- **`observation_failed` after launch:** preserve `started: true` and the returned PID/status in the report. Inspect; do not launch again automatically.

## Verification

A successful runtime result already includes a fresh observed postcondition; do not add redundant inspection. For persistence, report the resource ID, rendered/generated result, warnings, and `reloaded`/`rolled_back` state. “Done now and always” is true only when both the runtime mutation and the persistent write have succeeded at their respective scopes.
