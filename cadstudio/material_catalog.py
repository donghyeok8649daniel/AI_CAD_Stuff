"""Offline material references. Missing properties are never filled by analogy.

Canonical units: kg/m³, MPa, W/(m·K), 1/K, J/(kg·K), mass percent.
These records describe the named stock material and documented test conditions;
they are not certifications of a CAD body, printed part, seal or research sample.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal
import unicodedata
import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .part_product import validate_product_link

CHECKED_ON = '2026-10-06'
UNITS = {'density': 'kg/m³', 'youngs_modulus': 'MPa', 'poisson': '1',
         'yield_strength': 'MPa', 'tensile_strength': 'MPa',
         'thermal_conductivity': 'W/(m·K)', 'thermal_expansion': '1/K',
         'specific_heat': 'J/(kg·K)', 'water_absorption': '%'}
LABELS = {'density': '밀도', 'youngs_modulus': '탄성계수 E', 'poisson': '포아송 비 ν',
          'yield_strength': '항복강도', 'tensile_strength': '인장강도',
          'thermal_conductivity': '열전도율', 'thermal_expansion': '선팽창계수',
          'specific_heat': '비열', 'water_absorption': '흡수율'}


class MaterialSource(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    title: str = Field(min_length=1, max_length=240)
    url: str = Field(min_length=1, max_length=1500)
    revision: str = Field(default='', max_length=160)
    checked_on: str = CHECKED_ON

    @field_validator('url')
    @classmethod
    def checked_url(cls, value):
        return validate_product_link(value)

    @field_validator('checked_on')
    @classmethod
    def checked_date(cls, value):
        date.fromisoformat(value)
        return value


class MaterialProperty(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False, frozen=True)
    value: float | None = None
    unit: str = Field(max_length=40)
    basis: Literal['typical', 'minimum', 'nominal', 'approximate', 'range', 'unknown', 'user'] = 'unknown'
    minimum: float | None = None
    maximum: float | None = None
    temperature_c: float | None = Field(default=None, ge=-273.15, le=3000)
    temperature_max_c: float | None = Field(default=None, ge=-273.15, le=3000)
    direction: str = Field(default='', max_length=160)
    condition: str = Field(default='', max_length=1200)
    source_index: int | None = Field(default=None, ge=0, le=15)

    @model_validator(mode='after')
    def coherent_range(self):
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError('물성 범위의 최솟값이 최댓값보다 큽니다.')
        if self.temperature_c is not None and self.temperature_max_c is not None and self.temperature_c > self.temperature_max_c:
            raise ValueError('물성 온도 범위가 잘못되었습니다.')
        if self.basis == 'unknown' and self.value is not None:
            raise ValueError('미확인 물성에는 수치를 넣을 수 없습니다.')
        if self.basis == 'range' and (self.minimum is None or self.maximum is None or self.value is not None):
            raise ValueError('범위 물성은 단일값 없이 최소·최대를 기록하세요.')
        if self.basis not in ('unknown', 'range') and self.value is None:
            raise ValueError('확인된 물성의 값을 입력하세요.')
        return self


class MaterialProvenance(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    origin: Literal['catalog', 'user'] = 'catalog'
    catalog_id: str | None = Field(default=None, max_length=100)
    manufacturer: str = Field(default='', max_length=200)
    designation: str = Field(default='', max_length=200)
    sources: list[MaterialSource] = Field(default_factory=list, max_length=16)
    properties: dict[str, MaterialProperty] = Field(default_factory=dict, max_length=32)
    notes: list[str] = Field(default_factory=list, max_length=16)

    @model_validator(mode='after')
    def references(self):
        for key, fact in self.properties.items():
            if key not in UNITS and key not in ('youngs_modulus_100', 'youngs_modulus_110', 'youngs_modulus_111'):
                raise ValueError('지원하지 않는 물성 이름입니다: '+key)
            unit = UNITS.get(key, 'MPa')
            if fact.unit != unit:
                raise ValueError('물성 단위가 다릅니다: '+key+' · '+unit)
            if fact.source_index is not None and fact.source_index >= len(self.sources):
                raise ValueError('물성 출처 번호가 범위를 벗어났습니다.')
        if any(len(note) > 2000 for note in self.notes):
            raise ValueError('재질 설명은 항목당 2000자 이내로 입력하세요.')
        return self


@dataclass(frozen=True, slots=True)
class MaterialCatalogEntry:
    catalog_id: str
    name: str
    category: str
    manufacturer: str
    designation: str
    behavior: Literal['isotropic', 'anisotropic', 'nonlinear']
    properties: tuple[tuple[str, MaterialProperty], ...]
    sources: tuple[MaterialSource, ...]
    notes: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()

    def provenance(self) -> MaterialProvenance:
        return MaterialProvenance(catalog_id=self.catalog_id, manufacturer=self.manufacturer,
            designation=self.designation, properties=dict(self.properties),
            sources=list(self.sources), notes=list(self.notes))


def _source(title, url, revision=''):
    return MaterialSource(title=title, url=url, revision=revision)


def _fact(key, value, condition='', *, source=0, basis='typical', temperature=None, high=None, direction=''):
    return MaterialProperty(value=value, unit=UNITS.get(key, 'MPa'), basis=basis if value is not None else 'unknown',
        condition=condition, source_index=source if value is not None else None,
        temperature_c=temperature, temperature_max_c=high, direction=direction)


def _properties(**facts):
    return tuple((key, facts.get(key, _fact(key, None, '공식 자료에서 확인하지 않은 값')))
                 for key in UNITS) + tuple((key, value) for key, value in facts.items() if key not in UNITS)


KAISER = _source('Kaiser Aluminum · 6061 extruded shapes',
    'https://online.kaiseraluminum.com/depot/PublicProductInformation/Document/1006/Kaiser_Aluminum_Shapes_Soft_Alloy.pdf', 'KA-SH-6061-1.09 · pp. 2–3')
HYDRO = _source('Hydro · Alloy 6061',
    'https://www.hydro.com/globalassets/01-products--services/extruded-profiles/americas/ena-resources/alloy-data-sheets/hydro_2019_data_sheet_6061.pdf', '2019/01 (2/2019)')
SSAB_GENERAL = _source('SSAB · 20 questions about steel', 'https://www.ssab.com/en/support/product-material-data/steel/20-questions', 'web · revision not stated')
SSAB_S355 = _source('SSAB · S355J2+N Zero', 'https://www.ssab.com/-/media/files/en/zero/data_sheet_2422_ssab_s355j2n_zero_2025_01_21.pdf', '2422 · 2025-01-21')
OUTOKUMPU = _source('Outokumpu · Core range', 'https://www.outokumpu.com/en/products/product-ranges/-/media/files/products/core/outokumpu-core-range-datasheet.pdf', 'web PDF · tables 4 and 6')
ENSINGER_PC = _source('Ensinger · TECANAT natural', 'https://www.ensingerplastics.com/en-us/shapes/polycarbonate-tecanat-natural', 'US ASTM technical data · web revision not stated')
ENSINGER_POM = _source('Ensinger · Food technology stock shapes', 'https://www.ensingerplastics.com/-/media/ensinger/files/document-teaser-files/brochures/shapes/food-technology-shapes-en.pdf', 'metric stock-shape table · revision not stated')
ENSINGER_PMMA = _source('Ensinger · Extruded acrylic sheet', 'https://www.ensingerplastics.com/-/media/ensinger/files/document-teaser-files/uk-documents/datasheet-extruded-acrylic-sheet-en.pdf', 'extruded acrylic · revision not stated')
ENSINGER_PTFE = _source('Ensinger · TECAFLON PTFE natural', 'https://www.ensingerplastics.com/pt-br/semiacabados/tecaflon-ptfe', 'German stock shapes · revision not stated')
WACKER = _source('Wacker · ELASTOSIL LR 3003/50 A/B', 'https://www.wacker.com/h/en-us/medias/ELASTOSIL-LR-300350-AB-en-2021.06.30-v18.pdf', 'v18 · 2021-06-30')
SI_DENSITY = _source('BIPM · Silicon density comparison CCM.D-K1.2023', 'https://www.bipm.org/kcdb/comparison?id=1807', 'results 2026-03-18 · natural-silicon reference sphere')
SI_ELASTIC = _source('Hopcroft, Nix and Kenny · Young’s modulus of silicon', 'https://people.eecs.berkeley.edu/~pister/147fa15/Resources/Hopcroft10.pdf', 'JMEMS 19(2), 2010 · DOI 10.1109/JMEMS.2009.2039697')

CATALOG = (
    MaterialCatalogEntry('al_6061_t6_extruded', 'Al 6061-T6 · 압출재', '금속', 'Kaiser / Hydro', '6061-T6 extruded stock', 'isotropic',
        _properties(density=_fact('density', 2700, 'Kaiser nominal density', temperature=20, basis='nominal'),
            youngs_modulus=_fact('youngs_modulus', 68300, 'Kaiser printed value 68.3 GPa; average tension/compression'),
            yield_strength=_fact('yield_strength', 240, 'Hydro T6/T6511 extrusion minimum; 0.2% offset; verify product thickness', source=1, basis='minimum'),
            tensile_strength=_fact('tensile_strength', 260, 'Hydro T6/T6511 extrusion minimum; verify product thickness', source=1, basis='minimum'),
            thermal_conductivity=_fact('thermal_conductivity', 167, 'T6 typical', source=1, temperature=25),
            thermal_expansion=_fact('thermal_expansion', 23.58e-6, '13.1e-6 per °F × 1.8; average 20–100 °C', source=1, temperature=20, high=100)),
        (KAISER, HYDRO), ('압출재 참고값입니다. 판재·용접 열영향부·다른 조질에 그대로 적용하지 마세요.', '포아송 비와 피로 수명은 미확인입니다. 자동 인장해석 적용은 하지 않습니다.'), ('알루미늄', 'aluminum', 'aluminium', '6061', 't6')),
    MaterialCatalogEntry('steel_s355j2n_plate', '강재 S355J2+N · 6–16 mm 판재', '금속', 'SSAB', 'S355J2+N Zero · 6–16 mm', 'isotropic',
        _properties(density=_fact('density', 7850, 'SSAB general steel approximation; not lot measurement', source=1, basis='approximate'),
            youngs_modulus=_fact('youngs_modulus', 200000, 'SSAB general steel approximation at room temperature', source=1, basis='approximate'),
            yield_strength=_fact('yield_strength', 355, '6–16 mm heavy plate; minimum; transverse to rolling', basis='minimum', direction='transverse to rolling'),
            tensile_strength=MaterialProperty(value=None, unit='MPa', basis='range', minimum=470, maximum=630, source_index=0, direction='transverse to rolling', condition='6–16 mm heavy plate')),
        (SSAB_S355, SSAB_GENERAL), ('큰 두께의 항복강도는 별도 값입니다. 얇은 챔버 판재의 인증값으로 사용하지 마세요.', '습한 환경의 부식·코팅 적합성은 별도 확인이 필요합니다.'), ('steel', '강철', '구조강', 's355')),
    MaterialCatalogEntry('stainless_304_cold_sheet', '스테인리스 304 / 1.4301 · 냉연', '금속', 'Outokumpu', 'Core 304/4301 · cold rolled C', 'isotropic',
        _properties(density=_fact('density', 7900, '7.9 kg/dm³ × 1000'), youngs_modulus=_fact('youngs_modulus', 200000, '200 GPa × 1000', temperature=20),
            yield_strength=_fact('yield_strength', 230, 'EN cold rolled C; Rp0.2; not ASTM value', basis='minimum'),
            tensile_strength=MaterialProperty(value=None, unit='MPa', basis='range', minimum=540, maximum=750, source_index=0, condition='EN cold rolled C'),
            thermal_conductivity=_fact('thermal_conductivity', 15, temperature=20),
            thermal_expansion=_fact('thermal_expansion', 16e-6, 'average 20–100 °C', temperature=20, high=100),
            specific_heat=_fact('specific_heat', 500, temperature=20)), (OUTOKUMPU,),
        ('염화물·응력부식·용접 상태와 재료 성적서는 별도 확인하세요. 방습 또는 밀폐 성능을 인증하지 않습니다.',), ('sus304', 'stainless', '스텐', '304', '1.4301')),
    MaterialCatalogEntry('pc_tecanat_natural', 'PC · TECANAT natural · 투명창', '폴리머 / 창', 'Ensinger', 'TECANAT natural · US stock-shape data', 'isotropic',
        _properties(density=_fact('density', 1190, '1.19 g/cm³ × 1000'),
            youngs_modulus=_fact('youngs_modulus', 340000*.006894757293168, '340000 psi × 0.006894757293168; ASTM D638', temperature=(73-32)*5/9),
            yield_strength=_fact('yield_strength', 9300*.006894757293168, '9300 psi × 0.006894757293168; ASTM D638', temperature=(73-32)*5/9)),
        (ENSINGER_PC,), ('가공용 PC 참고값이며 FDM 출력물 값이 아닙니다. 화학적 적합성·응력균열·밀폐 성능은 별도입니다.',), ('polycarbonate', '폴리카보네이트', 'window', '투명')),
    MaterialCatalogEntry('pom_c_tecaform_ah', 'POM-C · TECAFORM AH natural', '폴리머 / 창', 'Ensinger', 'TECAFORM AH natural stock shapes', 'isotropic',
        _properties(density=_fact('density', 1410, '1.41 g/cm³ × 1000; ISO 1183'),
            youngs_modulus=_fact('youngs_modulus', 2800, 'ISO 527-2'),
            yield_strength=_fact('yield_strength', 67, 'tensile yield; ISO 527-2'),
            tensile_strength=_fact('tensile_strength', 67, 'ISO 527-2'),
            thermal_conductivity=_fact('thermal_conductivity', .39, 'ISO 22007-4'),
            thermal_expansion=_fact('thermal_expansion', 13e-5, 'ISO 11359-1/2; 23–60 °C', temperature=23, high=60, direction='longitudinal'),
            specific_heat=_fact('specific_heat', 1400, '1.4 J/(g·K) × 1000; ISO 22007-4'),
            water_absorption=_fact('water_absorption', .05, '24 h immersion; ISO 62; not humidity swelling law', temperature=23)),
        (ENSINGER_POM,), ('가공 소재 참고값입니다. 수분 흡수율은 습도별 치수 변화나 투습·누설 모델이 아닙니다.',), ('acetal', '델린', 'pom', '플라스틱')),
    MaterialCatalogEntry('pmma_extruded_sheet', 'PMMA · 압출 아크릴창', '폴리머 / 창', 'Ensinger', 'Extruded acrylic sheet', 'isotropic',
        _properties(density=_fact('density', 1190, '1.19 g/cm³ × 1000'),
            youngs_modulus=MaterialProperty(value=None, unit='MPa', basis='range', minimum=3000, maximum=3300, source_index=0, condition='ISO 527; no scalar selected'),
            tensile_strength=_fact('tensile_strength', 72, 'ISO 527; not yield strength'),
            water_absorption=_fact('water_absorption', .30, '24 h; ISO 62; not humidity expansion law')),
        (ENSINGER_PMMA,), ('탄성계수는 범위로만 확인되어 단일값을 자동 선택하지 않습니다. 충격 보호창과 압력창의 적합성은 별도입니다.',), ('acrylic', '아크릴', 'window', '투명')),
    MaterialCatalogEntry('ptfe_tecaflon_natural', 'PTFE · TECAFLON natural · 씰 참고', '씰 / 절연', 'Ensinger', 'TECAFLON PTFE natural · German stock shapes', 'nonlinear',
        _properties(density=_fact('density', 2150, '2.15 g/cm³ × 1000'),
            tensile_strength=_fact('tensile_strength', 22, 'ASTM D4894; not yield strength'),
            thermal_conductivity=_fact('thermal_conductivity', .20, 'ASTM C177'),
            thermal_expansion=_fact('thermal_expansion', 13e-5, 'ASTM D696; longitudinal 25–100 °C', temperature=25, high=100, direction='longitudinal')),
        (ENSINGER_PTFE,), ('크리프·비선형 씰 압축·누설량은 이 목록에서 해석하지 않습니다. E와 ν는 미확인입니다.',), ('테프론', 'seal', '가스켓')),
    MaterialCatalogEntry('silicone_lr3003_50', '실리콘 고무 · ELASTOSIL LR 3003/50', '씰 / 절연', 'Wacker', 'ELASTOSIL LR 3003/50 A/B · post-cured', 'nonlinear',
        _properties(density=_fact('density', 1130, '1.13 g/cm³ × 1000; cured; ISO 1183-1 A'),
            tensile_strength=_fact('tensile_strength', 10.3, 'ISO 37 type 1; cure 5 min/165 °C + post-cure 4 h/200 °C')),
        (WACKER,), ('Shore A 50은 탄성계수나 포아송 비가 아닙니다. 씰 압축·점탄성·투습성·누설 모델은 미확인입니다.',), ('silicone', 'rubber', '실리콘', '고무', 'gasket', '패킹')),
    MaterialCatalogEntry('silicon_single_crystal', 'Si · 단결정 · 방향 확인 필요', '연구 시편', 'BIPM / Hopcroft et al.', 'Natural single-crystal silicon · reference', 'anisotropic',
        _properties(density=_fact('density', 2329, 'natural-silicon reference sphere; nominal, not wafer lot measurement', basis='nominal', temperature=20),
            youngs_modulus_100=_fact('youngs_modulus_100', 130000, 'directional reference only; cannot replace cubic stiffness tensor', source=1, direction='[100]'),
            youngs_modulus_110=_fact('youngs_modulus_110', 169000, 'directional reference only', source=1, direction='[110]'),
            youngs_modulus_111=_fact('youngs_modulus_111', 188000, 'directional reference only', source=1, direction='[111]')),
        (SI_DENSITY, SI_ELASTIC), ('등방성 E·ν와 항복강도는 비워 둡니다. 웨이퍼 방향·도핑·표면 결함·취성 파괴·고정구는 별도 확인이 필요합니다.', '현재 등방성 인장 솔버에 자동 적용하지 않습니다. 연구 솔버나 다른 작업은 실행하지 않습니다.'), ('wafer', '웨이퍼', 'silicon', 'si', '실리콘 웨이퍼')),
)


def get_catalog_entry(catalog_id: str) -> MaterialCatalogEntry | None:
    return next((entry for entry in CATALOG if entry.catalog_id == catalog_id), None)


def search_catalog(query: str = '', category: str | None = None) -> tuple[MaterialCatalogEntry, ...]:
    tokens = unicodedata.normalize('NFKC', query).casefold().split()
    def matches(token, text):
        # Short material codes (PC, Si, PLA) must not match words such as plate.
        if token.isascii() and token.isalpha() and len(token) <= 3:
            return re.search(r'(?<![a-z0-9])'+re.escape(token)+r'(?![a-z0-9])', text) is not None
        return token in text
    return tuple(entry for entry in CATALOG if (not category or entry.category == category) and all(
        matches(token, unicodedata.normalize('NFKC', ' '.join((entry.catalog_id, entry.name, entry.category,
            entry.manufacturer, entry.designation, *entry.aliases))).casefold()) for token in tokens))


def categories() -> tuple[str, ...]:
    return tuple(dict.fromkeys(entry.category for entry in CATALOG))


def material_from_catalog(catalog_id: str):
    from .models import Material
    entry = get_catalog_entry(catalog_id)
    if entry is None:
        raise ValueError('재질 목록 ID를 찾을 수 없습니다: '+catalog_id)
    properties = dict(entry.properties)
    values = {key: properties[key].value for key in UNITS}
    return Material(name=entry.name, **values, behavior=entry.behavior, catalog_id=entry.catalog_id,
                    provenance=entry.provenance().model_dump(mode='json'))


def format_details(entry: MaterialCatalogEntry) -> str:
    lines = [entry.name, entry.manufacturer+' · '+entry.designation,
             '모델: '+entry.behavior+' · 미확인 값은 null · 재료 성적서/씰 성능 인증 아님']
    for key, fact in entry.properties:
        value = f'{fact.minimum:g}–{fact.maximum:g}' if fact.basis == 'range' else '미확인' if fact.value is None else f'{fact.value:g}'
        title = LABELS.get(key, key)
        lines.append(f'{title}: {value} {fact.unit} [{fact.basis}]')
        conditions = [fact.condition, fact.direction]
        if fact.temperature_c is not None:
            conditions.append(f'{fact.temperature_c:g}'+(f'–{fact.temperature_max_c:g}' if fact.temperature_max_c is not None else '')+' °C')
        if any(conditions):
            lines.append('  조건: '+' · '.join(value for value in conditions if value))
    lines.extend(entry.notes)
    for source in entry.sources:
        lines.append(f'출처: {source.title} · {source.revision} · 확인 {source.checked_on}\n{source.url}')
    return '\n'.join(lines)
