"""Small offline index of source-backed mechanical and power-connection facts.

Every numeric value is tied to an exact SKU or a named standards reference.
Catalog current limits are never inferred to be a circuit's operating current.
Unverified panel cutouts, printed-part fits, and mechanical loads stay unset.
"""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata


RETRIEVED_ON = "2026-10-03"


@dataclass(frozen=True, slots=True)
class SourceRef:
    title: str
    url: str
    revision: str = ""
    retrieved_on: str = RETRIEVED_ON


@dataclass(frozen=True, slots=True)
class SpecFact:
    label: str
    value: float | str
    unit: str
    qualifier: str = "documented"
    condition: str = ""

    def describe(self) -> str:
        value = f"{self.value:g}" if isinstance(self.value, (int, float)) else self.value
        suffix = f" {self.unit}" if self.unit else ""
        condition = f" · 조건: {self.condition}" if self.condition else ""
        return f"{self.label}: {value}{suffix} [{self.qualifier}]{condition}"


@dataclass(frozen=True, slots=True)
class WireSpec:
    awg: int
    stranding: str
    insulation_od_mm: float | None
    dcr_ohm_per_1000ft: float
    free_air_current_a: float
    free_air_condition: str = "단일 도체, 자유공기, 주변 30 °C"

    @property
    def dcr_ohm_per_m(self) -> float:
        return self.dcr_ohm_per_1000ft / 304.8


@dataclass(frozen=True, slots=True)
class HoleSpec:
    thread: str
    fit: str
    diameter_mm: float
    standard: str
    source_url: str


@dataclass(frozen=True, slots=True)
class HeadSpec:
    thread: str
    diameter_mm: float
    standard: str
    source_url: str


@dataclass(frozen=True, slots=True)
class MechanicalCatalogEntry:
    catalog_id: str
    category: str
    manufacturer: str
    model: str
    summary: str
    sources: tuple[SourceRef, ...]
    exact_skus: tuple[str, ...] = ()
    ratings: tuple[SpecFact, ...] = ()
    dimensions: tuple[SpecFact, ...] = ()
    notes: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    wire_spec: WireSpec | None = None
    hole_spec: HoleSpec | None = None
    head_spec: HeadSpec | None = None

    @property
    def source_url(self) -> str:
        return self.sources[0].url

    @property
    def display_name(self) -> str:
        return f"{self.manufacturer} {self.model}"


JST_XH = SourceRef("JST XH connector catalog", "https://www.jst-mfg.com/product/pdf/eng/eXH.pdf")
JST_VH = SourceRef("JST VH connector product profile", "https://www.jst-mfg.com/product/index.php?lang=2&series=262")
JST_VH_PDF = SourceRef("JST VH connector catalog", "https://www.jst-mfg.com/product/pdf/eng/eVH.pdf")
MOLEX_HEADER = SourceRef("Molex 39281023 product", "https://www.molex.com/en-us/products/part-detail/39281023")
MOLEX_HOUSING = SourceRef("Molex 39012020 product", "https://www.molex.com/en-us/products/part-detail/39012020")
PHOENIX_PLUG = SourceRef("Phoenix Contact 1757019 product", "https://www.phoenixcontact.com/en-us/products/pcb-plug-mstb-25-2-st-508-1757019")
PHOENIX_HEADER = SourceRef("Phoenix Contact 1759017 product", "https://www.phoenixcontact.com/en-us/products/pcb-header-mstb-25-2-g-508-1759017")
KYCON_JACK = SourceRef("Kycon KLDLX-0202-x drawing", "https://www.kycon.com/Pub_Eng_Draw/KLDLX-0202-x.pdf", "A4, 2026-06-11")
SWITCHCRAFT_JACK = SourceRef("Switchcraft 712A product", "https://www.switchcraft.com/dc-power-jack-0-100-2-5mm-pin-solder-lugs-termination/712a/")
SWITCHCRAFT_DRAWING = SourceRef("Switchcraft 712A customer drawing", "https://www.switchcraft.com/assets/1/24/712A%20722A%20732A_CD.PDF", "J, 2021-06-11")
ISO_273 = SourceRef("ISO 273:1979 record", "https://www.iso.org/standard/4183.html", "1979")
ISO_4762 = SourceRef("ISO 4762:2004 record", "https://www.iso.org/standard/34460.html", "2004")
BOSSARD_SURFACE_PAGE = SourceRef(
    "Bossard surface-pressure technical page",
    "https://www.bossard.com/us-en/knowledge-hub/resources/technical-information/"
    "surface-pressure-in-fastening-connections/",
)
BOSSARD_SURFACE_PDF = SourceRef(
    "Bossard ISO 273 hole and ISO 4762 head dimensions, pp. 54-55",
    "https://assets.eu.ctfassets.net/0vp0u5uh75zd/7MM4CVEWakvMoaUSg5YsPX/"
    "c4b6542d94541de714325d3d8ebb7dc7/"
    "053_056_Surface_pressure_mounted_Fastening_EN_01_2025.pdf",
    "01-2025",
)


def _wire(model: str, awg: int, stranding: str, od: float | None, dcr: float,
          free_air_a: float) -> MechanicalCatalogEntry:
    spec = WireSpec(awg, stranding, od, dcr, free_air_a)
    return MechanicalCatalogEntry(
        f"belden_{model}", "전선", "Belden", model,
        f"{awg} AWG 주석도금 동선. 명목 DC 저항으로 전압 강하를 추정할 수 있습니다.",
        (SourceRef(f"Belden {model} product", f"https://www.belden.com/products/cable/electronic-wire-cable/lead-wire-hook-up-wire/{model}"),),
        exact_skus=(model,), wire_spec=spec,
        notes=("자유공기 단일 도체 전류는 하네스·케이스·커넥터의 허용 전류가 아닙니다.",
               "저항은 명목값이며 도체 온도에 따른 증가는 별도로 평가해야 합니다."),
        aliases=(f"AWG{awg}", f"{awg} AWG", "전원선", "배선"),
    )


def _clearance(thread: str, diameter: float) -> MechanicalCatalogEntry:
    hole = HoleSpec(thread, "medium", diameter, "ISO 273:1979", BOSSARD_SURFACE_PAGE.url)
    return MechanicalCatalogEntry(
        f"iso273_medium_{thread.lower()}", "관통홀 규격", "Bossard", f"ISO 273 medium · {thread}",
        f"{thread} 볼트용 medium 관통홀 호칭 Ø{diameter:g} mm.",
        (BOSSARD_SURFACE_PAGE, BOSSARD_SURFACE_PDF, ISO_273),
        dimensions=(SpecFact("관통홀 호칭 지름", diameter, "mm", "ISO 273 medium"),),
        notes=("나사산 가공용 탭 하공이 아닙니다.",
               "FDM 프린트의 실제 치수 편차나 사용자 간극 0/0.2 mm를 이 표준 치수에 자동 더하지 않습니다."),
        aliases=(thread, "clearance hole", "통과홀", "볼트 구멍"),
        hole_spec=hole,
    )


def _head(thread: str, diameter: float) -> MechanicalCatalogEntry:
    head = HeadSpec(thread, diameter, "ISO 4762:2004", BOSSARD_SURFACE_PAGE.url)
    return MechanicalCatalogEntry(
        f"iso4762_head_{thread.lower()}", "나사 머리", "Bossard", f"ISO 4762 socket head · {thread}",
        f"{thread} 소켓머리 캡스크루의 머리 외경 dK 참고 치수.",
        (BOSSARD_SURFACE_PAGE, BOSSARD_SURFACE_PDF, ISO_4762),
        dimensions=(SpecFact("머리 외경 dK", diameter, "mm", "source dimension"),),
        notes=("머리 외경은 카운터보어의 완성 치수나 공차가 아닙니다.",
               "재질·강도 등급·체결 토크·기계 하중은 이 항목에서 지정하지 않습니다."),
        aliases=(thread, "socket head", "cap screw", "육각소켓머리", "카운터보어"),
        head_spec=head,
    )


CATALOG: tuple[MechanicalCatalogEntry, ...] = (
    MechanicalCatalogEntry(
        "jst_xh_2", "전원 커넥터", "JST", "XH 2극 · B2B-XH-A",
        "2.50 mm 피치 상향 PCB 헤더와 정확한 결합 하우징·AWG 22용 단자.",
        (JST_XH,), exact_skus=("B2B-XH-A", "XHP-2", "SXH-001T-P0.6"),
        ratings=(SpecFact("계열 전류 정격", 3, "A AC/DC", "conditional rating", "AWG 22 사용"),
                 SpecFact("계열 전압 정격", 250, "V AC/DC", "rated")),
        dimensions=(SpecFact("접점 피치", 2.5, "mm"),
                    SpecFact("2극 헤더 도면 B", 7.4, "mm"),
                    SpecFact("조립 기판 높이", 9.8, "mm"),
                    SpecFact("포스트 한 변", 0.64, "mm"),
                    SpecFact("적용 PCB 두께", 1.6, "mm")),
        notes=("도면 B는 제조사 도면의 변수이며 전체 바운딩 박스로 재해석하지 않습니다.",
               "JST는 PCB 홀 크기를 기판 재질과 드릴 방법에 따라 검토하라고 안내합니다."),
        aliases=("JST XH", "2.5mm", "2핀", "커넥터"),
    ),
    MechanicalCatalogEntry(
        "jst_vh_2", "전원 커넥터", "JST", "VH 2극 · B2P-VH",
        "3.96 mm 피치 표준형 상향 PCB 헤더와 결합 하우징·AWG 16용 단자.",
        (JST_VH, JST_VH_PDF), exact_skus=("B2P-VH", "VHR-2N", "SVH-41T-P1.1"),
        ratings=(SpecFact("계열 전류 정격", 10, "A AC/DC", "conditional rating", "AWG 16 및 표준형 헤더"),
                 SpecFact("계열 전압 정격", 250, "V AC/DC", "rated")),
        dimensions=(SpecFact("접점 피치", 3.96, "mm"),
                    SpecFact("2극 헤더 도면 A", 3.96, "mm"),
                    SpecFact("2극 헤더 도면 B", 7.86, "mm"),
                    SpecFact("포스트 폭", 1.14, "mm")),
        notes=("측면형 B2PS-VH는 다른 형상입니다.",
               "차폐형 헤더의 AWG 18 조건 7 A를 이 표준형 조합의 정격으로 섞지 않습니다."),
        aliases=("JST VH", "3.96mm", "2핀", "전원 커넥터"),
    ),
    MechanicalCatalogEntry(
        "molex_minifit_jr_2", "전원 커넥터", "Molex", "Mini-Fit Jr. 2극 · 39281023",
        "2열 2극 수직 PCB 헤더와 리셉터클 하우징. crimp 단자는 별도 선택해야 합니다.",
        (MOLEX_HEADER, MOLEX_HOUSING), exact_skus=("39281023", "39012020"),
        ratings=(SpecFact("헤더 접점당 최대 전류", 9, "A", "maximum", "정확한 mating 단자·전선·열 조건을 별도 확인"),
                 SpecFact("헤더 최대 전압", 600, "V", "maximum")),
        dimensions=(SpecFact("결합/PCB 피치", 4.2, "mm"),
                    SpecFact("권장 PCB 두께", 1.6, "mm"),
                    SpecFact("PCB 핀 길이", 3.5, "mm")),
        notes=("Molex 온라인 페이지는 두 품번 모두 제한된 정보만 게시합니다. 공급 상태와 상세 도면을 별도 확인하세요.",
               "9 A 최대값을 조립 하네스의 연속 운전 허용 전류로 전파하지 않습니다."),
        aliases=("Mini Fit Jr", "39-28-1023", "39-01-2020", "4.2mm"),
    ),
    MechanicalCatalogEntry(
        "phoenix_mstb_2", "전원 커넥터", "Phoenix Contact", "MSTB 2,5/2-ST-5,08 + 2-G-5,08",
        "2극 탈착 플러그 1757019와 PCB 헤더 1759017의 정확한 조합.",
        (PHOENIX_PLUG, PHOENIX_HEADER), exact_skus=("1757019", "1759017"),
        ratings=(SpecFact("공칭 전류", 12, "A", "nominal", "1757019·1759017 제품 데이터; 도체/열 조건 별도 확인"),
                 SpecFact("공칭 전압", 320, "V", "nominal", "과전압 범주·오염도별 rated voltage는 원문 확인")),
        dimensions=(SpecFact("피치", 5.08, "mm"),
                    SpecFact("플러그 폭 w", 10.16, "mm"),
                    SpecFact("플러그 높이 h", 15, "mm"),
                    SpecFact("플러그 길이 l", 18.3, "mm"),
                    SpecFact("헤더 폭 w", 10.16, "mm"),
                    SpecFact("헤더 높이 h", 11.8, "mm"),
                    SpecFact("헤더 길이 l", 12, "mm"),
                    SpecFact("헤더 설치 높이", 8.57, "mm"),
                    SpecFact("헤더 핀 단면", "1 × 1", "mm"),
                    SpecFact("PCB 홀 지름", 1.4, "mm"),
                    SpecFact("플러그 허용 도체 단면적", "0.2–2.5", "mm²"),
                    SpecFact("피복 벗김 길이", 7, "mm"),
                    SpecFact("플러그 나사 체결 토크", "0.5–0.6", "N·m")),
        notes=("플러그/헤더는 부하 또는 전압이 걸린 상태에서 연결·분리하지 않습니다.",
               "두 극의 +/리턴 배정은 제조사 치수가 아니라 설계 회로에서 결정합니다."),
        aliases=("Phoenix", "terminal block", "단자대", "5.08mm", "COMBICON"),
    ),
    MechanicalCatalogEntry(
        "kycon_kldlx_a", "패널 DC 잭", "Kycon", "KLDLX-0202-A",
        "우각 패널 장착 DC 잭, 센터핀 2.0 mm.",
        (KYCON_JACK,), exact_skus=("KLDLX-0202-A",),
        ratings=(SpecFact("정격 전류", 5, "A", "rated", "Kycon KLDLX-0202-A 도면"),
                 SpecFact("정격 전압", 24, "V DC", "rated"),
                 SpecFact("접점 저항 최대", 30, "mΩ", "maximum")),
        dimensions=(SpecFact("센터핀 지름", 2, "mm"),
                    SpecFact("잠금 나사", "M8×0.75", ""),
                    SpecFact("권장 최소 패널 두께", 1.5, "mm"),
                    SpecFact("동봉 와셔 외경", 10.9, "mm"),
                    SpecFact("동봉 와셔 내경", 8.1, "mm")),
        notes=("패널 가공 구멍 지름은 확인되지 않았습니다. 와셔 내경 Ø8.1 mm를 cutout으로 사용하지 마세요.",
               "센터핀 극성은 부품이 지정하지 않습니다."),
        aliases=("DC jack", "barrel jack", "2.0mm", "전원 잭"),
    ),
    MechanicalCatalogEntry(
        "kycon_kldlx_b", "패널 DC 잭", "Kycon", "KLDLX-0202-B",
        "우각 패널 장착 DC 잭, 센터핀 2.5 mm.",
        (KYCON_JACK,), exact_skus=("KLDLX-0202-B",),
        ratings=(SpecFact("정격 전류", 5, "A", "rated", "Kycon KLDLX-0202-B 도면"),
                 SpecFact("정격 전압", 24, "V DC", "rated"),
                 SpecFact("접점 저항 최대", 30, "mΩ", "maximum")),
        dimensions=(SpecFact("센터핀 지름", 2.5, "mm"),
                    SpecFact("잠금 나사", "M8×0.75", ""),
                    SpecFact("권장 최소 패널 두께", 1.5, "mm"),
                    SpecFact("동봉 와셔 외경", 10.9, "mm"),
                    SpecFact("동봉 와셔 내경", 8.1, "mm")),
        notes=("패널 가공 구멍 지름은 확인되지 않았습니다. 와셔 내경 Ø8.1 mm를 cutout으로 사용하지 마세요.",
               "센터핀 극성은 부품이 지정하지 않습니다."),
        aliases=("DC jack", "barrel jack", "2.5mm", "전원 잭"),
    ),
    MechanicalCatalogEntry(
        "switchcraft_712a", "패널 DC 잭", "Switchcraft", "712A",
        "센터핀 2.5 mm 납땜 러그 패널 DC 잭.",
        (SWITCHCRAFT_JACK, SWITCHCRAFT_DRAWING), exact_skus=("712A",),
        ratings=(SpecFact("정격 전류", 5, "A", "rated", "712A 제품 페이지"),
                 SpecFact("정격 전압", 24, "V", "rated")),
        dimensions=(SpecFact("센터핀 지름", 2.5, "mm"),
                    SpecFact("도면 전면 외경", 11, "mm", "reference"),
                    SpecFact("도면 본체 길이", 20.8, "mm", "reference"),
                    SpecFact("장착 나사", "5/16-32 NEF 2A", "", "reference")),
        notes=("고객 도면은 치수를 참고용이라고 명시합니다.",
               "너트 마무리 토크는 손으로 조인 후 수동 공구로 8–10 lb-in이며 전동/충격 공구는 권장되지 않습니다.",
               "절연 와셔 유무에 따른 패널 cutout은 자동 지정하지 않습니다."),
        aliases=("DC jack", "barrel jack", "2.5mm", "전원 잭"),
    ),
    _wire("9923", 24, "7×32", None, 28.7, 5),
    _wire("9921", 22, "7×30", 1.6, 18.1, 11),
    _wire("9919", 20, "7×28", 1.8, 11.2, 11),
    _wire("9918", 18, "16×30", 2.0, 7.15, 20),
    _wire("9916", 16, "26×30", 2.3, 4.44, 28.8),
    _wire("8916", 14, "41×30", None, 2.7, 39),
    _clearance("M4", 4.5),
    _clearance("M5", 5.5),
    _clearance("M6", 6.6),
    _clearance("M8", 9.0),
    _head("M4", 7.0),
    _head("M5", 8.5),
    _head("M6", 10.0),
    _head("M8", 13.0),
)

_BY_ID = {entry.catalog_id: entry for entry in CATALOG}


def get_catalog_entry(catalog_id: str) -> MechanicalCatalogEntry | None:
    return _BY_ID.get(catalog_id)


def categories() -> tuple[str, ...]:
    return tuple(dict.fromkeys(entry.category for entry in CATALOG))


def _normal(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def search_catalog(query: str = "", category: str | None = None) -> tuple[MechanicalCatalogEntry, ...]:
    tokens = _normal(query).split()
    matches = []
    for entry in CATALOG:
        if category and entry.category != category:
            continue
        haystack = _normal(" ".join((entry.category, entry.manufacturer, entry.model,
                                     entry.summary, *entry.exact_skus, *entry.aliases)))
        if all(token in haystack for token in tokens):
            matches.append(entry)
    return tuple(matches)


def get_clearance_hole(thread: str, fit: str = "medium") -> HoleSpec | None:
    if fit.casefold() != "medium":
        return None
    entry = _BY_ID.get(f"iso273_medium_{thread.strip().lower()}")
    return entry.hole_spec if entry else None


def get_socket_head(thread: str) -> HeadSpec | None:
    entry = _BY_ID.get(f"iso4762_head_{thread.strip().lower()}")
    return entry.head_spec if entry else None


def format_ai_spec(entry: MechanicalCatalogEntry) -> str:
    """Copyable reference, including limits and unknowns, without inferred loads."""
    lines = [f"[공식 출처 기반 설계 참고] {entry.display_name}",
             f"분류: {entry.category}", f"설명: {entry.summary}"]
    if entry.exact_skus:
        lines.append("정확한 품번: " + ", ".join(entry.exact_skus))
    if entry.ratings:
        lines.append("정격·한계 (조건을 유지할 것):")
        lines.extend(f"- {fact.describe()}" for fact in entry.ratings)
    if entry.dimensions:
        lines.append("기구·장착 치수:")
        lines.extend(f"- {fact.describe()}" for fact in entry.dimensions)
    if entry.wire_spec:
        wire = entry.wire_spec
        lines.extend(("전선 자료:",
                      f"- {wire.awg} AWG, 연선 {wire.stranding}, 피복 외경 " +
                      (f"{wire.insulation_od_mm:g} mm" if wire.insulation_od_mm is not None else "미확인"),
                      f"- 명목 도체 DC 저항: {wire.dcr_ohm_per_1000ft:g} Ω/1000 ft "
                      f"({wire.dcr_ohm_per_m:.6g} Ω/m, 단위 환산)",
                      f"- 제조사 자유공기 전류: {wire.free_air_current_a:g} A "
                      f"[{wire.free_air_condition}; 하네스 허용 전류가 아님]"))
    if entry.hole_spec:
        lines.append(f"선택 관통홀: {entry.hole_spec.thread}, {entry.hole_spec.fit}, "
                     f"Ø{entry.hole_spec.diameter_mm:g} mm ({entry.hole_spec.standard})")
    if entry.head_spec:
        lines.append(f"소켓머리 외경: {entry.head_spec.thread}, "
                     f"dK {entry.head_spec.diameter_mm:g} mm ({entry.head_spec.standard})")
    if entry.notes:
        lines.append("적용 조건·미확인 항목:")
        lines.extend(f"- {note}" for note in entry.notes)
    lines.append("공식 출처:")
    lines.extend(f"- {source.title}: {source.url} "
                 f"(확인 {source.retrieved_on}" +
                 (f", 판 {source.revision}" if source.revision else "") + ")"
                 for source in entry.sources)
    lines.append("실제 부하 전류, 극성, 패널 cutout, FDM 공차 및 기계 하중은 이 자료에서 자동 결정하지 않는다.")
    return "\n".join(lines)


def format_details(entry: MechanicalCatalogEntry) -> str:
    return format_ai_spec(entry)
