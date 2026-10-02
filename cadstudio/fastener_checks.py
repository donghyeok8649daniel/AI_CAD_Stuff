"""Narrow, source-backed preliminary check for static axial bolt tension.

This is not a joint, plastic-thread, preload, shear, bending or fatigue model.
Nothing is inferred from CAD geometry or from the machine's unspecified load.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


SOURCE_PAGE = (
    "https://www.bossard.com/ch-en/knowledge-hub/resources/technical-information/"
    "screws-property-class-04-to-12/"
)
SOURCE_PDF = (
    "https://assets.eu.ctfassets.net/0vp0u5uh75zd/1VPwGxSRcAQdDRArMtTqeY/"
    "8fe01cf6ef692e134b45f895fb69fe97/"
    "012_016_Screws_property_class46_Fastening_EN_01_2025.pdf"
)
PITCH_SOURCE_PDF = (
    "https://assets.eu.ctfassets.net/0vp0u5uh75zd/2tYqENAuufvdsudjM8Qbrc/"
    "b3461eaa59c2203d3a8b9509ac24dacf/"
    "096_098_Metric_ISOthreads_Fastening_EN_01_2025.pdf"
)
SOURCE_EDITION = "Bossard 01-2025, pp. 12 and 14; ISO 898-1 coarse metric thread"
RETRIEVED_ON = "2026-10-03"


@dataclass(frozen=True, slots=True)
class BoltProofSpec:
    thread: str
    pitch_mm: float
    property_class: str
    stress_area_mm2: float
    proof_stress_mpa: float
    published_proof_load_n: float
    source_url: str = SOURCE_PDF
    pitch_source_url: str = PITCH_SOURCE_PDF
    source_page_url: str = SOURCE_PAGE
    source_edition: str = SOURCE_EDITION
    retrieved_on: str = RETRIEVED_ON

    @property
    def conservative_proof_force_n(self) -> float:
        # The printed load table is rounded; cap it at the stress calculation.
        return min(self.published_proof_load_n,
                   self.stress_area_mm2 * self.proof_stress_mpa)


# Bossard's 01-2025 ISO 898-1 coarse-pitch table, limited to four common sizes.
# Sp is the stress UNDER PROOF LOAD, not tensile strength or joint allowable load.
_SIZES = (
    ("M4", 0.7, 8.78, 5100, 7290),
    ("M5", 0.8, 14.2, 8230, 11800),
    ("M6", 1.0, 20.1, 11600, 16700),
    ("M8", 1.25, 36.6, 21200, 30400),
)
SPECS = tuple(
    BoltProofSpec(thread, pitch, strength_class, area, proof_stress, proof_load)
    for thread, pitch, area, load_88, load_109 in _SIZES
    for strength_class, proof_stress, proof_load in
    (("8.8", 580, load_88), ("10.9", 830, load_109))
)
_BY_KEY = {(spec.thread, spec.property_class): spec for spec in SPECS}


def get_bolt_proof_spec(thread: str, property_class: str = "8.8") -> BoltProofSpec | None:
    if not isinstance(thread, str) or not isinstance(property_class, str):
        return None
    return _BY_KEY.get((thread.strip().upper(), property_class.strip()))


@dataclass(frozen=True, slots=True)
class AxialBoltCheck:
    spec: BoltProofSpec
    total_axial_force_n: float
    bolt_count: int
    safety_factor: float
    actual_force_per_bolt_n: float
    factored_force_per_bolt_n: float
    factored_tensile_stress_mpa: float
    stress_utilization: float
    table_load_utilization: float
    utilization: float
    proof_margin: float
    reference_capacity_total_n: float
    within_proof_reference: bool


def check_axial_bolts(
    thread: str,
    property_class: str,
    total_axial_force_n: float,
    bolt_count: int,
    safety_factor: float,
    *,
    assume_equal_sharing: bool,
    applicable_head_geometry: bool = False,
    m8_standard_proof_variant: bool = False,
) -> AxialBoltCheck:
    """Compare user-supplied pure axial tension with a proof-load reference.

    The selected class must describe the real steel bolt. `bolt_count` assumes
    identical bolts share the external force equally. No CAD load is invented.
    """
    spec = get_bolt_proof_spec(thread, property_class)
    if spec is None:
        raise ValueError("지원하는 볼트는 8.8/10.9급 보통 피치 M4, M5, M6, M8뿐입니다.")
    if assume_equal_sharing is not True:
        raise ValueError("볼트의 균등 하중 분담 가정을 직접 확인해야 합니다.")
    if applicable_head_geometry is not True:
        raise ValueError("낮은 머리·접시머리처럼 증명하중을 낮출 수 있는 형상이 아님을 확인해야 합니다.")
    if spec.thread == "M8" and m8_standard_proof_variant is not True:
        raise ValueError("M8은 6az 용융아연도금 감소 증명하중 대상이 아님을 확인해야 합니다.")
    if (isinstance(bolt_count, bool) or not isinstance(bolt_count, int)
            or not 1 <= bolt_count <= 1_000_000):
        raise ValueError("볼트 개수는 1~1,000,000의 정수로 입력하세요.")
    for value, name, minimum in (
        (total_axial_force_n, "총 축방향 인장 하중", 0),
        (safety_factor, "안전계수", 1),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{name}은 수치로 입력하세요.")
        try:
            finite = math.isfinite(value)
        except OverflowError:
            finite = False
        invalid = not finite or (value <= 0 if minimum == 0 else value < 1)
        if invalid:
            raise ValueError(f"{name}은 {'0 초과' if minimum == 0 else '1 이상'}의 유한한 값이어야 합니다.")
    actual = float(total_axial_force_n) / bolt_count
    factored = actual * float(safety_factor)
    if not math.isfinite(factored) or factored <= 0:
        raise ValueError("하중과 안전계수의 곱이 계산 범위를 넘습니다.")
    stress = factored / spec.stress_area_mm2
    by_stress = stress / spec.proof_stress_mpa
    by_table = factored / spec.published_proof_load_n
    utilization = max(by_stress, by_table)
    if utilization <= 0:
        raise ValueError("입력 하중이 부동소수점 계산 정밀도보다 작습니다.")
    margin = 1 / utilization - 1
    if not math.isfinite(margin):
        raise ValueError("입력 하중이 부동소수점 계산 정밀도보다 작습니다.")
    capacity = bolt_count * spec.conservative_proof_force_n / safety_factor
    if not math.isfinite(capacity):
        raise ValueError("볼트 개수에 따른 참조 하중이 계산 범위를 넘습니다.")
    return AxialBoltCheck(
        spec=spec,
        total_axial_force_n=float(total_axial_force_n),
        bolt_count=bolt_count,
        safety_factor=float(safety_factor),
        actual_force_per_bolt_n=actual,
        factored_force_per_bolt_n=factored,
        factored_tensile_stress_mpa=stress,
        stress_utilization=by_stress,
        table_load_utilization=by_table,
        utilization=utilization,
        proof_margin=margin,
        reference_capacity_total_n=capacity,
        within_proof_reference=utilization <= 1,
    )


def format_axial_check(result: AxialBoltCheck, language: str = "ko") -> str:
    """A report scoped to one check; never labels the assembly as safe."""
    spec = result.spec
    if language == "en":
        state = ("within the proof reference" if result.within_proof_reference
                 else "above the proof reference")
        return "\n".join((
            "Preliminary static axial bolt tension check · not a joint safety certification",
            f"Bolt: {spec.thread}×{spec.pitch_mm:g}, property class {spec.property_class}, ISO coarse pitch",
            f"Entered total axial tensile force: {result.total_axial_force_n:g} N",
            f"{result.bolt_count} identical bolts · equal load sharing assumed · user safety factor {result.safety_factor:g}",
            f"External force per bolt: {result.actual_force_per_bolt_n:g} N",
            f"Factored force per bolt: {result.factored_force_per_bolt_n:g} N",
            f"Nominal tensile stress area As: {spec.stress_area_mm2:g} mm²",
            f"Calculated tensile stress: {result.factored_tensile_stress_mpa:.3f} MPa",
            f"Selected class proof stress Sp: {spec.proof_stress_mpa:g} MPa",
            f"Published proof load Fp: {spec.published_proof_load_n:g} N per bolt",
            f"Conservative utilization: {result.utilization:.3f} ({result.utilization * 100:.1f}%)",
            f"Margin against proof reference: {result.proof_margin * 100:.1f}% · {state}",
            f"Total external force at this reference and safety factor: {result.reference_capacity_total_n:.1f} N",
            "Scope: room-temperature ISO 898-1 class steel bolts, applicable head geometry, pure static axial tension through the threaded section only.",
            "Not checked: shear, bending, eccentricity, preload/torque, fatigue, vibration, impact, thread pull-out, nut, washer, substrate, FDM plastic, head failure, or actual load sharing.",
            "M8 bolts with 6az hot-dip galvanized threads may require a reduced proof load.",
            "Utilization at or below one does not certify the joint or machine as safe.",
            f"Source: {spec.source_edition}; checked {spec.retrieved_on}",
            spec.source_url,
            f"Coarse-pitch source: Bossard 01-2025, p. 97; {spec.pitch_source_url}",
        ))
    state = "참조 증명하중 이내" if result.within_proof_reference else "참조 증명하중 초과"
    return "\n".join((
        "정적 축방향 볼트 인장 사전 검토 · 조립체 안전 인증 아님",
        f"대상: {spec.thread}×{spec.pitch_mm:g}, 강도 등급 {spec.property_class}, ISO 보통 피치",
        f"입력 총 축방향 인장 하중: {result.total_axial_force_n:g} N",
        f"동일 볼트 {result.bolt_count}개 · 균등 하중 분담 가정 · 사용자 안전계수 {result.safety_factor:g}",
        f"실제 외력/볼트: {result.actual_force_per_bolt_n:g} N",
        f"안전계수 적용 외력/볼트: {result.factored_force_per_bolt_n:g} N",
        f"공칭 인장 유효단면적 As: {spec.stress_area_mm2:g} mm²",
        f"계산 인장응력: {result.factored_tensile_stress_mpa:.3f} MPa",
        f"8.8/10.9 등급 중 선택한 등급의 증명응력 Sp: {spec.proof_stress_mpa:g} MPa",
        f"제조사 표의 증명하중 Fp: {spec.published_proof_load_n:g} N/볼트",
        f"보수적으로 작은 기준을 사용한 이용률: {result.utilization:.3f} ({result.utilization * 100:.1f}%)",
        f"증명하중 대비 여유율: {result.proof_margin * 100:.1f}% · 판정: {state}",
        f"선택 안전계수에서 이 기준의 총 외력 한계: {result.reference_capacity_total_n:.1f} N",
        "적용 범위: 실온의 실제 ISO 898-1 등급 강재 볼트, 머리 형상이 증명하중을 낮추지 않고 나사부에 순수 정적 축인장이 작용하는 경우만.",
        "제외: 전단·굽힘·편심·프리로드/체결 토크·피로·진동·충격·나사산 뽑힘·너트·와셔·모재·FDM 플라스틱·볼트 머리 파손·하중 분배 검증.",
        "M8의 6az 용융아연도금 볼트에는 이 표와 다른 감소 증명하중이 적용될 수 있습니다.",
        "이용률이 1 이하라도 결합부나 기계 전체가 안전하다는 뜻은 아닙니다.",
        f"출처: {spec.source_edition}; 확인 {spec.retrieved_on}",
        spec.source_url,
        f"보통 피치 근거: Bossard 01-2025, p. 97; {spec.pitch_source_url}",
    ))
