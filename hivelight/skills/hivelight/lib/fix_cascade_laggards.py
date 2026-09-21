"""After a cascade shift, DONE milestones between the anchor and followers can
be skipped (not shifted), breaking order. This script reads the saved plan and
for each matter, finds any milestone still at a pre-shift date (significantly
older than the cascaded items) and shifts it by the matter's original delta
using cascade-no-followers (single-milestone shift with target update).

Also shifts active tasks that didn't move with the cascade (likely DONE tasks
the cascade skipped — left to discretion since they're completed).
"""
from __future__ import annotations
import datetime as dt
import json
import time
from hivelight import HivelightClient

def f(x): return dt.datetime.utcfromtimestamp(x/1000).strftime("%Y-%m-%d") if x else "-"
def ascii_(s): return (s or "").encode("ascii", "replace").decode("ascii")


def main(also_fix_done_tasks: bool = False):
    c = HivelightClient()  # uses default workspace from ~/.config/hivelight-skill/config.json
    with open("shift_plan_all.json", "r", encoding="utf-8") as f_in:
        plan_doc = json.load(f_in)
    now_ms = int(time.time() * 1000)
    delta_by_matter = {p["matter_id"]: p["delta_ms"] for p in plan_doc["plan"]}

    n_shifted = n_err = 0
    errors = []
    for matter_id, delta_ms in delta_by_matter.items():
        try:
            ms_list = c.milestones.list(matter_id=matter_id).get("data", [])
        except Exception as e:
            print(f"  list err {matter_id}: {e}")
            continue
        laggards = [m for m in ms_list
                    if m["attributes"].get("due-date") is not None
                    and m["attributes"]["due-date"] < now_ms]
        if not laggards:
            continue
        mname = ascii_(next((m["attributes"].get("name") for m in ms_list if m["id"] == matter_id), ""))
        # Get matter name from the plan
        plan_entry = next((p for p in plan_doc["plan"] if p["matter_id"] == matter_id), {})
        mname = plan_entry.get("matter_name", "?")
        print(f"\n{mname} ({matter_id})  delta=+{round(delta_ms/86_400_000)}d  laggards={len(laggards)}")
        for m in laggards:
            a = m["attributes"]
            ms_name = ascii_(a.get("name"))
            cur_due = a["due-date"]
            cur_target = a.get("target-date") or cur_due
            new_due = cur_due + delta_ms
            try:
                c.milestones.shift(
                    milestone_id=m["id"],
                    matter_id=matter_id,
                    new_due_date=new_due,
                    new_target_date=new_due,
                    offset_ms=delta_ms,
                    include_following=False,
                    shift_tasks=False,
                )
                n_shifted += 1
                print(f"    [ok]  {ms_name[:40]:<42}  {f(cur_due)} -> {f(new_due)}")
            except Exception as e:
                n_err += 1
                errors.append({"matter": matter_id, "ms": m["id"], "err": str(e)[:200]})
                print(f"    [ERR] {ms_name[:40]:<42}  {type(e).__name__}: {str(e)[:200]}")

    print(f"\nDone. Laggard milestones shifted: {n_shifted}  errors: {n_err}.")


if __name__ == "__main__":
    main()
