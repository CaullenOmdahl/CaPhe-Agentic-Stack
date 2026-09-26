import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT))
from tools.stack_dispatch import argv_for

class DispatchTests(unittest.TestCase):
    def test_claude_cli_route_passes_declared_effort(self):
        route={"client":"claude","vendor_model":"claude-opus-5-5","effort":"high"}
        args=argv_for(route,"prompt")
        self.assertEqual(args[args.index("--effort")+1],"high")

    def test_dry_run_emits_valid_event_without_contacting_client(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); digest="a"*64
            contract={"parent_id":"task-1","task_class":"mechanical","source":{"snapshot_digest":digest}}
            route={"schema_version":2,"client":"codex","vendor_model":"test","model":"test-model","config":"test","effort":"medium","service_tier":"standard","isolation_verified":True}
            snapshot={"digest":digest,"classification":"public","tracked_only":True,"contains_ignored":False,"contains_untracked":False,"contains_secrets":False,"root":str(root)}
            for name,value in (("contract.json",contract),("route.json",route),("snapshot.json",snapshot)): (root/name).write_text(json.dumps(value))
            event=root/"event.json"
            result=subprocess.run([sys.executable,str(ROOT/"tools/stack_dispatch.py"),"--contract",str(root/"contract.json"),"--route",str(root/"route.json"),"--snapshot",str(root/"snapshot.json"),"--event",str(event)],text=True,capture_output=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr); self.assertEqual(json.loads(event.read_text())["model"],"test-model")
