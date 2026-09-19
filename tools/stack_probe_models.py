"""Produce a private, conservative capability overlay without sending model prompts."""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.model_routing import load_json, validate_registry

COMMANDS = {"codex": ["codex", "--version"], "claude": ["claude", "--version"], "agy": ["agy", "--version"], "gemini": ["gemini", "--version"]}
def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--registry", required=True); parser.add_argument("--output", required=True); args = parser.parse_args()
    registry = validate_registry(load_json(args.registry)); models = {}
    for key, entry in registry["models"].items():
        command = COMMANDS.get(entry["client"]); available = bool(command and shutil.which(command[0])); version = "unavailable"
        if available:
            result = subprocess.run(command, text=True, capture_output=True, timeout=10)
            available = result.returncode == 0; version = (result.stdout or result.stderr).strip()[:200]
        models[key] = {"available": available, "efforts": [], "service_tiers": [], "client_version": version, "probed_at": datetime.now(timezone.utc).isoformat(), "isolation": False}
    Path(args.output).write_text(json.dumps({"schema_version": 1, "models": models}, indent=2) + "\n")
if __name__ == "__main__": main()
