# Hivelight API Inventory

Reference for the operations on `app.hivelight.com/v1/*` (the application API) that
the plugin uses to cover functions not currently exposed by the public API at
`api.hivelight.com/v1`.

## Architectural notes

- **Backend:** AWS API Gateway behind CloudFront (per `apigw-requestid` and `x-amz-cf-*` response headers).
- **Auth:** `Authorization: Bearer <jwt>` header. Cookies-only requests return 401.
- **Token:** HS256-signed JWT, payload `{userId, exp, iat, region, fiat, ...}`. 3-day lifetime.
- **⚠️ TWO TOKENS exist simultaneously and have different scopes — this is critical:**
  - `localStorage.token` — **broad user token**, payload has `{userId, region, exp, iat, fiat}`. Use for: whoami, list workspaces, workspace-switching, anything cross-workspace.
  - `sessionStorage.token` — **workspace-scoped token**, payload has all of the above PLUS `{organizationId, workspaceId, country, role}`. Use for: tasks, milestones, matters, workflows — basically any resource inside a workspace. Without this token, DynamoDB-backed endpoints return 422 "The provided key element does not match the schema" because they use `workspaceId` from the JWT as the partition key.
  - **The skill must obtain and refresh BOTH.** The workspace-scoped token is minted via `GET /identity/switch/workspace?workspaceId=<id>&then=<path>` after the broad token is acquired.
- **Refresh:** Password-auth users have **no working refresh path** — JS source scan confirms `/v1/identities/refresh` is never called by the web client. They must re-login every 3 days. SSO users get a proper OAuth `refresh_token` via Cognito.
- **Storage:** Token stored in `localStorage.token` for default workspace; `sessionStorage.token` when scoped to a specific workspace (transient session).
- **MFA:** JWT may contain `mfa: "REQUESTED"` indicating the returned token is not yet usable; a follow-up MFA verification step is required (endpoint not captured — none of the test accounts have MFA enabled).
- **Response envelope:** Most resources use JSON:API spec (`{jsonapi: {version: '1.0'}, data: {type, id, attributes, relationships}, included: [...]}`).
- **Request shapes:** Mixed. Workflow mutations use plain JSON; matter-level milestone/task mutations use JSON:API. Inconsistent but each endpoint is consistent within itself.
- **Dates:**
  - Template dates (in roadmaps/task lists): **relative**, `{relativeTo: "ROADMAP_START_DATE"|"MILESTONE_DUE_DATE"|"MILESTONE_TARGET_DATE"|"CURRENT_DATE", plus|minus: <days>}`.
  - Instance dates (on a matter): **absolute** Unix millisecond timestamps.
- **Path encoding:** Hierarchical IDs use colon delimiters, e.g. `<workflowId>:DRAFT:<milestoneId>:<taskId>` is `workflow:draft-suffix:milestone:task`.

---

## Status legend

`✅ confirmed working` | `🔍 partial / shape not fully captured` | `❌ not captured`

---

## Identity / Session

| Status | Op | Method + Path | Body / Notes |
|---|---|---|---|
| ✅ | Login (password) | `POST /v1/identities/authenticate` | Body: `{data:{type:"user", attributes:{email, password}}, meta:{recaptchaToken}}`. Response: `{meta:{token:<JWT>}}`. JWT payload includes `userId`, `region` (e.g. "us-east-1"), `iat`, `exp`, `fiat`, and possibly `mfa:"REQUESTED"` (which means the token is not yet usable and an MFA verification step follows). |
| ⚠️ | Refresh token | `POST /v1/identities/refresh` | **Endpoint exists server-side but the web client never calls it for password-auth users.** Source scan confirms: no `/refresh` URL appears anywhere in the Hivelight JS bundle. Password-auth users must re-login (with reCAPTCHA) every 3 days. SSO users have their own OAuth refresh path (Cognito `refresh_token`). |
| ✅ | Login (SSO/Cognito) | Redirect to `https://auth-{region}.app.hivelight.com/login?client_id=<id>&redirect_uri=<app-url>&response_type=code` | Standard OAuth 2.0 code flow. Returns `{hivelightToken, ssoRefreshToken: {token, expiresAt}}` after token exchange. Use this path for long-lived sessions (~30 days). |
| ✅ | Switch workspace | `GET /identity/switch/workspace?workspaceId=<id>&then=<path>` | Browser-flow workspace re-bind. May silently re-issue token. |
| ✅ | Whoami (full) | `GET /v1/users/whoami?from=core` | Returns full user + all workspaces + permissions (large response). |
| ✅ | Whoami (thin) | `GET /v1/users/whoami` | Smaller variant. |
| ✅ | List workspaces | `GET /v1/workspaces` | List of workspaces the user belongs to. |

---

## Configuration / Lookups (cacheable)

| Status | Op | Path |
|---|---|---|
| ✅ | Frontend chunk versions | `GET /v1/configurations/versions` |
| ✅ | Jurisdictions | `GET /v1/configurations/jurisdictions` |
| ✅ | Matter types | `GET /v1/configurations/matter/types` |
| ✅ | Captcha config | `GET /v1/configurations/security/captcha` |
| ✅ | SSO config | `GET /v1/configurations/single-sign-on` |

---

## Workflows (templates — roadmaps + task lists)

A workflow is either a `ROADMAP` (has its own milestones) or a `TASK_LIST` (one synthetic milestone with id `TASK_LIST`). All workflow mutations target the draft (path suffix `:DRAFT`); the draft must be published before it can be applied to a matter.

| Status | Op | Method + Path | Request body |
|---|---|---|---|
| ✅ | List workflows | `GET /v1/workflows?filter=<json>&from=<n>&query=<text>` | `filter` is JSON-encoded `{type: "ROADMAP"\|"TASK_LIST", audience: ["WORKSPACE","ORGANIZATION","NONE"]}`. |
| ✅ | Get workflow | `GET /v1/workflows/{id}` or `GET /v1/workflows/{id}:DRAFT` | Returns full tree (milestones nested). |
| ✅ | Create workflow | `POST /v1/workflows` | JSON:API: `{jsonapi:{version:"1.0"}, data:{type:"workflow", attributes:{name, description-as-html, type:"ROADMAP"\|"TASK_LIST"}}}`. Returns workflow with `:DRAFT` suffix. |
| ✅ | Add milestone (roadmap draft) | `POST /v1/workflows/{id}:DRAFT/milestones` | Plain JSON: `{name, descriptionAsHtml, targetDate:{relativeTo:"MILESTONE_DUE_DATE", minus:N}, dueDate:{relativeTo:"ROADMAP_START_DATE", plus:N}}` |
| ✅ | Add task to milestone (draft) | `POST /v1/workflows/{id}:DRAFT/milestones/{milestoneId}/tasks` | Plain JSON: `{name, descriptionAsHtml, dueDate:{relativeTo:"MILESTONE_TARGET_DATE", minus:N}, estimates:{unitValue:0}}`. For task lists, `milestoneId` is the literal string `TASK_LIST` and `relativeTo` is `"CURRENT_DATE"`. |
| ✅ | List tasks in template milestone | `GET /v1/workflows/{id}:DRAFT/milestones/{milestoneId}/tasks` | |
| ✅ | Publish workflow | `POST /v1/workflows/{id}:DRAFT/publish` | `{audience: "WORKSPACE"\|"ORGANIZATION"\|"PUBLIC"}`. Drops the `:DRAFT` suffix, bumps version. |

### Workflow lifecycle — full picture (from JS bundle)

The workflow chunk (`workflow/0.0.25/static/js/444.15ed5287.chunk.js`) reveals the complete API surface. URL base: `i = "/v1/workflows"`.

| Op | Method + Path | Notes |
|---|---|---|
| Create workflow | `POST /v1/workflows` | (already captured) |
| Get workflow | `GET /v1/workflows/{id}` | Returns full tree with milestones. |
| Delete workflow | `DELETE /v1/workflows/{id}` | **Returns 422 if workflow is currently published. Must unpublish first.** No body required. |
| **Change audience (incl. unpublish)** | `POST /v1/workflows/{id}/publish` with `{audience: <enum>}` | One endpoint covers all audience changes. UI lives in the workflow page's metadata sidebar as `Audience: <value>` with a `Change…` button. Modal title: "Change workflow's audience". Values: `NONE` (UI label: "Nobody / Unpublished"), `WORKSPACE`, `ORGANIZATION`, `PUBLIC`. Setting to `NONE` is what enables `DELETE /v1/workflows/{id}` (which 422s on still-published workflows). |
| Create draft (for published workflow) | `POST /v1/workflows/{id}/draft` | Creates an editable draft on a published workflow. |
| Discard draft | `DELETE /v1/workflows/{id}:DRAFT/draft` | For never-published workflows, this is the only delete path. Returns `{message: "Workflow draft discarded"}`. |
| Copy workflow | `POST /v1/workflows/{id}/copy` | Duplicate an existing workflow. |
| Add milestone | `POST /v1/workflows/{id}:DRAFT/milestones` | Plain JSON body (already captured). |
| Edit milestone (dates/name) | `POST /v1/workflows/{id}:DRAFT/milestones/{mid}` | Body: `{name, descriptionAsHtml, dueDate, targetDate}` — JS confirms shape. |
| Delete milestone (template) | `DELETE /v1/workflows/{id}:DRAFT/milestones/{mid}` | No body. |
| Add task to milestone | `POST /v1/workflows/{id}:DRAFT/milestones/{mid}/tasks` | (already captured) |
| Edit task in template | `POST /v1/workflows/{id}:DRAFT/milestones/{mid}/tasks/{tid}` | Body is the full task. |
| Delete task (template) | `DELETE /v1/workflows/{id}:DRAFT/milestones/{mid}/tasks/{tid}` | No body. |
| Move task (reorder) | `POST /v1/workflows/{id}:DRAFT/milestones/{mid}/tasks/{tid}?action=move` | Body: `{before, after}` task IDs for relative positioning. |
| Add task link | `POST /v1/workflows/{id}:DRAFT/milestones/{mid}/tasks/{tid}/links` | Body: `{taskId, type}` — links to another task by relationship type. |
| Remove task link | `DELETE /v1/workflows/{id}:DRAFT/milestones/{mid}/tasks/{tid}/links/{linkId}` | |
| Publish workflow | `POST /v1/workflows/{id}:DRAFT/publish` | Body: `{audience: "WORKSPACE"\|"ORGANIZATION"\|"PUBLIC"\|"NONE"}`. (already captured) |

---

## Matters (instances)

| Status | Op | Method + Path | Body / Notes |
|---|---|---|---|
| ✅ | List matters (search) | `GET /v1/matters/search?query={text}&filters={json}` | Filters are JSON-encoded. |
| ✅ | Get matter | `GET /v1/matters/{id}` | **No Content-Type header on GETs** — sending `Content-Type: application/json` triggers a JSON-parse error on the empty body. |
| ✅ | **Create matter** | `POST /v1/matters` | JSON:API body: `{jsonapi:{version:"1.0"}, data:{type:"matter", attributes:{name, types:[], jurisdictions:[], roles:{OWNER:[<userId>]}}}}`. Optional `?matterId={id}` query var seen elsewhere for variant flows. Name gets auto-prefixed with a sequential ID (e.g. `"250006 - <your name>"`). |
| ✅ | **Apply workflow to matter** | `POST /v1/workflows/{workflowId}/apply?startDate={ms}&matterId={mid}&milestoneId=` | **All params are query string, NO body.** `startDate` is Unix ms when the roadmap timeline starts. `milestoneId` empty for new milestones; populate to apply a TASK_LIST into an existing milestone. Returns `{workspaceId, matterId, workflowId, status:"APPLIED"}`. |
| ✅ | Update matter (full) | `POST /v1/matters/{id}` | JSON:API body with full matter object. |
| ✅ | Update matter attribute (bulk) | `POST /v1/matters/{ids-comma-separated}/{attributeName}` | Body: `{[attributeName]: value}` (e.g. `tags`, `types`). |
| ✅ | Set matter roles | `POST /v1/matters/{id}/roles` | Body: `{meta:{roles:{...}}}`. |
| ✅ | Add/replace user in role | `POST /v1/matters/{ids}/roles/{roleName}?userId={uid}&action={REPLACE\|ADD\|REMOVE}` | |
| ✅ | Remove user from role | `DELETE /v1/matters/{id}/roles/{roleName}?userId={uid}` | |
| ✅ | Star matter | `POST /v1/matters/{id}/star` | No body. |
| ✅ | Unstar matter | `DELETE /v1/matters/{id}/star` | No body. |
| ✅ | Archive matter | `POST /v1/matters/{id}/archive` | No body. **Required before delete.** |
| ✅ | Unarchive matter | `DELETE /v1/matters/{id}/archive` | No body. |
| ✅ | Delete matter | `DELETE /v1/matters/{id}` | No body. **Returns 403 unless matter is archived first.** |
| ✅ | Tag matter (single) | `POST /v1/matters/{id}/tag` | Body: `{data:{type:"matter", attributes:{tags:{label, value, type}}}}`. |
| ✅ | Tag matter (bulk set) | `POST /v1/matters/{ids}/tag` | Body: `{data:{type:"matter", attributes:{tags:[...]}}}`. |
| ✅ | Untag matter | `DELETE /v1/matters/{id}/tag/{tagId}` | |
| ✅ | Untag task | `DELETE /v1/tasks/{id}/tags/{tagId}` | |
| ✅ | List milestones on matter | `GET /v1/milestones?matterId=<id>` | Returns all milestones on a matter with status, pending/in-progress counts, target/due dates. |
| ✅ | List tasks on milestone | `GET /v1/tasks?matterId=<m>&milestoneId=<ms>&assignees=&dateFrom=&dateInterval=&dateTo=&from=&reviewers=&status=&priorityOnly=&readyOnly=&size=100&sort=&tags=&tz=<tz>&workspaceId=` | All filter params are present even if empty. |
| ✅ | Get task | `GET /v1/tasks/{taskId}` | Full task with description, assignees, etc. |
| ✅ | List users for assignee picker | `GET /v1/users?matterId=<id>` | |
| ✅ | Get single task | `GET /v1/tasks/{taskId}` | Requires workspace-scoped JWT. |
| ✅ | Delete task(s) | `DELETE /v1/tasks/{id1,id2,...}` | Comma-separated IDs for bulk. No body. Requires workspace-scoped JWT. Returns the updated parent milestone. |
| ✅ | Update task status | `POST /v1/tasks/{taskId}/status` | Body: `{data:{type:"task", id, attributes:{status}}}`. |
| ✅ | Set task priority | `POST /v1/tasks/{taskId}/priority` | No body. |
| ✅ | Remove task priority | `DELETE /v1/tasks/{taskId}/priority` | No body. |
| ✅ | Bulk assign | `POST /v1/tasks/{taskIds}/assign/{userIds}?type=ASSIGNEE\|REVIEWER` | Comma-separated. |
| ✅ | Bulk tag | `POST /v1/tasks/{taskIds}/tags` | Body: `{data:{type:"task", attributes:{tags:[...]}}}`. |

---

## Practice-management imports (link-preserving)

Importing matters/contacts/tasks from a connected PMS (Clio, Actionstep, or Smokeball — Hivelight's three native integrations) via these endpoints **preserves the bidirectional sync link** to the source system. Creating a matter via `POST /v1/matters` does NOT establish that link — name changes, contacts, and tasks won't sync. Always use the import flow below for PMS-sourced data.

Each workspace has **one import session per connected PMS**, persistent across time. There is no `GET /v1/imports` listing endpoint — discover the session id from the workspace object instead.

| Status | Op | Endpoint | Notes |
|---|---|---|---|
| ✅ | Discover session id | `GET /v1/workspaces/{workspaceId}` → `data.attributes.integrations[].importId` | Each integration entry exposes `source` (e.g. `"clio"`), `enabled`, `status`, and `importId`. |
| ✅ | Get session details | `GET /v1/imports/{sessionId}` | Returns `source`, `region`, `enabled`, `options`, `status`, `progress` (per-type counters: contact/matter/task/user with `total`, `complete`, `ignored`, etc.), `webhooks`. |
| ✅ | List importable items | `GET /v1/imports/{sessionId}/items?type=matter&next=&filters=<urlencoded-json>` | Filters JSON: `{"complete": bool, "ignored": bool, "query": "<text>"}`. **Response envelope is `{meta:{items:[...]}}`** (not `data`). Each item carries `destinationId` (the Hivelight resource id assigned during normalization — usable immediately after import), `normalized` (mapped fields), `raw` (full PMS payload), `searchable` (lowercase concat of name/description/number/source-id/jurisdiction — what `query` matches against), `status` (`NORMALIZED`/`IMPORTING`/`COMPLETE`/etc.). |
| ✅ | Set per-item options | `POST /v1/imports/{sessionId}/meta?type=matter&itemIds=<id>` | Body: `{"meta": {"teamId": "<teamId>"}}`. Captured 2026-05-20: this is how the UI's "choose team" dropdown is persisted. GET on this endpoint returns 404 for arbitrary items — use `list_items` to read state. |
| ✅ | Trigger import | `POST /v1/imports/{sessionId}/import?type=matter&itemIds=<id>` | No body. Async server-side — response is the session object with global progress counters, NOT the new Hivelight resource. The `destinationId` from `list_items` IS the new matter id (it's pre-assigned at normalization time). |

**Practical recipe**:
1. `c.imports.default_session_id()` — discovers session id from `/v1/workspaces/{ws}`.
2. `c.imports.list_items(session_id, query="<filter>")` — paginated, with rich `raw` + `normalized` data.
3. (Optional) `c.imports.set_item_meta(session_id, item_id, team_id=...)` — override default team.
4. `c.imports.import_item(session_id, item_id, team_id=...)` — triggers import; auto-calls `set_item_meta` if `team_id` is passed.
5. The Hivelight matter id is `item["destinationId"]` from the list response — use it for follow-up `c.workflows.apply(...)` or `c.matters.assign_to_role(...)`.

**Known limitation (2026-05-20)**: applying a roadmap *during* import has a bug per the Hivelight team. Apply roadmaps as a separate step via `c.workflows.apply(workflow_id, matter_id)` after the import returns.

---

## ⭐ Gap closers — operations not in the public API

Higher-value operations the plugin fills in via the application API:

### 1. Create ad-hoc task

```http
POST /v1/tasks
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "jsonapi": { "version": "1.0" },
  "data": {
    "type": "task",
    "attributes": {
      "name": "Task name",
      "description-as-html": "<p>optional</p>",
      "matter-id": "<matterId>",
      "milestone-id": "<milestoneId>",
      "due-date": 1740376800000,
      "assignees": ["<userId>", ...],
      "reviewers": ["<userId>", ...],
      "is-priority": false
    }
  }
}
```

Returns the new task object with `task-id`.

### 2. Shift milestone date (on a matter) — TWO MODES

**Single mode (only this milestone):**
```http
POST /v1/milestones/{milestoneId}/date
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "data": {
    "type": "milestone",
    "id": "<milestoneId>",
    "attributes": {
      "id": "<milestoneId>",
      "targetDate": 1740376800000,
      "dueDate": 1740378600000,
      "isKeyDate": false
    },
    "relationships": {
      "matter": { "data": { "type": "matter", "id": "<matterId>" } }
    }
  }
}
```

**Cascade mode (shift this milestone + all subsequent milestones, optionally their tasks too):**

```http
POST /v1/milestones/{milestoneId}/date?include=following&shiftTasks=true&offset=206641521
```

Same body as single mode. Query params control cascading:
- `include=following` — also shift subsequent milestones in the same roadmap. Empty (or omitted) = just this milestone. (Captured from JS bundle — corresponds to UI checkbox "Also apply this update to other milestones of this roadmap".)
- `shiftTasks=true` — also shift tasks of the affected milestones. (Corresponds to a tasks-cascade checkbox.)
- `offset=<milliseconds>` — relative shift amount in **MILLISECONDS** (not days). The body's dates apply to THIS milestone explicitly; the cascade applies the offset to subsequent items. **Captured from a real UI shift on 2026-05-19**: a ~2.39-day shift sent `offset=206641521`. Prior "offset=7 shifts by 7 days" empirical claim was wrong — that test used such small values the unit difference was invisible. **NOTE**: target-dates on subsequent milestones only update reliably when this cascade endpoint is used; single-mode (`POST /date` without query params) appears to only update due-date and silently ignores `targetDate`.

Dates in body are absolute Unix millisecond timestamps.

**By-design behaviour — cascade preserves DONE-item completion dates**: cascading from an anchor with `include=following&shiftTasks=true` shifts NOTSTARTED/INPROGRESS milestones and their tasks, but **deliberately leaves DONE milestones (and DONE tasks) at their existing dates**. This is intentional: DONE items have historical completion dates that should remain accurate even when the rest of the roadmap is rescheduled. Validated empirically 2026-05-20 — confirmed product behaviour, not a bug.

**Workaround for demo-data / data-refresh scenarios** (where you specifically want to move DONE items too): after the cascade, walk the matter and re-shift any items whose dates are still pre-shift using single-milestone cascade-no-followers calls (see common-recipes Recipe 9 / `lib/fix_cascade_laggards.py`). Only use this when you're regenerating demo data or batch-rescheduling — for normal "this client is delayed by N weeks" shifts, the default behaviour is what you want.

**Earlier-suspected gotcha — anchor-past-followers — DISPROVEN**: an earlier session believed the cascade fails when anchor's new due is later than followers' old positions. With the unit fix (offset in ms, not days), this is NOT the case — cascade evaluates "following" by old positions and applies offset regardless of where the anchor lands.

### 3. Shift task date (and any other task attribute)

```http
POST /v1/tasks/{taskId}
Authorization: Bearer <jwt>
Content-Type: application/json

{
  "jsonapi": { "version": "1.0" },
  "data": {
    "type": "task",
    "id": "<taskId>",
    "attributes": {
      "due-date": 1740378600000,
      /* ... entire existing task attributes are echoed back ... */
    }
  }
}
```

This endpoint is a **full-task update** — you send the entire task body, not just the changed fields. The skill should fetch the task via `GET /v1/tasks/{id}` first, merge in changes, then POST it back.

### 4. Build workflow / task list (roadmap editor)

See "Workflows" section above. Full flow:
1. `POST /v1/workflows` with `type: "ROADMAP"` or `"TASK_LIST"` → creates a `:DRAFT`.
2. For each milestone (roadmaps only): `POST /v1/workflows/{id}:DRAFT/milestones`.
3. For each task: `POST /v1/workflows/{id}:DRAFT/milestones/{milestoneId}/tasks`. (Use `milestoneId="TASK_LIST"` for task lists.)
4. `POST /v1/workflows/{id}:DRAFT/publish` with `{audience}` to publish.

---

## Captured request/response bodies in full

(saved separately — see the recorder buffer in browser session)

---

## API key management (for skill first-run setup)

Base path: `/v1/api`. Source: chunk `720.ece2cb16.chunk.js`, module 4505.

| Op | Method + Path | Body / Notes |
|---|---|---|
| List API keys | `GET /v1/api/keys` | Returns `{data: [{type:"apikey", id, attributes:{label, userId, workspaceId, first4, status, createdDate, lastUsedDate, ...}}]}`. **`first4` only — never the full key.** |
| Create API key | `POST /v1/api/keys` | Body: `{meta:{label: "<descriptive name>", userId: "<userId of key owner>"}}`. Response includes `data.attributes.value` containing the **full 64-character key — exposed only in this one response**. Key inherits the named user's permissions. |
| Delete (revoke permanently) | `DELETE /v1/api/keys/{keyId}` | No body. |
| Suspend (pause without revoking) | `POST /v1/api/keys/{keyId}/suspend` | No body. |
| Unsuspend (reactivate) | `DELETE /v1/api/keys/{keyId}/suspend` | No body. |

**Skill first-run auto-setup flow:**

1. Drive browser to Hivelight login (reCAPTCHA → real user login)
2. Capture `localStorage.token` (broad JWT) + trigger workspace switch to capture `sessionStorage.token` (scoped JWT)
3. Call `POST /v1/api/keys` with `{meta:{label:"Hivelight Skill (auto)", userId:<userId from JWT>}}` — captures the `value` from the response
4. Store the API key value in OS keychain (Windows Credential Manager / macOS Keychain / libsecret)
5. From then on: public API ops use `x-api-key: <stored key>` (durable, no expiry); internal ops use Bearer JWT (3-day, browser re-auth when expired)

This means **users only ever need a real browser session for**:
- First-time setup (~30 seconds)
- Every 3 days when the JWT expires AND they want to use a gap feature (workflow build, date shift, etc.). For pure public-API use cases (matter create, task list, workflow apply, etc.), they may go indefinitely without re-auth.

## Server quirks (non-obvious return shapes)

- **`GET /v1/matters/{id}` returns 200 + `{}` (empty object) for non-existent matter ids**, NOT 404. Always check `response.get("data")` before assuming success. Verified empirically on 2026-05-19.
- **Bogus internal paths return 200 + the SPA HTML index** (the API gateway falls through to the React shell). The client now detects HTML content and raises `HivelightNotFound`.

## Server-side automatic task reassignment (documented behaviour, important)

When a workflow is applied to a matter, Hivelight **auto-resolves task assignee/reviewer roles** to specific users via a documented cascade. Reassignment also fires when a user is removed from the matter team. As long as `OWNER` is filled (mandatory for matter creation), every task ends up with a real user. See [docs.hivelight.com — automatic task reassignment](https://docs.hivelight.com/en/articles/8797952-automatic-task-reassignment-matter-roles-matter-team-roles).

Cascade chains (per published Hivelight diagram; admin path verified empirically 2026-05-19):

```
ADMINISTRATIVE_2 -> ADMINISTRATIVE_1 -> LEGAL_3 -> LEGAL_2 -> LEGAL_1 -> LEAD -> OWNER
LEGAL_3 -> LEGAL_2 -> LEGAL_1 -> LEAD -> OWNER
ADVOCATE_1 -> LEAD -> OWNER
CONSULTANT_1 -> LEAD -> OWNER
BUSINESS_1 -> OWNER          (direct; skips LEAD)
LEAD -> OWNER
```

The admin chain crosses INTO the legal chain at LEGAL_3, not directly to LEAD. Empirical test of the v2 Texas roadmap (20 tasks) auto-resolved exactly per these chains.

Implication for the skill: **don't manually patch up task assignees after applying a workflow** — set the matter team via `c.matters.set_team()` or `c.matters.assign_to_role()` BEFORE (or at any point), and let Hivelight resolve everything.

## Common-mistakes catalog (things I tripped on; document them so the skill avoids them)

1. **Do not send `Content-Type: application/json` on GET requests.** The server attempts to parse an empty body as JSON and returns 422 "Content type defined as JSON but an invalid JSON was provided".
2. **Most resource endpoints require the workspace-scoped JWT** (sessionStorage), not the broad localStorage token. With the wrong token, calls return 422 "The provided key element does not match the schema" because the server uses `workspaceId` from JWT as a DynamoDB partition key.
3. **Two-step destructive ops** — published workflows must have audience set to NONE before delete; matters must be archived before delete. Both return 403 / 422 if you skip the precondition.
4. **Apply-workflow uses query-string args only — no body**. Easy to assume JSON:API shape.
5. **Workflow paths use colon-suffixed IDs** for drafts (`{id}:DRAFT`), and the workflow tree URL pattern is hierarchical (`workflow/milestones/tasks`), with `TASK_LIST` as a special synthetic milestone for task-list-type workflows.
6. **Matter names are auto-prefixed** with a sequential numeric ID by the server (e.g. `"250006 - "`). The skill should not pre-add such prefixes.
7. **DELETE endpoints should NOT send a request body** — Content-Type:application/json + no body triggers "invalid JSON". Just omit both.
