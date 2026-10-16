"""Pure Python rigid pin alignment. Preview data only; no CAD/Qt dependency."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, is_dataclass
import math
from typing import Mapping, Sequence

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class Pin:
    xyz: Vec3
    net: str | None = None
    voltage_role: str | None = None
    voltage_range_v: tuple[float, float] | None = None


@dataclass(frozen=True)
class Board:
    pins: Mapping[str, Pin]
    footprint_verified: bool = False
    pin_map_verified: bool = False


@dataclass(frozen=True)
class PinPair:
    source_pin: str
    target_pin: str
    net_compatibility: str | None = None


@dataclass(frozen=True)
class Mating:
    source_normal: Vec3 | None = None
    target_normal: Vec3 | None = None
    source_side: str | None = None
    target_side: str | None = None
    allowed_side_pairs: Sequence[tuple[str, str]] = ()
    stand_off_height_mm: float | None = None
    insertion_depth_mm: float | None = None
    keying_verified: bool = False
    source_key_axis: Vec3 | None = None
    target_key_axis: Vec3 | None = None


@dataclass(frozen=True)
class Constraints:
    max_pin_error_mm: float = 0.05
    pitch_tolerance_mm: float = 0.05
    normal_tolerance_deg: float = 1.0
    tolerances_verified: bool = False
    fixed_mounts: Sequence[Mapping] = ()
    locked_source_pose: Mapping | None = None


@dataclass(frozen=True)
class AlignmentRequest:
    source: Board
    target: Board
    mapping: Sequence[PinPair]
    units: str = "mm"
    mating: Mating = field(default_factory=Mating)
    constraints: Constraints = field(default_factory=Constraints)
    net_equivalences: Sequence[tuple[str, str]] = ()


def _add(a, b):
    return [x + y for x, y in zip(a, b)]


def _sub(a, b):
    return [x - y for x, y in zip(a, b)]


def _mul(a, n):
    return [x * n for x in a]


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def _norm(a):
    return math.sqrt(_dot(a, a))


def _cross(a, b):
    return [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]


def _unit(a):
    n = _norm(a)
    if n < 1e-12:
        raise ValueError("Zero or degenerate direction")
    return _mul(a, 1 / n)


def _mv(r, p):
    return [_dot(row, p) for row in r]


def _transpose(r):
    return [list(row) for row in zip(*r)]


def _mm(a, b):
    bt = _transpose(b)
    return [[_dot(row, col) for col in bt] for row in a]


def _det(r):
    return _dot(r[0], _cross(r[1], r[2]))


def _mean(points):
    return [sum(p[k] for p in points) / len(points) for k in range(3)]


def _number(v, name, nonnegative=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise ValueError(name + " must be finite")
    if nonnegative and v < 0:
        raise ValueError(name + " must be nonnegative")
    return float(v)


def _mapping(value, name):
    if not isinstance(value, Mapping):
        raise ValueError(name + " must be a mapping")
    return value


def _vec(v, name):
    if not isinstance(v, (tuple, list)) or len(v) != 3:
        raise ValueError(name + " must have three coordinates")
    return [_number(x, name) for x in v]


def _angle(a, b):
    return math.degrees(math.acos(max(-1.0, min(1.0, _dot(_unit(a), _unit(b))))))


def _rotation_angle(r):
    return math.degrees(math.acos(max(-1.0, min(1.0, (sum(r[i][i] for i in range(3)) - 1) / 2))))


def _rotation_valid(r):
    if not isinstance(r, (list, tuple)) or len(r) != 3:
        return False
    try:
        rows = [_vec(row, "rotation") for row in r]
    except ValueError:
        return False
    product = _mm(rows, _transpose(rows))
    return (abs(_det(rows) - 1) < 1e-7 and
            max(abs(product[i][j] - (1 if i == j else 0)) for i in range(3) for j in range(3)) < 1e-7)


def _pairs(n):
    return [(i, j) for i in range(n) for j in range(i + 1, n)]


def _largest_symmetric_eigenvector(matrix):
    """Jacobi eigensolver for Horn's symmetric 4x4 quaternion matrix."""
    a = [row[:] for row in matrix]
    v = [[float(i == j) for j in range(4)] for i in range(4)]
    scale = max(abs(x) for row in a for x in row)
    for _ in range(100):
        p, q = max(_pairs(4), key=lambda ij: abs(a[ij[0]][ij[1]]))
        if abs(a[p][q]) <= max(1e-15, scale * 1e-14):
            break
        tau = (a[q][q] - a[p][p]) / (2 * a[p][q])
        t = (1 if tau >= 0 else -1) / (abs(tau) + math.sqrt(1 + tau*tau))
        c = 1 / math.sqrt(1 + t*t)
        s = t * c
        apq = a[p][q]
        a[p][p] -= t * apq
        a[q][q] += t * apq
        a[p][q] = a[q][p] = 0.0
        for k in range(4):
            if k not in (p, q):
                akp, akq = a[k][p], a[k][q]
                a[k][p] = a[p][k] = c*akp - s*akq
                a[k][q] = a[q][k] = s*akp + c*akq
            vkp, vkq = v[k][p], v[k][q]
            v[k][p], v[k][q] = c*vkp - s*vkq, s*vkp + c*vkq
    index = max(range(4), key=lambda i: a[i][i])
    return _unit([v[k][index] for k in range(4)])


def _horn(source, target):
    cs, ct = _mean(source), _mean(target)
    s = [[0.0]*3 for _ in range(3)]
    for a, b in zip(source, target):
        a, b = _sub(a, cs), _sub(b, ct)
        for i in range(3):
            for j in range(3):
                s[i][j] += a[i]*b[j]
    xx, xy, xz = s[0]
    yx, yy, yz = s[1]
    zx, zy, zz = s[2]
    n = [[xx+yy+zz, yz-zy, zx-xz, xy-yx],
         [yz-zy, xx-yy-zz, xy+yx, zx+xz],
         [zx-xz, xy+yx, -xx+yy-zz, yz+zy],
         [xy-yx, zx+xz, yz+zy, -xx-yy+zz]]
    w, x, y, z = _largest_symmetric_eigenvector(n)
    r = [[1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)],
         [2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)],
         [2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)]]
    return r, _sub(ct, _mv(r, cs))


def _noncollinear(points):
    if len(points) < 3:
        return False
    vectors = [_sub(p, points[0]) for p in points[1:]]
    baseline = max(vectors, key=_norm)
    scale = _norm(baseline)
    if scale < 1e-10:
        return False
    return any(_norm(_cross(baseline,v)) > 1e-10*scale*scale for v in vectors)


def _noncoplanar(points):
    if len(points) < 4:
        return False
    vectors = [_sub(p, points[0]) for p in points[1:]]
    baseline = max(vectors,key=_norm)
    scale = _norm(baseline)
    if scale < 1e-10:
        return False
    normal = max((_cross(baseline,v) for v in vectors),key=_norm)
    return any(abs(_dot(v,normal)) > 1e-10*scale**3 for v in vectors)


def _normal_constrained(source, target, source_face, target_face):
    i, j = max(_pairs(len(source)),
               key=lambda pair: _norm(_sub(source[pair[1]], source[pair[0]])))

    def frame(points, normal):
        x = _unit(_sub(points[j], points[i]))
        z = _unit(_sub(normal, _mul(x, _dot(normal, x))))
        y = _cross(z, x)
        return _transpose([x, y, z])

    fs, ft = frame(source, source_face), frame(target, _mul(target_face, -1))
    r = _mm(ft, _transpose(fs))
    return r, _sub(_mean(target), _mv(r, _mean(source)))


def _voltage_check(source, target):
    roles = {"drive", "accept", "passive", "ground"}
    a, b = source.get("voltage_role"), target.get("voltage_role")
    if (a is not None and a not in roles) or (b is not None and b not in roles):
        return "error", "INVALID_VOLTAGE_ROLE"
    ranges = []
    for pin in (source, target):
        v = pin.get("voltage_range_v")
        if v is None:
            ranges.append(None)
            continue
        if not isinstance(v, (list, tuple)) or len(v) != 2:
            return "error", "INVALID_VOLTAGE_RANGE"
        lo, hi = [_number(n, "voltage range") for n in v]
        if lo > hi:
            return "error", "INVALID_VOLTAGE_RANGE"
        ranges.append((lo, hi))
    if a == b == "drive":
        return "error", "OUTPUT_TO_OUTPUT"
    if (a == "ground" and b not in (None, "ground")) or (b == "ground" and a not in (None, "ground")):
        return "error", "GROUND_ROLE_MISMATCH"
    if a is None or b is None or None in ranges:
        return "unverified", "VOLTAGE_INFORMATION_MISSING"
    va, vb = ranges
    if a == b == "ground":
        return ("compatible", None) if va == vb == (0.0, 0.0) else ("error", "GROUND_VOLTAGE_MISMATCH")
    if a == "drive":
        return ("compatible", None) if vb[0] <= va[0] and va[1] <= vb[1] else ("error", "VOLTAGE_INCOMPATIBLE")
    if b == "drive":
        return ("compatible", None) if va[0] <= vb[0] and vb[1] <= va[1] else ("error", "VOLTAGE_INCOMPATIBLE")
    if max(va[0], vb[0]) > min(va[1], vb[1]):
        return "error", "VOLTAGE_INCOMPATIBLE"
    return "unverified", "OPERATING_VOLTAGE_NOT_ESTABLISHED"


def _mounts_and_lock(constraints, pin_tol, normal_tol):
    raw_mounts = constraints.get("fixed_mounts",())
    if not isinstance(raw_mounts,(tuple,list)):
        raise ValueError("fixed_mounts must be a list or tuple")
    mounts = []
    for mount in raw_mounts:
        mount = _mapping(mount,"fixed mount")
        mounts.append(dict(source=_vec(mount["source_xyz_mm"],"source mount"),
            target=_vec(mount["target_xyz_mm"],"target mount"),
            tolerance=_number(mount.get("tolerance_mm",pin_tol),"mount tolerance",True)))
    locked = constraints.get("locked_source_pose")
    if locked is not None:
        locked = _mapping(locked,"locked_source_pose")
        rotation = locked["rotation"]
        if not _rotation_valid(rotation):
            raise ValueError("Locked source pose must be a proper rigid transform")
        locked = dict(rotation=[list(row) for row in rotation],
            translation=_vec(locked["translation_xyz_mm"],"locked source translation"),
            linear_tolerance=_number(locked.get("translation_tolerance_mm",pin_tol),"locked translation tolerance",True),
            angular_tolerance=_number(locked.get("rotation_tolerance_deg",normal_tol),"locked angle tolerance",True))
    return mounts,locked


def _pose_candidates(source,target,source_face,target_face,face_ready,mounts,locked):
    """Finite proposal set, not a complete constrained-rigid feasibility solver."""
    candidates = []

    def add(label,r,t):
        if not _rotation_valid(r):
            raise ValueError("Solver did not produce a proper rigid rotation")
        if any(max(abs(a-b) for ar,br in zip(r,c["rotation"]) for a,b in zip(ar,br)) < 1e-10
               and _norm(_sub(t,c["translation"])) < 1e-10 for c in candidates):
            return
        candidates.append(dict(label=label,rotation=r,translation=t))

    if len(source) >= 3 and _noncollinear(source) and _noncollinear(target):
        r,t = _horn(source,target)
        add("pin_least_squares",r,t)
    if len(source) >= 2 and face_ready:
        try:
            r,t = _normal_constrained(source,target,source_face,target_face)
        except ValueError:
            pass  # No baseline/normal frame; another explicit candidate may work.
        else:
            add("pin_baseline_and_face",r,t)
    if locked is not None:
        add("locked_source_pose",locked["rotation"],locked["translation"])
    if mounts:
        ms,mt = [m["source"] for m in mounts],[m["target"] for m in mounts]
        if len(ms) >= 3 and _noncollinear(ms) and _noncollinear(mt):
            r,t = _horn(ms,mt)
            add("mount_least_squares",r,t)
        if len(ms) >= 2 and face_ready:
            try:
                r,t = _normal_constrained(ms,mt,source_face,target_face)
            except ValueError:
                pass
            else:
                add("mount_baseline_and_face",r,t)
        # Retain candidate orientations, then align each mount or their centroid.
        for candidate in list(candidates):
            r = candidate["rotation"]
            translations = [_sub(m["target"],_mv(r,m["source"])) for m in mounts]
            add(candidate["label"]+"+mount_centroid",r,_mean(translations))
            for i,t in enumerate(translations):
                add(candidate["label"]+f"+mount_{i}",r,t)
    return candidates


def _evaluate_pose(candidate,source,target,source_face,target_face,key_s,key_t,
                   mounts,locked,pin_tol,normal_tol):
    """Compare every constraint at the same complete rigid pose."""
    r,t = candidate["rotation"],candidate["translation"]
    transformed = [_add(_mv(r,p),t) for p in source]
    errors = [_norm(_sub(p,q)) for p,q in zip(transformed,target)]
    checks = []

    def check(code,value,tolerance,numeric_slack):
        checks.append(dict(code=code,value=value,tolerance=tolerance,
            satisfied=value <= tolerance+numeric_slack,
            normalized=value/max(tolerance,numeric_slack)))

    check("PIN_FIT_RESIDUAL",max(errors),pin_tol,1e-10)
    evaluated = dict(label=candidate["label"],rotation=r,translation=t,
        transformed=transformed,pin_distances=errors,max_pin_error_mm=max(errors),
        mean_pin_error_mm=sum(errors)/len(errors),
        rms_pin_error_mm=math.sqrt(sum(e*e for e in errors)/len(errors)),
        fixed_mount_errors=[],locked_source_pose_residual=None)
    if source_face is not None and target_face is not None:
        evaluated["normal_error_deg"] = _angle(_mv(r,source_face),_mul(target_face,-1))
        check("MATING_NORMAL_CONFLICT",evaluated["normal_error_deg"],normal_tol,1e-8)
    if key_s is not None:
        evaluated["key_error_deg"] = _angle(_mv(r,key_s),key_t)
        check("KEY_ALIGNMENT_CONFLICT",evaluated["key_error_deg"],normal_tol,1e-8)
    for index,m in enumerate(mounts):
        error = _norm(_sub(_add(_mv(r,m["source"]),t),m["target"]))
        evaluated["fixed_mount_errors"].append(dict(index=index,error_mm=error,tolerance_mm=m["tolerance"]))
        check("FIXED_MOUNT_CONFLICT",error,m["tolerance"],1e-10)
    if locked is not None:
        linear = _norm(_sub(t,locked["translation"]))
        angular = _rotation_angle(_mm(r,_transpose(locked["rotation"])))
        evaluated["locked_source_pose_residual"] = dict(
            translation_mm=linear,rotation_deg=angular,
            translation_tolerance_mm=locked["linear_tolerance"],
            rotation_tolerance_deg=locked["angular_tolerance"])
        check("LOCKED_BOARD_TRANSLATION_CONFLICT",linear,locked["linear_tolerance"],1e-10)
        check("LOCKED_BOARD_ROTATION_CONFLICT",angular,locked["angular_tolerance"],1e-8)
    evaluated["checks"] = checks
    evaluated["feasible"] = all(c["satisfied"] for c in checks)
    evaluated["score"] = [max(c["normalized"] for c in checks),
                          sum(c["normalized"] for c in checks)]
    return evaluated


def align_pins(request: Mapping | AlignmentRequest) -> dict:
    """Return a detached candidate. Inputs are never written; see API.md."""
    result = dict(status="rejected", alignment_candidate_valid=False, transform=None,
        coordinate_contract="source_body_local_to_target_body_local",
        units="mm", scale=1.0, pin_errors=[], pitch_errors=[], fixed_mount_errors=[],
        locked_source_pose_residual=None, issues=[], mechanical_mating_safety_verified=False,
        preview_only=True, input_mutated=False,
        limits=["No 3D collision, connector insertion/retention, strength, vibration, electrical rating or physical mating safety qualification.",
                "Only explicit pin coordinates, declared tolerances, mapping, net and voltage facts are considered."])

    def issue(code, severity, message, **extra):
        result["issues"].append(dict(code=code,severity=severity,message=message,**extra))

    try:
        if not is_dataclass(request) and not isinstance(request,Mapping):
            raise ValueError("request must be a mapping or AlignmentRequest")
        raw = asdict(request) if is_dataclass(request) else deepcopy(dict(request))
        raw = _mapping(raw,"request")
        if raw.get("units") != "mm":
            raise ValueError("units must explicitly be 'mm'; no automatic scale conversion")
        sb, tb = _mapping(raw["source"],"source"), _mapping(raw["target"],"target")
        sp, tp = _mapping(sb["pins"],"source pins"), _mapping(tb["pins"],"target pins")
        pairs = raw["mapping"]
        if not isinstance(pairs, (list, tuple)) or not pairs:
            raise ValueError("Explicit nonempty pin mapping is required")
        source_ids, target_ids = [], []
        source, target = [], []
        for pair in pairs:
            pair = _mapping(pair,"pin mapping item")
            a, b = pair["source_pin"], pair["target_pin"]
            if not isinstance(a,str) or not a or not isinstance(b,str) or not b:
                raise ValueError("Mapped pin IDs must be nonempty strings")
            if a in source_ids or b in target_ids:
                issue("DUPLICATE_PIN_MAPPING","error","Each source and target pin may be mapped once",source_pin=a,target_pin=b)
                return result
            if a not in sp or b not in tp:
                raise ValueError("Mapping references an unknown pin")
            _mapping(sp[a],"source pin")
            _mapping(tp[b],"target pin")
            source_ids.append(a)
            target_ids.append(b)
            source.append(_vec(sp[a]["xyz"], "source pin"))
            target.append(_vec(tp[b]["xyz"], "target pin"))
        if sb.get("footprint_verified") is not True or tb.get("footprint_verified") is not True:
            issue("FOOTPRINT_UNVERIFIED","unverified","Both footprints must have verified coordinate provenance")
        if sb.get("pin_map_verified") is not True or tb.get("pin_map_verified") is not True:
            issue("PIN_MAP_UNVERIFIED","unverified","Both pin maps and electrical declarations need explicit verification")
        constraints = _mapping(raw.get("constraints",{}),"constraints")
        pin_tol = _number(constraints.get("max_pin_error_mm",.05),"pin tolerance",True)
        pitch_tol = _number(constraints.get("pitch_tolerance_mm",.05),"pitch tolerance",True)
        normal_tol = _number(constraints.get("normal_tolerance_deg",1),"normal tolerance",True)
        if constraints.get("tolerances_verified") is not True:
            issue("TOLERANCE_UNVERIFIED","unverified","Default or unknown tolerances do not establish a verified fit")
        mating = _mapping(raw.get("mating",{}),"mating")
        mounts,locked = _mounts_and_lock(constraints,pin_tol,normal_tol)
        height, depth = mating.get("stand_off_height_mm"), mating.get("insertion_depth_mm")
        if height is None or depth is None:
            issue("MATING_HEIGHT_UNSPECIFIED","unverified","Explicit stand-off height and insertion depth are required")
            offset = 0.0
        else:
            height = _number(height,"stand-off height",True)
            depth = _number(depth,"insertion depth",True)
            offset = height - depth
        side_s, side_t = mating.get("source_side"), mating.get("target_side")
        sides_known = side_s in ("top","bottom") and side_t in ("top","bottom")
        if not sides_known:
            issue("MATING_SIDE_UNSPECIFIED","unverified","Select the physical mating side on both boards")
        allowed = mating.get("allowed_side_pairs") or []
        if not allowed:
            issue("MATING_SIDE_POLICY_UNVERIFIED","unverified","Allowed side pairs require a connector/mount specification")
        elif sides_known and [side_s,side_t] not in [list(p) for p in allowed]:
            issue("WRONG_SIDE","error","Selected board sides violate the declared allowed side pairs")
        if mating.get("keying_verified") is not True:
            issue("KEYING_UNVERIFIED","unverified","Connector keying or confirmed unkeyed construction must be explicit")
        key_s,key_t = mating.get("source_key_axis"),mating.get("target_key_axis")
        if (key_s is None) != (key_t is None):
            raise ValueError("Both key axes are required when key-axis alignment is declared")
        if key_s is not None:
            key_s,key_t = _unit(_vec(key_s,"source key axis")),_unit(_vec(key_t,"target key axis"))
        source_face = target_face = None
        if mating.get("source_normal") is not None and mating.get("target_normal") is not None and sides_known:
            source_face = _mul(_unit(_vec(mating["source_normal"],"source normal")),1 if side_s=="top" else -1)
            target_face = _mul(_unit(_vec(mating["target_normal"],"target normal")),1 if side_t=="top" else -1)
            target = [_add(p,_mul(target_face,offset)) for p in target]
        else:
            issue("MATING_NORMAL_UNSPECIFIED","unverified","Board top outward normals are needed to verify facing")
            if abs(offset) > 1e-12:
                issue("MATING_OFFSET_DIRECTION_UNKNOWN","error","A nonzero offset cannot be applied without the target face normal")
        result["mating"] = dict(source_side=side_s,target_side=side_t,
            stand_off_height_mm=height,insertion_depth_mm=depth,normal_offset_mm=offset,
            desired_source_points_mm=target,
            offset_rule="target_reference + target_selected_face_normal * (stand_off_height_mm - insertion_depth_mm)")
        equivalences = {tuple(p) for p in raw.get("net_equivalences",[])}
        for index,(a,b) in enumerate(zip(source_ids,target_ids)):
            ns,nt = sp[a].get("net"),tp[b].get("net")
            declared = pairs[index].get("net_compatibility")
            if declared not in (None,"compatible","incompatible","unverified"):
                raise ValueError("net_compatibility must be compatible, incompatible or unverified")
            if declared == "incompatible":
                net_status = "error"
                issue("NET_INCOMPATIBLE","error","Explicit mapping facts declare incompatible pin functions",source_pin=a,target_pin=b)
            elif not ns or not nt:
                net_status = "unverified"
                issue("NET_UNSPECIFIED","unverified","Both mapped pin nets must be explicit",source_pin=a,target_pin=b)
            elif declared == "compatible" or (ns,nt) in equivalences:
                net_status = "compatible"
            else:
                net_status = "unverified"
                issue("NET_COMPATIBILITY_UNVERIFIED","unverified","Board-local net labels do not establish compatibility; an explicit mapping fact is needed",source_pin=a,target_pin=b)
            voltage_status,code = _voltage_check(sp[a],tp[b])
            if code:
                issue(code,"error" if voltage_status=="error" else "unverified","Mapped voltage declarations are incompatible or incomplete",source_pin=a,target_pin=b)
            result["pin_errors"].append(dict(source_pin=a,target_pin=b,net_status=net_status,
                voltage_status=voltage_status,source_xyz_mm=source[index],
                target_mating_xyz_mm=target[index]))
        for i,j in _pairs(len(source)):
            ds,dt = _norm(_sub(source[i],source[j])),_norm(_sub(target[i],target[j]))
            result["pitch_errors"].append(dict(source_pins=[source_ids[i],source_ids[j]],
                target_pins=[target_ids[i],target_ids[j]],source_distance_mm=ds,
                target_distance_mm=dt,error_mm=abs(ds-dt)))
        if any(p["error_mm"] > pitch_tol + 1e-10 for p in result["pitch_errors"]):
            issue("PITCH_MISMATCH","error","Mapped inter-pin distances require deformation or scale")
        face_ready = (source_face is not None and target_face is not None
                      and height is not None and depth is not None and sides_known)
        candidates = _pose_candidates(source,target,source_face,target_face,face_ready,mounts,locked)
        evaluations = [_evaluate_pose(c,source,target,source_face,target_face,key_s,key_t,
                       mounts,locked,pin_tol,normal_tol) for c in candidates]
        feasible = [e for e in evaluations if e["feasible"]]
        result["candidate_search"] = dict(
            method="Finite pin/face/locked-pose/mount-derived proposals; not a complete constrained solver",
            candidates_evaluated=len(evaluations),feasible_candidates=len(feasible),
            global_infeasibility_proven=False)
        result["candidate_evaluations"] = [
            dict(label=e["label"],feasible=e["feasible"],score=e["score"],
                 checks=e["checks"],max_pin_error_mm=e["max_pin_error_mm"],
                 mean_pin_error_mm=e["mean_pin_error_mm"]) for e in evaluations]
        if not evaluations:
            issue("ROTATION_UNDERDETERMINED","underdetermined",
                  "No determined pin/face frame or explicit locked pose is available")
        else:
            selected = min(feasible or evaluations,key=lambda e:tuple(e["score"]))
            result["candidate_search"]["selected"] = selected["label"]
            rotation,translation = selected["rotation"],selected["translation"]
            for row,xyz,error in zip(result["pin_errors"],selected["transformed"],selected["pin_distances"]):
                row.update(transformed_xyz_mm=xyz,error_mm=error)
            for key in ("max_pin_error_mm","mean_pin_error_mm","rms_pin_error_mm",
                        "fixed_mount_errors","locked_source_pose_residual","normal_error_deg","key_error_deg"):
                if key in selected:
                    result[key] = selected[key]
            result["transform"] = dict(rotation=rotation,translation_xyz_mm=translation,
                determinant=_det(rotation),scale=1.0,method=selected["label"])
            if not feasible:
                for check in selected["checks"]:
                    if not check["satisfied"]:
                        issue(check["code"],"unresolved",
                              "Selected candidate violates this constraint; global infeasibility is not established",
                              value=check["value"],tolerance=check["tolerance"])
                issue("CONSTRAINT_SOLUTION_UNVERIFIED","unresolved",
                      "No feasible pose found in the finite candidate set; another allowed pose may exist")
                # A noncoplanar nominal reflection is a separate diagnostic.
                # Use proper LS RMS, not only one candidate's maximum residual.
                if _noncoplanar(source):
                    lr,lt = _horn(source,target)
                    ls_errors = [_norm(_sub(_add(_mv(lr,p),lt),q)) for p,q in zip(source,target)]
                    ls_rms = math.sqrt(sum(e*e for e in ls_errors)/len(ls_errors))
                    mirrored = [[-p[0],p[1],p[2]] for p in source]
                    mr,mt = _horn(mirrored,target)
                    mirror_errors = [_norm(_sub(_add(_mv(mr,p),mt),q)) for p,q in zip(mirrored,target)]
                    result["diagnostic_reflection_best_max_error_mm"] = max(mirror_errors)
                    if ls_rms > pin_tol+1e-10 and max(mirror_errors) <= pin_tol+1e-10:
                        issue("REFLECTION_REQUIRED","error",
                              "Nominal fit requires an improper reflection; proper rigid LS RMS exceeds the pin tolerance")
        severities = {i["severity"] for i in result["issues"]}
        result["status"] = ("rejected" if "error" in severities else
                            "underdetermined" if "underdetermined" in severities else
                            "constraint_unresolved" if "unresolved" in severities else
                            "unverified" if "unverified" in severities else "aligned_preview")
        result["alignment_candidate_valid"] = result["status"] == "aligned_preview"
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        issue("INVALID_INPUT","error",str(exc))
        result["status"] = "rejected"
        result["alignment_candidate_valid"] = False
    return result
