"""Scan every active matter in the configured workspace; report overdue + target-stale counts."""
import datetime as dt, time
from hivelight import HivelightClient

c = HivelightClient()   # uses default workspace from ~/.config/hivelight-skill/config.json
now_ms = int(time.time()*1000)
DAY = 86_400_000


def f(x): return dt.datetime.utcfromtimestamp(x/1000).strftime("%Y-%m-%d") if x else "----------"


matters = []
page = 0
size = 100
while True:
    batch = c.internal_call("GET", "/v1/matters", query={"from": page * size, "size": size}).get("data", [])
    if not batch:
        break
    matters.extend(batch)
    if len(batch) < size:
        break
    page += 1
print(f"Total matters in workspace (paginated): {len(matters)}\n")

rows = []
for m in matters:
    a = m.get("attributes", {})
    if a.get("is-archived"):
        continue
    mid = m["id"]
    name = (a.get("name") or "?").encode("ascii", "replace").decode("ascii")
    try:
        ms = c.milestones.list(matter_id=mid).get("data", [])
    except Exception as e:
        rows.append({"name": name, "id": mid, "error": str(e)[:80]})
        continue
    dated = [x for x in ms if x["attributes"].get("due-date") is not None]
    overdue = [x for x in dated if x["attributes"]["due-date"] < now_ms]
    stale = [x for x in dated
             if x["attributes"].get("target-date") is not None
             and abs(x["attributes"]["due-date"] - x["attributes"]["target-date"]) > DAY]
    rows.append({
        "name": name, "id": mid,
        "ms_total": len(ms), "ms_dated": len(dated),
        "overdue": len(overdue), "stale": len(stale),
        "earliest_due": f(dated[0]["attributes"]["due-date"]) if dated else None,
    })

# Print summary
print(f"{'#':>3}  {'Matter':<45} {'ms':>3} {'dated':>5} {'overdue':>7} {'tgt-stale':>9}  earliest")
print("-" * 100)
for i, r in enumerate(rows, 1):
    if "error" in r:
        print(f"{i:>3}  {r['name'][:44]:<45}  err: {r['error']}")
    else:
        print(f"{i:>3}  {r['name'][:44]:<45} {r['ms_total']:>3} {r['ms_dated']:>5} {r['overdue']:>7} {r['stale']:>9}  {r.get('earliest_due') or ''}")

# Aggregate
to_shift = [r for r in rows if r.get("overdue", 0) > 0]
to_align = [r for r in rows if r.get("stale", 0) > 0]
print(f"\n=== {len(to_shift)} matters with overdue milestones ===")
for r in to_shift:
    print(f"  {r['name'][:45]:<46}  ms={r['ms_total']:>2}  overdue={r['overdue']:>2}  earliest={r['earliest_due']}  id={r['id']}")
print(f"\n=== {len(to_align)} matters with target-stale milestones ===")
for r in to_align:
    print(f"  {r['name'][:45]:<46}  stale={r['stale']:>2}  id={r['id']}")
