"""One-off: explain 225 JSON records vs 202 rendered rows (multi-city grouping?)."""
import collections
import json

data = json.load(open("scripts/one_off/recipe_spike/captures/janestreet/raw/000.json"))
print("records:", len(data))
print("distinct ids:", len({d["id"] for d in data}))

by_pos = collections.Counter((d["position"], d["availability"]) for d in data)
print("distinct (position, availability) groups:", len(by_pos))
multi = {k: v for k, v in by_pos.items() if v > 1}
print("groups with >1 city:", len(multi))
for (pos, avail), n in sorted(multi.items(), key=lambda kv: -kv[1])[:8]:
    cities = [d["city"] for d in data if d["position"] == pos and d["availability"] == avail]
    print(f"  {n}x {pos!r} [{avail}] cities={cities}")

cities = collections.Counter(d["city"] for d in data)
print("cities:", dict(cities))
