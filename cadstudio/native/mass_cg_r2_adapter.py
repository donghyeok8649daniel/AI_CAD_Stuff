"""Exact schema2 provenance adapter. No geometry execution or transform calls.

Purchased IDs are determined by the bound SOURCE AUDIT, never by a nullable
point or global frame. Legacy archive is not a source of active coordinates.
"""
from copy import deepcopy
from .mass_cg_review import fingerprint, vector, model_fingerprint

R2_SHA = "669efab05bdad7e4c4ff8569838676dd4f68a6ee49dca785181778b6f2fe60db"
AUDIT_SHA = "5670fb44c7c63aaa03ff876f648f46256ddd0d7f44f649e06fcc8f6acff5c271"
FRAME = "D2_MODEL_WORLD_MM"


class AdapterProblem(ValueError):
    pass


def require(condition, code, pid=None):
    if not condition:
        raise AdapterProblem(code + (":" + pid if pid else ""))


def unique_rows(rows, key):
    require(isinstance(rows, list), "invalid_row_list")
    result = {}
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get(key), str) and row[key], "missing_row_id")
        require(row[key] not in result, "duplicate_row_id", row[key])
        result[row[key]] = row
    return result


def adapt_schema2(contract, audit, prior_packet, report, contract_sha256, active_design):
    require(contract_sha256 == R2_SHA, "unknown_contract_hash")
    require(contract.get("schema_version") == 2 and not isinstance(contract.get("schema_version"), bool), "unsupported_schema")
    require(contract.get("format") == "urc2027.mass-centroid-input-contract", "wrong_format")
    require(model_fingerprint(active_design) == prior_packet["model_fingerprint"], "active_model_stale")
    active_parts = unique_rows(active_design.get("parts"), "id")
    require(contract.get("units") == {"mass": "g", "length": "mm", "density": "kg/m3", "rotation": "degrees"}, "wrong_units")
    require(contract.get("coordinate_frame", {}).get("id") == FRAME, "placement_frame_mismatch")
    require(contract.get("input_baselines", {}).get("pcad", {}).get("sha256") ==
            audit["bindings"]["current_original"]["sha256"], "source_model_sha_mismatch")
    require(contract.get("input_baselines", {}).get("report", {}).get("sha256") ==
            audit["bindings"]["build3_report"]["sha256"], "source_report_sha_mismatch")
    require(contract["coordinate_frame"].get("actual_operating_dummy_x_mm") is None, "actual_dummy_invented")
    require(contract["coordinate_frame"].get("cached_reference_dummy_x_mm") == prior_packet["cached_reference_dummy_x_mm"], "cached_pose_changed")
    rows = unique_rows(contract.get("part_inputs"), "part_id")
    audited = unique_rows(audit.get("part_results"), "part_id")
    reports = unique_rows(report.get("physical_inventory"), "id")
    expected = set(prior_packet["part_ids"])
    require(set(rows) == set(audited) == set(reports) == expected and len(expected) == 250, "source_part_set_mismatch")
    purchased = {pid for pid, a in audited.items() if a["producer_status"] == "inherited_nominal_proxy_frame_unproven"}
    geometry = {pid for pid, a in audited.items() if a["producer_status"] == "proven_world_geometry"}
    require(len(purchased) == 20 and len(geometry) == 230 and purchased | geometry == expected, "source_classification_unknown")
    audit_indexes = {r["part_id"]: i for i, r in enumerate(audit["part_results"])}
    owners = {o["owner_part_id"]: o for o in prior_packet["owners"]}
    children = {c["part_id"]: c for c in prior_packet["covered_rows"]}
    normalized = deepcopy(prior_packet)
    new_owners = {o["owner_part_id"]: o for o in normalized["owners"]}
    for pid, row in rows.items():
        cg = row.get("cg", {})
        a, original = audited[pid], reports[pid]
        cp = cg.get("coordinate_provenance", {})
        require(cp.get("source_audit_sha256") == AUDIT_SHA, "source_audit_sha_mismatch", pid)
        require(cp.get("source_audit_pointer") == "/part_results/" + str(audit_indexes[pid]), "source_audit_pointer_mismatch", pid)
        require(cp.get("producer_status") == a["producer_status"] and cp.get("producer_chain") == a["producer_chain"], "producer_chain_mismatch", pid)
        require(cp.get("report_pointer") == a["report_pointer"] == row.get("source", {}).get("json_pointer"), "source_report_pointer_mismatch", pid)
        require(row.get("source", {}).get("current_part_id") == pid, "source_part_id_mismatch", pid)
        # Hash the bound SOURCE representation (typed saved transform), and
        # separately compare numeric values. JS JSON17 and Python17.0 encode
        # differently; their identical coordinate must not change source SHA.
        active_pose = active_parts[pid]["transform"]
        require(cp.get("source_pose_sha256") == a["pose_sha256"] == fingerprint(active_pose)
                and row["placement"]["transform"] == active_pose, "source_pose_mismatch", pid)
        require(row["placement"].get("coordinate_frame") == FRAME, "placement_frame_mismatch", pid)
        require(cp.get("qualified_as_physical_mass_CG") is False and cg.get("allowed_for_physical_CG") is False, "physical_qualification_invented", pid)
        require(cg.get("apply_part_transform_again") is False, "additional_transform_forbidden", pid)
        require(cg.get("actual_mass_entity_world_mm") is None and cg.get("actual_part_local_mm") is None
                and cg.get("purchased_mass_entity_cg_world_mm") is None, "actual_CG_invented", pid)
        require(row.get("native_unit_quantity") == 1 and not isinstance(row["native_unit_quantity"], bool), "quantity_multiplication", pid)
        require(row.get("geometry_solid_members") == original["physical_geometry_solid_members_count"]
                and row.get("physical_piece_quantity_from_cached_ledger") == original["physical_quantity_ea"], "source_quantity_changed", pid)
        require(row.get("mass", {}).get("actual_installed_g") is None, "actual_mass_invented", pid)
        if pid in purchased:
            require(cp.get("kind") == "inherited_nominal_reference_frame_unproven", "purchased_provenance_kind", pid)
            require(cp.get("coordinate_frame_id") is None and cp.get("frame_qualified") is False
                    and cg.get("inherited_nominal_reference_frame") is None, "purchased_frame_fallback_forbidden", pid)
            require(cg.get("cached_geometry_centroid_world_mm") is None and cg.get("cached_centroid_is_already_world") is None
                    and cg.get("conditional_uniform_density_cg_world_mm") is None, "purchased_geometry_fallback_forbidden", pid)
            point = cg.get("inherited_nominal_reference_point_mm")
            require(vector(point) and point == original["centroid_mm"] == owners[pid]["geometry_centroid"]["world_mm"], "purchased_point_source_mismatch", pid)
            reference = {"point_mm": deepcopy(point), "frame_id": None, "frame_qualified": False,
                         "kind": "inherited_nominal_reference", "for_display_and_source_diff_only": True}
            world = {"world_mm": None, "frame_id": None, "model_fingerprint": prior_packet["model_fingerprint"],
                     "producer_status": "inherited_nominal_proxy_frame_unproven",
                     "evidence": {"source_audit_sha256": AUDIT_SHA, "source_audit_pointer": cp["source_audit_pointer"]}}
        else:
            require(cp.get("kind") == "cached_world_geometry" and cp.get("frame_qualified") is True
                    and cp.get("coordinate_frame_id") == FRAME and cg.get("cached_centroid_is_already_world") is True, "geometry_provenance_unqualified", pid)
            point = cg.get("cached_geometry_centroid_world_mm")
            require(vector(point) and point == original["centroid_mm"], "geometry_point_source_mismatch", pid)
            require(cg.get("inherited_nominal_reference_point_mm") is None, "geometry_inherited_fallback_forbidden", pid)
            require(cg.get("conditional_uniform_density_cg_world_mm") in (None, point), "conditional_point_source_mismatch", pid)
            reference = None
            world = {"world_mm": deepcopy(point), "frame_id": cp["coordinate_frame_id"],
                     "model_fingerprint": prior_packet["model_fingerprint"], "producer_status": "proven_world_geometry",
                     "evidence": {"source_audit_sha256": AUDIT_SHA, "source_audit_pointer": cp["source_audit_pointer"]}}
        ownership, mass = row["mass_ownership"], row["mass"]
        if pid in children:
            require(ownership.get("policy") == "covered_by_parent_not_additive"
                    and ownership.get("covered_by_part_id") == children[pid]["owner_part_id"]
                    and ownership.get("mass_entity_id") == "M_" + children[pid]["owner_part_id"]
                    and ownership.get("included_part_ids") == [] and mass.get("accounted_nominal_g") is None
                    and mass.get("count_in_nominal_total") is False and mass.get("declared_reference_g") is None
                    and mass.get("design_target_g") is None and mass.get("geometry_density_estimate_g") is None,
                    "covered_child_ownership_changed", pid)
        else:
            o = owners[pid]
            require(ownership.get("policy") == "count_once_for_covered_set" and ownership.get("mass_entity_id") == o["entity_id"]
                    and ownership.get("included_part_ids") == o["part_ids"] and ownership.get("covered_by_part_id") is None
                    and mass.get("count_in_nominal_total") is True, "mass_ownership_changed", pid)
            declared = mass.get("design_target_g") if mass.get("design_target_g") is not None else mass.get("declared_reference_g")
            require(mass.get("accounted_nominal_g") == o["nominal_g"] and declared == o["declared_g"]
                    and mass.get("geometry_density_estimate_g") == o["estimate_g"]
                    and mass.get("cached_volume_mm3") == o["volume_mm3"] and mass.get("density_kg_m3") == o["density_kg_m3"], "mass_basis_changed", pid)
            new_owners[pid]["geometry_centroid"] = world
            new_owners[pid]["inherited_reference"] = reference
    extras = [{"id": i["id"], "state": "unknown", "mass_g": i["mass_g"], "point_mm": i["cg_world_mm"],
               "item_ids": i["installed_part_ids"]} for i in contract["unmodeled_incremental_inputs"]]
    require(extras == prior_packet["additions"], "unknown_addition_scope_changed")
    summary = contract.get("summary", {})
    require(summary.get("actual_complete_mass_g") is None and summary.get("actual_complete_CG_world_mm") is None
            and summary.get("physical_CG_ready") is False, "actual_output_invented")
    normalized["source_schema"] = 2
    normalized["source_contract_sha256"] = R2_SHA
    normalized["provenance_summary"] = {"purchased_inherited_reference_unproven": 20, "geometry_centroid_parts": 230,
                                        "geometry_estimate_owners": 226, "covered_rotors": 4,
                                        "prior_label_finding": "resolved_by_schema2_label_change",
                                        "physical_frame_CG_still_unresolved": True, "additional_transforms": 0}
    return normalized
