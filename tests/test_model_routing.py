import copy
import json
import tempfile
from pathlib import Path
import unittest

from tools.model_routing import RoutingError, resolve_v2, source_safe, validate_registry

ROOT = Path(__file__).parents[1]
REGISTRY = json.loads((ROOT / "registry/models.json").read_text())

def overlay():
    return {"schema_version": 1, "models": {key: {"available": True, "efforts": value["efforts"], "service_tiers": ["standard"], "client_version": "test", "probed_at": "2026-09-19T00:00:00Z", "isolation": True, **({"resolved_model": value["vendor_model"]} if value["client"] == "claude" else {})} for key, value in REGISTRY["models"].items()}}
def contract(task_class="mechanical", lane="mechanically-proven"):
    return {"task_class": task_class, "lane": lane, "source": {"snapshot_digest": "a" * 64}}
def policy():
    return {"schema_version":2,"roles":{"hypervisor":"codex-terra","planner":"codex-astra"},"incumbent":{"model":"codex-terra","config":"incumbent","effort":"medium","service_tier":"standard"},"routes":{"mechanical":{"route":{"model":"gemini-flash","config":"pilot","effort":"high","service_tier":"standard"},"pilot_approved":True}},"lane_ceilings":{"mechanical":"mechanically-proven"}}

class ModelRoutingTests(unittest.TestCase):
    def test_registry_is_closed_and_candidate_is_not_routable(self):
        registry = copy.deepcopy(REGISTRY); validate_registry(registry)
        with self.assertRaises(RoutingError): resolve_v2(contract(), registry, overlay(), policy())
        registry["models"]["codex-terra"]["status"] = "pilot"; registry["models"]["gemini-flash"]["status"] = "pilot"
        self.assertEqual(resolve_v2(contract(), registry, overlay(), policy())["model"], "gemini-flash")

    def test_unsafe_remote_source_never_reaches_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            safe = {"digest":"a"*64,"classification":"sanitized","tracked_only":True,"contains_ignored":False,"contains_untracked":False,"contains_secrets":False,"root":directory}
            source_safe(contract(), safe)
            for key in ("contains_ignored", "contains_untracked", "contains_secrets"):
                unsafe=copy.deepcopy(safe); unsafe[key]=True
                with self.subTest(key=key), self.assertRaises(RoutingError): source_safe(contract(), unsafe)
            unsafe=copy.deepcopy(safe); unsafe["classification"]="unknown"
            with self.assertRaises(RoutingError): source_safe(contract(), unsafe)

    def test_lane_ceiling_rejects_misclassification(self):
        registry=copy.deepcopy(REGISTRY); registry["models"]["codex-terra"]["status"]="pilot"
        with self.assertRaises(RoutingError): resolve_v2(contract("mechanical", "scoped-behavior"), registry, overlay(), policy())

    def test_claude_alias_requires_matching_observed_model_identity(self):
        registry=copy.deepcopy(REGISTRY)
        for key in ("claude-opus", "codex-terra"):
            registry["models"][key]["status"]="pilot"
        route={"model":"claude-opus","config":"claude","effort":"high","service_tier":"standard"}
        routing_policy=policy(); routing_policy["incumbent"]=route
        observed=overlay(); observed["models"]["claude-opus"].pop("resolved_model")
        with self.assertRaisesRegex(RoutingError, "alias resolution"):
            resolve_v2(contract(), registry, observed, routing_policy)
        observed["models"]["claude-opus"]["resolved_model"]="different-model"
        with self.assertRaisesRegex(RoutingError, "alias resolution"):
            resolve_v2(contract(), registry, observed, routing_policy)
        observed["models"]["claude-opus"]["resolved_model"]=registry["models"]["claude-opus"]["vendor_model"]
        self.assertEqual(resolve_v2(contract(), registry, observed, routing_policy)["vendor_model"], "claude-opus-5-5")
