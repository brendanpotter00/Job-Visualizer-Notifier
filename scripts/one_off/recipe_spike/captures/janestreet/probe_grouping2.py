"""One-off: per-audience group counts vs rendered row counts."""
import collections
import json

data = json.load(open("scripts/one_off/recipe_spike/captures/janestreet/raw/000.json"))
exp = [d for d in data if d["availability"] == "Full-Time: Experienced"]
stu = [d for d in data if d["availability"] != "Full-Time: Experienced"]
print("experienced records:", len(exp), "groups(position):", len({d["position"] for d in exp}),
      "groups(position,availability):", len({(d["position"], d["availability"]) for d in exp}))
print("student records:", len(stu), "groups(position):", len({d["position"] for d in stu}),
      "groups(position,availability):", len({(d["position"], d["availability"]) for d in stu}))
print("student availability groups:",
      collections.Counter(d["availability"] for d in stu))
print("student (position,availability) groups:",
      len({(d["position"], d["availability"]) for d in stu}))
