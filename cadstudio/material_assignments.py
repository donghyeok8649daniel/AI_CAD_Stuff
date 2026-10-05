"""Atomic, explicit per-part material assignments and optional tensile values."""
from __future__ import annotations

from copy import deepcopy
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field
from .models import Design, Material
from .material_catalog import MaterialProperty, MaterialProvenance, UNITS, material_from_catalog


def _design(raw: Design | dict) -> Design:
    return Design.model_validate(raw.model_dump() if isinstance(raw, Design) else deepcopy(raw))


def _targets(design: Design, part_ids: str | Iterable[str]) -> tuple[str, ...]:
    ids = (part_ids,) if isinstance(part_ids, str) else tuple(dict.fromkeys(part_ids))
    if not ids:
        raise ValueError('재질을 적용할 부품을 선택하세요.')
    existing = {part.id for part in design.parts}
    missing = [identifier for identifier in ids if identifier not in existing]
    if missing:
        raise ValueError('재질 대상 부품을 찾을 수 없습니다: '+', '.join(missing))
    return ids


def part_material(raw: Design | dict, part_id: str) -> Material | None:
    design = _design(raw)
    _targets(design, part_id)
    part = next(part for part in design.parts if part.id == part_id)
    return Material.model_validate(part.material.model_dump()) if part.material else None


def assign_material(raw: Design | dict, part_ids: str | Iterable[str],
                    material: Material | dict | None = None, *,
                    catalog_id: str | None = None, replace_existing: bool = False) -> Design:
    """Return a new design; geometry, wiring, color and other bodies stay exact.

    Existing assignments (including custom input) require explicit replacement.
    No inference from role/color/name or default printed PLA is performed.
    """
    design = _design(raw)
    targets = _targets(design, part_ids)
    if (material is None) == (catalog_id is None):
        raise ValueError('사용자 재질 또는 목록 재질 중 하나를 지정하세요.')
    chosen = material_from_catalog(catalog_id) if catalog_id is not None else Material.model_validate(
        material.model_dump() if isinstance(material, Material) else material)
    blocked = [part.name for part in design.parts if part.id in targets and part.material is not None
               and part.material.model_dump() != chosen.model_dump() and not replace_existing]
    if blocked:
        raise ValueError('기존 재질을 보존했습니다. 교체하려면 기존 재질도 교체를 선택하세요: '+', '.join(blocked))
    data = design.model_dump()
    for part in data['parts']:
        if part['id'] in targets:
            part['material'] = deepcopy(chosen.model_dump())
    return Design.model_validate(data)


def remove_material(raw: Design | dict, part_ids: str | Iterable[str]) -> Design:
    design = _design(raw)
    targets = _targets(design, part_ids)
    data = design.model_dump()
    for part in data['parts']:
        if part['id'] in targets:
            part.pop('material', None)
    return Design.model_validate(data)


def custom_material(original: Material | dict | None, changes: dict) -> Material:
    """Retain untouched custom/source data; edited values lose catalog authority."""
    allowed = set(UNITS) | {'name', 'behavior'}
    if set(changes) - allowed:
        raise ValueError('수정할 수 없는 재질 항목입니다.')
    current = Material.model_validate(original.model_dump() if isinstance(original, Material) else original or {})
    data = current.model_dump()
    changed = {key: value for key, value in changes.items() if data.get(key) != value}
    if not changed:
        return Material.model_validate(data)
    data.update(changed)
    if current.provenance is not None:
        record = MaterialProvenance.model_validate(current.provenance).model_copy(deep=True)
    else:
        # A newly edited manual material records units and unknowns too. Merely
        # viewing an unchanged legacy material keeps its original JSON exact.
        record = MaterialProvenance(origin='user', properties={
            key: MaterialProperty(value=data.get(key), unit=unit,
                basis='unknown' if data.get(key) is None else 'user',
                condition='사용자 입력 · 온도·방향·시험 조건 미지정')
            for key, unit in UNITS.items()})
    record.origin = 'user'
    record.catalog_id = None
    for key, value in changed.items():
        if key in UNITS:
            record.properties[key] = MaterialProperty(value=value, unit=UNITS[key],
                basis='unknown' if value is None else 'user', condition='사용자 입력 · 출처 수치와 별도로 확인 필요')
    data['provenance'] = record.model_dump(mode='json')
    data.pop('catalog_id', None)
    return Material.model_validate(data)


class TensileMaterialValues(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    young_gpa: float = Field(gt=.001, le=2000)
    poisson: float = Field(ge=0, le=.45)
    yield_mpa: float = Field(gt=0, le=100000)


def tensile_material_values(material: Material | dict) -> TensileMaterialValues:
    """Offer complete scalar values for an explicit user action, never defaults.

    The existing small-strain solver is isotropic. Directional Si values and
    nonlinear seals cannot be silently reduced to an isotropic approximation.
    """
    chosen = Material.model_validate(material.model_dump() if isinstance(material, Material) else material)
    if chosen.behavior in ('anisotropic', 'nonlinear'):
        raise ValueError('이 재질은 이방성 또는 비선형입니다. 현재 등방성 인장해석에 적용할 수 없습니다.')
    missing = [key for key in ('youngs_modulus', 'poisson', 'yield_strength') if getattr(chosen, key) is None]
    if missing:
        raise ValueError('인장해석에 필요한 재질 값이 미확인입니다: '+', '.join(missing))
    return TensileMaterialValues(young_gpa=chosen.youngs_modulus/1000,
                                 poisson=chosen.poisson, yield_mpa=chosen.yield_strength)


def tensile_settings_with_material(raw: Design | dict, part_id: str, settings: dict) -> dict:
    """Explicit helper: return validated settings, without changing saved studies."""
    material = part_material(raw, part_id)
    if material is None:
        raise ValueError('부품의 재질을 먼저 지정하세요.')
    if settings.get('part_id') != part_id:
        raise ValueError('해석 설정의 부품과 재질 대상이 다릅니다.')
    values = tensile_material_values(material)
    from .tensile import TensileSettings
    candidate = deepcopy(settings)
    candidate.update(values.model_dump())
    return TensileSettings.model_validate(candidate).model_dump()
