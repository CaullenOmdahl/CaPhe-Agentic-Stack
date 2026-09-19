import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

ROOT=Path(__file__).parents[1]
class DispatchTests(unittest.TestCase):
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
