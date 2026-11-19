"""Read-only, full-scope presentation of the development gate and its evidence.

Bounded observations remain separate from formal acceptance. This module never
loads arbitrary evidence contents or changes the state/gate/runner authority.
"""
from __future__ import annotations

import copy
import json
import re


def project_status(control, state, gate, groups, *, verify=True):
    package = control.root / "docs/product/04_全量功能清单.json"
    scenarios = control.root / "docs/product/09_验收场景.md"
    titles, definitions = {}, {}
    try:
        definitions = {row["id"]: row for row in json.loads(package.read_text())["capabilities"]}
        titles.update({key: value["title"] for key, value in definitions.items()})
    except (OSError, ValueError, KeyError, TypeError):
        pass  # The actual gate reports scope integrity failures independently.
    try:
        titles.update(dict(re.findall(r"^## (S\d{2})｜(.+)$", scenarios.read_text(), re.M)))
    except OSError:
        pass
    debt = {(row["id"], row.get("axis")): row["reasons"]
            for row in gate["engineering_debt"] + gate["human_debt"]}
    checked = {}

    def reference(value):
        value = copy.deepcopy(value)
        if not verify:
            value["reference_check"] = {"status": "pending", "errors": None}
            return value
        key = (str(value.get("path")), str(value.get("sha256")))
        if key not in checked:
            checked[key] = control._artifact_errors(value)
        value["reference_check"] = {"status": "unavailable_or_changed" if checked[key] else "matched",
                                    "errors": list(checked[key])}
        return value

    def bounded(value):
        value = reference(value)
        # A hash match says only that this referenced file still has these bytes.
        # It does not upgrade an observation to whole-scope acceptance.
        value["formal_acceptance"] = False
        digest = value.get("source", {}).get("code_digest")
        value["source_relation"] = ("unknown" if not verify else "current" if digest == gate["source"]["code_digest"]
                                    else "different" if digest else "not_recorded")
        return value

    rows = []
    for group, ids in groups:
        for item_id in ids:
            item = state.get(group, {}).get(item_id)
            present = item is not None
            item = item or {}
            axes = {}
            for axis in ("implementation", "engineering", "human"):
                value = item.get(axis, {})
                reasons = list(debt.get((item_id, axis), [])) if verify else ["fresh_full_gate_required"]
                if not present:
                    reasons.append("required item missing from state")
                # Gate normally supplies these reasons; retain fail-closed
                # behavior for a missing row or axis in a damaged state.
                if not value and not reasons:
                    reasons.append("axis missing from state")
                evidence = copy.deepcopy(value.get("evidence", []))
                for receipt in evidence:
                    receipt["validation_errors"] = control.evidence_errors(receipt, axis, gate["source"]) if verify else None
                    receipt["validation_status"] = "checked" if verify else "pending"
                axes[axis] = {"status": value.get("status", "missing"),
                              "gate_satisfied": (not reasons and not gate["scope_errors"]) if verify else None,
                              "gate_reasons": reasons,
                              "evidence": evidence,
                              "bounded_evidence": [bounded(r) for r in value.get("bounded_evidence", [])],
                              "evidence_scope": value.get("evidence_scope", "")}
            blockers = [{"id": key, **copy.deepcopy(state.get("blockers", {}).get(key, {}))}
                        for key in item.get("blockers", [])]
            related = [{key: copy.deepcopy(unit[key]) for key in
                        ("id", "status", "failure", "blockers", "covers", "resolution") if key in unit}
                       for unit in state.get("queue", []) if item_id in unit.get("covers", [])]
            actions = []
            if not present:
                actions.append({"origin": "gate", "action": "restore_required_item"})
            if gate["scope_errors"]:
                actions.append({"origin": "gate", "action": "repair_scope_integrity",
                                "reasons": gate["scope_errors"]})
            for axis, value in axes.items():
                if value["gate_reasons"]:
                    actions.append({"origin": "gate", "action": "supply_current_axis_evidence" if verify else "refresh_current_evidence_verification",
                                    "axis": axis, "reasons": value["gate_reasons"]})
            rows.append({"id": item_id, "group": group, "title": titles.get(item_id, item.get("title", item_id)),
                         "present": present, "stage": item.get("stage", definitions.get(item_id, {}).get("stage")),
                         "scenarios": item.get("scenarios", definitions.get(item_id, {}).get("scenarios", [])),
                         "axes": axes, "blockers": blockers,
                         "limitations": copy.deepcopy(item.get("limitations", [])),
                         "next_actions": actions, "related_units": related,
                         "observations": [bounded(r) for r in item.get("observations", [])],
                         "recorded_index": reference(item["current_evidence_index"])
                         if item.get("current_evidence_index") else None})
    return {"projection_schema": 1, "items": rows,
            "projection_scope": {"required_count": sum(len(ids) for _, ids in groups),
                                 "present_count": sum(row["present"] for row in rows),
                                 "scope_sha256": state.get("scope_sha256"),
                                 "state_updated_at": state.get("updated_at"),
                                 "gate_source_digest": gate["source"]["code_digest"],
                                 "scope_errors": gate["scope_errors"],
                                 "verification_status": "checked" if verify else "pending"},
            "current_checkpoint": copy.deepcopy(state.get("current_checkpoint"))}
