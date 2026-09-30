"""Closed, public-safe registry and route validation for remote model dispatch."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


class RoutingError(ValueError):
    pass


LANES = ("mechanically-proven", "scoped-behavior", "full-risk")
STATUSES = ("candidate", "pilot", "active", "deprecated", "retired")
CLIENTS = ("codex", "claude", "agy", "gemini", "local")
SAFE_CLASSIFICATIONS = ("public", "sanitized")


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", value):
        raise RoutingError("invalid identifier")


def _closed(value, required, optional=()):
    if not isinstance(value, dict) or set(value) - set(required) - set(optional) or set(required) - set(value):
        raise RoutingError("missing or unknown fields")


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise RoutingError("duplicate JSON key")
            result[key] = value
        return result
    try:
        return json.loads(Path(path).read_text(), object_pairs_hook=unique)
    except (OSError, json.JSONDecodeError) as error:
        raise RoutingError("cannot load JSON") from error


def validate_registry(registry):
    _closed(registry, ("schema_version", "models"))
    if registry["schema_version"] != 1 or not isinstance(registry["models"], dict):
        raise RoutingError("unsupported registry")
    for name, entry in registry["models"].items():
        _id(name)
        required = ("vendor", "family", "client", "vendor_model", "tier", "roles", "classes", "efforts", "rates", "context_window", "status", "lifecycle", "rationale", "decision_refs")
        _closed(entry, required, ("predecessor", "successor"))
        if entry["client"] not in CLIENTS or entry["status"] not in STATUSES or not isinstance(entry["context_window"], int) or entry["context_window"] < 1:
            raise RoutingError("invalid registry entry")
        if not all(isinstance(entry[key], str) and entry[key] for key in ("vendor", "family", "vendor_model", "tier", "rationale")):
            raise RoutingError("invalid registry text")
        if not all(isinstance(entry[key], list) and all(isinstance(v, str) and v for v in entry[key]) for key in ("roles", "classes", "efforts", "decision_refs")):
            raise RoutingError("invalid registry lists")
        if not isinstance(entry["rates"], dict) or not isinstance(entry["lifecycle"], dict):
            raise RoutingError("invalid registry metadata")
    return registry


def validate_overlay(overlay):
    _closed(overlay, ("schema_version", "models"))
    if overlay["schema_version"] != 1 or not isinstance(overlay["models"], dict):
        raise RoutingError("unsupported overlay")
    for model, observed in overlay["models"].items():
        _id(model); _closed(observed, ("available", "efforts", "service_tiers", "client_version", "probed_at", "isolation"), ("resolved_model",))
        if type(observed["available"]) is not bool or type(observed["isolation"]) is not bool or not all(isinstance(v, str) and v for v in observed["efforts"] + observed["service_tiers"]):
            raise RoutingError("invalid overlay capability")
        if "resolved_model" in observed and observed["resolved_model"] is not None and (not isinstance(observed["resolved_model"], str) or not observed["resolved_model"]):
            raise RoutingError("invalid resolved model identity")
    return overlay


def source_safe(contract, snapshot):
    """Reject remote egress unless both contract and immutable snapshot are safe."""
    source = contract.get("source", {})
    _closed(snapshot, ("digest", "classification", "tracked_only", "contains_ignored", "contains_untracked", "contains_secrets", "root"))
    if snapshot["classification"] not in SAFE_CLASSIFICATIONS or not snapshot["tracked_only"] or snapshot["contains_ignored"] or snapshot["contains_untracked"] or snapshot["contains_secrets"]:
        raise RoutingError("remote dispatch source snapshot is not safe")
    if snapshot["digest"] != source.get("snapshot_digest"):
        raise RoutingError("source snapshot digest mismatch")
    root = Path(snapshot["root"])
    if not root.is_absolute() or not root.is_dir() or (root / ".git").exists():
        raise RoutingError("source snapshot root is not an isolated directory")


def validate_policy(policy):
    _closed(policy, ("schema_version", "roles", "incumbent", "routes", "lane_ceilings"))
    if policy["schema_version"] != 2 or set(policy["roles"]) != {"hypervisor", "planner"}:
        raise RoutingError("unsupported routing policy")
    for value in policy["roles"].values(): _id(value)
    for field in ("incumbent",): validate_route(policy[field])
    if not isinstance(policy["routes"], dict) or not isinstance(policy["lane_ceilings"], dict):
        raise RoutingError("invalid policy maps")
    for task_class, lane in policy["lane_ceilings"].items():
        _id(task_class)
        if lane not in LANES: raise RoutingError("invalid lane ceiling")
    for task_class, candidate in policy["routes"].items():
        _id(task_class); _closed(candidate, ("route", "pilot_approved"))
        validate_route(candidate["route"])
        if type(candidate["pilot_approved"]) is not bool: raise RoutingError("invalid pilot admission")


def validate_route(route):
    _closed(route, ("model", "config", "effort", "service_tier"))
    for value in route.values(): _id(value)


def _lane_allowed(actual, ceiling):
    return LANES.index(actual) <= LANES.index(ceiling)


def _route_usable(model, observed):
    return (
        model is not None
        and observed is not None
        and model["status"] in ("pilot", "active")
        and observed["available"]
        and observed["isolation"]
        and (model["client"] != "claude" or observed.get("resolved_model") == model["vendor_model"])
    )


def resolve_v2(contract, registry, overlay, policy):
    validate_registry(registry); validate_overlay(overlay); validate_policy(policy)
    task_class, lane = contract.get("task_class"), contract.get("lane")
    _id(task_class)
    if lane not in LANES or task_class not in policy["lane_ceilings"] or not _lane_allowed(lane, policy["lane_ceilings"][task_class]):
        raise RoutingError("task exceeds lane ceiling")
    candidate = policy["routes"].get(task_class)
    route = candidate["route"] if candidate and candidate["pilot_approved"] else policy["incumbent"]
    model = registry["models"].get(route["model"]); observed = overlay["models"].get(route["model"])
    if not _route_usable(model, observed):
        if route == policy["incumbent"]: raise RoutingError("incumbent route unavailable or unsafe")
        route = policy["incumbent"]; model = registry["models"].get(route["model"]); observed = overlay["models"].get(route["model"])
        if not _route_usable(model, observed): raise RoutingError("incumbent route unavailable or unsafe")
    if route["effort"] not in observed["efforts"] or route["service_tier"] not in observed["service_tiers"]:
        raise RoutingError("route capability unavailable")
    return {**route, "schema_version": 2, "client": model["client"], "vendor_model": model["vendor_model"], "isolation_verified": True, "policy_basis": "pilot" if candidate and route == candidate["route"] else "incumbent"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
