"""Explicit saved flexible-wire scope for mechanical interference checks.

Only the exact product-spec tag opts a body out. Names, electrical roles,
geometry kinds, groups and visibility never imply exemption. This is an
author's classification, not a flexible-cable clearance or electrical check;
connectors, terminals and boards remain in scope unless explicitly mistagged.
"""
from collections.abc import Mapping

FLEXIBLE_WIRE_LABEL = '간섭 분류'
FLEXIBLE_WIRE_VALUE = '유연 전선'


def _field(record, name, default=None):
    return record.get(name, default) if isinstance(record, Mapping) else getattr(record, name, default)


def flexible_wire_part_ids(design):
    """Read typed or saved design data without copying a large project."""
    identifiers = []
    for part in _field(design, 'parts', ()):
        product = _field(part, 'product')
        if product is not None and any(
                _field(spec, 'label') == FLEXIBLE_WIRE_LABEL and
                _field(spec, 'value') == FLEXIBLE_WIRE_VALUE
                for spec in _field(product, 'specs', ())):
            identifiers.append(_field(part, 'id'))
    return identifiers


def collision_exclusion_stats(design):
    identifiers = flexible_wire_part_ids(design)
    return dict(flexible_wire_excluded_ids=identifiers,
                flexible_wire_excluded_count=len(identifiers))


def collision_caption(stats):
    """Show the mechanical scope even at zero, preserving legacy captions."""
    count = len(stats.get('collisions', []))
    excluded = stats.get('flexible_wire_excluded_count', 0)
    if excluded:
        return f'고정부품 간섭 {count}건 · 전선 {excluded}개 제외'
    return f'간섭 {count}건' if count else ''
