---
name: hivelight
description: Use when the user wants to operate Hivelight (app.hivelight.com) — creating matters, building or applying workflows and roadmaps, managing tasks, shifting deadlines, cleaning up demo workspaces, or any other Hivelight automation. Also use when the user mentions Hivelight by name or asks Claude to act on a Hivelight matter, task, milestone, or workflow.
---

# Hivelight

## Overview

This skill lets Claude operate `app.hivelight.com` on the user's behalf. It wraps both the public API (documented at developers.hivelight.com) and a set of internal endpoints that aren't exposed publicly but are needed for workflow building, cascade date shifts, and ad-hoc task creation.

Core operating principle: there are two API surfaces and the skill routes calls to the right one transparently. The user just asks for what they want done.

## First check: credentials

Before any operation, verify credentials exist. If the user is invoking this skill and there's no stored API key, run the setup flow:

```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/hivelight/lib/setup.py" --sandbox-workspace "<workspace name>"
```

(If `${CLAUDE_PLUGIN_ROOT}` isn't set in your shell, the absolute path is wherever the plugin was unzipped, e.g. `~/.claude/plugins/hivelight/skills/hivelight/lib/setup.py`.)

This opens a browser window. The user logs in once. The skill harvests a JWT, auto-creates an API key, and stores both in the OS keychain. Subsequent invocations don't need a browser.

If a call raises `HivelightAuthExpired`, the workspace-scoped JWT has aged out (3-day lifetime) — re-run setup. The exception message includes the absolute path to `setup.py` on this machine. The API key itself never expires.

## Invoking the Python client from Claude

The skill's Python module lives at `${CLAUDE_PLUGIN_ROOT}/skills/hivelight/lib/`. To use it from a bash tool call, set `PYTHONPATH` or run with the directory as cwd:

```bash
cd "${CLAUDE_PLUGIN_ROOT}/skills/hivelight/lib" && python -c "from hivelight import HivelightClient; c = HivelightClient(); print(c.matters.list())"
```

For multi-step operations, write a temp script that sets up sys.path explicitly:

```python
import sys
sys.path.insert(0, "${CLAUDE_PLUGIN_ROOT}/skills/hivelight/lib")
from hivelight import HivelightClient
c = HivelightClient()
# ... your operations
```

## Using the client

Common ops have ergonomic helpers. For everything else, use `client.call(...)`.

```python
from hivelight import HivelightClient
c = HivelightClient()

# Common — ergonomic
c.matters.list()
c.matters.create(name="Jane Smith — slip and fall", owner_user_id=...)
c.workflows.apply(workflow_id="abc", matter_id="xyz", start_date=...)
c.milestones.shift(milestone_id="m1", matter_id="x", new_due_date=..., new_target_date=...,
                   offset_days=14, include_following=True, shift_tasks=True)
c.tasks.create(name="Call client", matter_id="x", milestone_id="m1", due_date=...)

# Import matters from a connected practice-management system (Clio, Actionstep,
# or Smokeball) — preserves the bidirectional sync link.
# IMPORTANT: do NOT use c.matters.create for PMS-sourced matters; use this flow.
session_id = c.imports.default_session_id()
items = c.imports.list_items(session_id, query="family law")["meta"]["items"]
c.imports.import_item(session_id, item_id=items[0]["meta"]["id"], team_id="<team>")
# items[i]["destinationId"] is the new Hivelight matter id — use it for follow-up
# workflow apply / role assignment. See common-recipes.md Recipe 10.

# Anything else — generic
c.call("POST", "/v1/some/path", json_body={...})           # internal API (Bearer JWT)
c.call("GET",  "/v1/matters/{id}", path_params={"id": "..."}, public=True)  # public API (x-api-key)
```

## When to read the supporting files

- **[api-inventory.md](api-inventory.md)** — read this when you need an endpoint not covered by the ergonomic helpers. Comprehensive list with auth requirements, request shapes, and known gotchas.
- **[workflow-gen-guide.md](workflow-gen-guide.md)** — read this when the user wants to BUILD a new workflow/roadmap from a natural-language description (e.g. "build me a conveyancing roadmap"). Covers data model, relative-date semantics, and a worked example.
- **[common-recipes.md](common-recipes.md)** — read this for worked examples of common multi-step operations (apply workflow to new matter, cascade date shift across a roadmap, etc.).
- **[lib/README.md](lib/README.md)** — how to invoke the Python module from a Claude Code bash shell.

## When you're unsure or hit an edge case

The bundled docs above cover the common cases. For anything outside them, consult these external resources before guessing or asking the user. **Prefer fetching the relevant doc page over making assumptions about Hivelight behavior.**

### `https://docs.hivelight.com/en/` — Help centre (user-facing)

When to use it: questions about **how a feature works in the product** that aren't covered by the bundled docs. Things like "what happens when X status reaches Y?", "what does this UI option do?", "what's the recommended workflow for Z scenario?".

URL pattern: collection → article. Examples:
- `https://docs.hivelight.com/en/collections/9556360-roadmaps` (collection index)
- `https://docs.hivelight.com/en/articles/9482307-how-to-edit-a-roadmap` (specific article)

Categories that exist: Getting Started, Account Setup, Quick Start, Matters, Milestones, Tasks, Roadmaps, Reporting.

If you're about to advise the user on a feature you're not 100% sure about, fetch the help article first. Quote the doc verbatim when relaying.

### `https://developers.hivelight.com/` — Public API documentation

When to use it: confirming the **canonical shape of a documented public-API endpoint**. The api-inventory.md catalog is comprehensive but the public docs are the authoritative source for the supported subset (matters, tasks (read/status only), workflows (list/get only), webhooks, workspace, users).

Specifically check the public docs when:
- Implementing webhook handling (not yet in the inventory)
- Picking between the public API and the internal API — public is preferred when it offers the same operation
- A response shape from a public endpoint doesn't match your expectation

For internal endpoints (anything in api-inventory.md NOT marked as "public"), the public docs won't help — those endpoints are documented only by the inventory.

### Order of operations when stuck

1. Check api-inventory.md for the endpoint and its known quirks
2. Check workflow-gen-guide.md or common-recipes.md if it's a workflow / multi-step concern
3. Fetch the relevant help-centre article if it's a "how does the product work" question
4. Fetch the public API docs if it's a "what's the documented spec" question
5. Only then ask the user. Most of the time one of the above will answer it.

## Common mistakes

1. **Don't send `Content-Type: application/json` on GET or DELETE requests.** The server tries to JSON-parse the empty body and returns 422. The client handles this correctly — but if you're hand-crafting curl, watch for it.
2. **Use the right token for the right host.** Public API (`api.hivelight.com`) takes `x-api-key`. Internal API (`app.hivelight.com`) takes `Authorization: Bearer <JWT>`, and most resource ops need the **workspace-scoped** JWT (not the broad one). The client routes automatically — don't override unless you know why.
3. **Workflow drafts use a `:DRAFT` suffix** on the workflow ID. Always operate on the draft, then `publish()` to materialize it. Editing a published workflow requires creating a new draft first (`POST /v1/workflows/{id}/draft`).
4. **Matter delete requires archive first.** `DELETE /v1/matters/{id}` returns 403 unless the matter is archived. The client surfaces this clearly; just call `c.matters.archive(...)` before `c.matters.delete(...)`.
5. **Workflow delete requires unpublish first.** Set `audience="NONE"` via `c.workflows.unpublish(...)` before `c.workflows.delete(...)`.
6. **Always confirm with the user before mutating real client data.** Especially for delete/archive/shift operations on production matters. Default to dry-run summaries; ask before committing.

## What this skill does NOT do (yet)

- MFA verification — defer until first MFA-enabled user surfaces (endpoint not captured).
- SSO/Cognito refresh tokens — only password-auth users for v1.
- Real-time / webhook flows.

If the user asks for one of these, say so explicitly rather than guessing.
