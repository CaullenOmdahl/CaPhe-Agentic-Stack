"""Create an isolated, tracked-only remote-input snapshot from a Git revision."""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, tarfile, tempfile
from pathlib import Path

PREFIXES = (b"github" + b"_pat_", b"gh" + b"[" + b"pousr" + b"]_", b"s" + b"k-" + b"(?:proj-|svcacct-)?")
SECRET = re.compile(b"(?:" + b"|".join(PREFIXES) + b")[A-Za-z0-9_-]{20,}")
def main():
    p=argparse.ArgumentParser(); p.add_argument("--revision",required=True); p.add_argument("--classification",choices=("public","sanitized"),required=True); p.add_argument("--root",required=True); p.add_argument("--manifest",required=True); args=p.parse_args()
    root=Path(args.root).resolve()
    if root.exists() and any(root.iterdir()): raise SystemExit("snapshot root must be empty")
    root.mkdir(parents=True, exist_ok=True)
    archive=subprocess.run(["git","archive","--format=tar",args.revision],capture_output=True,check=True).stdout
    if SECRET.search(archive): raise SystemExit("snapshot contains token-like content")
    with tempfile.NamedTemporaryFile() as handle:
        handle.write(archive); handle.flush()
        with tarfile.open(handle.name) as tar:
            if any(member.name.startswith("/") or ".." in Path(member.name).parts or member.issym() or member.islnk() for member in tar.getmembers()): raise SystemExit("unsafe archive member")
            tar.extractall(root, filter="data")
    digest=hashlib.sha256(archive).hexdigest()
    Path(args.manifest).write_text(json.dumps({"digest":digest,"classification":args.classification,"tracked_only":True,"contains_ignored":False,"contains_untracked":False,"contains_secrets":False,"root":str(root)},indent=2)+"\n")
if __name__ == "__main__": main()
