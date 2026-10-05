"""Small, source-linked electrical parts index for the native CAD workbench.

Catalog entries are references, not electrical models. A recommended power
supply current, an absolute maximum, and a motor stall current are *not* the
part's operating current. We deliberately leave the DC load current unset
unless a particular operating point is documented and appropriate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CircuitKind = Literal["battery", "wire", "switch", "resistor", "capacitor", "inductor",
                      "load", "motor", "actuator", "mcu"]
ElectricalFunction = Literal["motor", "actuator", "encoder", "motor_driver", "controller", "load_cell", "adc", "humidity_temperature"]


@dataclass(frozen=True, slots=True)
class ElectricalCatalogEntry:
    catalog_id: str
    category: str
    manufacturer: str
    model: str
    series: str
    source_url: str
    spec_summary: str
    suggested_kind: CircuitKind | None = None
    nominal_voltage_v: float | None = None
    rated_current_a: float | None = None
    reference_only: bool = False
    aliases: tuple[str, ...] = ()
    resistance_ohm: float | None = None
    capacitance_f: float | None = None
    inductance_h: float | None = None
    winding_resistance_ohm: float | None = None
    capacitor_polarized: bool = False
    # Passive withstand voltage is distinct from a battery source or a
    # motor's operating point. A capacitor must never create a voltage source.
    rated_voltage_v: float | None = None
    # Product functions are independent of the simplified DC circuit kind.
    # An ESC or standalone encoder is not a generic MCU load, and one product
    # can contain both a motor and an encoder. Family rows have no inferred role.
    functional_roles: tuple[ElectricalFunction, ...] = ()
    encoder_interface: Literal["quadrature", "absolute_i2c"] | None = None
    # Quadrature counts use all four edges of both A/B channels per revolution
    # of the named shaft. P/R and gearbox-output counts must not be conflated.
    encoder_counts_per_rev: int | None = None
    encoder_reference: Literal["motor_shaft", "encoder_shaft"] | None = None
    motor_gear_ratio: float | None = None

    @property
    def display_name(self) -> str:
        return f"{self.manufacturer} {self.model}"


# Exact product links were checked against manufacturer or supplier documentation. The
# model's source URL and catalog ID travel with the saved electrical component.
# Family rows provide discovery links only; their pins and ratings vary by SKU.
CATALOG: tuple[ElectricalCatalogEntry, ...] = (
    ElectricalCatalogEntry(
        "rpi3bplus", "MPU 보드", "Raspberry Pi", "3 Model B+", "Raspberry Pi 3",
        "https://www.raspberrypi.com/products/raspberry-pi-3-model-b-plus/",
        "5 V 전원, 권장 공급기 2.5 A, 40핀 헤더. 2.5 A는 보드의 고정 소비전류가 아닙니다. 일반 GPIO는 3.3 V 신호입니다.",
        "mcu", 5.0, aliases=("raspberry pi 3 b+", "라즈베리파이 3 b+", "라즈베리파이 3b+"),
    ),
    ElectricalCatalogEntry(
        "rpi4b", "MPU 보드", "Raspberry Pi", "4 Model B", "Raspberry Pi 4",
        "https://www.raspberrypi.com/products/raspberry-pi-4-model-b/specifications/",
        "5 V USB-C 또는 GPIO 입력, 최소 3 A 공급기, 40핀 헤더. 3 A는 보드의 고정 소비전류가 아닙니다. 일반 GPIO는 3.3 V 신호입니다.",
        "mcu", 5.0, aliases=("raspberry pi 4", "라즈베리파이 4", "rpi4"),
    ),
    ElectricalCatalogEntry(
        "rpi5", "MPU 보드", "Raspberry Pi", "5", "Raspberry Pi 5",
        "https://www.raspberrypi.com/products/raspberry-pi-5/",
        "5 V 전원, 권장 공급기 5 A, 40핀 헤더. 5 A는 보드 고정 소비전류가 아닙니다.",
        "mcu", 5.0, aliases=("raspberry pi 5", "라즈베리파이 5"),
    ),
    ElectricalCatalogEntry(
        "rpi_zero2w", "MPU 보드", "Raspberry Pi", "Zero 2 W", "Raspberry Pi Zero",
        "https://datasheets.raspberrypi.com/product/product-catalogue-2023.pdf",
        "5 V micro-USB 전원. 연결된 2023 제품 목록은 2 A 공급기를 제시하지만 공식 안내 문서별 권장값은 다를 수 있습니다. 40개 GPIO 패드는 기본 미장착이며 공급기 정격은 소비전류가 아닙니다.",
        "mcu", 5.0, aliases=("raspberry pi zero 2 w", "라즈베리파이 제로"),
    ),
    ElectricalCatalogEntry(
        "rpi_pico", "MCU 보드", "Raspberry Pi", "Pico", "Raspberry Pi Pico",
        "https://www.raspberrypi.com/products/raspberry-pi-pico/",
        "VSYS 전원 입력 범위 1.8–5.5 V. 연결 방식에 따라 실제 공급 전압·소비전류가 달라집니다.",
        "mcu", aliases=("rp2040", "라즈베리파이 피코"),
    ),
    ElectricalCatalogEntry(
        "rpi_pico2", "MCU 보드", "Raspberry Pi", "Pico 2", "Raspberry Pi Pico 2",
        "https://datasheets.raspberrypi.com/pico/pico-2-product-brief.pdf",
        "VSYS 전원 입력 범위 1.8–5.5 V. 연결 방식에 따라 실제 공급 전압·소비전류가 달라집니다.",
        "mcu", aliases=("rp2350", "라즈베리파이 피코 2"),
    ),
    ElectricalCatalogEntry(
        "stm32_nucleo_family", "MCU 보드", "STMicroelectronics", "STM32 Nucleo 보드 제품군", "STM32 Nucleo",
        "https://www.st.com/en/evaluation-tools/stm32-nucleo-boards/products.html",
        "Nucleo-32/64/144와 MCU별 전원·핀 사양이 다릅니다. 정확한 보드 주문 코드를 선택하세요.",
        reference_only=True, aliases=("stm", "stm32", "nucleo", "뉴클레오"),
    ),
    ElectricalCatalogEntry(
        "stm32g0_family", "MCU 제품군", "STMicroelectronics", "STM32G0 제품 선택기", "STM32G0",
        "https://www.st.com/en/microcontrollers-microprocessors/stm32g0-series.html",
        "G0x0/G0x1과 패키지·주문 코드별 핀·전원·소비전류가 다릅니다. 정확한 칩 번호를 선택하세요.",
        reference_only=True, aliases=("stm32", "stm", "g0", "m0+"),
    ),
    ElectricalCatalogEntry(
        "stm32g4_family", "MCU 제품군", "STMicroelectronics", "STM32G4 제품 선택기", "STM32G4",
        "https://www.st.com/en/microcontrollers-microprocessors/stm32g4-series/products.html",
        "모터 제어에 자주 쓰이는 G4 제품군입니다. 전기 정격·핀·패키지는 정확 SKU별 자료를 확인하세요.",
        reference_only=True, aliases=("stm32", "stm", "g4", "motor control"),
    ),
    ElectricalCatalogEntry(
        "stm32f4_family", "MCU 제품군", "STMicroelectronics", "STM32F4 제품 선택기", "STM32F4",
        "https://www.st.com/en/microcontrollers-microprocessors/stm32F4-series/products.html",
        "STM32F4의 정확한 칩·보드 변형을 선택하세요. 제품군 하나에 소비전류나 GPIO 한계를 공통값으로 붙이지 않습니다.",
        reference_only=True, aliases=("stm32", "stm", "f4"),
    ),
    ElectricalCatalogEntry(
        "stm32h7_family", "MCU 제품군", "STMicroelectronics", "STM32H7 제품 선택기", "STM32H7",
        "https://www.st.com/en/microcontrollers-microprocessors/stm32h7-series/products.html",
        "H7 칩·보드·전원 방식별 사양을 정확한 주문 코드로 확인하세요.",
        reference_only=True, aliases=("stm32", "stm", "h7"),
    ),
    ElectricalCatalogEntry(
        "stm32u5_family", "MCU 제품군", "STMicroelectronics", "STM32U5 제품 선택기", "STM32U5",
        "https://www.st.com/en/microcontrollers-microprocessors/stm32U5-series/products.html",
        "U5 변형별 핀·전원·저전력 모드 전류가 다릅니다. 동작 모드와 정확 SKU를 확인하세요.",
        reference_only=True, aliases=("stm32", "stm", "u5", "low power"),
    ),
    ElectricalCatalogEntry(
        "stm32mp1_family", "MPU 제품군", "STMicroelectronics", "STM32MP1 제품 선택기", "STM32MP1",
        "https://www.st.com/en/microcontrollers-microprocessors/stm32mp1-series.html",
        "MPU 칩·모듈·개발 보드별 다중 전원 레일이 다릅니다. 단일 2단자 MCU 부하로 자동 변환하지 않습니다.",
        reference_only=True, aliases=("stm32", "stm", "mpu", "mp1"),
    ),
    ElectricalCatalogEntry(
        "stm32f103c8t6", "MCU 칩", "STMicroelectronics", "STM32F103C8T6 칩", "STM32F1",
        "https://www.st.com/en/microcontrollers-microprocessors/stm32f103c8",
        "STM32F103C8T6 칩 자료입니다. Blue Pill 등 제3자 보드의 회로·커넥터 사양을 보증하지 않습니다.",
        reference_only=True, aliases=("blue pill", "블루필", "stm32f103"),
    ),
    ElectricalCatalogEntry(
        "nucleo_g0b1re", "MCU 보드", "STMicroelectronics", "NUCLEO-G0B1RE", "STM32 Nucleo-64",
        "https://www.st.com/en/evaluation-tools/nucleo-g0b1re.html",
        "STM32G0B1RE 기반 Nucleo-64 보드. 사용자의 실제 STM32 보드 모델로 추정하지 않습니다. 전원 점퍼·핀·소비전류는 보드 설명서 확인이 필요합니다.",
        "mcu", aliases=("stm32 g0b1", "stm32 nucleo"),
    ),
    ElectricalCatalogEntry(
        "nucleo_f446re", "MCU 보드", "STMicroelectronics", "NUCLEO-F446RE", "STM32 Nucleo-64",
        "https://www.st.com/en/evaluation-tools/nucleo-f446re.html",
        "STM32F446RE 기반 Nucleo-64 보드. 전원 점퍼·핀·소비전류는 보드 설명서 확인이 필요합니다.",
        "mcu", aliases=("stm32 f446", "stm32 nucleo"),
    ),
    ElectricalCatalogEntry(
        "nucleo_f103rb", "MCU 보드", "STMicroelectronics", "NUCLEO-F103RB", "STM32 Nucleo-64",
        "https://www.st.com/en/evaluation-tools/nucleo-f103rb.html",
        "STM32F103RB 기반 Nucleo-64 보드. 전원 점퍼·실제 소비전류를 보드 설명서와 사용 조건으로 확인하세요.",
        "mcu", aliases=("stm32 f103", "stm32 nucleo"),
    ),
    ElectricalCatalogEntry(
        "nucleo_f401re", "MCU 보드", "STMicroelectronics", "NUCLEO-F401RE", "STM32 Nucleo-64",
        "https://www.st.com/en/evaluation-tools/nucleo-f401re.html",
        "STM32F401RE 기반 Nucleo-64 보드. 보드의 전원 점퍼·핀·소비전류는 해당 사용자 설명서로 확인하세요.",
        "mcu", aliases=("stm32 f401", "stm32 nucleo"),
    ),
    ElectricalCatalogEntry(
        "nucleo_l476rg", "MCU 보드", "STMicroelectronics", "NUCLEO-L476RG", "STM32 Nucleo-64",
        "https://www.st.com/en/evaluation-tools/nucleo-l476rg.html",
        "STM32L476RG 기반 Nucleo-64 보드. 저전력 모드별 소비전류와 보드 자체 소비전류를 구분하세요.",
        "mcu", aliases=("stm32 l476", "stm32 nucleo"),
    ),
    ElectricalCatalogEntry(
        "nucleo_h753zi", "MCU 보드", "STMicroelectronics", "NUCLEO-H753ZI", "STM32 Nucleo-144",
        "https://www.st.com/en/evaluation-tools/nucleo-h753zi.html",
        "STM32H753ZI 기반 Nucleo-144 보드. H743ZI와 다른 제품입니다. 보드 전원·핀·소비전류는 해당 설명서를 확인하세요.",
        "mcu", aliases=("stm32 h753", "stm32 nucleo"),
    ),
    ElectricalCatalogEntry(
        "b_l475e_iot01a", "MCU 보드", "STMicroelectronics", "B-L475E-IOT01A", "STM32 Discovery IoT",
        "https://www.st.com/en/evaluation-tools/b-l475e-iot01a.html",
        "STM32L475E 기반 Discovery IoT 보드. ST가 NRND로 표시합니다. 사용자의 'B' 보드로 단정하지 않으며 전원·핀은 정확한 보드 도면을 확인하세요.",
        reference_only=True, aliases=("stm b", "stm32 b", "discovery", "b-l475"),
    ),
    ElectricalCatalogEntry(
        "b_l4s5i_iot01a", "MCU 보드", "STMicroelectronics", "B-L4S5I-IOT01A", "STM32 Discovery IoT",
        "https://www.st.com/en/evaluation-tools/b-l4s5i-iot01a.html",
        "STM32L4+ Discovery IoT 보드. ST가 NRND로 표시합니다. 실제 보드 모델과 핀·전원 구성을 확인하세요.",
        reference_only=True, aliases=("stm b", "stm32 b", "discovery", "b-l4s5"),
    ),
    ElectricalCatalogEntry(
        "b_u585i_iot02a", "MCU 보드", "STMicroelectronics", "B-U585I-IOT02A", "STM32 Discovery IoT",
        "https://www.st.com/en/evaluation-tools/b-u585i-iot02a.html",
        "STM32U585AI 기반 Discovery IoT 보드. 'B' 보드 후보 자료이며 사용자의 실제 모델로 단정하지 않습니다.",
        reference_only=True, aliases=("stm b", "stm32 b", "discovery", "b-u585"),
    ),
    ElectricalCatalogEntry(
        "arduino_uno_r3", "MCU 보드", "Arduino", "UNO Rev3", "UNO",
        "https://docs.arduino.cc/hardware/uno-rev3/",
        "UNO Rev3 공식 하드웨어 자료. 실제 공급 경로와 보드 소비전류를 확인한 뒤 회로에 입력하세요.",
        "mcu", aliases=("arduino", "아두이노", "uno r3"),
    ),
    ElectricalCatalogEntry(
        "arduino_uno_r4_wifi", "MCU 보드", "Arduino", "UNO R4 WiFi", "UNO R4",
        "https://docs.arduino.cc/hardware/uno-r4-wifi",
        "5 V GPIO, VIN 6–24 V. VIN 허용 범위와 MCU 동작 전압은 서로 다른 사양입니다. 보드 실제 소비전류는 구성에 따라 측정하세요.",
        "mcu", aliases=("arduino", "아두이노", "uno"),
    ),
    ElectricalCatalogEntry(
        "arduino_nano_esp32", "MCU 보드", "Arduino", "Nano ESP32", "Nano",
        "https://docs.arduino.cc/resources/datasheets/ABX00083-datasheet.pdf",
        "3.3 V GPIO, VIN 6–21 V. 공급 입력 범위와 GPIO 전압은 서로 다른 사양이며 회로 부하전류는 직접 확인하세요.",
        "mcu", aliases=("arduino", "아두이노", "esp32"),
    ),
    ElectricalCatalogEntry(
        "arduino_mega2560_r3", "MCU 보드", "Arduino", "Mega 2560 Rev3", "Mega",
        "https://docs.arduino.cc/hardware/mega-2560/",
        "ATmega2560 기반 보드, 디지털 핀 54개·아날로그 입력 16개. 실제 전원 경로와 소비전류를 확인한 뒤 입력하세요.",
        "mcu", aliases=("arduino", "아두이노", "mega"),
    ),
    ElectricalCatalogEntry(
        "arduino_nano_every", "MCU 보드", "Arduino", "Nano Every", "Nano",
        "https://docs.arduino.cc/hardware/nano-every",
        "ATmega4809 기반 Nano 계열. 기존 Nano와 비슷한 핀 배치를 쓰지만 회로·전원 조건을 제품 자료로 확인하세요.",
        "mcu", aliases=("arduino", "아두이노", "nano"),
    ),
    ElectricalCatalogEntry(
        "arduino_nano33_ble_rev2", "MCU 보드", "Arduino", "Nano 33 BLE Rev2", "Nano 33 BLE",
        "https://docs.arduino.cc/hardware/nano-33-ble-rev2",
        "nRF52840·9축 IMU가 있는 Rev2 제품입니다. 핀 전압과 소비전류는 정확한 Rev2 자료 및 사용 모드로 확인하세요.",
        "mcu", aliases=("arduino", "아두이노", "nano", "ble"),
    ),
    ElectricalCatalogEntry(
        "arduino_giga_r1_wifi", "MCU 보드", "Arduino", "GIGA R1 WiFi", "GIGA",
        "https://docs.arduino.cc/hardware/giga-r1-wifi",
        "STM32H747XI 기반 보드입니다. USB-C/외부 전원 경로와 GPIO 핀 정격을 제품 도면으로 확인하세요.",
        "mcu", aliases=("arduino", "아두이노", "giga", "stm32"),
    ),
    ElectricalCatalogEntry(
        "arduino_nano_classic", "MCU 보드", "Arduino", "Nano (classic)", "Nano",
        "https://docs.arduino.cc/hardware/nano/",
        "고전 Nano 보드의 공식 핀·회로 자료. 다른 Nano 변형과 핀 전압·전원 경로를 혼동하지 마세요.",
        "mcu", aliases=("arduino", "아두이노", "classic nano"),
    ),
    ElectricalCatalogEntry(
        "esp32_devkitc_v4", "MCU 보드", "Espressif", "ESP32-DevKitC V4", "ESP32-DevKitC",
        "https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html",
        "모듈·헤더 변형이 있는 개발 보드입니다. 실제 모듈 번호와 전원/핀 회로를 확인하세요.",
        "mcu", aliases=("esp32", "devkit", "에스프레시프"),
    ),
    ElectricalCatalogEntry(
        "ti_drv8833", "모터 드라이버", "Texas Instruments", "DRV8833", "DRV8833",
        "https://www.ti.com/product/DRV8833",
        "모터 공급 VM 2.7–10.8 V. 1.5 A RMS·2 A 피크는 PWP/RTY 패키지 조건이며 열 설계에 좌우됩니다. 드라이버 회로 모델은 아직 미지원입니다.",
        reference_only=True, aliases=("h bridge", "h-bridge", "h브리지", "구동기"),
        functional_roles=("motor_driver",),
    ),
    ElectricalCatalogEntry(
        "st_b_g431b_esc1", "STM32 ESC / 모터 드라이버 보드", "STMicroelectronics", "B-G431B-ESC1", "STM32G431CB ESC",
        "https://www.st.com/resource/en/user_manual/dm00564746-electronic-speed-controller-discovery-kit-for-drones-with-stm32g431cb-stmicroelectronics.pdf",
        "STM32G431CB 기반 3상 BLDC/PMSM ESC. 3S–6S LiPo 입력, PWM/UART/CAN과 J8 Hall/쿼드러처 엔코더 단자. 40 A 피크는 프로펠러 강제 냉각 시험 조건이며 연속 전류·보드 소비전류가 아닙니다. BEC는 딸림 보드 상태를 확인합니다. 첫 사용에는 MCSDK/Workbench로 센서와 FOC 펌웨어를 구성해야 하며 실제 FOC/PWM 동작 해석은 미지원입니다.",
        reference_only=True, aliases=("b-g431b-esc1", "b g431b esc1", "b-g431", "stm32g431", "g431b", "stm b", "stm32 b", "esc", "st esc"),
        functional_roles=("motor_driver", "controller"),
    ),
    ElectricalCatalogEntry(
        "st_evspin32g4", "STM32 모터 제어 평가 보드", "STMicroelectronics", "EVSPIN32G4", "STSPIN32G4",
        "https://www.st.com/en/evaluation-tools/evspin32g4.html",
        "STSPIN32G4/STM32G431 기반 3상 모터 제어 평가 보드. DC 버스 10–75 V, 디지털 Hall/쿼드러처 엔코더 입력과 ST Motor Control SDK 지원. 20 A RMS는 방열판 조건이며 보드 소비전류가 아닙니다. 단자별 핀 매핑과 실제 FOC 펌웨어 실행은 별도 검증이 필요합니다.",
        reference_only=True, aliases=("evspin", "stm32 esc", "stspin32g4", "foc", "모터 제어"),
        functional_roles=("motor_driver", "controller"),
    ),
    ElectricalCatalogEntry(
        "pololu_2130", "모터 드라이버 보드", "Pololu", "#2130 DRV8833 Dual Motor Driver Carrier", "DRV8833 carrier",
        "https://www.pololu.com/product/2130",
        "정확한 Pololu #2130 보드의 단자명이 확인됩니다. 모터 전원 2.7–10.8 V, 약 1.2 A 연속/2 A 피크는 채널·방열 조건입니다. TI 칩 패키지나 다른 DRV8833 모듈과 구분하며 H 브리지/PWM 동작 해석은 미지원입니다.",
        reference_only=True, aliases=("drv8833", "motor driver", "드라이버 보드", "h브리지", "pololu 2130"),
        functional_roles=("motor_driver",),
    ),
    ElectricalCatalogEntry(
        "toshiba_tb6612fng", "모터 드라이버", "Toshiba", "TB6612FNG", "TB6612",
        "https://toshiba.semicon-storage.com/info/datasheet_en_20141001.pdf?did=10660",
        "H 브리지 드라이버 공식 데이터시트. VM·VCC·채널 전류와 방열 조건을 부품 구성에 맞춰 확인하세요. 드라이버 동작 해석은 미지원입니다.",
        reference_only=True, aliases=("h bridge", "h브리지", "dc driver"),
    ),
    ElectricalCatalogEntry(
        "st_l298", "모터 드라이버", "STMicroelectronics", "L298", "L298",
        "https://www.st.com/en/motor-drivers/l298.html",
        "모터 공급 최대 46 V, 총 DC 전류 한계 4 A는 칩 한계이며 방열·채널별 조건을 별도 확인해야 합니다. L298N 모듈의 보드 사양과 혼동하지 마세요.",
        reference_only=True, aliases=("l298n", "h bridge", "h브리지"),
    ),
    ElectricalCatalogEntry(
        "ti_drv8825", "스테퍼 드라이버", "Texas Instruments", "DRV8825", "DRV8825",
        "https://www.ti.com/product/DRV8825",
        "모터 공급 8.2–45 V, 출력 최대 2.5 A는 방열 조건에 좌우됩니다. 스테퍼 전류 파형·초퍼 제어는 현재 미지원입니다.",
        reference_only=True, aliases=("stepper driver", "스테퍼 구동기"),
    ),
    ElectricalCatalogEntry(
        "ti_drv8871", "모터 드라이버", "Texas Instruments", "DRV8871", "DRV8871",
        "https://www.ti.com/product/DRV8871",
        "브러시 DC 모터용 H 브리지. 공급 6.5–45 V, 3.6 A는 피크 구동 한계이며 모터의 연속 소비전류가 아닙니다. 보호·PWM 동작은 미지원입니다.",
        reference_only=True, aliases=("h bridge", "h브리지", "dc driver"),
    ),
    ElectricalCatalogEntry(
        "allegro_a4988", "스테퍼 드라이버", "Allegro", "A4988", "A4988",
        "https://www.allegromicro.com/en/products/motor-drivers/brush-dc-motor-drivers/a4988",
        "3.3/5 V 논리 입력, 출력 최대 35 V·±2 A는 칩·방열 조건에 따른 한계입니다. 모듈별 정격과는 다릅니다.",
        reference_only=True, aliases=("stepper driver", "스테퍼 구동기"),
    ),
    ElectricalCatalogEntry(
        "pololu_4755", "기어드 모터·엔코더", "Pololu", "#4755 100:1 37D 12 V 엔코더", "37D",
        "https://www.pololu.com/product/4755",
        "12 V, 무부하 0.2 A, 이론적 정지(stall) 5.5 A. 모터축 엔코더는 A/B 양 채널의 모든 에지를 세는 64 CPR이며 실제 감속비는 102.083:1입니다. 엔코더 전원 3.5–20 V는 모터 전원과 별개이고 출력은 엔코더 Vcc까지 올라갑니다. 무부하·정지 전류를 연속 정격 전류로 사용하지 마세요.",
        "motor", 12.0, aliases=("37d", "gearmotor", "기어 모터", "엔코더 모터"),
        functional_roles=("motor", "encoder"), encoder_interface="quadrature",
        encoder_counts_per_rev=64, encoder_reference="motor_shaft",
        motor_gear_ratio=(25 * 30 * 28 * 28 * 30) / (10 * 10 * 12 * 12 * 12),
    ),
    ElectricalCatalogEntry(
        "stepperonline_17hs19_2004s1", "스테퍼 모터", "StepperOnline", "17HS19-2004S1", "NEMA 17",
        "https://www.omc-stepperonline.com/nema-17-bipolar-59ncm-84oz-in-2a-42x48mm-4-wires-w-1m-cable-connector-17hs19-2004s1",
        "각 상 2 A, 스텝각 1.8°, 각 상 저항 1.6 Ω. 상별 초퍼 구동이 필요하며 2단자 DC 모터 모델로 자동 변환하지 않습니다.",
        reference_only=True, aliases=("nema17", "stepper", "스텝 모터"),
        functional_roles=("motor",),
    ),
    ElectricalCatalogEntry(
        "maxon_666603", "BLDC 모터", "maxon", "EC-i 666603", "EC-i",
        "https://www.maxongroup.com/maxon/view/product/motor/ecmotor/EC-i/666603",
        "공칭 48 V·연속 공칭 전류 3.31 A인 3상 BLDC 제품입니다. 2단자 DC 저항부하로 자동 변환하지 않습니다.",
        reference_only=True, aliases=("bldc", "brushless", "브러시리스"),
        functional_roles=("motor",),
    ),
    ElectricalCatalogEntry(
        "robotis_xl330_m288t", "서보 액추에이터", "ROBOTIS", "DYNAMIXEL XL330-M288-T", "DYNAMIXEL XL330",
        "https://emanual.robotis.com/docs/en/dxl/x/xl330-m288/",
        "입력 3.7–6 V, 권장 5 V, TTL 반이중 통신. 5 V에서 1.47 A는 정지 토크 시험 조건이며 대기 17 mA도 동작 전류가 아닙니다. 실제 부하 전류를 별도로 입력해야 하며 위치·토크·통신 제어 동작은 미해석입니다.",
        "actuator", 5.0, aliases=("servo", "dynamixel", "서보모터", "액추에이터", "엑추에이터"),
    ),
    ElectricalCatalogEntry(
        "concentric_lact10p_12v_10", "선형 액추에이터", "Concentric", "Glideforce LACT10P-12V-10 (Pololu #3651)", "Glideforce LD 10:1",
        "https://www.pololu.com/product/3651",
        "12 V DC, 실제 스트로크 약 250 mm, 동적 하중 250 N, 무부하 약 28 mm/s. 양 끝 리미트 스위치와 위치 피드백 포텐셔미터가 있습니다. 전류는 부하에 따라 달라 3.2 A 한계나 7 A 정지 전류를 계산용 동작 전류로 자동 입력하지 않습니다. 제어·왕복 동작은 미해석입니다.",
        "actuator", 12.0, aliases=("linear actuator", "액추에이터", "엑추에이터", "리니어", "선형", "glideforce", "lact10p"),
    ),
    ElectricalCatalogEntry(
        "omron_e6b2_cwz6c_1000", "엔코더", "Omron", "E6B2-CWZ6C 1000 P/R 0.5 m", "E6B2-C",
        "https://www.ia.omron.com/products/family/487/specification.html",
        "공급 5 V −5% ~ 24 V +15%, 소비전류 최대 80 mA(고정 동작 전류가 아님), NPN 오픈 컬렉터 A/B/Z. 1000 P/R은 엔코더축 1회전당 A/B 모든 에지를 세면 4000 카운트입니다. 출력 풀업과 상대 장치 입력 사양을 확인하세요.",
        reference_only=True, aliases=("encoder", "로터리 엔코더", "omron e6b2"),
        functional_roles=("encoder",), encoder_interface="quadrature",
        encoder_counts_per_rev=4000, encoder_reference="encoder_shaft",
    ),
    ElectricalCatalogEntry(
        "ams_as5600_asot", "자기식 각도 센서 IC", "ams", "AS5600-ASOT SOIC-8 칩", "AS5600",
        "https://look.ams-osram.com/m/7059eac7531a86fd/original/AS5600-DS000365.pdf",
        "AS5600-ASOT SOIC-8 칩의 정확한 8핀 배치입니다. 3.3 V/5 V 전원 모드에서 전원·바이패스 연결이 다르며 외부 I²C 풀업 조건을 확인해야 합니다. 출처 불명 AS5600 모듈 핀과 혼동하지 마세요. 자기장·각도·프로토콜 동작은 미해석입니다.",
        reference_only=True, aliases=("as5600", "encoder", "엔코더", "각도 센서", "magnetic sensor"),
        functional_roles=("encoder",), encoder_interface="absolute_i2c",
    ),
    ElectricalCatalogEntry(
        "omron_e6b2_family", "엔코더", "Omron", "E6B2-C 제품군", "E6B2-C",
        "https://www.ia.omron.com/products/family/487/specification.html",
        "CWZ6C·CWZ5B·CWZ3E·CWZ1X는 공급 전압과 출력 회로가 다릅니다. 정확한 주문 코드·분해능(P/R)을 확인하세요.",
        reference_only=True, aliases=("encoder", "로터리 엔코더", "omron e6b2"),
    ),
    ElectricalCatalogEntry(
        "omron_e6c2_cwz6c_1000", "엔코더", "Omron", "E6C2-CWZ6C 1000 P/R 2 m", "E6C2-C",
        "https://www.ia.omron.com/products/family/488/specification.html",
        "공급 5 V −5% ~ 24 V +15%, 소비전류 최대 80 mA(고정 동작 전류가 아님), NPN 오픈 컬렉터 A/B/Z. 1000 P/R 변형은 엔코더축 1회전당 A/B 모든 에지를 세면 4000 카운트입니다. 출력 풀업과 입력 호환을 확인하세요.",
        reference_only=True, aliases=("encoder", "로터리 엔코더", "omron e6c2"),
        functional_roles=("encoder",), encoder_interface="quadrature",
        encoder_counts_per_rev=4000, encoder_reference="encoder_shaft",
    ),
    ElectricalCatalogEntry(
        "bourns_pec11r_family", "수동 엔코더 제품군", "Bourns", "PEC11R", "PEC11R",
        "https://www.bourns.com/docs/Product-Datasheets/pec11R.pdf",
        "기계식 증분 엔코더 제품군입니다. 펄스·디텐트·축 길이는 주문 접미어별로 다르므로 정확 SKU를 확인하세요.",
        reference_only=True, aliases=("encoder", "로터리 엔코더", "quadrature"),
    ),
    ElectricalCatalogEntry(
        "usdigital_e4t_family", "엔코더 제품군", "US Digital", "E4T 키트", "E4T",
        "https://www.usdigital.com/products/encoders/incremental/kit/e4t/",
        "분해능·전원·장착 규격은 주문 옵션별로 다릅니다. 기계식 결합과 출력 신호 사양을 함께 확인하세요.",
        reference_only=True, aliases=("encoder", "엔코더", "광학"),
    ),
    ElectricalCatalogEntry(
        "vishay_1n5819", "다이오드", "Vishay", "1N5819", "1N5817–1N5819",
        "https://www.vishay.com/docs/88525/1n5817.pdf",
        "반복 피크 역전압 40 V, 평균 정류전류 1 A는 데이터시트 시험 조건(리드 9.5 mm·90 °C)에 한정됩니다. 비선형 다이오드 해석은 미지원입니다.",
        reference_only=True, aliases=("schottky", "쇼트키", "정류"),
    ),
    ElectricalCatalogEntry(
        "vishay_1n4007", "다이오드", "Vishay", "1N4007", "1N4001–1N4007",
        "https://www.vishay.com/docs/88503/1n4001.pdf",
        "반복 피크 역전압 1000 V, 평균 정류전류 1 A는 데이터시트 시험 조건의 한계입니다. 비선형 순방향 전압·열 동작은 미해석입니다.",
        reference_only=True, aliases=("rectifier", "정류", "다이오드"),
    ),
    ElectricalCatalogEntry(
        "vishay_d_crcwp", "저항 제품군", "Vishay", "D/CRCW-P 칩 저항", "D/CRCW-P",
        "https://www.vishay.com/docs/20009/dcrcwp.pdf",
        "패키지·저항값·허용오차·정격 전력은 주문 코드별로 다릅니다. 정확한 SKU를 선택하기 전에는 계산용 Ω값을 자동 입력하지 않습니다.",
        reference_only=True, aliases=("resistor", "저항", "smd", "chip resistor"),
    ),
    ElectricalCatalogEntry(
        "panasonic_erj6enf1002v", "저항", "Panasonic", "ERJ6ENF1002V", "ERJ6EN",
        "https://industrial.panasonic.com/ww/products/pt/general-purpose-chip-resistors/models/ERJ6ENF1002V",
        "10 kΩ ±1%, 0805, 0.125 W 제품. 회로에는 10 kΩ만 넣으며 전력 손실은 표시된 0.125 W와 별도로 비교하세요.",
        "resistor", aliases=("resistor", "저항", "10k", "0805"), resistance_ohm=10000,
    ),
    ElectricalCatalogEntry(
        "panasonic_erj6enf1001v", "저항", "Panasonic", "ERJ6ENF1001V", "ERJ6EN",
        "https://industrial.panasonic.com/ww/products/pt/general-purpose-chip-resistors/models/ERJ6ENF1001V",
        "1 kΩ ±1%, 0805, 0.125 W 제품. 회로에는 1 kΩ만 넣으며 패키지의 전력 정격을 부하 전류로 바꾸지 않습니다.",
        "resistor", aliases=("resistor", "저항", "1k", "0805"), resistance_ohm=1000,
    ),
    ElectricalCatalogEntry(
        "murata_mlcc_family", "콘덴서 제품군", "Murata", "MLCC 세라믹 커패시터", "MLCC",
        "https://www.murata.com/en-global/products/capacitor/ceramiccapacitor/overview/lineup",
        "정전용량·정격 전압·DC 바이어스·온도 특성은 제품별로 다릅니다. 현 DC 회로 계산기는 커패시턴스 동작을 해석하지 않습니다.",
        reference_only=True, aliases=("capacitor", "콘덴서", "커패시터", "캐패시터", "mlcc"),
    ),
    ElectricalCatalogEntry(
        "kyocera_kgm15br71e104kt", "세라믹 콘덴서", "KYOCERA AVX", "KGM15BR71E104KT", "KGM",
        "https://search.kyocera-avx.com/product/KGM15BR71E104KT",
        "100 nF ±10%, 25 V DC, 비극성 0603 X7R. 구 품번 06033C104KAT2A. DC 계산에서는 개방이며 DC 바이어스·온도에 따른 실제 정전용량과 과도 응답은 미해석입니다.",
        "capacitor", aliases=("capacitor", "콘덴서", "커패시터", "캐패시터", "100nf", "0603"),
        capacitance_f=100e-9, rated_voltage_v=25.0,
    ),
    ElectricalCatalogEntry(
        "panasonic_eeufr1h101b", "전해 콘덴서", "Panasonic", "EEUFR1H101B", "FR-A",
        "https://industrial.panasonic.com/ww/products/pt/aluminum-cap-lead/models/EEUFR1H101B",
        "100 μF ±20%, 50 V 극성 전해 콘덴서. DC 계산에서는 개방이며 A는 +, B는 − 단자입니다. 리플 전류 정격을 DC 소비전류로 사용하지 않습니다. 과도 응답·리플·수명은 미해석입니다.",
        "capacitor", aliases=("capacitor", "콘덴서", "커패시터", "캐패시터", "100uf", "전해"),
        capacitance_f=100e-6, capacitor_polarized=True, rated_voltage_v=50.0,
    ),
    ElectricalCatalogEntry(
        "wurth_7447713100", "인덕터", "Würth Elektronik", "7447713100", "WE-PD",
        "https://www.we-online.com/components/products/datasheet/7447713100.pdf",
        "10 μH ±20%, 권선 DC 저항 20 °C에서 0.052 Ω 전형값(최대 0.062 Ω). DC 계산은 이 권선 저항만 사용합니다. 2.6 A는 ΔT=40 K 온도상승 조건, 4.1 A는 전형적 포화 전류이며 온도·포화·과도 응답은 미해석입니다.",
        "inductor", aliases=("inductor", "인덕터", "코일", "10uh", "쵸크", "choke"),
        inductance_h=10e-6, winding_resistance_ohm=0.052,
    ),
    ElectricalCatalogEntry(
        "infineon_mosfet_family", "MOSFET 제품군", "Infineon", "Power MOSFET 선택기", "Power MOSFET",
        "https://www.infineon.com/products/power/mosfet",
        "게이트 구동·RDS(on)·VDS·ID·열 사양이 SKU별로 다릅니다. 스위칭/열 동작은 현 회로 계산기에서 미지원입니다.",
        reference_only=True, aliases=("mosfet", "트랜지스터", "소자"),
    ),
    ElectricalCatalogEntry(
        "ti_csd18540q5b", "MOSFET", "Texas Instruments", "CSD18540Q5B", "CSD18540",
        "https://www.ti.com/product/CSD18540Q5B/part-details/CSD18540Q5B",
        "VDS 60 V 한계. 게이트 구동과 방열에 따른 허용 전류가 달라지며 스위칭 동작은 현 회로 계산기에서 미지원입니다.",
        reference_only=True, aliases=("mosfet", "트랜지스터", "소자"),
    ),
    ElectricalCatalogEntry(
        "infineon_irlz44npbf", "MOSFET", "Infineon", "IRLZ44NPBF", "IRLZ44N",
        "https://www.infineon.com/part/IRLZ44N",
        "N채널 MOSFET, VDS 최대 55 V. 제품의 25 °C 전류 한계를 실제 회로의 연속 전류로 대입하지 마세요. 게이트·방열 검증은 미지원입니다.",
        reference_only=True, aliases=("mosfet", "트랜지스터", "소자", "irlz44n"),
    ),
    ElectricalCatalogEntry(
        "ti_lm2596", "전압 조정기", "Texas Instruments", "LM2596 제품군", "LM2596",
        "https://www.ti.com/product/LM2596",
        "입력 범위 4.5–40 V, 최대 3 A 출력은 구성·방열 조건에 좌우됩니다. 스위칭 레귤레이터 동작은 현 DC 저항 모델에서 미지원입니다.",
        reference_only=True, aliases=("buck", "dc dc", "dcdc", "레귤레이터", "전압강하"),
    ),
    ElectricalCatalogEntry(
        "st_l7805cv", "전압 조정기", "STMicroelectronics", "L7805CV", "L78",
        "https://www.st.com/en/power-management/l78.html",
        "5 V 양전압 선형 조정기. 실제 출력 전류 한계는 입력전압·손실·방열에 좌우되며 레귤레이터 동작은 미해석입니다.",
        reference_only=True, aliases=("regulator", "레귤레이터", "7805"),
    ),
    ElectricalCatalogEntry(
        "jst_ph_family", "커넥터 제품군", "JST", "PH 와이어-보드 커넥터", "PH",
        "https://www.jst.com/products/crimp-style-connectors-wire-to-board-type/ph-connector/",
        "AWG 24 조건 2 A·100 V 사양. 극수·전선·접점·환경별 허용값을 확인하세요. 접점 저항은 미입력입니다.",
        reference_only=True, aliases=("connector", "커넥터", "전선", "배선"),
    ),
    ElectricalCatalogEntry(
        "molex_microfit_family", "커넥터 제품군", "Molex", "Micro-Fit 3.0", "Micro-Fit",
        "https://www.molex.com/en-us/products/connectors/wire-to-board-connectors/micro-fit-connectors",
        "허용 전류는 단자·전선 굵기·극수·온도에 따라 다릅니다. 제품군 수치를 회로의 전류 제한으로 자동 사용하지 않습니다.",
        reference_only=True, aliases=("connector", "커넥터", "전선", "배선"),
    ),
    ElectricalCatalogEntry(
        "jst_b2b_xh_a", "커넥터", "JST", "B2B-XH-A 2핀", "XH",
        "https://www.jst-mfg.com/product/pdf/eng/eXH.pdf",
        "2.5 mm 피치 2핀 보드 헤더. 맞는 하우징·접점·전선 굵기와 극성 표시를 별도로 확인하세요.",
        reference_only=True, aliases=("connector", "커넥터", "전선", "배선", "xh"),
    ),
    ElectricalCatalogEntry(
        "wago_221_412", "전선 커넥터", "WAGO", "221-412", "221",
        "https://www.wago.com/sg/installation-terminal-blocks-and-connectors/splicing-connector-with-levers/p/221-412",
        "2도체 레버 커넥터. 도체 단면적·전류·온도·규격은 실제 전선과 설치 조건에 맞게 확인하세요.",
        reference_only=True, aliases=("connector", "커넥터", "전선", "배선", "wago"),
    ),
    ElectricalCatalogEntry(
        "te_282834_2", "PCB 터미널", "TE Connectivity", "282834-2", "Buchanan",
        "https://www.te.com/en/product-282834-2.html",
        "2포지션 2.54 mm PCB 단자대. 정격은 도체·온도·PCB 패턴 조건과 함께 확인하세요.",
        reference_only=True, aliases=("terminal block", "터미널", "커넥터", "pcb"),
    ),
    ElectricalCatalogEntry(
        "alpha_3050", "전선", "Alpha Wire", "Premium 3050", "Premium hook-up wire",
        "https://www.alphawire.com/products/wire/hook-up-wire/premium/3050",
        "24 AWG 주석도금 구리, 정격 300 V RMS, 20 °C 공칭 DC 저항 25 Ω/1000 ft. 길이와 배치 조건별 허용 전류는 별도 확인하세요.",
        "wire", aliases=("24 awg", "hook up", "배선", "copper wire"),
    ),
    ElectricalCatalogEntry(
        "tdk_icm42670p", "IMU 센서", "TDK InvenSense", "ICM-42670-P", "ICM-42670",
        "https://product.tdk.com/system/files/dam/doc/product/sensor/mortion-inertial/imu/data_sheet/ds-000451-icm-42670-p.pdf",
        "VDD/VDDIO 1.71–3.6 V. 6축 저소음 모드의 0.55 mA는 특정 조건의 전형값이며 모든 모드의 정격이 아닙니다. I²C/SPI 기능 검증은 미지원입니다.",
        reference_only=True, aliases=("mpu", "imu", "gyro", "가속도", "자이로"),
    ),
    ElectricalCatalogEntry(
        "adi_adxl345", "가속도 센서", "Analog Devices", "ADXL345", "ADXL345",
        "https://www.analog.com/en/products/adxl345.html",
        "3축 디지털 가속도 센서. 전원·I²C/SPI 신호와 동작 모드별 소비전류는 공식 자료로 확인하세요. 센서 기능 해석은 미지원입니다.",
        reference_only=True, aliases=("imu", "accelerometer", "가속도", "sensor"),
    ),
    ElectricalCatalogEntry(
        "meanwell_lrs35_5", "AC/DC 전원", "MEAN WELL", "LRS-35-5", "LRS-35",
        "https://www.meanwell.com/Upload/PDF/LRS-35/LRS-35-SPEC.PDF",
        "5 V 출력, 7 A는 출력 용량입니다. 부하 소비전류가 아니며 AC 입력·접지·안전 규격은 별도 검토가 필요합니다.",
        reference_only=True, aliases=("power supply", "전원 공급기", "smps", "5v"),
    ),
    ElectricalCatalogEntry(
        "meanwell_lrs35_12", "AC/DC 전원", "MEAN WELL", "LRS-35-12", "LRS-35",
        "https://www.meanwell.com/Upload/PDF/LRS-35/LRS-35-SPEC.PDF",
        "12 V 출력, 3 A는 출력 용량입니다. 부하 소비전류가 아니며 AC 입력·접지·안전 규격은 별도 검토가 필요합니다.",
        reference_only=True, aliases=("power supply", "전원 공급기", "smps", "12v"),
    ),
    ElectricalCatalogEntry(
        "energizer_e91", "건전지", "Energizer", "E91 AA 알카라인", "E91",
        "https://data.energizer.com/pdfs/e91.pdf",
        "공칭 1.5 V AA 알카라인. 방전 전류·온도·잔량에 따라 전압과 용량이 변합니다. 내부저항과 방전 곡선은 미해석입니다.",
        reference_only=True, aliases=("battery", "건전지", "aa", "알카라인"),
    ),
    ElectricalCatalogEntry(
        "littelfuse_218_family", "퓨즈 제품군", "Littelfuse", "218 지연형 5×20 mm", "218",
        "https://www.littelfuse.com/assetdocs/fuse-218-datasheet?assetguid=a96d72b7-5296-4815-88b4-98b2f6738874",
        "정격 전류와 전압은 주문 코드·AC/DC 차단 조건별로 다릅니다. 퓨즈 시간-전류 곡선과 차단 동작은 현재 미해석입니다.",
        reference_only=True, aliases=("fuse", "퓨즈", "보호", "과전류"),
    ),
    ElectricalCatalogEntry('ti_ads131m04','하중 취득 ADC','Texas Instruments','ADS131M04','ADS131M0x',
        'https://www.ti.com/lit/ds/symlink/ads131m04.pdf',
        '4채널 동시 취득 24-bit SPI ADC IC. 최대 64 kSPS는 모드·클록·OSR 조건에 따릅니다. 이득 8 이상이면 각 입력 상한은 AVDD−1.8 V입니다. 3.3 V 브리지 직접 연결을 승인하지 않습니다.',
        reference_only=True,aliases=('load cell','adc','force','로드셀','하중','ads131'),functional_roles=('adc',)),
    ElectricalCatalogEntry('hbk_u10m_25kn_passive','인장·압축 로드셀','HBK','U10M 25 kN · passive 100% dynamic calibration','U10M',
        'https://www.hbm.com/fileadmin/mediapool/hbmdoc/technical/B01444.pdf',
        '정격 25 kN, 공칭 2 mV/V·비조정 실제 범위 2–2.5 mV/V, 여자 0.5–12 V. 표준 동적 범위 ±100% Fnom은 시험기 수명 인증이 아닙니다. 일련번호 교정·설치·케이블 옵션 확인이 필요합니다. 1-U10M/25kN은 어댑터 포함이며 맨몸 주문 코드와 다릅니다.',
        reference_only=True,aliases=('load cell','로드셀','하중','u10m','hbk','hbm','force'),functional_roles=('load_cell',)),
    ElectricalCatalogEntry('st_nucleo_g474re','수집 MCU 보드','STMicroelectronics','NUCLEO-G474RE','STM32G4 / MB1367',
        'https://www.st.com/resource/en/user_manual/um2505-stm32g4-nucleo64-boards-mb1367-stmicroelectronics.pdf',
        '별도 수집 보드 후보. UM2505 Rev 7의 선택 SPI/GPIO·전원 헤더만 모식도에 등록합니다. PA5/LD2/SB6, 실제 리비전·전원 점퍼·SPI/DRDY 펌웨어를 검토하세요. B-G431 ESC의 전류 피드백 핀을 빈 SPI 핀으로 사용하지 않습니다.',
        suggested_kind='mcu',aliases=('nucleo g474','g474re','stm32g474','daq','수집 mcu'),functional_roles=('controller',)),
    ElectricalCatalogEntry('maxon_ec_i52_667065','BLDC 모터 후보','maxon','EC-i 52 24 V 420 W · 667065 · NRND','EC-i 52',
        'https://www.maxongroup.com/maxon/view/product/667065',
        '현재 공식 페이지의 정격 24 V, 연속 토크 0.972 N·m·전류 18.3 A는 제조사 조건 값입니다. 2025 자료의 0.964 N·m·18.1 A와 섞지 않습니다. NRND이며 저속 왕복 냉각·전류 정의·Hall 전압·커넥터는 미확인입니다. U/V/W/Hall 기능 단자만 참고하고 FOC·부하 소비전류·15 kN 정격을 자동 계산하지 않습니다.',
        suggested_kind='motor',nominal_voltage_v=24,reference_only=True,aliases=('maxon 667065','ec-i52','bldc','brushless','피로시험 모터'),functional_roles=('motor',)),
    ElectricalCatalogEntry('ti_ads1232','브리지 ADC','Texas Instruments','ADS1232','ADS123x',
        'https://www.ti.com/lit/ds/symlink/ads1232.pdf',
        '브리지용 24-bit ADC IC, 10/80 SPS. Rev H 디지털 필터 대역은 각각 2.4/19 Hz이며 시험기 전체 대역·제어 주파수와 다릅니다. 실제 기준 전압·이득·핀·교정이 필요합니다.',
        reference_only=True,aliases=('load cell','adc','로드셀','브리지','ads123'),functional_roles=('adc',)),
    ElectricalCatalogEntry('avia_hx711','저속 브리지 ADC','AVIA Semiconductor','HX711','HX711',
        'https://cdn.sparkfun.com/datasheets/Sensors/ForceFlex/hx711_english.pdf',
        'AVIA 원문 자료를 SparkFun이 제공하는 SOP-16 IC 참고입니다. 내부 클록 10/80 SPS이며 고속 피로시험 하중 제어기로 간주하지 않습니다. 불특정 저가 모듈의 결선을 보증하지 않습니다.',
        reference_only=True,aliases=('load cell','adc','로드셀','hx711','저울'),functional_roles=('adc',)),
    ElectricalCatalogEntry('sensirion_sht31_dis_b','온습도 센서','Sensirion','SHT31-DIS-B','SHT3x-DIS',
        'https://sensirion.com/media/documents/213E6A3B/63A5A569/Datasheet_SHT3x_DIS.pdf',
        'I²C 온습도 센서 IC. 공급·ADDR·풀업·히터/측정 모드를 실제 보드와 확인하세요. 소비전류는 미입력이며 임의 브레이크아웃과 동일하다고 가정하지 않습니다.',
        reference_only=True,aliases=('humidity','temperature','습도','온도','sht31'),functional_roles=('humidity_temperature',)),
    ElectricalCatalogEntry('sensirion_sht45_ad1b','온습도 센서','Sensirion','SHT45-AD1B','SHT4x',
        'https://sensirion.com/media/documents/33FD6951/6A7C10A0/HT_DS_Datasheet_SHT4x_V7.3.pdf',
        '1.08–3.6 V I²C 센서 IC, 해당 AD1B 주소 0x44. 실제 측정/히터 모드별 전류와 보드 풀업은 별도 입력·검토합니다. 5 V 직접 인가를 승인하지 않습니다.',
        reference_only=True,aliases=('humidity','temperature','습도','온도','sht45'),functional_roles=('humidity_temperature',)),
)


_BY_ID = {entry.catalog_id: entry for entry in CATALOG}


def get_catalog_entry(catalog_id: str) -> ElectricalCatalogEntry | None:
    """Look up an immutable starter catalog entry by its stable ID."""
    return _BY_ID.get(catalog_id)


def catalog_functions(catalog_id: str) -> tuple[ElectricalFunction, ...]:
    """Return exact product functions, without approving a circuit or firmware model.

    Unknown and family IDs stay unclassified. A functional role is not proof of
    verified pins, electrical compatibility or eligibility for a simulation.
    """
    entry = get_catalog_entry(catalog_id)
    if entry is None:
        return ()
    if entry.functional_roles:
        return entry.functional_roles
    if not entry.reference_only and entry.suggested_kind == "mcu":
        return ("controller",)
    if not entry.reference_only and entry.suggested_kind in ("motor", "actuator"):
        return (entry.suggested_kind,)
    return ()


def has_catalog_function(catalog_id: str, function: ElectricalFunction) -> bool:
    """Check source-linked functional classification independently of DC kind."""
    return function in catalog_functions(catalog_id)


def search_catalog(query: str = "", *, limit: int = 100) -> tuple[ElectricalCatalogEntry, ...]:
    """Search part names, series, categories and common Korean/English aliases."""
    words = tuple(word.casefold() for word in query.split() if word)
    if not words:
        return CATALOG[:max(0, limit)]
    matches = []
    for entry in CATALOG:
        haystack = " ".join((entry.catalog_id, entry.category, entry.manufacturer,
                             entry.model, entry.series, entry.spec_summary, *entry.aliases)).casefold()
        if all(word in haystack for word in words):
            name = f"{entry.manufacturer} {entry.model}".casefold()
            score = (2 if query.casefold() in name else 0) + sum(word in name for word in words)
            matches.append((-score, entry.category, entry.manufacturer, entry.model, entry))
    matches.sort(key=lambda row: row[:4])
    return tuple(row[-1] for row in matches[:max(0, limit)])


def component_prefill(entry: ElectricalCatalogEntry) -> dict[str, object]:
    """Return only source-supported values; never turn PSU/stall limits into loads."""
    if entry.reference_only or entry.suggested_kind is None:
        return {}
    values: dict[str, object] = {
        "name": entry.display_name,
        "kind": entry.suggested_kind,
        "catalog_id": entry.catalog_id,
        "source_url": entry.source_url,
    }
    if entry.nominal_voltage_v is not None:
        field = "rated_voltage_v" if entry.suggested_kind in ("mcu", "motor", "actuator", "load") else "voltage_v"
        values[field] = entry.nominal_voltage_v
    if entry.rated_current_a is not None and entry.suggested_kind in ("mcu", "motor", "actuator", "load"):
        values["rated_current_a"] = entry.rated_current_a
    if entry.resistance_ohm is not None and entry.suggested_kind == "resistor":
        values["resistance_ohm"] = entry.resistance_ohm
    if entry.suggested_kind == "capacitor":
        if entry.capacitance_f is not None:
            values["capacitance_f"] = entry.capacitance_f
        values["capacitor_polarized"] = entry.capacitor_polarized
    if entry.suggested_kind == "inductor":
        if entry.inductance_h is not None:
            values["inductance_h"] = entry.inductance_h
        if entry.winding_resistance_ohm is not None:
            values["winding_resistance_ohm"] = entry.winding_resistance_ohm
    if entry.rated_voltage_v is not None and entry.suggested_kind in ("capacitor", "inductor"):
        values["rated_voltage_v"] = entry.rated_voltage_v
    if entry.suggested_kind == "actuator" and entry.rated_current_a is None:
        values["analysis_enabled"] = False
    return values
