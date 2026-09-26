"""Dispatch a validated v2 route only after its remote-input snapshot passes fail-closed checks."""
from __future__ import annotations
import argparse, json, subprocess, sys, time
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.benchmark_workflow import validate_event
from tools.model_routing import RoutingError, load_json, source_safe

def argv_for(route, prompt):
    model, effort = route["vendor_model"], route["effort"]
    if route["client"] == "codex": return ["codex", "exec", "--json", "--sandbox", "read-only", "--model", model, "--config", "model_reasoning_effort=" + effort, prompt]
    if route["client"] == "claude": return ["claude", "-p", prompt, "--output-format", "json", "--model", model, "--effort", effort]
    if route["client"] == "agy": return ["agy", "--sandbox", "--mode", "plan", "--dangerously-skip-permissions", "--model", model, "--effort", effort, "--print=" + prompt]
    if route["client"] == "gemini": return ["gemini", "-p", prompt, "--model", model]
    raise RoutingError("unsupported dispatcher client")

def _usage(value):
    raw = value.get("usage", {}) if isinstance(value, dict) else {}
    return {"input_tokens": raw.get("input_tokens"), "cached_input_tokens": raw.get("cached_input_tokens"), "output_tokens": raw.get("output_tokens"), "reasoning_tokens": raw.get("reasoning_tokens"), "output_includes_reasoning": raw.get("output_includes_reasoning")}

def main():
    p = argparse.ArgumentParser(); p.add_argument("--contract", required=True); p.add_argument("--route", required=True); p.add_argument("--snapshot", required=True); p.add_argument("--event", required=True); p.add_argument("--execute", action="store_true"); args = p.parse_args()
    try:
        contract, route, snapshot = load_json(args.contract), load_json(args.route), load_json(args.snapshot)
        source_safe(contract, snapshot)
        required = ("schema_version", "client", "vendor_model", "model", "config", "effort", "service_tier")
        if route.get("schema_version") != 2 or route.get("isolation_verified") is not True or any(key not in route for key in required): raise RoutingError("invalid resolved v2 route")
        prompt = json.dumps({"contract": contract, "result": "Return only bounded final evidence; do not read files outside supplied snapshot."}, separators=(",", ":"))
        result, started = {"final": "dry run", "usage": {}}, time.monotonic()
        if args.execute:
            run = subprocess.run(argv_for(route, prompt), text=True, capture_output=True, timeout=300, cwd=snapshot["root"])
            if run.returncode: raise RoutingError("worker failed")
            try: result = json.loads(run.stdout)
            except json.JSONDecodeError: result = {"final": run.stdout, "usage": {}}
        event = {"schema_version":1,"event_type":"request_final","request_id":contract["parent_id"] + "-request","task_id":contract["parent_id"],"config":route["config"],"model":route["model"],"effort":route["effort"],"service_tier":route["service_tier"],"task_class":contract["task_class"],"source_digest":snapshot["digest"],"harness_digest":snapshot["digest"],"repetition":0,"parent_id":None,"child_ids":[],"complete":True,"task_final":True,"acceptance_digest":snapshot["digest"],"usage":_usage(result),"outcome":"unknown","latency_ms":round((time.monotonic()-started)*1000,3),"external_wait_ms":None}
        validate_event(event); Path(args.event).write_text(json.dumps(event, separators=(",", ":")) + "\n")
    except (RoutingError, KeyError, TypeError, ValueError) as error:
        print(json.dumps({"status":"unsupported","reason":str(error)})); return 2
    return 0
if __name__ == "__main__": sys.exit(main())
