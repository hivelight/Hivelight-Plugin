"""Find every active matter in the configured workspace with overdue milestones, then for
each: pick a random new date for the earliest milestone in [TODAY+14d, TODAY+56d],
compute the delta, and shift every dated milestone (and its tasks) by that delta.

Uses the now-corrected lib (offset in ms) and the validated single-milestone
cascade-with-no-followers pattern that updates target-date alongside due-date.

Idempotent shape: rerun safely — matters with no overdue items are skipped.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import random
import time
from typing import Optional

from hivelight import HivelightClient

DAY_MS = 86_400_000
SHIFT_MIN_DAYS = 14
SHIFT_MAX_DAYS = 56
RANDOM_SEED = 20260520


def f(x): return dt.datetime.utcfromtimestamp(x / 1000).strftime("%Y-%m-%d") if x else "----------"
def ascii_(s): return (s or "").encode("ascii", "replace").decode("ascii")


def list_all_matters(c: HivelightClient) -> list[dict]:
    out, page, size = [], 0, 100
    while True:
        batch = c.internal_call("GET", "/v1/matters", query={"from": page * size, "size": size}).get("data", [])
        if not batch:
            break
        out.extend(batch)
        if len(batch) < size:
            break
        page += 1
    return out


def main(apply_changes: bool, only_matter_id: Optional[str] = None) -> None:
    random.seed(RANDOM_SEED)
    c = HivelightClient()  # uses default workspace from ~/.config/hivelight-skill/config.json
    now_ms = int(time.time() * 1000)
    today_utc = dt.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_ms = int(today_utc.timestamp() * 1000)
    print(f"Today (UTC): {today_utc.strftime('%Y-%m-%d')}")
    print(f"Shift window: TODAY+{SHIFT_MIN_DAYS}d .. TODAY+{SHIFT_MAX_DAYS}d "
          f"({f(today_ms + SHIFT_MIN_DAYS * DAY_MS)} .. {f(today_ms + SHIFT_MAX_DAYS * DAY_MS)})")
    print(f"Mode: {'APPLY' if apply_changes else 'DRY-RUN'}")
    print()

    matters = list_all_matters(c)
    if only_matter_id:
        matters = [m for m in matters if m["id"] == only_matter_id]
    active = [m for m in matters if not m.get("attributes", {}).get("is-archived")]
    print(f"Total matters: {len(matters)}  Active: {len(active)}")

    plan = []
    for m in active:
        mid = m["id"]
        mname = ascii_(m.get("attributes", {}).get("name"))
        try:
            ms_list = c.milestones.list(matter_id=mid).get("data", [])
        except Exception as e:
            print(f"[skip] {mname}: milestones list error: {e}")
            continue
        dated = [x for x in ms_list if x["attributes"].get("due-date") is not None]
        if not dated:
            continue
        dated.sort(key=lambda x: x["attributes"]["due-date"])
        overdue = [x for x in dated if x["attributes"]["due-date"] < now_ms]
        if not overdue:
            continue
        earliest = dated[0]
        old_anchor_due = earliest["attributes"]["due-date"]
        shift_days = random.randint(SHIFT_MIN_DAYS, SHIFT_MAX_DAYS)
        new_anchor_due_ms = today_ms + shift_days * DAY_MS
        delta_ms = new_anchor_due_ms - old_anchor_due
        plan.append({
            "matter_id": mid, "matter_name": mname,
            "earliest_ms_id": earliest["id"],
            "earliest_ms_name": ascii_(earliest["attributes"].get("name")),
            "old_anchor_due_ms": old_anchor_due,
            "new_anchor_due_ms": new_anchor_due_ms,
            "delta_ms": delta_ms,
            "delta_days_approx": round(delta_ms / DAY_MS),
            "ms_dated": len(dated),
            "ms_overdue": len(overdue),
            "ms_objs": [(x["id"], ascii_(x["attributes"].get("name")),
                         x["attributes"]["due-date"],
                         x["attributes"].get("target-date"))
                        for x in dated],
        })

    # Show plan
    print(f"\n{len(plan)} matter(s) need shifting.\n")
    print(f"{'#':>3}  {'Matter':<32} {'Earliest milestone':<26} {'Old earliest':<12} {'New earliest':<12}  {'+days':>6}  {'ms':>3}/{'ovr':>3}")
    print("-" * 110)
    for i, p in enumerate(plan, 1):
        print(f"{i:>3}  {p['matter_name'][:31]:<32} {p['earliest_ms_name'][:25]:<26} {f(p['old_anchor_due_ms']):<12} {f(p['new_anchor_due_ms']):<12}  {p['delta_days_approx']:>6}  {p['ms_dated']:>3}/{p['ms_overdue']:>3}")

    # Save plan
    plan_path = "shift_plan_all.json"
    plan_serializable = [{k: v for k, v in p.items() if k != "ms_objs"} for p in plan]
    with open(plan_path, "w", encoding="utf-8") as fout:
        json.dump({"seed": RANDOM_SEED, "today_ms": today_ms, "plan": plan_serializable}, fout, indent=2)
    print(f"\nPlan saved to {plan_path}")

    if not apply_changes:
        print("\nDRY-RUN — no changes applied. Re-run with --apply to execute.")
        return

    print("\n========== APPLYING (cascade mode — ONE call per matter) ==========\n")
    ok = err = 0
    errors = []
    for i, p in enumerate(plan, 1):
        mid = p["matter_id"]
        delta_ms = p["delta_ms"]
        anchor_id = p["earliest_ms_id"]
        new_anchor_due = p["new_anchor_due_ms"]
        print(f"[{i}/{len(plan)}] {p['matter_name']:<35} anchor={p['earliest_ms_name'][:25]:<26} +{p['delta_days_approx']}d")
        try:
            c.milestones.shift(
                milestone_id=anchor_id,
                matter_id=mid,
                new_due_date=new_anchor_due,
                new_target_date=new_anchor_due,
                offset_ms=delta_ms,
                include_following=True,
                shift_tasks=True,
                is_key_date=False,
            )
            ok += 1
        except Exception as e:
            err += 1
            errors.append({"matter": mid, "ms": anchor_id, "err": str(e)[:200]})
            print(f"    ERR: {type(e).__name__}: {str(e)[:200]}")

    print(f"\nDone. Matters cascaded: {ok}  errors: {err}.")
    if errors:
        for e in errors[:10]:
            print(f"  {e}")
    if errors:
        print("First few errors:")
        for e in errors[:10]:
            print(f"  {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Apply changes (default: dry-run only)")
    ap.add_argument("--matter", help="Restrict to a single matter id (for testing)")
    args = ap.parse_args()
    main(apply_changes=args.apply, only_matter_id=args.matter)
