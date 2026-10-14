"""View/print membership from declarations, separate from primary color role.

Motor evidence is a saved circuit type or explicit BOM Component ID. Names,
colors, shapes and movable joints never establish an electric motor.
No electrical registration, rating, power or motion readiness is implied.
"""
from collections.abc import Mapping

ROLES = frozenset(("structure", "electrical", "transmission", "specimen"))
MOTOR_TYPES = frozenset(("motor", "actuator", "dc_motor", "bldc_motor", "brushless_motor", "stepper_motor", "servo"))
MOTOR_BOM_IDS = frozenset(("MOTOR", "SERVO", "ELECTRIC_ACTUATOR", "STEPPER_MOTOR", "DC_MOTOR", "BLDC_MOTOR"))


def field(value, key, default=None):
    return value.get(key, default) if isinstance(value, Mapping) else getattr(value, key, default)


def role_membership_data(design):
    """Return sets; multiple filter memberships do not change stored color/role."""
    circuits = {}
    for c in field(field(design, "electrical"), "components", ()) or ():
        pid = field(c, "part_id")
        if pid:circuits.setdefault(pid, set()).add(field(c, "kind", ""))
    bom = field(design, "bom")
    rows = {field(r, "id"): r for r in field(bom, "items", ()) or ()}
    result = {}
    for part in field(design, "parts", ()) or ():
        pid, primary = field(part, "id"), field(part, "role", "unspecified")
        membership = {primary} if primary in ROLES else set()
        if pid in circuits:membership.add("electrical")
        binding = field(part, "bom")
        row = rows.get(field(binding, "item_id"))
        bound_bom = (bom is not None and binding is not None and row is not None
                     and field(binding, "document_id") == field(bom, "id")
                     and field(binding, "source_sha256") == field(bom, "source_sha256"))
        component = field(field(row, "raw_fields", {}), "Component ID", "") if bound_bom else ""
        motor = bool(circuits.get(pid, set()) & MOTOR_TYPES) or component in MOTOR_BOM_IDS
        if motor:membership.update(("electrical", "transmission"))
        result[pid] = {"roles": frozenset(membership), "electric_motor": motor}
    return result


def role_memberships(design):
    return {pid: value['roles'] for pid,value in role_membership_data(design).items()}
