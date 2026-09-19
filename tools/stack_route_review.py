"""Read-only routing telemetry report. It never changes policy or registry."""
from __future__ import annotations
import argparse, json, sys
from collections import defaultdict
from datetime import date
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.model_routing import load_json, validate_overlay, validate_policy, validate_registry

VOCABULARY = ("promote", "demote", "replace", "retire", "reprobe", "refresh-rates", "collect-more")
def main():
    p=argparse.ArgumentParser(); p.add_argument("--registry",required=True); p.add_argument("--overlay",required=True); p.add_argument("--policy",required=True); p.add_argument("--telemetry",required=True); args=p.parse_args()
    registry=validate_registry(load_json(args.registry)); overlay=validate_overlay(load_json(args.overlay)); validate_policy(load_json(args.policy))
    counts=defaultdict(int); flags=[]
    with open(args.telemetry) as stream:
        for line in stream:
            if line.strip():
                event=json.loads(line); counts[(event.get("task_class","unknown"),event.get("model","unknown"))]+=1
    today=date.today().isoformat()
    for model, entry in registry["models"].items():
        if entry["status"] in ("deprecated","retired"):
            flags.append({"model":model,"action":"replace" if entry["status"] == "deprecated" else "retire","reason":"registry lifecycle status"})
        if not overlay["models"].get(model,{}).get("available",False): flags.append({"model":model,"action":"reprobe","reason":"last probe unavailable"})
        checked=entry["rates"].get("checked")
        if not checked or checked > today: flags.append({"model":model,"action":"refresh-rates","reason":"missing or invalid rate date"})
    print(json.dumps({"schema_version":1,"dispatch_counts":[{"task_class":k[0],"model":k[1],"count":v} for k,v in sorted(counts.items())],"flags":flags,"vocabulary":list(VOCABULARY)}, indent=2))
if __name__ == "__main__": main()
