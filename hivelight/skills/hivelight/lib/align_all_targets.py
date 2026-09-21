"""Workspace-wide target=due alignment. For any milestone where target-date
differs from due-date by more than 1 day, apply the validated cascade-no-followers
align trick to set target = due without disturbing neighbours.
"""
import datetime as dt
from hivelight import HivelightClient

DAY_MS = 86_400_000

c = HivelightClient()   # uses default workspace from ~/.config/hivelight-skill/config.json


def f(x): return dt.datetime.utcfromtimestamp(x/1000).strftime("%Y-%m-%d") if x else "-"
def ascii_(s): return (s or "").encode("ascii", "replace").decode("ascii")


# Paginated matter list
matters, page, size = [], 0, 100
while True:
    batch = c.internal_call("GET", "/v1/matters", query={"from": page * size, "size": size}).get("data", [])
    if not batch:
        break
    matters.extend(batch)
    if len(batch) < size:
        break
    page += 1

fixed = err = 0
for m in matters:
    if m.get("attributes", {}).get("is-archived"):
        continue
    mid = m["id"]
    mname = ascii_(m.get("attributes", {}).get("name"))
    try:
        ms_list = c.milestones.list(matter_id=mid).get("data", [])
    except Exception as e:
        continue
    for ms in ms_list:
        a = ms["attributes"]
        cur_due = a.get("due-date")
        cur_target = a.get("target-date")
        if cur_due is None or cur_target is None:
            continue
        delta_ms = cur_due - cur_target
        if abs(delta_ms) <= DAY_MS:
            continue
        try:
            c.milestones.shift(
                milestone_id=ms["id"],
                matter_id=mid,
                new_due_date=cur_due,
                new_target_date=cur_due,
                offset_ms=delta_ms,
                include_following=False,
                shift_tasks=False,
                is_key_date=bool(a.get("is-key-date")),
            )
            fixed += 1
            print(f"  {mname[:25]:<27}  {ascii_(a.get('name'))[:35]:<37}  target {f(cur_target)} -> {f(cur_due)}")
        except Exception as e:
            err += 1
            print(f"  [ERR] {mname[:25]} / {ascii_(a.get('name'))}: {type(e).__name__}: {str(e)[:200]}")

print(f"\nDone. Aligned: {fixed}  errors: {err}")
