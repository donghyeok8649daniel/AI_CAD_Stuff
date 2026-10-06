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
OMRON_E6B2_SOURCE = "https://www.ia.omron.com/products/family/487/specification.html"
VISHAY_1N5819_SOURCE = "https://www.vishay.com/docs/88525/1n5817.pdf"
ST_BG431_ESC_SOURCE = (
    "https://www.st.com/resource/en/user_manual/"
    "dm00564746-electronic-speed-controller-discovery-kit-for-drones-with-stm32g431cb-stmicroelectronics.pdf"
)

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
        "st_b_g431b_esc1", "ST B-G431B-ESC1 · STM32G431CB ESC", ST_BG431_ESC_SOURCE,
        (
            ProductTerminal("BAT_POS", "J5 · V+", "power", "left", 0, ("3S–6S LiPo positive input",)),
            ProductTerminal("BAT_NEG", "J6 · V−", "ground", "left", 1, ("Battery negative / return",)),
            ProductTerminal("J3_BEC_5V", "J3.1 · 5V BEC", "power", "left", 2,
                            ("5 V external-board supply; daughterboard required",)),
            ProductTerminal("J3_UART_TX", "J3.2 · UART TX", "signal", "left", 3,
                            ("USART2_TX telemetry",),
                            signal_level_note="UART 입력 허용 전압과 상대 보드의 논리 전압을 확인하세요. PWM 핀의 5 V 허용을 UART 핀에 적용하지 않습니다.",
                            signal_level_note_en="Verify UART levels for each device. The PWM input's 5 V tolerance does not establish UART compatibility."),
            ProductTerminal("J3_UART_RX", "J3.3 · UART RX", "signal", "left", 4,
                            ("USART2_RX firmware/update interface",),
                            signal_level_note="UART 입력 허용 전압과 상대 보드의 논리 전압을 확인하세요. PWM 핀의 5 V 허용을 UART 핀에 적용하지 않습니다.",
                            signal_level_note_en="Verify UART levels for each device. The PWM input's 5 V tolerance does not establish UART compatibility."),
            ProductTerminal("J3_PWM", "J3.4 · PWM IN", "signal", "left", 5,
                            ("Speed command input", "3.3 V or 5 V PWM input, per UM2516 §6.1",),
                            signal_level_note="이 핀은 속도 명령 입력이며 GPIO 전원 출력이 아닙니다. 펌웨어 설정과 PWM 타이밍을 확인하세요.",
                            signal_level_note_en="Speed-command input, not a GPIO power output. Verify firmware configuration and PWM timing."),
            ProductTerminal("J3_GND", "J3.5 · GND", "ground", "left", 6, ("PWM/UART return",)),
            # The logical CAN/J8 terminal names are verified; numerical pad
            # ordering is deliberately omitted where not independently read.
            ProductTerminal("CAN_H", "J1 · CAN H", "signal", "left", 7,
                            ("CAN transceiver differential high",),
                            signal_level_note="CAN H/L은 차동 버스 단자입니다. MCU GPIO TX/RX에 직접 연결하지 말고 트랜시버와 종단 조건을 확인하세요.",
                            signal_level_note_en="Differential CAN bus terminal, not a raw MCU GPIO TX/RX. Verify transceivers and bus termination."),
            ProductTerminal("CAN_L", "J1 · CAN L", "signal", "left", 8,
                            ("CAN transceiver differential low",),
                            signal_level_note="CAN H/L은 차동 버스 단자입니다. MCU GPIO TX/RX에 직접 연결하지 말고 트랜시버와 종단 조건을 확인하세요.",
                            signal_level_note_en="Differential CAN bus terminal, not a raw MCU GPIO TX/RX. Verify transceivers and bus termination."),
            ProductTerminal("CAN_5V", "J1 · 5V IN", "power", "left", 9,
                            ("External power CAN input 5.0–5.5 V",)),
            ProductTerminal("CAN_GND", "J1 · GND", "ground", "left", 10, ("CAN power return",)),
            ProductTerminal("MOTOR_U", "J7 · U", "power", "right", 0, ("Switched 3-phase motor output U",)),
            ProductTerminal("MOTOR_V", "J7 · V", "power", "right", 1, ("Switched 3-phase motor output V",)),
            ProductTerminal("MOTOR_W", "J7 · W", "power", "right", 2, ("Switched 3-phase motor output W",)),
            ProductTerminal("SENSOR_A_H1", "J8 · A+ / H1", "signal", "right", 3,
                            ("Encoder A or Hall H1 input",),
                            signal_level_note="센서 신호 전압·입력 회로·모터 제어 펌웨어 설정을 공식 도면으로 확인하세요. 5 V 센서 전원으로 GPIO 호환을 단정하지 않습니다.",
                            signal_level_note_en="Verify sensor signal levels, input circuitry and motor-control firmware. Sensor 5 V supply alone does not prove GPIO compatibility."),
            ProductTerminal("SENSOR_B_H2", "J8 · B+ / H2", "signal", "right", 4,
                            ("Encoder B or Hall H2 input",),
                            signal_level_note="센서 신호 전압·입력 회로·모터 제어 펌웨어 설정을 공식 도면으로 확인하세요. 5 V 센서 전원으로 GPIO 호환을 단정하지 않습니다.",
                            signal_level_note_en="Verify sensor signal levels, input circuitry and motor-control firmware. Sensor 5 V supply alone does not prove GPIO compatibility."),
            ProductTerminal("SENSOR_Z_H3", "J8 · Z+ / H3", "signal", "right", 5,
                            ("Encoder index or Hall H3 input",),
                            signal_level_note="센서 신호 전압·입력 회로·모터 제어 펌웨어 설정을 공식 도면으로 확인하세요. 5 V 센서 전원으로 GPIO 호환을 단정하지 않습니다.",
                            signal_level_note_en="Verify sensor signal levels, input circuitry and motor-control firmware. Sensor 5 V supply alone does not prove GPIO compatibility."),
            ProductTerminal("SENSOR_5V", "J8 · 5V", "power", "right", 6,
                            ("Motor sensor supply, also available without daughterboard",)),
            ProductTerminal("SENSOR_GND", "J8 · GND", "ground", "right", 7, ("Motor sensor return",)),
        ),
        "확인한 외부 전력·통신·센서 단자만 표시합니다. 내부 MCU 전체 GPIO나 J2 예약·J4 디버그 패드는 포함하지 않습니다. "
        "J1/J7/J8의 단자 기능명은 논리 배치이며 미확인 패드 번호를 붙이지 않습니다. BEC는 딸림 보드가 필요하고 "
        "CAN 5 V 입력·센서 5 V·배터리 입력을 자동 연결하지 않습니다. BLDC/PMSM 구동·FOC·펌웨어 시뮬레이션은 지원하지 않습니다. " + _NOTE_KO,
        "Verified external power, communication and sensor terminals only; not all internal MCU GPIOs or reserved J2/debug J4 pads. "
        "J1/J7/J8 use logical terminal names without guessed numerical pad ordering. BEC requires the daughterboard. "
        "CAN 5 V input, sensor supply and battery input are not automatically tied together. BLDC/PMSM commutation, FOC and firmware are not simulated. " + _NOTE_EN,
        "ST UM2516 Rev 4 §§5.3–5.5, §6.1, Figures 9–11/14 and Table 5; "
        "MB1419-G431CBU6-C01 schematic sheets MCU (J3), CAN (J1), POWER STAGE (J5/J6/J7), SENSING (J8). "
        "Official source checked 2026-10-05.",
    ),
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
        "omron_e6b2_cwz6c_1000", "Omron E6B2-CWZ6C 1000 P/R 0.5 m",
        OMRON_E6B2_SOURCE,
        (
            ProductTerminal("ENCODER_VCC", "Brown · +Vcc", "power", "left", 0,
                            ("Encoder supply 5 V −5% to 24 V +15%",)),
            ProductTerminal("ENCODER_GND", "Blue · 0 V common", "ground", "left", 1,
                            ("Encoder 0 V / external ground reference",)),
            ProductTerminal("ENCODER_A", "Black · phase A", "signal", "right", 0,
                            ("Quadrature A output", "NPN open-collector, external pull-up required",),
                            signal_voltage_reference="external_pullup",
                            signal_level_note="NPN 오픈 컬렉터 출력의 High 전압은 외부 풀업이 정합니다. 엔코더 전원 5–24 V를 신호 전압으로 사용하지 말고 풀업 전압·수신부 입력 허용 전압을 확인하세요.",
                            signal_level_note_en="The external pull-up sets the NPN open-collector high level. Do not use the 5–24 V encoder supply as the signal voltage; verify pull-up voltage and receiver input limits."),
            ProductTerminal("ENCODER_B", "White · phase B", "signal", "right", 1,
                            ("Quadrature B output", "NPN open-collector, external pull-up required",),
                            signal_voltage_reference="external_pullup",
                            signal_level_note="NPN 오픈 컬렉터 출력의 High 전압은 외부 풀업이 정합니다. 엔코더 전원 5–24 V를 신호 전압으로 사용하지 말고 풀업 전압·수신부 입력 허용 전압을 확인하세요.",
                            signal_level_note_en="The external pull-up sets the NPN open-collector high level. Do not use the 5–24 V encoder supply as the signal voltage; verify pull-up voltage and receiver input limits."),
            ProductTerminal("ENCODER_Z", "Orange · phase Z", "signal", "right", 2,
                            ("Encoder index output", "NPN open-collector, external pull-up required",),
                            signal_voltage_reference="external_pullup",
                            signal_level_note="인덱스 Z도 A/B와 같은 NPN 오픈 컬렉터 회로입니다. 외부 풀업과 수신부의 전압 한계를 확인하세요.",
                            signal_level_note_en="Index Z uses the same NPN open-collector circuit as A/B. Verify the external pull-up and receiver voltage limits."),
        ),
        "E6B2-CWZ6C 1000 P/R의 공식 5가닥 색상·기능표입니다. 다른 CWZ 변형에 "
        "적용하거나 커넥터 번호·실제 배선을 추정하지 않습니다. 실드는 내부 회로나 "
        "케이스에 연결되지 않은 것으로 명시되어 자동 접지하지 않습니다. 1000 P/R은 "
        "A/B 양 채널 모든 에지를 세면 엔코더축당 4000 카운트입니다. 출력의 High "
        "전압은 외부 풀업이 정하며 공급 전압으로 GPIO 호환을 판단하지 않습니다. " + _NOTE_KO,
        "Exact CWZ6C 1000 P/R five-wire color/function table, not another CWZ "
        "variant or an inferred connector order. The shield is not internally "
        "connected to the case or circuitry and is not automatically grounded. "
        "1000 P/R corresponds to 4000 counts per encoder-shaft turn when counting "
        "all A/B edges. The external pull-up sets the signal high level; the "
        "encoder supply does not establish GPIO compatibility. " + _NOTE_EN,
        "Omron E6B2-C datasheet CSM_E6B2-C_DS_E_6_3, p.2 ratings and p.3 "
        "CWZ6C NPN I/O circuit/color table. Official PDF: "
        "https://www.ia.omron.com/data_pdf/cat/e6b2-c_ds_e_6_3_csm491.pdf?id=487",
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
def _measurement_diagram(catalog_id, model, source, pins, evidence):
    terminals=[]
    sides={'left':0,'right':0}
    for number,key,label,kind,side in pins:
        terminals.append(ProductTerminal(key,f'{number} · {label}',kind,side,sides[side],(label+' package-pin function',),
            signal_voltage_reference='',
            signal_level_note='신호 레벨·풀업·수신 핀의 허용 전압을 별도로 확인하세요.' if kind=='signal' else '',
            signal_level_note_en='Verify signal levels, pull-ups and receiver input limits separately.' if kind=='signal' else ''))
        sides[side]+=1
    return ProductDiagram(catalog_id,model,source,tuple(terminals),
        '제조사 패키지 핀 기능 참고입니다. PCB·브레이크아웃·펌웨어 시뮬레이션이나 동작 인증이 아닙니다. 자료 확인일 2026-10-06.',
        'Manufacturer package-pin reference. Not a dimensioned PCB/footprint, verified breakout or firmware simulation. Checked 2026-10-06.',evidence)


from .measurement_catalog import ADS131M04_SOURCE, ADS1232_SOURCE, HX711_SOURCE, SHT31_SOURCE, SHT45_SOURCE, HBK_U10M_SOURCE

PRODUCT_DIAGRAMS += (
    ProductDiagram('maxon_ec_i52_667065','maxon 667065 · functional phase / Hall reference','https://www.maxongroup.com/maxon/view/product/667065',(
        ProductTerminal('MOTOR_U','Phase U · functional','power','left',0,('Three-phase winding terminal U; connector assignment pending',)),
        ProductTerminal('MOTOR_V','Phase V · functional','power','left',1,('Three-phase winding terminal V; connector assignment pending',)),
        ProductTerminal('MOTOR_W','Phase W · functional','power','left',2,('Three-phase winding terminal W; connector assignment pending',)),
        ProductTerminal('HALL_VCC','Hall supply · voltage pending','power','right',0,('Hall power function; actual voltage and connector not verified',)),
        ProductTerminal('HALL_GND','Hall GND · functional','ground','right',1,('Hall return; actual connector assignment pending',)),
        ProductTerminal('HALL_H1','H1 · functional','signal','right',2,('Hall channel function; wire/color/connector and signal level pending',)),
        ProductTerminal('HALL_H2','H2 · functional','signal','right',3,('Hall channel function; wire/color/connector and signal level pending',)),
        ProductTerminal('HALL_H3','H3 · functional','signal','right',4,('Hall channel function; wire/color/connector and signal level pending',))),
        '공식 3상·Hall 센서 제품의 기능 단자 참고이며 U/V/W·H1/H2/H3는 결선 설계 이름입니다. 실제 선 색·커넥터 순서·Hall 전압은 미확인입니다. FOC·전류·열 시뮬레이션이 아닙니다. 확인일 2026-10-06.',
        'Functional design names U/V/W and H1/H2/H3 for the manufacturer three-phase Hall motor. Wire colors, connector order and Hall supply levels remain unverified. Not a dimensioned PCB/footprint or FOC/current/thermal simulation. Checked 2026-10-06.',
        'maxon 667065 official product page: 3 phases, Hall sensors, 24 V nominal and NRND. No physical connector numbering or phase-current conversion inferred.'),
    ProductDiagram('hbk_u10m_25kn_passive','HBK U10M 25 kN · passive functional terminals',HBK_U10M_SOURCE,(
        ProductTerminal('EXC_POS','EXC+','power','left',0,('Bridge excitation positive',)),ProductTerminal('EXC_NEG','EXC−','ground','left',1,('Bridge excitation return',)),
        ProductTerminal('SENSE_POS','SENSE+','signal','left',2,('Positive excitation sense',)),ProductTerminal('SENSE_NEG','SENSE−','signal','left',3,('Negative excitation sense',)),
        ProductTerminal('SIG_POS','SIG+','signal','right',0,('Differential bridge output positive',)),ProductTerminal('SIG_NEG','SIG−','signal','right',1,('Differential bridge output negative',)),
        ProductTerminal('SHIELD','Shield / housing','other','right',2,('Cable shield connected to housing',))),
        '수동 브리지 기능 단자 참고이며 케이블 색·커넥터 핀 번호는 지정하지 않습니다. 선택한 실제 옵션 설명서로 확인하세요. PCB나 내부 회로 시뮬레이션이 아닙니다. 확인일 2026-10-06.',
        'Passive bridge functional terminals only. No cable colors or connector pin numbers assumed; check the actual selected option. Not a dimensioned PCB/footprint or internal circuit simulation. Checked 2026-10-06.',
        'HBK B01444 04 E00 14, 22 Aug 2025, p12 passive six-wire functions; p13–14 25 kN passive standard dynamic specifications.'),
    _measurement_diagram('ti_ads131m04','TI ADS131M04 · PW TSSOP-20',ADS131M04_SOURCE,(
        (1,'AVDD','AVDD','power','left'),(2,'AGND','AGND','ground','left'),
        (3,'AIN0P','AIN0P','signal','left'),(4,'AIN0N','AIN0N','signal','left'),
        (5,'AIN1N','AIN1N','signal','left'),(6,'AIN1P','AIN1P','signal','left'),
        (7,'AIN2P','AIN2P','signal','left'),(8,'AIN2N','AIN2N','signal','left'),
        (9,'AIN3N','AIN3N','signal','left'),(10,'AIN3P','AIN3P','signal','left'),
        (11,'SYNC_RESET','SYNC / RESET','signal','right'),(12,'CS','CS','signal','right'),
        (13,'DRDY','DRDY','signal','right'),(14,'SCLK','SCLK','signal','right'),
        (15,'DOUT','DOUT','signal','right'),(16,'DIN','DIN','signal','right'),
        (17,'CLKIN','CLKIN','signal','right'),(18,'CAP','CAP','other','right'),
        (19,'DGND','DGND','ground','right'),(20,'DVDD','DVDD','power','right')),
        'TI SBAS890D §5 PW pin map and §6.3 input limits; not RUK WQFN numbering.'),
    _measurement_diagram('ti_ads1232','TI ADS1232 · PW TSSOP-24',ADS1232_SOURCE,(
        (1,'DVDD','DVDD','power','right'),(2,'DGND','DGND','ground','right'),
        (3,'CLKIN_XTAL1','CLKIN / XTAL1','signal','right'),(4,'XTAL2','XTAL2','other','right'),
        (5,'DGND_5','DGND','ground','right'),(6,'DGND_6','DGND','ground','right'),
        (7,'TEMP','TEMP','signal','right'),(8,'A0','A0','signal','right'),
        (9,'CAP_9','CAP','other','left'),(10,'CAP_10','CAP','other','left'),
        (11,'AINP1','AINP1','signal','left'),(12,'AINN1','AINN1','signal','left'),
        (13,'AINN2','AINN2','signal','left'),(14,'AINP2','AINP2','signal','left'),
        (15,'REFN','REFN','signal','left'),(16,'REFP','REFP','signal','left'),
        (17,'AGND','AGND','ground','left'),(18,'AVDD','AVDD','power','left'),
        (19,'GAIN0','GAIN0','signal','right'),(20,'GAIN1','GAIN1','signal','right'),
        (21,'SPEED','SPEED','signal','right'),(22,'PDWN','PDWN','signal','right'),
        (23,'SCLK','SCLK','signal','right'),(24,'DRDY_DOUT','DRDY / DOUT','signal','right')),
        'TI SBAS350H Rev H §5 PW pin map; §6.5 10/80 SPS filter specifications.'),
    _measurement_diagram('avia_hx711','AVIA HX711 · SOP-16',HX711_SOURCE,(
        (1,'VSUP','VSUP','power','left'),(2,'BASE','BASE','other','left'),
        (3,'AVDD','AVDD','power','left'),(4,'VFB','VFB','other','left'),
        (5,'AGND','AGND','ground','left'),(6,'VBG','VBG','other','left'),
        (7,'INA_NEG','INA−','signal','left'),(8,'INA_POS','INA+','signal','left'),
        (9,'INB_NEG','INB−','signal','left'),(10,'INB_POS','INB+','signal','left'),
        (11,'PD_SCK','PD_SCK','signal','right'),(12,'DOUT','DOUT','signal','right'),
        (13,'XO','XO','other','right'),(14,'XI','XI','other','right'),
        (15,'RATE','RATE','signal','right'),(16,'DVDD','DVDD','power','right')),
        'AVIA HX711 manufacturer datasheet SOP-16 pin description; document hosted by SparkFun.'),
    _measurement_diagram('sensirion_sht31_dis_b','Sensirion SHT31-DIS-B · DFN-8',SHT31_SOURCE,(
        (1,'SDA','SDA','signal','right'),(2,'ADDR','ADDR','signal','left'),
        (3,'ALERT','ALERT','signal','right'),(4,'SCL','SCL','signal','right'),
        (5,'VDD','VDD','power','left'),(6,'NRESET','nRESET','signal','left'),
        (7,'R','R · connect VSS','other','left'),(8,'VSS','VSS','ground','left')),
        'Sensirion SHT3x-DIS V7 December 2022 §2.1 DFN pin assignment.'),
    _measurement_diagram('sensirion_sht45_ad1b','Sensirion SHT45-AD1B · DFN-4',SHT45_SOURCE,(
        (1,'SDA','SDA','signal','right'),(2,'SCL','SCL','signal','right'),
        (3,'VDD','VDD','power','left'),(4,'VSS','VSS','ground','left')),
        'Sensirion SHT4x V7.3 June 2026 DFN4 pin assignment; exact AD1B address 0x44.'),
)
EXPANSION_CHECKED_DATE = "2026-10-07"


def _module_diagram(catalog_id, model, source, terminals, note, note_en, evidence,
                    *, logic_supply=None, logic_signals=()):
    """Lay out verified functional terminals without inventing physical order.

    Tuples explicitly supply every terminal's key, label, kind and function.
    Side coordinates only arrange the vector drawing. A repeated supply pad
    can be represented by one labelled functional terminal, never inferred
    electrical wiring between separately named rails.
    """
    positions = {"left": 0, "right": 0}
    pins = []
    for key, label, kind, side, functions in terminals:
        levels = {}
        if key in logic_signals and logic_supply is not None:
            reference, low, high = logic_supply
            levels = dict(
                signal_voltage_reference=reference,
                signal_voltage_min_v=low, signal_voltage_max_v=high,
                signal_level_note="신호 기준은 실제 보드 로직 전원입니다. 전원 범위가 상대 GPIO 호환을 승인하지 않습니다.",
                signal_level_note_en="Signal reference follows the actual board logic rail. Its supply range does not approve the other device's GPIO compatibility.")
        pins.append(ProductTerminal(key, label, kind, side, positions[side], functions, **levels))
        positions[side] += 1
    return ProductDiagram(
        catalog_id, model, source, tuple(pins),
        note + " 기능별 자체 벡터 모식도이며 단자 좌우 배치는 실물 순서가 아닙니다. "
        "치수가 있는 PCB/풋프린트나 내부 회로·펌웨어 시뮬레이션이 아닙니다. "
        f"공식 자료 확인일 {EXPANSION_CHECKED_DATE}.",
        note_en + " Functional vector reference; left/right positions are not physical pad order. "
        "Not a dimensioned PCB/footprint or internal-circuit/firmware simulation. "
        f"Official source checked {EXPANSION_CHECKED_DATE}.", evidence)


PRODUCT_DIAGRAMS += (
    _module_diagram(
        "ti_ref5025aid", "TI REF5025AID · SOIC-8 IC", "https://www.ti.com/lit/ds/symlink/ref50.pdf",
        (
            ("DNC_1", "1 · DNC", "other", "left", ("Do not connect",)),
            ("VIN", "2 · VIN", "power", "left", ("Input supply 2.7–18 V for REF5025AID",)),
            ("TEMP", "3 · TEMP", "signal", "left", ("Temperature-dependent analog output",)),
            ("GND", "4 · GND", "ground", "left", ("Reference return",)),
            ("TRIM_NR", "5 · TRIM/NR", "other", "right", ("Output trim / noise-reduction network",)),
            ("OUT", "6 · VOUT", "power", "right", ("2.5 V reference output; ±10 mA source/sink limit",)),
            ("NC_7", "7 · NC", "other", "right", ("No internal connection",)),
            ("DNC_8", "8 · DNC", "other", "right", ("Do not connect",)),
        ),
        "표준 AI 등급 SOIC-8 칩입니다. EI 등급의 1번 EN이나 42 V 입력을 적용하지 않습니다. "
        "원격 SENSE 핀이 없으며 사용자 여자 캐리어·버퍼·센스 회로의 전체 단자도와 다릅니다. 출력 한계는 소비전류가 아닙니다.",
        "Standard AI-grade SOIC-8 chip, not an EI-grade 42 V/EN variant. No remote SENSE pins; "
        "this is not the complete user's excitation carrier, buffer or sensing circuit. Output limits are not consumption.",
        "TI SBOS410O (October 2025) Table 4-1, Figure 5-1 and Table 5-1; §6.3 REF5025 recommended supply and output limits."),
    _module_diagram(
        "meanwell_hdr60_5", "MEAN WELL HDR-60-5 · 5 V PSU",
        "https://www.meanwell.com/Upload/PDF/HDR-60/HDR-60-SPEC.PDF",
        (
            ("AC_L", "5 · AC/L", "other", "left", ("AC line input 85–264 VAC",)),
            ("AC_N", "6 · AC/N", "other", "left", ("AC neutral input",)),
            ("DC_NEG", "1,2 · −V", "ground", "right", ("DC output return; two parallel screws",)),
            ("DC_POS", "3,4 · +V", "power", "right", ("5 V output; two parallel screws; 6.5 A capacity, 32.5 W",)),
        ),
        "5 V 모델은 32.5 W입니다. 각 출력의 병렬 나사는 하나의 기능 단자로 표시합니다. "
        "Class II이며 FG 단자를 만들지 않습니다. AC 입력·전원 변환·안전·회생 전력은 미해석이며 자동 DC 전원으로 등록하지 않습니다.",
        "The 5 V variant is 32.5 W. Parallel output screws share one functional terminal. "
        "Class II; no invented FG terminal. AC, conversion, installation and regeneration are not analysed; not an automatic DC source.",
        "HDR-60-SPEC 2026-04-03 p2 model column and p4 visually checked Terminal Pin No. Assignment: 5 AC/L, 6 AC/N."),
    _module_diagram(
        "meanwell_lrs600_24", "MEAN WELL LRS-600-24 · 24 V PSU",
        "https://www.meanwell.com/Upload/PDF/LRS-600/LRS-600-SPEC.PDF",
        (
            ("AC_L", "1 · AC/L", "other", "left", ("AC line; set 115/230 VAC input selector for the installation",)),
            ("AC_N", "2 · AC/N", "other", "left", ("AC neutral",)),
            ("FG", "3 · FG / PE", "other", "left", ("Protective/frame earth; distinct from DC output return",)),
            ("DC_NEG", "4–6 · −V", "ground", "right", ("DC output return; three parallel screws",)),
            ("DC_POS", "7–9 · +V", "power", "right", ("24 V output; three parallel screws; 25 A capacity",)),
        ),
        "FG는 DC −V와 별개입니다. 24 V·25 A는 출력 용량이며 부하 소비전류나 회생 전력 흡수 능력이 아닙니다. "
        "입력 선택 스위치를 확인해야 하며 AC·변환·접지·설치 안전을 DC 계산으로 승인하지 않습니다.",
        "FG is distinct from −V. The 24 V/25 A output capacity is neither load consumption nor rated regenerative absorption. "
        "Check the mains selector. The DC solver does not approve AC conversion, earthing or installation.",
        "LRS-600-SPEC 2025-09-12 p2 exact -24 column and p4 visually checked Terminal Pin No. Assignment."),
    _module_diagram(
        "adafruit_904", "Adafruit INA219 breakout · #904",
        "https://learn.adafruit.com/adafruit-ina219-current-sensor-breakout/pinouts",
        (
            ("VIN", "VIN / VCC", "power", "left", ("2.7–5.5 V logic supply",)),
            ("GND", "GND", "ground", "left", ("Logic return",)),
            ("SCL", "SCL", "signal", "left", ("I2C clock; 10 kΩ pull-up to VCC",)),
            ("SDA", "SDA", "signal", "left", ("I2C data; 10 kΩ pull-up to VCC",)),
            ("VIN_POS", "Vin+", "power", "right", ("High-side current sense: source side",)),
            ("VIN_NEG", "Vin−", "power", "right", ("High-side current sense: load side, not GND",)),
        ),
        "Adafruit #904 외부 기능 단자입니다. Vin−는 접지가 아닙니다. 주소 A0/A1 솔더 점퍼는 외부 GPIO 핀으로 만들지 않습니다. "
        "I2C 기본 주소 0x40이며 내부 shunt·ADC 측정 동작은 별도입니다.",
        "Adafruit #904 external terminals. Vin− is not ground. Address A0/A1 solder jumpers are not invented GPIO terminals. "
        "Default I2C address 0x40; internal shunt/ADC behaviour is separate.",
        "Adafruit #904 product and INA219 guide Pinouts: Power Pins, Data Pins, Current Sense Inputs and Address Jumpers.",
        logic_supply=("VCC", 2.7, 5.5), logic_signals=("SCL", "SDA")),
    _module_diagram(
        "adafruit_4226", "Adafruit INA260 breakout · #4226",
        "https://learn.adafruit.com/adafruit-ina260-current-voltage-power-sensor-breakout/pinouts",
        (
            ("VCC", "Vcc", "power", "left", ("2.7–5.5 V logic supply",)),
            ("GND", "GND", "ground", "left", ("Logic return",)),
            ("SCL", "SCL", "signal", "left", ("I2C clock; pull-up to Vcc",)),
            ("SDA", "SDA", "signal", "left", ("I2C data; pull-up to Vcc",)),
            ("ALERT", "Alert", "signal", "left", ("Alert output referenced to Vcc",)),
            ("VIN_POS", "Vin+", "power", "right", ("Current-sense source side",)),
            ("VIN_NEG", "Vin−", "power", "right", ("Current-sense load side, not logic ground",)),
            ("VBUS", "VBus", "other", "right", ("Voltage sense; tied to Vin+ by default VB jumper",)),
        ),
        "VB 점퍼의 기본 VBus–Vin+ 연결과 low-side 변경을 구분해야 합니다. A0/A1 주소 점퍼는 핀으로 추가하지 않습니다. "
        "Vin−와 GND를 자동 연결하지 않으며 측정 기능을 회로 구동 모델로 가정하지 않습니다.",
        "Check the default VBus–Vin+ VB jumper before low-side wiring. A0/A1 address jumpers are not additional terminals. "
        "Vin− and GND are not automatically wired; measurement functions do not define a drive model.",
        "Adafruit #4226 INA260 guide Pinouts: power/data/current-sense pins, Alert pin and VBus pin.",
        logic_supply=("VCC", 2.7, 5.5), logic_signals=("SCL", "SDA", "ALERT")),
    _module_diagram(
        "adafruit_1085", "Adafruit ADS1115 STEMMA QT · #1085",
        "https://learn.adafruit.com/adafruit-4-channel-adc-breakouts/pinouts",
        (
            ("VIN", "VIN", "power", "left", ("2–5 V supply",)),
            ("GND", "GND", "ground", "left", ("Supply and analog return",)),
            ("SCL", "SCL", "signal", "left", ("I2C clock; 10 kΩ pull-up to VIN",)),
            ("SDA", "SDA", "signal", "left", ("I2C data; 10 kΩ pull-up to VIN",)),
            ("ALRT", "ALRT", "signal", "left", ("Comparator / conversion-ready output",)),
            *((f"A{i}", f"A{i}", "signal", "right", (f"Analog input {i}",)) for i in range(4)),
            ("APLUS", "A+", "power", "right", ("Filtered VIN output; not an ADC input",)),
            ("AMINUS", "A−", "ground", "right", ("Filtered GND output; not an ADC input",)),
        ),
        "현재 STEMMA QT 버전의 기능 단자입니다. "
        "구형 ADDR 헤더나 뒷면 주소 점퍼를 같은 외부 핀으로 추정하지 않습니다. 실물 리비전을 확인하세요. A+/A−는 전원 출력입니다.",
        "Functional terminals of the current STEMMA QT variant. Do not infer the old ADDR header from its back-side address jumper. "
        "Confirm the physical revision. A+/A− are supply outputs.",
        "Adafruit #1085 product variant and ADS1115 guide Pinouts, including QT A+/A− power outputs and A0–A3 inputs.",
        logic_supply=("VIN", 2.0, 5.0), logic_signals=("SCL", "SDA")),
    _module_diagram(
        "adafruit_5346", "Adafruit MCP23017 breakout · #5346",
        "https://learn.adafruit.com/adafruit-mcp23017-i2c-gpio-expander/pinouts",
        (
            ("VIN", "VIN", "power", "left", ("3–5 V supply / logic rail",)),
            ("GND", "GND", "ground", "left", ("Supply return",)),
            ("SCL", "SCL", "signal", "left", ("I2C clock; level-shifted with pull-up",)),
            ("SDA", "SDA", "signal", "left", ("I2C data; level-shifted with pull-up",)),
            ("IA", "IA", "signal", "left", ("Port A interrupt; configurable polarity / open drain",)),
            ("IB", "IB", "signal", "left", ("Port B interrupt; configurable polarity / open drain",)),
            ("RST", "RST", "signal", "left", ("Active-low reset",)),
            *((f"D{i}", f"D{i}", "other", "left", (f"I2C address strap bit {i}; not port A{i}",)) for i in range(3)),
            *((f"{bank}{i}", f"{bank}{i}", "signal", "right",
               (("Digital output only recommended by manufacturer erratum",) if i == 7
                else ("Digital GPIO; not an analog input",))) for bank in ("A", "B") for i in range(8)),
        ),
        "정확한 #5346 보드입니다. 2026-09-22 제조사 안내에 따라 A7/B7 입력 사용 시 SDA 손상 가능성이 있어 출력 전용으로 표시합니다. "
        "A/B 번호는 아날로그 채널이 아닙니다. 기본 주소 0x20이며 실제 I2C·확장 GPIO 펌웨어 동작은 별도입니다.",
        "Exact #5346 breakout. The manufacturer's 2026-09-22 erratum warns of SDA corruption when A7/B7 are inputs; "
        "these are labelled output-only. A/B are digital, not analog channels. Default address 0x20; GPIO firmware behaviour is separate.",
        "Adafruit #5346 MCP23017 guide Pinouts and A7/B7 erratum; D0/D1/D2 address straps, IA/IB and RST.",
        logic_supply=("VIN", 3.0, 5.0), logic_signals=("SCL", "SDA")),
    _module_diagram(
        "adafruit_815", "Adafruit PCA9685 servo PWM · #815",
        "https://learn.adafruit.com/16-channel-pwm-servo-driver/pinouts",
        (
            ("VCC", "VCC", "power", "left", ("3–5 V logic supply; PWM high level",)),
            ("VPLUS", "V+", "power", "left", ("Separate servo-power rail; repeated parallel pads",)),
            ("GND", "GND", "ground", "left", ("Common logic/servo return; repeated parallel pads",)),
            ("SCL", "SCL", "signal", "left", ("I2C clock; pull-up to VCC",)),
            ("SDA", "SDA", "signal", "left", ("I2C data; pull-up to VCC",)),
            ("OE", "OE", "signal", "left", ("High disables PWM outputs; pulled low by default",)),
            *((f"PWM{i}", f"{i} · PWM", "signal", "right", ("PWM output; high level is VCC; all channels share frequency",)) for i in range(16)),
        ),
        "VCC와 서보 V+는 별도 전원입니다. 채널별 V+/GND 반복 패드는 각각 하나의 공통 기능 단자로 표시합니다. "
        "16개 PWM은 동일 주파수이며 모터 동력·H-bridge 출력이 아닙니다. 0–15는 채널 번호로 헤더 패드 번호가 아닙니다.",
        "VCC and servo V+ are separate. Repeated channel V+/GND pads are represented by their common functional terminals. "
        "The 16 PWM channels share frequency and are not H-bridge power outputs. 0–15 are channel numbers, not physical pad numbers.",
        "Adafruit #815 PCA9685 guide Pinouts: control inputs, VCC/V+ distinction and PWM outputs.",
        logic_supply=("VCC", 3.0, 5.0), logic_signals=("SCL", "SDA", *tuple(f"PWM{i}" for i in range(16)))),
    _module_diagram(
        "adafruit_3190", "Adafruit DRV8871 breakout · #3190",
        "https://learn.adafruit.com/adafruit-drv8871-brushed-dc-motor-driver-breakout/pinouts",
        (
            ("VM", "VM / Power+", "power", "left", ("6.5–45 V motor supply; parallel power pads",)),
            ("GND", "GND / Power−", "ground", "left", ("Common power/control return",)),
            ("IN1", "IN1", "signal", "left", ("Bridge control input 1; 3/5 V logic compatible",)),
            ("IN2", "IN2", "signal", "left", ("Bridge control input 2; 3/5 V logic compatible",)),
            ("OUT1", "OUT1", "power", "right", ("Switched motor terminal 1; not logic ground",)),
            ("OUT2", "OUT2", "power", "right", ("Switched motor terminal 2; not logic ground",)),
        ),
        "별도 로직 VCC를 만들지 않습니다. 두 출력 모두 스위칭 모터 단자이며 OUT2를 GND로 취급하지 않습니다. "
        "VM 입력 최소 6.5 V를 지키며 모터 PWM·전류 제한·열 한계를 DC 부하 모델이 계산하지 않습니다.",
        "No invented logic VCC terminal. Both outputs are switched motor terminals; OUT2 is not GND. "
        "VM requires at least 6.5 V. The DC load model does not calculate PWM, current limiting or thermal limits.",
        "Adafruit #3190 DRV8871 guide Pinouts: motor power, IN1/IN2 controls and motor outputs."),
    _module_diagram(
        "adafruit_2857", "Adafruit SHT31-D breakout · #2857",
        "https://learn.adafruit.com/adafruit-sht31-d-temperature-and-humidity-sensor-breakout/pinouts",
        (
            ("VIN", "Vin", "power", "left", ("2.5–5 V supply",)),
            ("GND", "GND", "ground", "left", ("Supply return",)),
            ("SCL", "SCL", "signal", "right", ("I2C clock; 10 kΩ pull-up to Vin",)),
            ("SDA", "SDA", "signal", "right", ("I2C data; 10 kΩ pull-up to Vin",)),
            ("ADR", "ADR", "other", "left", ("I2C address strap: low 0x44 / high 0x45",)),
            ("RST", "RST", "signal", "left", ("Active-low reset; board pull-up",)),
            ("ALR", "ALR", "signal", "right", ("Alert output",)),
        ),
        "정확한 Adafruit 보드 외부 단자입니다. DFN IC의 핀 번호를 헤더 번호로 쓰지 않습니다. "
        "I2C 풀업은 Vin 기준이므로 5 V Vin과 3.3 V GPIO의 호환을 자동 승인하지 않습니다.",
        "Exact breakout terminals, not the DFN IC pin numbers. I2C pull-ups follow Vin; "
        "5 V Vin does not automatically approve a 3.3 V GPIO connection.",
        "Adafruit #2857 SHT31-D guide Pinouts: power/data pins, ADR, RST and ALR.",
        logic_supply=("VIN", 2.5, 5.0), logic_signals=("SCL", "SDA")),
    _module_diagram(
        "adafruit_2652", "Adafruit BME280 breakout · #2652",
        "https://learn.adafruit.com/adafruit-bme280-humidity-barometric-pressure-temperature-sensor-breakout/pinouts",
        (
            ("VIN", "Vin", "power", "left", ("3–5 V board input",)),
            ("GND", "GND", "ground", "left", ("Common return",)),
            ("3VO", "3Vo", "power", "left", ("Regulated 3.3 V output, not supply input",)),
            ("SCK", "SCK / SCL", "signal", "right", ("Shared SPI clock / I2C clock terminal",)),
            ("SDI", "SDI / SDA", "signal", "right", ("Shared SPI MOSI / I2C data terminal",)),
            ("SDO", "SDO", "signal", "right", ("SPI MISO or I2C address strap; default 0x77, low 0x76",)),
            ("CS", "CS", "signal", "right", ("SPI active-low chip select",)),
        ),
        "동일한 SCK/SCL·SDI/SDA 패드를 별도 핀으로 복제하지 않습니다. SPI/I2C 모드와 SDO 주소 설정을 확인하세요. "
        "3Vo는 출력이며 보드 로직 레벨 시프터의 기준은 Vin입니다.",
        "Shared SCK/SCL and SDI/SDA pads are not duplicated. Check SPI/I2C mode and SDO address selection. "
        "3Vo is an output; the board level shifters follow Vin.",
        "Adafruit #2652 BME280 guide Pinouts: power pins and SPI/I2C logic pins.",
        logic_supply=("VIN", 3.0, 5.0), logic_signals=("SCK", "SDI", "SDO", "CS")),
    _module_diagram(
        "adafruit_6357", "Adafruit AS5600 STEMMA QT · #6357",
        "https://learn.adafruit.com/adafruit-as5600-magnetic-angle-sensor/pinouts",
        (
            ("VIN", "Vin", "power", "left", ("3 V or 5 V board supply",)),
            ("V3O", "V3o", "power", "left", ("Regulated 3.3 V output",)),
            ("GND", "GND", "ground", "left", ("Supply return",)),
            ("SDA", "SDA", "signal", "right", ("I2C data; level shifted, pull-up to Vin; address 0x36",)),
            ("SCL", "SCL", "signal", "right", ("I2C clock; level shifted, pull-up to Vin",)),
            ("OUT", "OUT", "signal", "right", ("Analog/PWM angle output referenced to internal VDD, not Vin",)),
        ),
        "DIR은 뒷면 점퍼 설정이며 추가 헤더 핀으로 만들지 않습니다. 절대각 I2C/아날로그/PWM 출력이며 quadrature A/B가 아닙니다. "
        "OUT의 내부 VDD 기준과 SDA/SCL의 Vin 기준을 혼동하지 마세요.",
        "DIR is a back-side jumper, not an invented header terminal. Absolute-angle I2C/analog/PWM output, not quadrature A/B. "
        "OUT follows internal VDD, while SDA/SCL follow Vin.",
        "Adafruit #6357 AS5600 guide Pinouts: power pins, I2C pins, OUT and DIR jumper.",
        logic_supply=("VIN", 3.0, 5.0), logic_signals=("SDA", "SCL")),
)

_BY_ID = {diagram.catalog_id: diagram for diagram in PRODUCT_DIAGRAMS}


def product_diagram(catalog_id: str) -> ProductDiagram | None:
    """Return an exact supported terminal map; unknown/model-family IDs get None."""
    return _BY_ID.get(catalog_id)


def available_product_diagrams() -> tuple[ProductDiagram, ...]:
    """Offline, immutable reference records with no GUI or numerical dependency."""
    return PRODUCT_DIAGRAMS
