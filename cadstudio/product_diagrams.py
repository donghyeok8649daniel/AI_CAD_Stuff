"""Primary-source terminal references for exact non-MCU electrical products.

These immutable data records draw native vector terminal blocks; they neither
download artwork nor implement device behavior. ``side``/``position`` are
schematic layout coordinates, not measured PCB or connector coordinates.
Manufacturers' physical numbers are only printed when the source verifies them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


ProductTerminalKind = Literal["signal", "power", "ground", "other"]
SOURCE_CHECKED_DATE = "2026-10-03"


@dataclass(frozen=True, slots=True)
class ProductTerminal:
    key: str
    label: str
    kind: ProductTerminalKind
    side: Literal["left", "right"]
    position: int
    functions: tuple[str, ...] = ()
    # A signal's supply-dependent voltage reference is independent of any
    # abstract motor/load DC branch rating. Bounds describe that reference's
    # supported supply range, never a fixed GPIO output voltage or permission.
    signal_voltage_reference: str = ""
    signal_voltage_min_v: float | None = None
    signal_voltage_max_v: float | None = None
    signal_level_note: str = ""
    signal_level_note_en: str = ""


@dataclass(frozen=True, slots=True)
class ProductDiagram:
    catalog_id: str
    model: str
    source_url: str
    terminals: tuple[ProductTerminal, ...]
    note: str = ""
    note_en: str = ""
    evidence: str = ""


AS5600_SOURCE = "https://look.ams-osram.com/m/7059eac7531a86fd/original/AS5600-DS000365.pdf"
POLOLU_DRV8833_SOURCE = "https://www.pololu.com/product/2130"
POLOLU_4755_SOURCE = "https://www.pololu.com/product/4755"
VISHAY_1N5819_SOURCE = "https://www.vishay.com/docs/88525/1n5817.pdf"

_NOTE_KO = (
    "제조사에서 확인한 단자 기능을 자체 벡터 모식도로 표시합니다. 치수가 있는 "
    "PCB/풋프린트나 내부 회로 시뮬레이션이 아닙니다. 전원·신호·참조 단자를 "
    "자동 연결하거나 전기적으로 같은 노드로 가정하지 않습니다. "
    f"공식 자료 확인일 {SOURCE_CHECKED_DATE}."
)
_NOTE_EN = (
    "Manufacturer-verified terminal functions, drawn as an original vector "
    "reference. Not a dimensioned PCB/footprint or internal-circuit simulation. "
    "Supply, signal and reference terminals are not automatically wired or "
    "assumed to be the same electrical node. "
    f"Official source checked {SOURCE_CHECKED_DATE}."
)


PRODUCT_DIAGRAMS: tuple[ProductDiagram, ...] = (
    ProductDiagram(
        "ams_as5600_asot", "ams AS5600-ASOT (SOIC-8 IC)", AS5600_SOURCE,
        (
            ProductTerminal("VDD5V", "1 · VDD5V", "power", "left", 0,
                            ("5 V mode supply",)),
            ProductTerminal("VDD3V3", "2 · VDD3V3", "power", "left", 1,
                            ("3.3 V mode supply / 5 V mode regulator bypass",)),
            ProductTerminal("OUT", "3 · OUT", "signal", "left", 2,
                            ("Analog/PWM output",),
                            signal_level_note="OUT 출력은 전원 모드·출력 설정에 따라 달라집니다. MCU 입력 허용 전압과 아날로그/PWM 설정을 확인하세요.",
                            signal_level_note_en="OUT depends on supply mode and output configuration. Verify MCU input limits and analog/PWM configuration."),
            ProductTerminal("GND", "4 · GND", "ground", "left", 3,
                            ("Ground",)),
            ProductTerminal("DIR", "8 · DIR", "signal", "right", 0,
                            ("Direction polarity input",)),
            ProductTerminal("SCL", "7 · SCL", "signal", "right", 1,
                            ("I2C clock input", "External pull-up conditions",),
                            signal_level_note="I2C 풀업 전압과 MCU/센서의 입력 허용 전압을 확인하세요. 전원 모드만으로 신호 호환을 확정하지 않습니다.",
                            signal_level_note_en="Verify I2C pull-up voltage and MCU/sensor input limits. Supply mode alone does not establish signal compatibility."),
            ProductTerminal("SDA", "6 · SDA", "signal", "right", 2,
                            ("I2C data I/O", "External pull-up conditions",),
                            signal_level_note="I2C 풀업 전압과 MCU/센서의 입력 허용 전압을 확인하세요. 전원 모드만으로 신호 호환을 확정하지 않습니다.",
                            signal_level_note_en="Verify I2C pull-up voltage and MCU/sensor input limits. Supply mode alone does not establish signal compatibility."),
            ProductTerminal("PGO", "5 · PGO", "signal", "right", 3,
                            ("Programming option input", "Internal pull-up",)),
        ),
        "SOIC-8 칩의 위에서 본 핀 번호입니다. 출처가 불분명한 AS5600 모듈의 "
        "헤더 배치로 사용하지 마세요. 5 V 모드에서 VDD3V3는 레귤레이터 바이패스 "
        "핀이고, 3.3 V 모드에서 두 전원 핀을 연결하는 방식이 다릅니다. 데이터시트의 "
        "전원·바이패스·I2C 풀업 회로를 따로 확인하세요. " + _NOTE_KO,
        "SOIC-8 IC top-view pin numbers, not the header layout of an unknown "
        "AS5600 module. VDD3V3 is a regulator bypass in 5 V mode; the two supply "
        "pins use a different connection in 3.3 V mode. Consult the datasheet "
        "supply, decoupling and I2C pull-up circuit before wiring. " + _NOTE_EN,
        "AS5600 DS000365 v1-06, Figure 3/4 pin assignment and Figure 45 ordering; "
        "Application Information supply modes. AS5600-ASOT is SOIC-8.",
    ),
    ProductDiagram(
        "pololu_2130", "Pololu #2130 DRV8833 Dual Motor Driver Carrier",
        POLOLU_DRV8833_SOURCE,
        (
            ProductTerminal("VIN", "VIN · motor supply", "power", "left", 0,
                            ("Reverse-protected motor supply input",)),
            ProductTerminal("VMM", "VMM · protected motor rail", "power", "left", 1,
                            ("Motor rail after reverse-protection MOSFET",)),
            ProductTerminal("GND", "GND · supply/control ground", "ground", "left", 2,
                            ("Common supply/control ground",)),
            ProductTerminal("AIN1", "AIN1", "signal", "left", 3,
                            ("Channel A control input", "PWM-capable input",)),
            ProductTerminal("AIN2", "AIN2", "signal", "left", 4,
                            ("Channel A control input", "PWM-capable input",)),
            ProductTerminal("BIN1", "BIN1", "signal", "left", 5,
                            ("Channel B control input", "PWM-capable input",)),
            ProductTerminal("BIN2", "BIN2", "signal", "left", 6,
                            ("Channel B control input", "PWM-capable input",)),
            ProductTerminal("nSLEEP", "SLP / nSLEEP", "signal", "left", 7,
                            ("Active-low sleep input", "Board pull-up",)),
            ProductTerminal("AOUT1", "AOUT1", "power", "right", 0,
                            ("Channel A half-bridge 1 output",)),
            ProductTerminal("AOUT2", "AOUT2", "power", "right", 1,
                            ("Channel A half-bridge 2 output",)),
            ProductTerminal("BOUT1", "BOUT1", "power", "right", 2,
                            ("Channel B half-bridge 1 output",)),
            ProductTerminal("BOUT2", "BOUT2", "power", "right", 3,
                            ("Channel B half-bridge 2 output",)),
            ProductTerminal("nFAULT", "FLT / nFAULT", "signal", "right", 4,
                            ("Open-drain active-low fault output", "External pull-up required",),
                            signal_level_note="오픈 드레인 출력에는 외부 풀업이 필요합니다. 풀업 전압과 MCU 입력 허용 전압을 확인하세요.",
                            signal_level_note_en="The open-drain output requires an external pull-up. Verify pull-up voltage and MCU input limits."),
            ProductTerminal("AISEN", "AISEN · current sense A", "other", "right", 5,
                            ("Grounded by default", "Board modification for current limit",)),
            ProductTerminal("BISEN", "BISEN · current sense B", "other", "right", 6,
                            ("Grounded by default", "Board modification for current limit",)),
        ),
        "Pololu #2130 캐리어의 제조사 단자명입니다. 15개 단자 기능을 논리 순서로 "
        "그리며 16개 헤더 패드의 물리 순서·번호를 주장하지 않습니다. 여러 GND 패드는 "
        "같은 접지 기능으로 표시합니다. AISEN/BISEN은 기본 접지 연결이며 전류 제한을 "
        "사용하려면 보드 수정이 필요합니다. 전압·전류 제한과 H 브리지/PWM 동작은 "
        "이번 단자 모식도에서 해석하지 않습니다. " + _NOTE_KO,
        "Manufacturer terminal names of the exact Pololu #2130 carrier. Fifteen "
        "named terminal functions in logical order, not a claim about the "
        "physical order/numbers of sixteen header pads. Multiple GND pads share "
        "the ground function. AISEN/BISEN are grounded by default and require "
        "board modifications for current limiting. Device voltage/current "
        "limits, H-bridge switching and PWM behavior are not simulated. " + _NOTE_EN,
        "Pololu #2130 product page: Using the motor driver, Pinout table, "
        "Current limiting, and carrier schematic. Exact carrier, not TI IC package.",
    ),
    ProductDiagram(
        "pololu_4755", "Pololu #4755 100:1 37D 12 V gearmotor with encoder",
        POLOLU_4755_SOURCE,
        (
            ProductTerminal("MOTOR_RED", "Red · motor terminal", "power", "left", 0,
                            ("One brushed motor terminal", "Polarity selects direction",)),
            ProductTerminal("MOTOR_BLACK", "Black · motor terminal", "power", "left", 1,
                            ("Other brushed motor terminal", "Polarity selects direction",)),
            ProductTerminal("ENCODER_VCC", "Blue · encoder Vcc", "power", "left", 2,
                            ("Encoder supply 3.5-20 V",)),
            ProductTerminal("ENCODER_GND", "Green · encoder GND", "ground", "left", 3,
                            ("Encoder ground",)),
            ProductTerminal("ENCODER_A", "Yellow · encoder A", "signal", "right", 0,
                            ("Quadrature A output", "Output swings 0 to encoder Vcc",),
                            signal_voltage_reference="encoder_vcc", signal_voltage_min_v=3.5,
                            signal_voltage_max_v=20.0,
                            signal_level_note="엔코더 전원은 별도 3.5–20 V이고 A/B 출력은 엔코더 Vcc까지 올라갑니다. 모터 정격 전압으로 추정하지 말고 MCU 입력 허용 전압·레벨 변환을 확인하세요.",
                            signal_level_note_en="The encoder uses a separate 3.5–20 V supply and A/B outputs swing to encoder Vcc. Do not infer it from the motor rating; verify MCU input limits and level translation."),
            ProductTerminal("ENCODER_B", "White · encoder B", "signal", "right", 1,
                            ("Quadrature B output", "Output swings 0 to encoder Vcc",),
                            signal_voltage_reference="encoder_vcc", signal_voltage_min_v=3.5,
                            signal_voltage_max_v=20.0,
                            signal_level_note="엔코더 전원은 별도 3.5–20 V이고 A/B 출력은 엔코더 Vcc까지 올라갑니다. 모터 정격 전압으로 추정하지 말고 MCU 입력 허용 전압·레벨 변환을 확인하세요.",
                            signal_level_note_en="The encoder uses a separate 3.5–20 V supply and A/B outputs swing to encoder Vcc. Do not infer it from the motor rating; verify MCU input limits and level translation."),
        ),
        "#4755의 공식 전선 색상표를 사용하며 커넥터 핀 번호·물리 순서를 추정하지 "
        "않습니다. 빨강/검정은 고정 +/− 표시가 아닌 모터 두 단자이며 극성에 따라 "
        "회전 방향이 바뀝니다. 엔코더 전원은 모터 전원과 별개입니다. 출력 A/B는 "
        "엔코더 Vcc까지 올라가므로 3.3 V MCU와 자동 호환된다고 판단하지 않습니다. "
        "파형·회전·엔코더 카운트를 시뮬레이션하지 않습니다. " + _NOTE_KO,
        "Exact #4755 official wire-color table; connector pin numbers and physical "
        "lead order are not inferred. Red/black are two bidirectional motor "
        "terminals, not fixed +/− supply designations. Encoder power is separate "
        "from motor power. A/B outputs swing to encoder Vcc, so 3.3 V MCU "
        "compatibility is not assumed. Waveforms, rotation and encoder counts "
        "are not simulated. " + _NOTE_EN,
        "Pololu #4755 product page, Using the Encoder: six-wire color/function "
        "table and separate encoder Vcc/output conditions.",
    ),
    ProductDiagram(
        "vishay_1n5819", "Vishay 1N5819 (DO-204AL/DO-41)", VISHAY_1N5819_SOURCE,
        (
            ProductTerminal("ANODE", "A · anode", "other", "left", 0,
                            ("Anode lead",)),
            ProductTerminal("CATHODE", "K · cathode (band)", "other", "right", 0,
                            ("Cathode lead identified by color band",)),
        ),
        "DO-204AL/DO-41 패키지의 띠 표시 쪽이 캐소드입니다. 제조사에서 핀 1/2를 "
        "정하지 않은 리드에 임의 번호를 붙이지 않습니다. 단자와 극성 참고용이며 "
        "순방향 전압·역누설·열·정류 동작을 계산하지 않습니다. " + _NOTE_KO,
        "The color-band end of the DO-204AL/DO-41 package is the cathode. "
        "No invented pin 1/2 numbering for the unnumbered leads. A polarity "
        "reference, not a forward-drop, reverse-leakage, thermal or rectifier "
        "simulation. " + _NOTE_EN,
        "Vishay 1N5817/1N5818/1N5819 document 88525, Mechanical Data: "
        "Polarity: color band denotes cathode end; DO-204AL/DO-41 package.",
    ),
)
_BY_ID = {diagram.catalog_id: diagram for diagram in PRODUCT_DIAGRAMS}


def product_diagram(catalog_id: str) -> ProductDiagram | None:
    """Return an exact supported terminal map; unknown/model-family IDs get None."""
    return _BY_ID.get(catalog_id)


def available_product_diagrams() -> tuple[ProductDiagram, ...]:
    """Offline, immutable reference records with no GUI or numerical dependency."""
    return PRODUCT_DIAGRAMS
