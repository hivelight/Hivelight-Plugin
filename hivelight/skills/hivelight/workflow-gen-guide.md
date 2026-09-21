# Workflow Generation Guide

This file is for the case where a user describes a legal process in natural language and wants the skill to materialise it as a Hivelight workflow (roadmap or task list). Read this before building.

## What you're producing

A **roadmap** is a published template that other people can apply to matters. It contains:

- **Workflow metadata** — name, description, jurisdictions (optional filter), matter types (optional filter), audience (who can use it).
- **Milestones** — ordered chunks of work. Each has a name, description, due date, and target date. Dates are **relative**, not absolute.
- **Tasks** — items inside a milestone. Each has a name, description, due date (relative to the parent milestone), an **assignee role**, a **reviewer role**, and optionally links to other tasks within the same milestone. **All five — name, description, due offset, assignee role, reviewer role — should be populated.** Bare-name tasks with zero-offset dates and no roles produce an obviously machine-generated roadmap.

The publishing model: you create a **draft** (id has `:DRAFT` suffix), populate it, and then `publish()` with an audience. After publishing the draft suffix is dropped from the id and the workflow becomes available to apply to matters.

## The relative-date system

Hivelight templates use relative dates so a single workflow can be applied to many matters with different start dates.

There are four anchors:

| `relativeTo` | Used for | Meaning |
|---|---|---|
| `ROADMAP_START_DATE` | Milestone due dates | "N days after the matter's start date" |
| `MILESTONE_DUE_DATE` | Milestone target dates | "M days before the milestone's own due date" |
| `MILESTONE_TARGET_DATE` | Task due dates (within a roadmap milestone) | "K days before the milestone's target date" |
| `CURRENT_DATE` | Task due dates (within a task-list workflow) | "K days after the moment the task list is applied" |

Direction is encoded as `plus: N` (after) or `minus: M` (before). E.g. a task due 2 days before its milestone target is `{relativeTo: "MILESTONE_TARGET_DATE", minus: 2}`.

## Build sequence

1. `c.workflows.create(name=..., description_html=..., type="ROADMAP")` → returns draft with id like `"abc123:DRAFT"`.
2. For each milestone (in order):
   - `c.workflows.add_milestone(workflow_draft_id="abc123:DRAFT", name=..., due_days_from_start=N, target_minus_days_from_due=M)`
   - For each task in that milestone:
     - `c.workflows.add_task(workflow_draft_id="abc123:DRAFT", milestone_id=<id from previous response>, name=..., due_minus_days_from_target=K)`
3. (Optional) Edit task assignees, descriptions, tags via individual edit endpoints.
4. **Reorder each milestone's tasks so the editor displays them in execution order** (see "Task display order" below):
   - `c.workflows.reorder_tasks_chronologically(workflow_draft_id="abc123:DRAFT", milestone_id=<id>)`
5. `c.workflows.publish(workflow_draft_id="abc123:DRAFT", audience="WORKSPACE")` → drops suffix, version becomes 1.

For a **task list** (instead of a roadmap), pass `type="TASK_LIST"` to `create()`. Task lists have only one synthetic milestone with the literal id `"TASK_LIST"`. Tasks are still added to it the same way, and their due dates use `relativeTo: "CURRENT_DATE"` automatically when you call `add_task` with that milestone id.

## Always confirm before publishing

This is non-negotiable: **show the user the proposed structure as plain text first** and ask them to confirm before calling `publish()`. The structure should include each milestone with its dates, each task with its due date relative to the milestone, and any assumptions you made (typical durations, jurisdiction-specific steps, etc.).

If the user says "looks good", publish. If they suggest changes, edit the draft (don't recreate from scratch) and re-show.

## Heuristics for generating from natural language

### Sizing milestones
- A typical legal matter has 3–7 milestones. More than 8 means you're probably putting too many things at the top level — group related items.
- Each milestone is a "stage" the matter passes through. Words like "after we…", "once we have…", or "before we can…" in the user's description usually mark milestone boundaries.

### Sizing tasks
- A task is one thing one person does. If you find yourself writing "Do X AND Y", split it.
- Tasks within a milestone aren't strictly ordered by Hivelight, but adjacent tasks usually have due dates close to each other.

### Estimating durations
- Ask the user for typical durations if not specified. If they don't know, use conservative defaults:
  - Simple admin tasks: 1–2 days
  - Document drafting: 3–7 days
  - Client communication / scheduling: 2–5 days
  - External waiting (court, government, third party): 14–30 days, mark these as key dates
- Use `is_key_date: true` (passed to `set_dates` after publishing, since draft milestones don't carry this attribute) for milestones whose due date is statutory or otherwise immovable.

### Jurisdiction & matter type filters
- If the user mentions a specific jurisdiction ("NSW Personal Injury") or matter type ("Conveyancing"), include it as a metadata filter so the roadmap surfaces only on matching matters.
- If unsure, leave both empty — the workflow becomes available to all matters.

### Description content

- **Roadmap description**: 1–2 sentences explaining what the workflow is for and when to use it. The legal team scans these when picking a roadmap for a new matter.
- **Milestone descriptions**: optional but useful for unfamiliar processes. Keep them short.
- **Task descriptions**: every task should have one. HTML is supported. **Follow the four-section structure used by Hivelight's own demo content** — it's how the team thinks about tasks:

  ```html
  <p><b>Description</b></p>
  <p>What is this task and why does it matter? Plain-English context for whoever picks it up.</p>
  <p><b>Steps</b></p>
  <ol>
    <li>Specific action 1</li>
    <li>Specific action 2</li>
    <li>Move to Review when complete, message the Reviewer to check.</li>
  </ol>
  <p><b>Outcomes</b></p>
  <p>The concrete artifact or state change this task produces.</p>
  <p><b>Resources</b></p>
  <p>Precedent files, key links, internal references — as HTML <code>&lt;a&gt;</code> tags.</p>
  ```

  Don't ship bare-name tasks. A roadmap with empty descriptions reads as machine-generated even when the structure is correct.

### Roles (assignee + reviewer)

Every template task **must** have an assignee role and a reviewer role. These are functional roles, not specific users — at template authoring time you don't know who'll do the work. Hivelight's canonical role enum:

| Enum value | UI label |
|---|---|
| `OWNER` | Matter Owner — usually the principal or partner who owns the matter |
| `LEAD` | Matter Lead — day-to-day senior responsible for the matter |
| `PRINCIPAL` | Principal |
| `LEGAL_1` | Senior Lawyer |
| `LEGAL_2` | Junior Lawyer |
| `LEGAL_3` | Law Clerk / Paralegal |
| `ADMINISTRATIVE_1` | Senior Legal Assistant |
| `ADMINISTRATIVE_2` | Junior Legal Assistant |
| `BUSINESS_1` | Business Administrator |
| `ADVOCATE_1` | Advocate |
| `CONSULTANT_1` | Consultant |

**Sensible defaults by task type:**

| Task character | Default assignee | Default reviewer |
|---|---|---|
| Initial client contact / intake call | `LEGAL_3` or `ADMINISTRATIVE_2` | `LEAD` |
| Conflict check | `ADMINISTRATIVE_1` | `LEAD` |
| Drafting docs / letters | `LEGAL_2` | `LEGAL_1` |
| Strategic decisions / advice to client | `LEAD` | `OWNER` |
| Filings / lodgements | `LEGAL_3` | `LEGAL_1` |
| Bookkeeping / trust admin | `BUSINESS_1` | `LEAD` |

These are starting points — confirm with the user if the firm has a different convention. The actual mapping for a workspace is in `/v1/configurations/workspace` (`matterRoleDefinitions`).

### Auto-reassignment cascade — pick the LOWEST sensible role

Hivelight automatically resolves task assignee/reviewer roles to actual users based on the matter team. **If the named role is unfilled on the matter, the task escalates up the cascade.** This is well-documented behavior: see [docs.hivelight.com Automatic task reassignment](https://docs.hivelight.com/en/articles/8797952-automatic-task-reassignment-matter-roles-matter-team-roles).

The cascade hierarchy (per Hivelight's published diagram; admin-portion verified empirically 2026-05-19):

```
ADMINISTRATIVE_2  ->  ADMINISTRATIVE_1  ->  LEGAL_3  ->  LEGAL_2  ->  LEGAL_1  ->  LEAD  ->  OWNER
LEGAL_3                                 ->  LEGAL_2  ->  LEGAL_1  ->  LEAD  ->  OWNER
ADVOCATE_1                                                        ->  LEAD  ->  OWNER
CONSULTANT_1                                                      ->  LEAD  ->  OWNER
BUSINESS_1                                                                   ->  OWNER  (direct, skips LEAD)
LEAD                                                                         ->  OWNER
```

The admin chain crosses INTO the legal chain at LEGAL_3 — an unfilled Senior Admin Assistant escalates to the Paralegal/Law Clerk, then up through the legal chain to LEAD and OWNER. This is the documented behavior and matches empirical testing.

Reassignment fires both at **workflow-apply time** AND when **a user is removed** from a matter team. So as long as OWNER is filled (which is mandatory for matter creation), every task ends up with a real user assigned.

**Implications for the workflow generator:**

- **Pick the lowest role that makes sense** — the cascade handles the upward path automatically. Assigning a drafting task to `LEGAL_2` means "Junior Lawyer if filled, else Senior Lawyer, else Lead, else Owner".
- **For decisions, pick the actual decision-maker.** Don't assign a strategy meeting to `LEGAL_3` and rely on cascade — the work is properly an `OWNER` / `LEAD` activity. Cascade is for capacity, not authority.
- **`BUSINESS_1` skips `LEAD`** and goes straight to `OWNER`. This is documented behavior — financial / admin tasks are owner-level not lead-level.
- **`PRINCIPAL` is a team role but not a functional role.** A Principal user on the matter team may hold OWNER or LEAD positions on specific matters; tasks don't directly assign to PRINCIPAL.
- **Workflow tasks with no assignee at all** are treated as `LEAD`, then `OWNER`. So a task with `assigneeRole=""` still resolves cleanly.

### Task links (within-milestone dependencies)

Hivelight supports three relationship types between tasks **in the same milestone** (cross-milestone links are not allowed):

- `REQUIRES` — "Requires": the linked task is a prerequisite of the current task. *"The current task requires the linked task to be completed before it is ready to start."*
- `REQUIRED_BY` — "Required by": the current task is a prerequisite of the linked task.
- `RELATED_TO` — neither is a prerequisite, but they're meaningfully related.

Reference: [How to use task links to show relationships between tasks](https://docs.hivelight.com/en/articles/9470610-how-to-use-task-links-to-show-relationships-between-tasks).

The UI displays linked tasks as a checklist on the task card — completing the prerequisite ticks it off. Use links liberally for sequential work — they let the team see the dependency graph at a glance.

**CRITICAL — chronological-order invariant.** A `REQUIRES` link is only sane if the prerequisite's due date is **on or before** the dependent's due date. Within a milestone (where `due_minus_days_from_target` measures days *before* the milestone target), this means: for every `B REQUIRES A`, you need `A.due_minus >= B.due_minus`. Linking a task to a prerequisite that is due *later* produces a roadmap that is impossible to complete on time and reads as obviously broken when the team opens the matter. The Hivelight UI does NOT always display tasks in chronological order, so visual inspection is not a safeguard — you must enforce this in code.

**Algorithm to use — sort first, then chain.** Do NOT rely on the order tasks appear in the input spec.

```python
# 1) Build all tasks for the milestone (capture id + due_minus on each).
created = []  # list of {"name", "id", "due_minus"}
for t_spec in milestone_spec["tasks"]:
    resp = c.workflows.add_task(
        workflow_draft_id=draft_id,
        milestone_id=mid,
        name=t_spec["name"],
        description_html=t_spec["description"],
        due_minus_days_from_target=t_spec["due_minus"],
        assignee_role=t_spec["assignee"],
        reviewer_role=t_spec["reviewer"],
    )
    created.append({
        "name": t_spec["name"],
        "id": resp["data"]["attributes"]["task-id"],
        "due_minus": t_spec["due_minus"],
    })

# 2) Sort by due_minus DESCENDING (highest minus = earliest in the milestone).
chrono = sorted(created, key=lambda t: -t["due_minus"])

# 3) Chain: each task REQUIRES the previous task in chronological order.
#    Skip linking when due_minus is identical AND there is no real dependency
#    (parallel work in the same window doesn't need a link — see "same-day" note below).
for i in range(1, len(chrono)):
    prev, curr = chrono[i - 1], chrono[i]
    if prev["due_minus"] == curr["due_minus"]:
        continue  # parallel: link only if there is a genuine prerequisite
    c.workflows.link_tasks(
        workflow_draft_id=draft_id,
        milestone_id=mid,
        from_task_id=curr["id"],   # dependent
        to_task_id=prev["id"],     # prerequisite (due same day or earlier)
        type="REQUIRES",
    )
```

**Same-day tasks.** When two tasks share a `due_minus`, prefer leaving them unlinked unless one is a true prerequisite of the other (e.g. "Take retainer" genuinely cannot precede "Sign engagement letter" even if they happen in the same meeting). Auto-chaining same-day tasks creates ceremonial links that add noise without informing scheduling.

**Cross-checking before publish.** Before calling `publish()`, walk every link you created and assert `prereq.due_minus >= dependent.due_minus`. If any link fails this check, do not publish — show the user the offending pair and either reorder, drop the link, or change a due date with their explicit confirmation. The client's `link_tasks()` enforces this guardrail at runtime; passing `allow_inverted_dates=True` is required to override it for the rare case where the inversion is intentional (e.g. corrective work that must run before a previously scheduled task).

### Task display order (rank field) — must be set explicitly

The Hivelight editor displays tasks within a milestone by sorting on a Lexorank-style `rank` string attribute that the server assigns on creation. The order is **NOT insertion order, NOT due-date order, NOT task-id order** — it's whatever rank string the server happens to allocate. Two consequences:

1. **A roadmap will read as out-of-order even when the SPEC was written chronologically** unless you explicitly reorder tasks after creating them.
2. **You can't audit the displayed order by reading the SPEC** — you must inspect `rank` on each task.

After creating all tasks in a milestone (with their `due_minus` set correctly), call:

```python
c.workflows.reorder_tasks_chronologically(
    workflow_draft_id=draft_id,
    milestone_id=mid,
)
```

This sorts the milestone's tasks by `due_minus` DESC (highest minus = earliest in the milestone) and chains move calls so the editor displays them in execution order. The first task in the milestone will be the no-prerequisites kickoff task; the last will be the one due closest to the milestone target date.

The lower-level primitives if you need finer control:

- `c.workflows.move_task(workflow_draft_id, milestone_id, task_id, before_rank=<rank_str>)` — sets a new rank lexicographically less than the given rank.
- `c.workflows.move_task(workflow_draft_id, milestone_id, task_id, after_rank=<rank_str>)` — sets a new rank lexicographically greater.
- `c.workflows.move_task_relative_to(workflow_draft_id, milestone_id, task_id, before_task_id=<id>)` — same idea but takes a task id (it looks up the current rank for you).

**Critical:** the move endpoint takes RANK STRINGS, not task IDs. The first version of this client tried to pass task IDs and produced random-looking orderings because the server happily treated the ids as rank strings. Always use the helpers above instead of hand-rolling the POST.

The reorder must happen on the `:DRAFT`, not the published workflow. If the workflow is already published and you need to fix the order, create a draft (`POST /v1/workflows/{id}/draft`), reorder, then republish.

### Intra-milestone date staggering

**Fan tasks out as evenly as the work allows.** A roadmap where every task in a milestone shares the same due date reads as machine-generated even if the structure and roles are right. Real legal work is rarely "all due the same day"; even when work happens in one sitting, the tasks should still have a notional order.

**Default formula** — for a milestone with target offset T days before due and N tasks:

```
task_i due_minus = round((N - i) / N * T)
```

So a 5-day milestone (target -5 from due) with 4 tasks fans out as:
- Task 1 due at -5 (start of the window)
- Task 2 due at -4
- Task 3 due at -2
- Task 4 due at 0 (close-out)

For a tighter milestone (e.g. 1-day target) with 5 tasks, the natural spread is fractional — round to 1, 1, 1, 0, 0 if you must, but consider whether the milestone is genuinely big enough for 5 tasks or whether some should merge. Five tasks all due on the same day is a smell.

**Exceptions where bunching is legitimate** (use sparingly, and document why in the task description):

| Situation | Example | What to do |
|---|---|---|
| Statutory deadline forces same date | "Lodge by EOD on statutory cut-off day" | Same date is correct — but explain in the description that this date is non-negotiable. |
| Tasks in one client-facing session | "Conduct VOI" + "Issue trust account details" + "Take initial retainer" all in the same meeting | Bunch on the meeting date. Same date is honest. |
| One task can't start until another finishes, with negligible work in between | "Sign engagement letter" then "Open matter file in PMS" | Same date is OK; the REQUIRES link encodes the actual order. |
| Court / external party imposes a window with no internal preference | E.g. discovery responses any time in 30-day window | Spread anyway — the firm benefits from a planned rhythm. |

**Anti-pattern: putting 5+ tasks all at `due_minus_days_from_target=0`** unless you can write a one-line description for each explaining why that specific timing is forced. If you can't, fan them out.

## Worked example

**User prompt:** "Build me a roadmap for handling the pre-filing stage of a personal injury claim in NSW."

**First, you summarise back to confirm the scope:**

> I'll build a 4-milestone roadmap covering: (1) intake & costs agreement, (2) gathering records, (3) drafting & sending the pre-litigation notice, (4) settlement attempt or filing decision. Each milestone has 2–4 tasks. Sound right, or adjust before I draft it?

**After the user confirms, you draft (as text, not API calls yet):**

```
Roadmap: "Personal Injury — Pre-filing (NSW)"
Jurisdictions: ["AU-NSW"]
Matter types: ["Personal Injury"]

Milestone 1: Intake & costs agreement (due: day 7 after start, target: day 5)
  - Initial client consultation (due 2 days before milestone target)
  - Conflict check (due 3 days before milestone target)
  - Send and obtain signed costs agreement (due 0 days before milestone target)

Milestone 2: Gathering records (due: day 45, target: day 40)
  - Send authorities to medical providers (due 30 days before milestone target)
  - Send authority to police / employer (due 30 days before milestone target)
  - Follow up outstanding records (due 7 days before milestone target)
  - Save records to matter (due 0 days before milestone target)

Milestone 3: Pre-litigation notice (due: day 70, target: day 65)
  - Draft notice (due 14 days before milestone target)
  - Internal review (due 7 days before milestone target)
  - Send to defendant / insurer (due 0 days before milestone target)

Milestone 4: Settlement or filing decision (due: day 120, target: day 115)
  - Defendant response received & reviewed (due 30 days before target)
  - Settlement conference (due 14 days before target)
  - Decision: settle or proceed to filing (due 0 days before target)
```

**Then ask: "Does this structure look right? If so, I'll create it as a draft, populate it, and publish to the workspace audience."**

After approval, fire the API calls in sequence. If anything fails partway, the draft remains and the user can resume.

## Anti-patterns

- **Don't auto-publish.** Always wait for explicit user confirmation after showing the structure.
- **Don't invent jurisdictions or matter types.** Use `c.call("GET", "/v1/configurations/jurisdictions", public=True)` if you need the canonical list. Same for matter types at `/v1/configurations/matter/types`.
- **Don't combine create + populate + publish into one silent operation.** Show progress per step so the user can interrupt if something looks off.
- **Don't ship tasks without descriptions, roles, and varied dates.** A roadmap where every task in a milestone is due at the same time, has no description, and no assignee/reviewer reads as machine-generated. The four required-for-quality fields per task are: descriptive name, four-section HTML description, varied `due_minus_days_from_target`, and BOTH `assignee_role` and `reviewer_role`. Use sequential `REQUIRES` links within each milestone where there's real ordering.
- **Don't add `is_key_date: true` to draft milestones.** That attribute lives on the matter-level milestone (after the workflow is applied), not the template. Add it via `c.milestones.set_dates(..., is_key_date=True)` after the roadmap is applied to a matter.
- **Don't cross-milestone-link.** Hivelight rejects task links where the two tasks aren't in the same milestone.
