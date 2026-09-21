# Common Recipes

Worked examples for high-frequency multi-step operations. Each recipe is the user's prompt + the operations to perform + expected outcome. Use these as templates; adapt the IDs.

---

## Recipe 1: Apply an existing workflow to a new matter

**User says:** "Create a new matter for Jane Smith and apply the personal injury pre-filing roadmap to it."

**Operations:**

```python
from hivelight import HivelightClient
c = HivelightClient()

# 1. Find the workflow (filter by name match — fuzzy)
workflows = c.workflows.list(type="ROADMAP")
match = next(
    w for w in workflows["data"]
    if "personal injury" in w["attributes"]["name"].lower()
    and "pre-filing" in w["attributes"]["name"].lower()
)
workflow_id = match["attributes"]["workflow-id"]

# 2. Get the current user as the matter owner
me = c.call("GET", "/v1/users/whoami", requires_workspace=False)
user_id = me["data"]["id"]

# 3. Create the matter
matter_resp = c.matters.create(
    name="Jane Smith",
    owner_user_id=user_id,
    jurisdictions=["AU-NSW"],
)
matter_id = matter_resp["data"]["id"]

# 4. Apply the workflow (start date = now by default)
c.workflows.apply(workflow_id=workflow_id, matter_id=matter_id)

print(f"Done. Matter {matter_id} now has the roadmap applied.")
```

**Confirmation step before running:** show the user the matched workflow name and the matter name; ask "Apply <workflow> to a new matter named '<name>'?"

---

## Recipe 2: Cascade-shift all milestones on a matter by N days

**User says:** "The client just told us they need everything pushed back two weeks on the Smith matter. Shift it."

**Operations:**

```python
# 1. List milestones in due-date order
milestones = c.milestones.list(matter_id=matter_id)["data"]
sorted_ms = sorted(milestones, key=lambda m: m["attributes"]["due-date"])

# 2. Shift the FIRST milestone — that one carries the offset to all subsequent
first = sorted_ms[0]
old_due = first["attributes"]["due-date"]
old_target = first["attributes"]["target-date"]
new_due = old_due + 14 * 86_400_000   # 14 days in ms
new_target = old_target + 14 * 86_400_000

c.milestones.shift(
    milestone_id=first["id"],
    matter_id=matter_id,
    new_due_date=new_due,
    new_target_date=new_target,
    offset_days=14,
    include_following=True,   # cascade to all later milestones
    shift_tasks=True,          # also shift tasks within them
)
```

**Notes:**
- `offset_days` is a client-side convenience (auto-converted to milliseconds before the wire call). The underlying server query param is `offset=<milliseconds>` — captured from a live UI shift on 2026-05-19 (a ~2.39-day UI shift sent `offset=206641521`). If you ever hand-craft the request, send ms, not days.
- The body's new dates apply to THIS milestone; the offset is what the server applies to every subsequent milestone and their tasks.
- The first call mutates everything. No second call needed.
- **By-design — DONE milestones and tasks don't move**: the cascade intentionally leaves DONE items at their existing dates so historical completion dates remain accurate. This is correct behaviour for normal "client is delayed by N weeks" shifts. ONLY override (with `lib/fix_cascade_laggards.py` or single-item shifts) when you're regenerating demo data or doing a bulk reschedule where preserving completion history isn't important — typically a workspace refresh, not a real-world rescheduling.
- **Note — earlier-suspected anchor-past-followers gotcha was a UNIT BUG**: prior sessions believed cascade fails when the anchor's new due lands past its followers. That was actually the `offset` being interpreted as ms when sent as days. With the unit fix, cascade evaluates "following" by old positions and works regardless of anchor's new placement.
- **Pitfall — target-date in single mode**: `POST /v1/milestones/{id}/date` with NO cascade query params silently ignores `targetDate`, only updating due-date. To set target-date on a single milestone without disturbing followers, use the cascade endpoint with `include_following=False, shift_tasks=False, offset_ms=(cur_due - cur_target)` and `targetDate=cur_due` in the body.

**Confirmation step before running:** show the user the list of milestones with old → new dates so they can sanity-check, then ask "Confirm shift of these N milestones and their tasks?"

---

## Recipe 3: Clean up a demo workspace — push all matter dates 30 days forward

**User says:** "The demo workspace is full of overdue dates. Push everything forward a month so demos look fresh."

**Operations:**

```python
# 1. List all (non-archived) matters in the workspace
matters = c.matters.list()["data"]

# 2. For each matter, shift the first milestone forward 30 days with cascade
shifted = []
for m in matters:
    matter_id = m["id"]
    milestones = c.milestones.list(matter_id=matter_id)["data"]
    if not milestones:
        continue
    sorted_ms = sorted(milestones, key=lambda x: x["attributes"]["due-date"])
    first = sorted_ms[0]
    new_due = first["attributes"]["due-date"] + 30 * 86_400_000
    new_target = first["attributes"]["target-date"] + 30 * 86_400_000
    c.milestones.shift(
        milestone_id=first["id"],
        matter_id=matter_id,
        new_due_date=new_due,
        new_target_date=new_target,
        offset_days=30,
        include_following=True,
        shift_tasks=True,
    )
    shifted.append(m["attributes"].get("name"))
print(f"Shifted dates on {len(shifted)} matters by +30 days.")
```

**Confirmation step:** "I'm about to shift dates on {N} matters by 30 days. Should I proceed, or do you want to exclude any?"

---

## Recipe 4: Create an ad-hoc reminder task

**User says:** "Add a task to the Smith matter to call the client next Tuesday."

**Operations:**

```python
import datetime as dt

# 1. Compute next Tuesday at 5pm in user's local TZ
today = dt.date.today()
days_until_tue = (1 - today.weekday() + 7) % 7 or 7  # Monday=0, Tuesday=1
next_tue = dt.datetime.combine(today + dt.timedelta(days=days_until_tue), dt.time(17, 0))

# 2. Find a milestone to attach to — the current "active" one
milestones = c.milestones.list(matter_id=matter_id)["data"]
active = next(
    (m for m in milestones if m["attributes"].get("status") == "INPROGRESS"),
    milestones[0],  # fall back to first if none in progress
)

# 3. Create the task
c.tasks.create(
    name="Call client",
    matter_id=matter_id,
    milestone_id=active["id"],
    due_date=next_tue,
    description_html="<p>Confirm progress, answer questions.</p>",
)
```

---

## Recipe 5: Build a roadmap from scratch (see workflow-gen-guide.md for the full pattern)

**Sketch:**

```python
# 1. Create draft
draft = c.workflows.create(name="Conveyancing — Standard", type="ROADMAP",
                            description_html="<p>...</p>")
draft_id = draft["data"]["attributes"]["workflow-id"]  # has :DRAFT suffix

# 2. Add milestones; capture each milestone-id from the response
ms1_resp = c.workflows.add_milestone(workflow_draft_id=draft_id, name="Contract review",
                                      due_days_from_start=7)
ms1_id = ms1_resp["data"]["attributes"]["milestones"][-1]["milestone-id"]

# 3. Add tasks per milestone
c.workflows.add_task(workflow_draft_id=draft_id, milestone_id=ms1_id,
                     name="Review section 32", due_minus_days_from_target=2)
# ... etc ...

# 4. Confirm with user, then publish
# (show structure to user as plain text first)
c.workflows.publish(draft_id, audience="WORKSPACE")
```

---

## Recipe 6: Find all my overdue tasks across all my matters

**User says:** "Show me everything I'm late on."

**Operations:**

```python
me = c.call("GET", "/v1/users/whoami", requires_workspace=False)
my_id = me["data"]["id"]

# The task list endpoint accepts assignees and a date range
import time
overdue = c.tasks.list(
    assignees=[my_id],
    status=["TODO", "INPROGRESS"],
    size=100,
)
now_ms = int(time.time() * 1000)
late = [
    t for t in overdue["data"]
    if t["attributes"].get("due-date", 0) < now_ms
]
for t in late:
    print(f"- {t['attributes']['name']}  (due {t['attributes']['due-date']})")
```

---

## Recipe 7: Tear down a test matter cleanly (archive + delete)

```python
c.matters.archive(matter_id)
c.matters.delete(matter_id)  # would 403 without the archive step
```

## Recipe 8: Discard a half-built workflow draft

```python
# If the workflow was never published, the draft IS the workflow.
# Discard via the /draft endpoint with the :DRAFT suffix.
c.workflows.discard_draft(workflow_draft_id="abc:DRAFT")
```

If it was published and you only want to discard pending edits, same call. If you want to delete the whole published workflow, unpublish then delete:

```python
c.workflows.unpublish(workflow_id="abc")
c.workflows.delete(workflow_id="abc")
```

---

## Recipe 9: Align target-date with due-date on a milestone (no follower shift)

**User says:** "On this milestone, the target-date is stale (lagging behind due-date). Bring them in sync without moving anything else."

**Why this is tricky:** single-mode `POST /v1/milestones/{id}/date` (no query params) silently ignores `targetDate` and only updates due-date. To update target-date, you need cascade mode — but you DON'T want subsequent items to actually shift.

**The trick:** Use cascade mode with `include_following=False, shift_tasks=False`, so the cascade fires for THIS milestone only. The `offset_ms` must equal the target-date delta you're applying.

```python
# Find a milestone with target != due
m = next(x for x in c.milestones.list(matter_id=matter_id)["data"]
         if x["id"] == milestone_id)
cur_due = m["attributes"]["due-date"]
cur_target = m["attributes"]["target-date"]
delta_ms = cur_due - cur_target   # how far behind target is

c.milestones.shift(
    milestone_id=milestone_id,
    matter_id=matter_id,
    new_due_date=cur_due,         # unchanged
    new_target_date=cur_due,      # align with due
    offset_ms=delta_ms,            # MUST equal (new_target - old_target)
    include_following=False,
    shift_tasks=False,
)
```

Validated empirically 2026-05-19: target-date on the milestone moves to match due-date, neighbours untouched.

This pattern is what you reach for when an earlier shift (or workflow application) left target-date stranded at an old value while due-date has moved forward. It's also the workaround for the single-mode-ignores-target quirk.

---

## Recipe 10: Bulk-import matters from a connected practice management system

**User says:** *"Import all matters from our PMS where the Clio practice area is 'Family Law' and apply the Family Law Intake roadmap to each. Use the 'Family Law Team' as the default team."*

**Why this needs the import flow (not `c.matters.create`):** creating matters via the standard endpoint does NOT establish the sync link back to the PMS. Names, contacts, and tasks won't sync. The `/v1/imports/...` endpoints DO preserve the link.

**Provider-agnostic**: the same flow works whether the connected PMS is Clio, Actionstep, or Smokeball (Hivelight's three native integrations). The `source` is auto-detected from the workspace's integration record.

```python
from hivelight import HivelightClient
c = HivelightClient()

# 1. Discover the import session id for this workspace (works for any PMS)
session_id = c.imports.default_session_id()
# Or if multiple PMS connected:  c.imports.default_session_id(source="clio")

# 2. List importable items, filter by user criteria
all_items = c.imports.list_items(session_id, query="").get("meta", {}).get("items", [])
selected = [
    it for it in all_items
    if (it.get("raw", {}).get("practice_area") or {}).get("name") == "Family Law"
]

print(f"{len(selected)} Family Law matters to import:")
for it in selected:
    print(f"  - {it['normalized']['name']}  (Clio id: {it['meta']['id']})")
# Confirm with user before proceeding

# 3. Resolve roadmap + team
fam_roadmap = next(
    w for w in c.workflows.list(type="ROADMAP")["data"]
    if "Family Law Intake".lower() in w["attributes"]["name"].lower()
)
team_id = "<the team id you want>"  # discover via the workspace teams config

# 4. For each: trigger import (with team override), then apply roadmap to the
#    new Hivelight matter
for it in selected:
    item_id = it["meta"]["id"]
    new_matter_id = it["destinationId"]   # pre-assigned during normalization

    # Import: passes team_id through set_item_meta first, then triggers /import
    c.imports.import_item(session_id, item_id, team_id=team_id)

    # Apply roadmap as a separate step (applying a roadmap during import is not
    # supported yet; apply it as a follow-up call instead)
    c.workflows.apply(
        workflow_id=fam_roadmap["attributes"]["workflow-id"],
        matter_id=new_matter_id,
    )
    print(f"  Imported {it['normalized']['name']} -> matter {new_matter_id}")
```

**Confirmation step before mutating**: show the user the matched list (name + Clio id) and ask "Import these N matters with team X and roadmap Y?" Especially important for big onboarding batches.

**Key things to know:**
- The `destinationId` from `list_items` IS the Hivelight matter id — no separate lookup needed after import.
- `import_item` is async server-side. The session's `progress.matter.complete` counter increments as imports finish; usually within a second per matter but can take longer for large matters with many contacts/tasks.
- Filtering: `query` matches against a `searchable` field (name + description + number + source id + jurisdiction). For PMS-specific attributes like `practice_area`, `status`, `responsible_attorney`, list everything and filter client-side from `item["raw"]`.
- Multiple PMS providers connected on one workspace: use `default_session_id(source="clio")` or list_integrations() then pick the session id directly.
