"""Readonly mass/CG review prototype. Standard library; never builds a shape.

Evidence/qualification are supplied declarations, not a substitute for metrology.
This evaluator does not authorize manufacture, flight or equipment operation.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import math


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def model_fingerprint(design):
    # Deliberately conservative: ALL non-electrical data, including assets/mates
    # and saved placement. A rename may invalidate this prototype unnecessarily;
    # geometry/pose changes must never accidentally retain qualification.
    return fingerprint({k: v for k, v in design.items() if k != "electrical"})


def number(value, positive=False):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and (value > 0 if positive else value >= 0))


def vector(value):
    return (isinstance(value, (list, tuple)) and len(value) == 3
            and all(isinstance(v, (int, float)) and not isinstance(v, bool)
                    and math.isfinite(v) for v in value))


def world_point(point, transform):
    """Proven LOCAL input only. Extrinsic XYZ, column vectors Rz Ry Rx + t."""
    if not vector(point) or set(transform) != {"x", "y", "z", "rx", "ry", "rz"}:
        raise ValueError("Invalid local point/rigid transform")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool)
               and math.isfinite(v) for v in transform.values()):
        raise ValueError("Invalid transform values")
    x, y, z = point
    rx, ry, rz = [math.radians(transform[k]) for k in ("rx", "ry", "rz")]
    y, z = y * math.cos(rx) - z * math.sin(rx), y * math.sin(rx) + z * math.cos(rx)
    x, z = x * math.cos(ry) + z * math.sin(ry), -x * math.sin(ry) + z * math.cos(ry)
    x, y = x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz)
    result = [x + transform["x"], y + transform["y"], z + transform["z"]]
    if not vector(result):
        raise ValueError("Transform overflow")
    return result


def evaluate(spec, current_model_fingerprint):
    """Review normalized immutable inputs; return complete quantities or null.

    Numerical subtotals are explicitly marked subsets. Unknown owners/additions
    are never silently omitted from a COMPLETE mass/CG result.
    """
    result = {"schema": "cadstudio.mass-cg-review-1", "status": "data_insufficient",
              "valid_input_structure": True, "physical_ready": False,
              "actual_complete_mass_g": None, "actual_complete_CG_world_mm": None,
              "complete_conditional_CG_world_mm": None,
              "manufacturing_release": False, "flight_release": False,
              "issues": [], "rows": [], "coverage": {},
              "declared_nominal_subtotal_g": None,
              "geometry_density_estimate_subtotal_g": None,
              "conditional_nominal_total_g": None,
              "geometry_subset_CG_world_mm": None,
              "coordinate_frame_id": spec.get("frame_id"),
              "actual_operating_dummy_x_mm": spec.get("operating_configuration", {}).get("dummy_x_mm"),
              "cached_reference_dummy_x_mm": spec.get("cached_reference_dummy_x_mm"),
              "limitations": ["Qualification is an input declaration; no metrology/hardware verification is performed.",
                             "Geometric centroids and declared product masses are not actual assembly mass centroids.",
                             "No FRD conversion, kernel, mesh, history replay or model write is performed."]}

    def issue(code, entity=None, invalid=False, detail=None):
        result["issues"].append({"code": code, "entity": entity, "invalid": invalid, "detail": detail})
        if invalid:
            result["valid_input_structure"] = False

    if spec.get("units") != {"mass": "g", "length": "mm"}:
        issue("wrong_units", invalid=True)
    if not spec.get("frame_id"):
        issue("missing_frame", invalid=True)
    if not current_model_fingerprint or spec.get("model_fingerprint") != current_model_fingerprint:
        issue("stale_model_or_pose", invalid=True)
    ids = spec.get("part_ids", [])
    if not ids or any(not isinstance(p, str) or not p for p in ids) or len(set(ids)) != len(ids):
        issue("duplicate_or_missing_part_ids", invalid=True)
    expected = set(ids)
    owners = spec.get("owners", [])
    covered = spec.get("covered_rows", [])
    claims = Counter()
    entity_ids, owner_ids, covered_map = set(), set(), {}
    declared, estimated, nominal, geometric_points, actual_points = [], [], [], [], []
    measured_count = centroid_count = geometry_count = 0
    for child in covered:
        pid = child.get("part_id")
        if not pid or pid in covered_map or pid not in expected:
            issue("duplicate_or_unknown_covered_child", pid, True)
        covered_map[pid] = child.get("owner_part_id")
        if child.get("mass_g") is not None or child.get("count_additive") is not False:
            issue("covered_child_additive_mass", pid, True)
    for owner in owners:
        eid, pid = owner.get("entity_id"), owner.get("owner_part_id")
        row = {"entity_id": eid, "part_id": pid, "label": owner.get("label", pid),
               "covers": deepcopy(owner.get("part_ids", [])),
               "nominal_kind": owner.get("nominal_kind"),
               "nominal_g": owner.get("nominal_g"), "declared_g": owner.get("declared_g"),
               "estimate_g": owner.get("estimate_g"), "actual_g": None,
               "actual_CG_world_mm": None, "geometry_world_mm": None,
               "geometry_frame_status": "unknown", "actual_status": "unknown"}
        row["inherited_reference"] = deepcopy(owner.get("inherited_reference"))
        result["rows"].append(row)
        if not isinstance(eid, str) or not eid or eid in entity_ids:
            issue("duplicate_or_missing_owner", eid, True)
        entity_ids.add(eid)
        if pid in owner_ids or pid not in expected:
            issue("duplicate_or_unknown_owner_part", pid, True)
        owner_ids.add(pid)
        members = owner.get("part_ids", [])
        if (not members or pid not in members or len(set(members)) != len(members)
                or any(p not in expected for p in members)):
            issue("invalid_owner_coverage", eid, True)
        claims.update(members)
        if owner.get("quantity") != 1 or isinstance(owner.get("quantity"), bool):
            issue("quantity_multiplication_forbidden", eid, True)
        for key, destination in (("nominal_g", nominal), ("declared_g", declared), ("estimate_g", estimated)):
            v = owner.get(key)
            if v is not None:
                if not number(v, positive=True):
                    issue("invalid_" + key, eid, True)
                else:
                    destination.append(v)
        if owner.get("declared_g") is not None and owner.get("estimate_g") is not None:
            issue("mixed_declared_and_estimate_basis", eid, True)
        basis_value = owner.get("declared_g") if owner.get("declared_g") is not None else owner.get("estimate_g")
        if owner.get("nominal_g") != basis_value:
            issue("nominal_basis_mismatch", eid, True)
        if owner.get("estimate_g") is not None:
            volume, density = owner.get("volume_mm3"), owner.get("density_kg_m3")
            if not number(volume, positive=True) or not number(density, positive=True):
                issue("geometry_mass_missing_volume_or_density", eid, True)
            elif not math.isclose(volume * density * 1e-6, owner["estimate_g"], rel_tol=1e-10, abs_tol=1e-9):
                issue("geometry_density_mass_formula_mismatch", eid, True)
        g = owner.get("geometry_centroid", {})
        if row["inherited_reference"] is not None:
            ref = row["inherited_reference"]
            if (ref.get("frame_id") is not None or ref.get("frame_qualified") is not False
                    or ref.get("for_display_and_source_diff_only") is not True or not vector(ref.get("point_mm"))
                    or g.get("world_mm") is not None or g.get("frame_id") is not None):
                issue("inherited_reference_arithmetic_reuse_forbidden", eid, True)
            row["geometry_frame_status"] = "inherited_nominal_proxy_frame_unproven"
        if g.get("world_mm") is not None:
            if not vector(g["world_mm"]):
                issue("nonfinite_geometry_centroid", eid, True)
            elif (g.get("frame_id") != spec.get("frame_id")
                  or g.get("model_fingerprint") != current_model_fingerprint):
                issue("stale_geometry_frame_or_pose", eid, True)
            elif g.get("producer_status") == "proven_world_geometry" and g.get("evidence"):
                row["geometry_world_mm"] = list(g["world_mm"])
                row["geometry_frame_status"] = "proven_world_geometry"
                geometry_count += 1
                if number(owner.get("estimate_g"), positive=True):
                    geometric_points.append((owner["estimate_g"], g["world_mm"]))
            else:
                row["geometry_frame_status"] = g.get("producer_status", "unknown")
        actual = owner.get("actual", {})
        m = actual.get("mass_g")
        if m is None:
            issue("actual_mass_unknown", eid)
        elif not number(m, positive=True):
            issue("actual_mass_nonpositive_or_nonfinite", eid, True)
        elif (actual.get("mass_basis") not in ("measured", "qualified_product_mass")
              or not actual.get("mass_evidence")):
            issue("actual_mass_unqualified", eid)
        else:
            measured_count += 1
            row["actual_g"] = m
        point = actual.get("point_mm")
        if point is None:
            issue("actual_CG_unknown", eid)
        elif not vector(point):
            issue("actual_CG_nonfinite", eid, True)
        elif (actual.get("model_fingerprint") != current_model_fingerprint
              or actual.get("target_frame_id") != spec.get("frame_id")):
            issue("actual_CG_stale_model_or_frame", eid, True)
        elif (actual.get("centroid_basis") != "qualified_mass_centroid"
              or not actual.get("centroid_evidence")):
            issue("actual_CG_unqualified", eid)
        elif actual.get("space") == "WORLD":
            row["actual_CG_world_mm"] = list(point)
            centroid_count += 1
        elif (actual.get("space") == "LOCAL" and actual.get("local_frame_verified") is True
              and actual.get("transform_evidence")):
            try:
                row["actual_CG_world_mm"] = world_point(point, actual.get("transform", {}))
                centroid_count += 1
            except ValueError as exc:
                issue("invalid_local_CG_transform", eid, True, str(exc))
        else:
            issue("actual_CG_space_unverified", eid)
        if row["actual_g"] is not None and row["actual_CG_world_mm"] is not None:
            actual_points.append((row["actual_g"], row["actual_CG_world_mm"]))
            row["actual_status"] = "qualified_input"
    for child, parent in covered_map.items():
        matching = [o for o in owners if o.get("owner_part_id") == parent]
        if child in owner_ids or len(matching) != 1 or child not in matching[0].get("part_ids", []):
            issue("covered_child_owner_mismatch", child, True)
    for owner in owners:
        for child in owner.get("part_ids", []):
            if child != owner.get("owner_part_id") and covered_map.get(child) != owner.get("owner_part_id"):
                issue("undeclared_covered_child", child, True)
    missing = sorted(expected - set(claims))
    duplicates = sorted(p for p, count in claims.items() if count != 1)
    if missing:
        issue("missing_part_coverage", invalid=True, detail=missing)
    if duplicates:
        issue("duplicate_part_coverage", invalid=True, detail=duplicates)
    addition_ids, addition_members = set(), set()
    resolved_additions = 0
    for extra in spec.get("additions", []):
        eid, state = extra.get("id"), extra.get("state")
        if not eid or eid in addition_ids or eid in entity_ids:
            issue("duplicate_addition_id", eid, True)
        addition_ids.add(eid)
        if state == "unknown":
            issue("addition_scope_unknown", eid)
            if extra.get("mass_g") is not None or extra.get("point_mm") is not None:
                issue("unknown_addition_has_values", eid, True)
        elif state == "absent":
            if not extra.get("scope_evidence") or extra.get("item_ids") != []:
                issue("absence_scope_undocumented", eid)
            elif extra.get("mass_g") is not None or extra.get("point_mm") is not None:
                issue("absence_is_not_zero_mass_item", eid, True)
            else:
                resolved_additions += 1
        elif state == "present":
            members = extra.get("item_ids", [])
            if (not members or len(set(members)) != len(members) or set(members) & (expected | addition_members)):
                issue("addition_duplicate_or_ambiguous_scope", eid, True)
            addition_members.update(members)
            if extra.get("mass_g") is not None and not number(extra["mass_g"], positive=True):
                issue("addition_mass_nonpositive_or_nonfinite", eid, True)
            if extra.get("point_mm") is not None and not vector(extra["point_mm"]):
                issue("addition_CG_nonfinite", eid, True)
            if not number(extra.get("mass_g"), positive=True) or not vector(extra.get("point_mm")):
                issue("addition_missing_positive_mass_or_CG", eid)
            elif (extra.get("frame_id") != spec.get("frame_id")
                  or extra.get("model_fingerprint") != current_model_fingerprint):
                issue("addition_stale_model_or_frame", eid, True)
            elif (extra.get("mass_basis") not in ("measured", "qualified_product_mass")
                  or extra.get("centroid_basis") != "qualified_mass_centroid"
                  or not extra.get("mass_evidence") or not extra.get("centroid_evidence")
                  or not extra.get("scope_evidence")):
                issue("addition_measurement_or_scope_unqualified", eid)
            else:
                resolved_additions += 1
                actual_points.append((extra["mass_g"], extra["point_mm"]))
        else:
            issue("unknown_addition_state", eid, True)
    required_additions = spec.get("required_addition_ids", [])
    if len(set(required_additions)) != len(required_additions) or addition_ids != set(required_additions):
        issue("required_additions_missing_or_extra", invalid=True)
    config = spec.get("operating_configuration", {})
    if (config.get("qualified") is not True or not config.get("evidence")
            or config.get("model_fingerprint") != current_model_fingerprint):
        issue("actual_operating_configuration_unknown")
    if config.get("requires_dummy_position") is True and not isinstance(config.get("dummy_x_mm"), (int, float)):
        issue("actual_dummy_position_unknown")
    elif config.get("dummy_x_mm") is not None and (not isinstance(config["dummy_x_mm"], (int, float))
         or isinstance(config["dummy_x_mm"], bool) or not math.isfinite(config["dummy_x_mm"])):
        issue("actual_dummy_position_nonfinite", invalid=True)
    result["coverage"] = {"parts": len(ids), "owners": len(owners), "covered_children": len(covered),
                          "part_claims_once": sum(claims[p] == 1 for p in expected),
                          "qualified_mass_owners": measured_count, "qualified_CG_owners": centroid_count,
                          "proven_geometry_centroid_owners": geometry_count,
                          "geometry_estimate_subset_owners": len(geometric_points),
                          "resolved_additions": resolved_additions, "required_additions": len(required_additions)}
    result["covered_rows"] = deepcopy(covered)
    if result["valid_input_structure"]:
        try:
            result["declared_nominal_subtotal_g"] = math.fsum(declared) if declared else None
            result["geometry_density_estimate_subtotal_g"] = math.fsum(estimated) if estimated else None
            result["conditional_nominal_total_g"] = math.fsum(nominal) if len(nominal) == len(owners) else None
            if geometric_points:
                result["geometry_subset_CG_world_mm"] = weighted_point(geometric_points)
        except (ValueError, OverflowError):
            result["declared_nominal_subtotal_g"] = None
            result["geometry_density_estimate_subtotal_g"] = None
            result["conditional_nominal_total_g"] = None
            result["geometry_subset_CG_world_mm"] = None
            issue("nominal_or_subset_sum_nonfinite", invalid=True)
        if not result["issues"]:
            try:
                result["actual_complete_mass_g"] = math.fsum(m for m, p in actual_points)
                result["actual_complete_CG_world_mm"] = weighted_point(actual_points)
                result["physical_ready"] = True
                result["status"] = "qualified_input_complete_not_hardware_release"
            except (ValueError, OverflowError):
                result["actual_complete_mass_g"] = None
                result["actual_complete_CG_world_mm"] = None
                issue("weighted_sum_nonfinite", invalid=True)
    if not result["valid_input_structure"]:
        result["status"] = "invalid_input"
    return result


def weighted_point(pairs):
    total = math.fsum(m for m, p in pairs)
    if not number(total, positive=True):
        raise ValueError("Nonpositive/nonfinite total")
    # Normalized weights reduce intermediate overflow for large masses.
    point = [math.fsum((m / total) * p[k] for m, p in pairs) for k in range(3)]
    if not vector(point):
        raise ValueError("Nonfinite weighted centroid")
    return point
