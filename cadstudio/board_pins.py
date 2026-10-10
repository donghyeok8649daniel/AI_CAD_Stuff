"""Exact development-board header references, independent of the DC solver.

The drawing uses schematic left/right rows, not PCB dimensions. Pin labels carry
the manufacturer's connector coordinates. Only ``kind == 'signal'`` pins are
assignable signal terminals. Supply/reference/debug pins do not become ordinary
GPIOs, and board power must not be inferred from a GPIO logic voltage.

``SAME_NET:<key>`` identifies a second physical socket of a canonical signal.
It is connectivity metadata, not another selectable MCU peripheral function.
Source verification date: 2026-10-03. See docs/MCU_PIN_SOURCES.md for scope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


PinKind = Literal["signal", "power", "ground", "reset", "other"]
PinSide = Literal["left", "right"]
SOURCE_CHECKED_DATE = "2026-10-03"


@dataclass(frozen=True, slots=True)
class BoardPin:
    key: str
    label: str
    functions: tuple[str, ...]
    kind: PinKind
    side: PinSide
    position: int


@dataclass(frozen=True, slots=True)
class BoardPinout:
    catalog_id: str
    model: str
    source_url: str
    pins: tuple[BoardPin, ...]
    logic_voltage_v: float | None = None
    note: str = ""
    note_en: str = ""


_RPI_SOURCE = (
    "https://pip-assets.raspberrypi.com/categories/685-app-notes-guides-whitepapers/"
    "documents/RP-006553-WP/"
    "A-history-of-GPIO-usage-on-Raspberry-Pi-devices-and-current-best-practices"
)
_UNO_SOURCE = "https://docs.arduino.cc/resources/datasheets/A000066-datasheet.pdf"
_MEGA_SOURCE = "https://docs.arduino.cc/resources/datasheets/A000067-datasheet.pdf"
_ST_SOURCE = (
    "https://www.st.com/resource/en/user_manual/"
    "um1724-stm32-nucleo64-boards-mb1136-stmicroelectronics.pdf"
)
_PICO_SOURCE = "https://datasheets.raspberrypi.com/pico/Pico-R3-A4-Pinout.pdf"


def _pin(key: str, label: str, functions: tuple[str, ...], kind: PinKind,
         side: PinSide, position: int) -> BoardPin:
    return BoardPin(key, label, functions, kind, side, position)


def _rpi_pins() -> tuple[BoardPin, ...]:
    # Official GPIO usage white paper Figure 1; BCM names != physical numbers.
    gpio_at_pin = {
        3: 2, 5: 3, 7: 4, 8: 14, 10: 15, 11: 17, 12: 18, 13: 27,
        15: 22, 16: 23, 18: 24, 19: 10, 21: 9, 22: 25, 23: 11,
        24: 8, 26: 7, 27: 0, 28: 1, 29: 5, 31: 6, 32: 12, 33: 13,
        35: 19, 36: 16, 37: 26, 38: 20, 40: 21,
    }
    special = {
        0: ("ID_SD (HAT EEPROM)",), 1: ("ID_SC (HAT EEPROM)",),
        2: ("I2C SDA",), 3: ("I2C SCL",), 4: ("GPCLK0",),
        7: ("SPI CE1",), 8: ("SPI CE0",), 9: ("SPI MISO",),
        10: ("SPI MOSI",), 11: ("SPI SCLK",), 12: ("PWM0",),
        13: ("PWM1",), 14: ("UART TXD",), 15: ("UART RXD",),
        18: ("PCM_CLK",), 19: ("PCM_FS",), 20: ("PCM_DIN",),
        21: ("PCM_DOUT",),
    }
    result: list[BoardPin] = []
    for physical in range(1, 41):
        side: PinSide = "left" if physical % 2 else "right"
        position = (physical - 1) // 2
        coordinate = f"J8.{physical}"
        if physical in (1, 17):
            result.append(_pin(f"3V3_{physical}", f"{coordinate} · 3V3",
                               ("3.3 V rail",), "power", side, position))
        elif physical in (2, 4):
            result.append(_pin(f"5V_{physical}", f"{coordinate} · 5V",
                               ("5 V rail",), "power", side, position))
        elif physical in (6, 9, 14, 20, 25, 30, 34, 39):
            result.append(_pin(f"GND_{physical}", f"{coordinate} · GND",
                               ("GND",), "ground", side, position))
        else:
            gpio = gpio_at_pin[physical]
            kind: PinKind = "other" if gpio in (0, 1) else "signal"
            result.append(_pin(f"GPIO{gpio}", f"{coordinate} · GPIO{gpio}",
                               ("GPIO",) + special.get(gpio, ()),
                               kind, side, position))
    return tuple(result)


def _arduino_power() -> list[BoardPin]:
    # JANALOG/Analog table pins 1-8 on both exact Rev3 products.
    rows = (
        ("NC", "NC", ("Not connected",), "other"),
        ("IOREF", "IOREF", ("5 V logic reference",), "other"),
        ("RESET", "RESET", ("RESET",), "reset"),
        ("3V3_JANALOG4", "3V3", ("3.3 V rail",), "power"),
        ("5V_JANALOG5", "5V", ("5 V rail",), "power"),
        ("GND_JANALOG6", "GND", ("GND",), "ground"),
        ("GND_JANALOG7", "GND", ("GND",), "ground"),
        ("VIN", "VIN", ("VIN supply input",), "power"),
    )
    return [_pin(key, f"JANALOG.{i} · {label}", functions, kind, "left", i - 1)
            for i, (key, label, functions, kind) in enumerate(rows, 1)]


def _uno_pins() -> tuple[BoardPin, ...]:
    result = _arduino_power()
    for analog in range(6):
        functions = ("GPIO", f"ADC{analog}")
        if analog == 4:
            functions += ("I2C SDA",)
        elif analog == 5:
            functions += ("I2C SCL",)
        result.append(_pin(f"A{analog}", f"JANALOG.{analog + 9} · A{analog}",
                           functions, "signal", "left", analog + 8))
    for digital in range(14):
        functions = ("GPIO",)
        if digital in (3, 5, 6, 9, 10, 11):
            functions += ("PWM",)
        if digital in (0, 1):
            functions += (("UART RX" if digital == 0 else "UART TX"),)
        if digital in (2, 3):
            functions += ("External interrupt",)
        if digital in (10, 11, 12, 13):
            functions += ({10: "SPI SS", 11: "SPI MOSI/COPI",
                           12: "SPI MISO/CIPO", 13: "SPI SCK"}[digital],)
        result.append(_pin(f"D{digital}", f"JDIGITAL.{digital + 1} · D{digital}",
                           functions, "signal", "right", 17 - digital))
    result.extend((
        _pin("GND_JDIGITAL15", "JDIGITAL.15 · GND", ("GND",), "ground", "right", 3),
        _pin("AREF", "JDIGITAL.16 · AREF", ("Analog reference",), "other", "right", 2),
        _pin("SDA", "JDIGITAL.17 · SDA / A4", ("GPIO", "I2C SDA", "SAME_NET:A4"),
             "signal", "right", 1),
        _pin("SCL", "JDIGITAL.18 · SCL / A5", ("GPIO", "I2C SCL", "SAME_NET:A5"),
             "signal", "right", 0),
    ))
    return tuple(result)


def _mega_pins() -> tuple[BoardPin, ...]:
    result = _arduino_power()
    for analog in range(16):
        result.append(_pin(f"A{analog}", f"JANALOG.{analog + 9} · A{analog}",
                           ("GPIO", f"ADC{analog}"), "signal", "left", analog + 8))
    # Main digital edge connector: manual section 5.2's 1-based coordinates.
    coordinates = {**{n: 18 - n for n in range(14)},
                   **{n: 19 + n - 14 for n in range(14, 22)}}
    special = {
        0: ("UART0 RX",), 1: ("UART0 TX",), 14: ("UART3 TX",),
        15: ("UART3 RX",), 16: ("UART2 TX",), 17: ("UART2 RX",),
        18: ("UART1 TX",), 19: ("UART1 RX",), 20: ("I2C SDA",),
        21: ("I2C SCL",), 50: ("SPI MISO/CIPO",),
        51: ("SPI MOSI/COPI",), 52: ("SPI SCK",), 53: ("SPI SS",),
    }
    for digital in range(22):
        physical = coordinates[digital]
        functions = ("GPIO",) + special.get(digital, ())
        if digital in (*range(2, 14), 44, 45, 46):
            functions += ("PWM",)
        if digital in (2, 3, 18, 19, 20, 21):
            functions += ("External interrupt",)
        result.append(_pin(f"D{digital}", f"JDIGITAL.{physical} · D{digital}",
                           functions, "signal", "right", physical - 1))
    result.extend((
        _pin("SCL", "JDIGITAL.1 · SCL / D21", ("GPIO", "I2C SCL", "SAME_NET:D21"),
             "signal", "right", 0),
        _pin("SDA", "JDIGITAL.2 · SDA / D20", ("GPIO", "I2C SDA", "SAME_NET:D20"),
             "signal", "right", 1),
        _pin("AREF", "JDIGITAL.3 · AREF", ("Analog reference",), "other", "right", 2),
        _pin("GND_JDIGITAL4", "JDIGITAL.4 · GND", ("GND",), "ground", "right", 3),
    ))
    # The separate two-row D22-D53 connector, manual sections 5.5/5.6.
    # LHS/RHS are explicit manual row coordinates, not invented PCB pad names.
    for side, parity, offset, suffix in (("left", 0, 24, "LHS"), ("right", 1, 26, "RHS")):
        result.append(_pin(f"5V_XIO_{suffix}", f"XIO {suffix}.1 · 5V",
                           ("5 V rail",), "power", side, offset))
        for index, digital in enumerate(range(22 + parity, 54, 2), 2):
            functions = ("GPIO",) + special.get(digital, ())
            if digital in (44, 45, 46):
                functions += ("PWM",)
            result.append(_pin(f"D{digital}", f"XIO {suffix}.{index} · D{digital}",
                               functions, "signal", side, offset + index - 1))
        result.append(_pin(f"GND_XIO_{suffix}", f"XIO {suffix}.18 · GND",
                           ("GND",), "ground", side, offset + 17))
    return tuple(result)


def _nucleo_pins(variant: str) -> tuple[BoardPin, ...]:
    result: list[BoardPin] = []
    power = (
        ("NC", "NC", ("Not connected",), "other"),
        ("IOREF", "IOREF", ("3.3 V logic reference",), "other"),
        ("RESET", "RESET / NRST", ("NRST",), "reset"),
        ("3V3_CN6_4", "3V3", ("3.3 V input/output rail",), "power"),
        ("5V_CN6_5", "5V", ("5 V output rail",), "power"),
        ("GND_CN6_6", "GND", ("GND",), "ground"),
        ("GND_CN6_7", "GND", ("GND",), "ground"),
        ("VIN", "VIN", ("VIN supply input",), "power"),
    )
    for i, (key, label, functions, kind) in enumerate(power, 1):
        result.append(_pin(key, f"CN6.{i} · {label}", functions, kind, "left", i - 1))
    adc_prefix = {"f103rb": "ADC", "f401re": "ADC1", "f446re": "ADC123"}[variant]
    analog_ports = ("PA0", "PA1", "PA4", "PB0", "PC1", "PC0")
    analog_channels = (0, 1, 4, 8, 11, 10)
    for index, (port, channel) in enumerate(zip(analog_ports, analog_channels)):
        prefix = "ADC12" if variant == "f446re" and index in (2, 3) else adc_prefix
        result.append(_pin(f"A{index}", f"CN8.{index + 1} · A{index} / {port}",
                           ("GPIO", port, f"{prefix}_IN{channel}"),
                           "signal", "left", index + 8))
    ports = ("PA3", "PA2", "PA10", "PB3", "PB5", "PB4", "PB10", "PA8",
             "PA9", "PC7", "PB6", "PA7", "PA6", "PA5", "PB9", "PB8")
    timers = {3: "TIM2_CH2", 5: "TIM3_CH1", 6: "TIM2_CH3", 10: "TIM4_CH1",
              9: "TIM8_CH2" if variant == "f446re" else "TIM3_CH2",
              11: {"f103rb": "TIM3_CH2", "f401re": "TIM1_CH1N",
                   "f446re": "TIM14_CH1"}[variant]}
    peripherals = {0: "USART2_RX", 1: "USART2_TX", 10: "SPI1_CS",
                   11: "SPI1_MOSI", 12: "SPI1_MISO", 13: "SPI1_SCK",
                   14: "I2C1_SDA", 15: "I2C1_SCL"}
    for digital, port in enumerate(ports):
        if digital < 8:
            connector, physical, position = "CN9", digital + 1, 17 - digital
        else:
            connector = "CN5"
            physical = digital - 7 if digital < 14 else digital - 5
            position = 10 - physical
        functions = ("GPIO", port)
        if digital in timers:
            functions += (timers[digital],)
        if digital in peripherals:
            functions += (peripherals[digital],)
        if digital in (0, 1):
            functions += ("USART2 solder-bridge configuration",)
        result.append(_pin(f"D{digital}", f"{connector}.{physical} · D{digital} / {port}",
                           functions, "signal", "right", position))
    result.extend((
        _pin("AREF", "CN5.8 · AREF / AVDD", ("Analog reference",), "other", "right", 2),
        _pin("GND_CN5_7", "CN5.7 · GND", ("GND",), "ground", "right", 3),
    ))
    return tuple(result)


def _pico_pins() -> tuple[BoardPin, ...]:
    gpio_at_pin = {1: 0, 2: 1, 4: 2, 5: 3, 6: 4, 7: 5, 9: 6, 10: 7,
                   11: 8, 12: 9, 14: 10, 15: 11, 16: 12, 17: 13,
                   19: 14, 20: 15, 21: 16, 22: 17, 24: 18, 25: 19,
                   26: 20, 27: 21, 29: 22, 31: 26, 32: 27, 34: 28}
    # Peripheral names taken from the official Pico R3 A4 pinout, not exhaustive
    # RP2040 alternate-function claims. PIO/PWM require program configuration.
    special = {
        0: ("UART0 TX", "I2C0 SDA", "SPI0 RX"),
        1: ("UART0 RX", "I2C0 SCL", "SPI0 CSn"),
        2: ("I2C1 SDA", "SPI0 SCK"), 3: ("I2C1 SCL", "SPI0 TX"),
        4: ("UART1 TX", "I2C0 SDA", "SPI0 RX"),
        5: ("UART1 RX", "I2C0 SCL", "SPI0 CSn"),
        6: ("I2C1 SDA", "SPI0 SCK"), 7: ("I2C1 SCL", "SPI0 TX"),
        8: ("UART1 TX", "I2C0 SDA", "SPI1 RX"),
        9: ("UART1 RX", "I2C0 SCL", "SPI1 CSn"),
        10: ("I2C1 SDA", "SPI1 SCK"), 11: ("I2C1 SCL", "SPI1 TX"),
        12: ("UART0 TX", "I2C0 SDA", "SPI1 RX"),
        13: ("UART0 RX", "I2C0 SCL", "SPI1 CSn"),
        14: ("I2C1 SDA", "SPI1 SCK"), 15: ("I2C1 SCL", "SPI1 TX"),
        16: ("UART0 TX", "I2C0 SDA", "SPI0 RX"),
        17: ("UART0 RX", "I2C0 SCL", "SPI0 CSn"),
        18: ("I2C1 SDA", "SPI0 SCK"), 19: ("I2C1 SCL", "SPI0 TX"),
        20: ("I2C0 SDA",), 21: ("I2C0 SCL",),
        26: ("ADC0", "I2C1 SDA"), 27: ("ADC1", "I2C1 SCL"), 28: ("ADC2",),
    }
    result: list[BoardPin] = []
    for physical in range(1, 41):
        side: PinSide = "left" if physical <= 20 else "right"
        position = physical - 1 if physical <= 20 else 40 - physical
        if physical in gpio_at_pin:
            gpio = gpio_at_pin[physical]
            result.append(_pin(f"GP{gpio}", f"Pin {physical} · GP{gpio}",
                               ("GPIO", "PIO", "PWM") + special.get(gpio, ()),
                               "signal", side, position))
        elif physical in (3, 8, 13, 18, 23, 28, 33, 38):
            label = "AGND" if physical == 33 else "GND"
            result.append(_pin(f"{label}_{physical}", f"Pin {physical} · {label}",
                               (label,), "ground", side, position))
        else:
            key, label, functions, kind = {
                30: ("RUN", "RUN", ("Reset / run control",), "reset"),
                35: ("ADC_VREF", "ADC_VREF", ("ADC reference",), "other"),
                36: ("3V3_OUT", "3V3(OUT)", ("3.3 V output rail",), "power"),
                37: ("3V3_EN", "3V3_EN", ("Regulator enable",), "other"),
                39: ("VSYS", "VSYS", ("System supply input",), "power"),
                40: ("VBUS", "VBUS", ("USB VBUS rail",), "power"),
            }[physical]
            result.append(_pin(key, f"Pin {physical} · {label}", functions,
                               kind, side, position))
    return tuple(result)


_SCHEMATIC_NOTE = (
    "Functional header diagram, not a dimensioned PCB layout. "
    "Logic voltage is not a supply-input rating. Peripheral functions require "
    "firmware/OS configuration; this does not simulate firmware. "
    f"Official source checked {SOURCE_CHECKED_DATE}."
)
_NUCLEO_NOTE = (
    "MB1136 board, Arduino CN5/CN9/CN6/CN8 headers only; excludes Morpho, "
    "ST-LINK and debug headers. Default A4=PC1 and A5=PC0; solder-bridge "
    "changes can route them to PB9/PB8 for I2C. Consult UM1724 Rev 17 "
    "Table 10 before altering bridges. D0/D1 header access requires the "
    "appropriate SB62/SB63 configuration; ST-LINK VCP bridges SB13/SB14 "
    "can disconnect the header path. " + _SCHEMATIC_NOTE
)
_SCHEMATIC_NOTE_KO = (
    "헤더 연결용 모식도이며 치수가 있는 PCB 배치도가 아닙니다. "
    "GPIO 논리 전압은 보드 전원 입력 정격과 다릅니다. 주변 기능은 펌웨어/OS "
    "설정이 필요하며 펌웨어 실행을 시뮬레이션하지 않습니다. "
    f"공식 자료 확인일 {SOURCE_CHECKED_DATE}."
)
_NUCLEO_NOTE_KO = (
    "MB1136 보드의 Arduino CN5/CN9/CN6/CN8 헤더만 표시하며 Morpho/ST-LINK/"
    "디버그 헤더는 제외합니다. 기본 A4=PC1, A5=PC0이며 솔더 브리지를 변경하면 "
    "I2C PB9/PB8로 연결할 수 있습니다. 변경 전 UM1724 Rev 17 표 10을 확인하세요. "
    "D0/D1 헤더 접근은 SB62/SB63 설정을 확인해야 하며 ST-LINK VCP용 "
    "SB13/SB14 연결 시 헤더 경로가 분리될 수 있습니다. "
    + _SCHEMATIC_NOTE_KO
)

PINOUTS: tuple[BoardPinout, ...] = (
    BoardPinout("rpi3bplus", "Raspberry Pi 3 Model B+", _RPI_SOURCE, _rpi_pins(), 3.3,
                "40핀 J8 헤더의 실제 핀 번호와 BCM GPIO 이름입니다. GPIO0/GPIO1은 "
                "HAT EEPROM용 참고 핀입니다. " + _SCHEMATIC_NOTE_KO,
                "40-pin J8 header, physical numbers and BCM GPIO labels. "
                "GPIO0/GPIO1 ID EEPROM pins are reference-only. " + _SCHEMATIC_NOTE),
    BoardPinout("rpi4b", "Raspberry Pi 4 Model B", _RPI_SOURCE, _rpi_pins(), 3.3,
                "40핀 J8 헤더의 실제 핀 번호와 BCM GPIO 이름입니다. GPIO0/GPIO1은 "
                "HAT EEPROM용 참고 핀입니다. " + _SCHEMATIC_NOTE_KO,
                "40-pin J8 header, physical numbers and BCM GPIO labels. "
                "GPIO0/GPIO1 ID EEPROM pins are reference-only. " + _SCHEMATIC_NOTE),
    BoardPinout("arduino_uno_r3", "Arduino UNO Rev3", _UNO_SOURCE, _uno_pins(), 5.0,
                "JANALOG/JDIGITAL 주 헤더만 표시하며 ICSP/USB 브리지 프로그래밍 "
                "헤더는 제외합니다. SDA와 A4, SCL과 A5는 각각 같은 전기적 핀입니다. "
                + _SCHEMATIC_NOTE_KO,
                "Main JANALOG/JDIGITAL headers only; excludes ICSP and USB bridge "
                "programming headers. SDA is the same net as A4; SCL as A5. " + _SCHEMATIC_NOTE),
    BoardPinout("arduino_mega2560_r3", "Arduino Mega 2560 Rev3", _MEGA_SOURCE,
                _mega_pins(), 5.0,
                "JANALOG/JDIGITAL/XIO LHS/RHS 주 헤더만 표시하며 ICSP/JP5/USB "
                "브리지 프로그래밍 패드는 제외합니다. SDA=D20, SCL=D21은 같은 "
                "전기적 핀입니다. XIO LHS/RHS.1-18 좌표는 설명서 5.5/5.6 절입니다. "
                + _SCHEMATIC_NOTE_KO,
                "Main JANALOG/JDIGITAL and XIO LHS/RHS headers only; excludes "
                "ICSP/JP5/USB bridge programming pads. SDA duplicates D20 and "
                "SCL duplicates D21. XIO LHS/RHS.1-18 coordinates follow manual "
                "sections 5.5/5.6. " + _SCHEMATIC_NOTE),
    BoardPinout("nucleo_f401re", "ST NUCLEO-F401RE", _ST_SOURCE,
                _nucleo_pins("f401re"), 3.3, "UM1724 Rev 17 표 16. " + _NUCLEO_NOTE_KO,
                "UM1724 Rev 17 Table 16. " + _NUCLEO_NOTE),
    BoardPinout("nucleo_f446re", "ST NUCLEO-F446RE", _ST_SOURCE,
                _nucleo_pins("f446re"), 3.3, "UM1724 Rev 17 표 19. " + _NUCLEO_NOTE_KO,
                "UM1724 Rev 17 Table 19. " + _NUCLEO_NOTE),
    BoardPinout("nucleo_f103rb", "ST NUCLEO-F103RB", _ST_SOURCE,
                _nucleo_pins("f103rb"), 3.3, "UM1724 Rev 17 표 12. " + _NUCLEO_NOTE_KO,
                "UM1724 Rev 17 Table 12. " + _NUCLEO_NOTE),
    BoardPinout("rpi_pico", "Raspberry Pi Pico (RP2040)", _PICO_SOURCE,
                _pico_pins(), 3.3,
                "기본형 Pico의 양쪽 40개 핀만 표시하며 SWD 패드와 내부 GPIO23/24/25는 "
                "제외합니다. Pico W/Pico 2의 핀 배치로 사용하지 마세요. "
                + _SCHEMATIC_NOTE_KO,
                "Original Pico, 40 edge pins only; excludes SWD pads and internal "
                "GPIO23/24/25. Not a Pico W or Pico 2 pinout. " + _SCHEMATIC_NOTE),
)
_G474_SOURCE='https://www.st.com/resource/en/user_manual/um2505-stm32g4-nucleo64-boards-mb1367-stmicroelectronics.pdf'
PINOUTS += (BoardPinout('st_nucleo_g474re','ST NUCLEO-G474RE · MB1367 selected Arduino / Morpho headers',_G474_SOURCE,(
    _pin('NC_CN6_1','CN6.1 · NC',('Reserved for test',),'other','left',0),
    _pin('IOREF_CN6_2','CN6.2 · IOREF',('I/O reference',),'other','left',1),
    _pin('NRST_CN6_3','CN6.3 · NRST',('PG10-NRST reset',),'reset','left',2),
    _pin('3V3_CN6_4','CN6.4 · 3V3',('3.3 V input/output; SB5 and external-supply configuration must be checked',),'power','left',3),
    _pin('5V_CN6_5','CN6.5 · 5V',('5 V output rail; not automatically a safe external input',),'power','left',4),
    _pin('GND_CN6_6','CN6.6 · GND',('GND',),'ground','left',5),
    _pin('GND_CN6_7','CN6.7 · GND',('GND',),'ground','left',6),
    _pin('VIN_CN6_8','CN6.8 · VIN',('7–12 V input; power-source jumpers must be checked',),'power','left',7),
    _pin('PA5','CN5.6 · D13 / PA5',('GPIO','SPI1_SCK','LD2 via SB6; disconnect SB6 if using this candidate SPI clock'),'signal','right',0),
    _pin('PA6','CN5.5 · D12 / PA6',('GPIO','SPI1_MISO'),'signal','right',1),
    _pin('PA7','CN5.4 · D11 / PA7',('GPIO','SPI1_MOSI','TIM3_CH2'),'signal','right',2),
    _pin('PB6','CN5.3 · D10 / PB6',('GPIO','SPIx_CS','TIM4_CH1','PA9 high can enable UCPD1_CC1 dead-battery Rd; PWR_CR3.UCPD1_DBDIS=1 disables it'),'signal','right',3),
    _pin('PC7','CN5.2 · D9 / PC7',('GPIO','TIM3_CH2 or TIM8_CH2'),'signal','right',4),
    _pin('PB5','CN9.5 · D4 / PB5',('GPIO',),'signal','right',5),
    _pin('GND_CN5_7','CN5.7 · GND',('GND',),'ground','right',6),
    _pin('E5V_CN7_6','CN7.6 · E5V',('External input 4.75–5.25 V; 500 mA maximum; JP5 pins 5–6; external supply before USB',),'power','left',8),
    _pin('PA11','CN10.14 · PA11',('GPIO','FDCAN1_RX','AF9: FDCAN1_RX','LQFP64 pad 45; target MCU pin, not ST-LINK USB'),'signal','right',7),
    _pin('PA12','CN10.12 · PA12',('GPIO','FDCAN1_TX','AF9: FDCAN1_TX','LQFP64 pad 46; target MCU pin, not ST-LINK USB'),'signal','right',8),
    _pin('PB10','CN10.25 · PB10',('GPIO','USART3_TX','AF7: USART3_TX','LQFP64 pad 30; CN9.7 / D6 is the same GPIO'),'signal','right',9),
    _pin('PB11','CN10.18 · PB11',('GPIO','USART3_RX','AF7: USART3_RX','LQFP64 pad 33'),'signal','right',10),
    _pin('PB12','CN10.16 · PB12',('GPIO','LQFP64 pad 34'),'signal','right',11),
    _pin('PB8','CN10.3 · PB8',('GPIO','I2C1_SCL','AF4: I2C1_SCL','LQFP64 pad 61; CN5.10 / D15 is the same GPIO','BOOT0 shared; inspect JP7/SB4 and option bytes; I2C requires open-drain configuration'),'signal','right',12),
    _pin('PB9','CN10.5 · PB9',('GPIO','I2C1_SDA','AF4: I2C1_SDA','LQFP64 pad 62; CN5.9 / D14 is the same GPIO','Optional CN8.5 / A4 route via SB34 replaces PC1; I2C requires open-drain configuration'),'signal','right',13),
    _pin('PC6','CN10.4 · PC6',('GPIO','LQFP64 pad 38'),'signal','right',14),
    _pin('PA8','CN10.23 · PA8',('GPIO','TIM1_CH1','AF6: TIM1_CH1; input capture or output compare/PWM','LQFP64 pad 42; CN9.8 / D7 is the same GPIO'),'signal','left',9),
    _pin('PA9','CN10.21 · PA9',('GPIO','TIM1_CH2','AF6: TIM1_CH2; input capture or output compare/PWM','LQFP64 pad 43; CN5.1 / D8 is the same GPIO','UCPD1_DBCC1: high PA9 can enable PB6 dead-battery Rd; PWR_CR3.UCPD1_DBDIS=1 disables it'),'signal','left',10),
    _pin('PC0','CN7.38 · PC0',('GPIO','LQFP64 pad 8; CN8.6 / A5 shares this selected route','SB36 selects PC0; SB37 selects PA15 instead; inspect fitted bridges'),'signal','left',11),
    _pin('PC1','CN7.36 · PC1',('GPIO','LQFP64 pad 9; CN8.5 / A4 shares this selected route','SB35 selects PC1; SB34 selects PB9 instead; inspect fitted bridges'),'signal','left',12),
    _pin('PC2','CN7.35 · PC2',('GPIO','LQFP64 pad 10'),'signal','left',13),
    _pin('PC3','CN7.37 · PC3',('GPIO','LQFP64 pad 11'),'signal','left',14),
    _pin('PB0','CN7.34 · PB0',('GPIO','LQFP64 pad 24; CN8.4 / A3 is the same GPIO'),'signal','left',15),
    _pin('PB1','CN10.24 · PB1',('GPIO','LQFP64 pad 25'),'signal','left',16),
),3.3,
    'UM2505 Rev 7 표 15·16의 선택 Arduino/Morpho 단자와 표 7 E5V, DS12288 Rev 6의 LQFP64 핀·선택 AF입니다. 전체 보드 배치는 아닙니다. 중복 헤더는 같은 GPIO입니다. PC0/PC1은 SB36/35 선택 경로이며 PA15/PB9 대체 경로와 실장 브리지를 확인하세요. PB8은 BOOT0와 공유합니다. PA5는 LD2/SB6, PA9·PB6은 UCPD dead-battery Rd와 관련되며 PWR_CR3.UCPD1_DBDIS=1 조건을 확인하세요. E5V는 4.75–5.25 V·500 mA, JP5 5–6, 외부 전원 먼저·USB 나중입니다. 보드 리비전·I/O 전압·펌웨어·별도 ADC CLKIN 발진기를 확인하세요. 확인일 2026-10-10.',
    'Selected Arduino/Morpho terminals: UM2505 Rev 7 Tables 15/16 and E5V Table 7; LQFP64 pads/selected AFs: DS12288 Rev 6. Not a full board map and not a dimensioned PCB layout. Duplicate headers share one GPIO. PC0/PC1 require SB36/35 routes; check PA15/PB9 alternatives and fitted bridges. PB8 shares BOOT0. PA5 shares LD2/SB6. PA9 can enable PB6 dead-battery Rd; check PWR_CR3.UCPD1_DBDIS=1. E5V: 4.75–5.25 V, 500 mA maximum, JP5 pins 5–6, external power before USB. Confirm board revision, I/O voltage, firmware and separate ADC CLKIN oscillator. Official source checked 2026-10-10.'),)
PINOUTS += (
    BoardPinout(
        "rpi_zero2w", "Raspberry Pi Zero 2 W · J8",
        "https://datasheets.raspberrypi.com/rpizero2/raspberry-pi-zero-2-w-reduced-schematics.pdf",
        _rpi_pins(), 3.3,
        "공식 PiZero 2 W R1 회로도의 J8 40개 패드 번호·BCM GPIO입니다. J8는 DNF로 표시되므로 "
        "헤더가 실제 장착됐는지 확인하세요. ID_SD/ID_SC는 EEPROM용 참고 단자입니다. "
        + _SCHEMATIC_NOTE_KO.replace(SOURCE_CHECKED_DATE, "2026-10-07"),
        "J8's 40 physical pads and BCM GPIOs checked against the PiZero 2 W R1 reduced schematic. "
        "J8 is marked DNF: confirm the fitted header. ID_SD/ID_SC are EEPROM reference pins. "
        + _SCHEMATIC_NOTE.replace(SOURCE_CHECKED_DATE, "2026-10-07")),
    BoardPinout(
        "rpi_pico2", "Raspberry Pi Pico 2 · RP2350",
        "https://datasheets.raspberrypi.com/pico/pico-2-datasheet.pdf",
        _pico_pins(), 3.3,
        "Pico 2 데이터시트 2026-07-03판 그림 2·4와 3.1절에서 40개 가장자리 단자와 표시된 UART/I2C/SPI/ADC "
        "기능을 별도로 확인했습니다. SWD·내부 GP23/24/25/29는 제외합니다. GPIO는 3.3 V로 고정이며 "
        "칩의 1.8 V I/O 가능성을 보드에 적용하지 않습니다. "
        + _SCHEMATIC_NOTE_KO.replace(SOURCE_CHECKED_DATE, "2026-10-07"),
        "40 edge pins and depicted UART/I2C/SPI/ADC functions independently checked against Pico 2 "
        "datasheet 2026-07-03, Figures 2/4 and §3.1. Excludes SWD and internal GP23/24/25/29. "
        "Board I/O is fixed at 3.3 V; the chip's optional 1.8 V I/O is not applicable here. "
        + _SCHEMATIC_NOTE.replace(SOURCE_CHECKED_DATE, "2026-10-07")),
)

_BY_ID = {pinout.catalog_id: pinout for pinout in PINOUTS}


def board_pinout(catalog_id: str) -> BoardPinout | None:
    """Return an exact known model; family or unverified clone IDs return None."""
    return _BY_ID.get(catalog_id)


def available_pinouts() -> tuple[BoardPinout, ...]:
    """Stable offline references; no network access or heavyweight GUI import."""
    return PINOUTS
