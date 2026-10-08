"""Compact offline product references checked against primary sources.

Only short factual records are bundled, not copied vendor pages or firmware.
Each record keeps a stable identity, source and evidence date. A verified
product identity does not imply a verified pin map or a behavioral simulator.
"""

SOURCE_CHECKED_DATE = "2026-10-08"
_rows: list[dict] = []


def _add(identifier, category, maker, model, series, source, summary, **values):
    _rows.append(dict(catalog_id=identifier, category=category, manufacturer=maker,
                      model=model, series=series, source_url=source, spec_summary=summary,
                      source_checked_date=SOURCE_CHECKED_DATE,
                      evidence=values.pop("evidence", "Official product documentation; product identity and stated fields only."),
                      **values))


# Product codes and MCU identities are listed in ST's official selector.
# Header pinouts and power jumper revisions are deliberately not inferred.
ST_NUCLEO_SOURCE = "https://www.st.com/en/evaluation-tools/stm32-nucleo-boards/products.html"
NUCLEO_MODELS = (
    ("NUCLEO-G031K8", "STM32G031K8", 32),
    ("NUCLEO-G431RB", "STM32G431RB", 64),
    ("NUCLEO-G491RE", "STM32G491RE", 64),
    ("NUCLEO-G071RB", "STM32G071RB", 64),
    ("NUCLEO-G070RB", "STM32G070RB", 64),
    ("NUCLEO-F042K6", "STM32F042K6", 32),
    ("NUCLEO-F031K6", "STM32F031K6", 32),
    ("NUCLEO-F030R8", "STM32F030R8", 64),
    ("NUCLEO-F091RC", "STM32F091RC", 64),
    ("NUCLEO-F302R8", "STM32F302R8", 64),
    ("NUCLEO-F303RE", "STM32F303RE", 64),
    ("NUCLEO-F303ZE", "STM32F303ZE", 144),
    ("NUCLEO-F412ZG", "STM32F412ZG", 144),
    ("NUCLEO-F439ZI", "STM32F439ZI", 144),
    ("NUCLEO-F767ZI", "STM32F767ZI", 144),
    ("NUCLEO-H723ZG", "STM32H723ZG", 144),
    ("NUCLEO-H563ZI", "STM32H563ZI", 144),
    ("NUCLEO-H503RB", "STM32H503RB", 64),
    ("NUCLEO-L073RZ", "STM32L073RZ", 64),
    ("NUCLEO-L031K6", "STM32L031K6", 32),
    ("NUCLEO-L412KB", "STM32L412KB", 32),
    ("NUCLEO-U575ZI-Q", "STM32U575ZIT6Q", 144),
    ("NUCLEO-WB55RG", "STM32WB55RG", 64),
    ("NUCLEO-WL55JC", "STM32WL55JC", 64),
)
for board, chip, size in NUCLEO_MODELS:
    _add("st_" + board.lower().replace("-", "_"), "MCU 보드", "STMicroelectronics", board,
         f"STM32 Nucleo-{size}", ST_NUCLEO_SOURCE,
         f"{chip} 기반 정확한 Nucleo-{size} 보드. 전원 점퍼·보드 리비전·헤더 핀은 제품 설명서를 확인하세요. "
         "이번 자료는 제품 식별이며 미확인 헤더를 자동 배선하거나 소비전류를 임의 설정하지 않습니다.",
         suggested_kind="mcu", aliases=("stm", "stm32", "nucleo", chip.lower(), "뉴클레오"),
         evidence=f"ST official Nucleo product selector: {board} / {chip} / Nucleo-{size}.")


ARDUINO_MODELS = (
    ("uno_r4_minima", "UNO R4 Minima", "UNO R4", "Renesas RA4M1·5 V GPIO·VIN 6–24 V. VIN과 GPIO 전압은 다릅니다."),
    ("mkr_zero", "MKR Zero", "MKR", "SAMD21 기반, microSD와 전용 SPI1 지원."),
    ("nano_rp2040_connect", "Nano RP2040 Connect", "Nano", "RP2040·NINA-W102 기반. 공식 문서의 End of Life 제품입니다."),
    ("portenta_h7", "Portenta H7", "Portenta", "STM32H747 이중 코어·80핀 고밀도 커넥터 포함."),
    ("zero", "Zero", "Arduino Classic", "SAMD21 Cortex-M0+ 기반·EDBG 디버거 포함."),
    ("leonardo", "Leonardo", "Arduino Classic", "ATmega32U4 기반·20개 디지털 I/O·16 MHz."),
    ("nano_33_iot", "Nano 33 IoT", "Nano", "SAMD21 기반 IoT 보드. 보드와 연결 모듈의 전원·핀 조건을 확인하세요."),
    ("mkr_wifi_1010", "MKR WiFi 1010", "MKR", "SAMD21·NINA-W102 기반. 연결 방식별 공급 경로를 확인하세요."),
    ("due", "Due", "Arduino Due", "SAM3X8E 기반. UNO/Mega의 5 V GPIO와 같은 전압으로 가정하지 않습니다."),
)
for slug, board, series, summary in ARDUINO_MODELS:
    _add("arduino_" + slug, "MCU 보드", "Arduino", board, series,
         "https://docs.arduino.cc/hardware/" + slug.replace("_", "-") + "/",
         summary + " 정확한 보드의 공식 도면을 연결한 제품 자료입니다. 실제 핀맵·소비전류는 자동 추정하지 않습니다.",
         suggested_kind="mcu", aliases=("arduino", "아두이노", slug.replace("_", " ")))

ESPRESSIF_MODELS = (
    ("esp32_s3_devkitc1", "ESP32-S3-DevKitC-1", "esp32s3/esp32-s3-devkitc-1/index.html", "ESP32-S3", "WROOM-1/1U/2 모듈·보드 리비전과 메모리 옵션을 구분하세요."),
    ("esp32_c3_devkitm1", "ESP32-C3-DevKitM-1", "esp32c3/esp32-c3-devkitm-1/user_guide.html", "ESP32-C3", "MINI-1/1U 모듈. USB·5V 헤더·3V3 헤더는 상호 배타적인 전원 공급 방식입니다."),
    ("esp32_c6_devkitc1", "ESP32-C6-DevKitC-1 v1.2", "esp32c6/esp32-c6-devkitc-1/user_guide.html", "ESP32-C6", "정확한 v1.2 사용자 설명서. 다른 보드 버전의 헤더를 적용하지 않습니다."),
    ("esp32_s2_devkitc1", "ESP32-S2-DevKitC-1", "esp32s2/esp32-s2-devkitc-1/user_guide.html", "ESP32-S2", "WROOM/WROVER 옵션과 핀 점유 조건을 제품 설명서로 확인하세요."),
)
for identifier, board, path, series, summary in ESPRESSIF_MODELS:
    _add(identifier, "MCU 보드", "Espressif", board, series,
         "https://docs.espressif.com/projects/esp-dev-kits/en/latest/" + path,
         summary + " 공급 전압과 GPIO 논리 전압은 별개이며 전체 펌웨어 동작을 검증한 자료가 아닙니다.",
         suggested_kind="mcu", aliases=("esp", "esp32", "와이파이", "wifi"))

for identifier, model, source, summary in (
    ("rpi_pico_w", "Pico W", "https://www.raspberrypi.com/products/raspberry-pi-pico/", "RP2040·무선 LAN·Bluetooth, 전원 입력 1.8–5.5 V. 무선용 내부 핀 점유를 확인하세요."),
    ("rpi_pico2_w", "Pico 2 W", "https://www.raspberrypi.com/products/raspberry-pi-pico-2/", "RP2350 기반 무선 모델. 기존 Pico와 MCU·메모리·부트 조건을 구분하세요."),
    ("pjrc_teensy40", "Teensy 4.0", "https://www.pjrc.com/store/teensy40.html", "600 MHz Cortex-M7·3.3 V GPIO, 5 V 허용 GPIO로 가정하지 않습니다."),
    ("pjrc_teensy41", "Teensy 4.1", "https://www.pjrc.com/store/teensy41.html", "600 MHz Cortex-M7·55 I/O 중 42개 외곽 핀, GPIO 3.3 V. USB와 VIN의 전원 역류 조건을 확인하세요."),
    ("beaglebone_black", "BeagleBone Black", "https://www.beagleboard.org/boards/beaglebone-black", "Cortex-A8 Linux SBC·PRU 포함. P8/P9 헤더와 부트 기능의 충돌을 확인하세요."),
    ("beagleplay", "BeaglePlay", "https://www.beagleboard.org/boards/beagleplay", "AM6254 Cortex-A53 Linux SBC. mikroBUS/Grove/Qwiic 등 실제 커넥터의 전원·신호를 구분하세요."),
    ("beagley_ai", "BeagleY-AI", "https://www.beagleboard.org/boards/beagley-ai", "AM67A 기반 SBC·40핀 확장 헤더. Raspberry Pi와 동일한 모든 핀 기능으로 단정하지 않습니다."),
):
    maker = "Raspberry Pi" if identifier.startswith("rpi_") else "PJRC" if identifier.startswith("pjrc_") else "BeagleBoard"
    _add(identifier, "MCU 보드" if identifier.startswith(("rpi_pico", "pjrc_")) else "MPU 보드",
         maker, model, model.split()[0], source,
         summary + " 이번 등록은 공식 제품 식별 자료이며 미확인 핀·소비전류를 자동 채우지 않습니다.",
         suggested_kind="mcu", aliases=("mcu", "mpu", "board", "보드", "controller", model.lower()))

for identifier, name in (("rpi_compute4", "Compute Module 4"), ("rpi_compute5", "Compute Module 5")):
    _add(identifier, "MPU 모듈", "Raspberry Pi", name, "Compute Module",
         "https://www.raspberrypi.com/products/" + ("compute-module-4/" if identifier.endswith("4") else "compute-module-5/"),
         "RAM·eMMC·무선 옵션과 실제 캐리어 보드 선택이 필요한 모듈 자료. 다른 옵션의 커넥터·전원·소비전류를 공통값으로 자동 등록하지 않습니다.",
         reference_only=True, aliases=("cm4" if identifier.endswith("4") else "cm5", "mpu", "라즈베리", "컴퓨트"))


# Exact device product references, not guessed development-board pinouts.
TI_DEVICE_ROWS = (
    ("DRV8251", "모터 드라이버", "DC H-bridge·4.5–48 V 동작 전원. 4.1 A peak는 연속 전류나 소비전류가 아닙니다.", ("motor_driver",)),
    ("DRV8876", "모터 드라이버", "DC H-bridge·전류 검출/피드백 포함. 부하 전류·PCB 방열과 peak 한계를 구분하세요.", ("motor_driver",)),
    ("DRV8711", "모터 드라이버", "외부 N-MOSFET용 스테퍼 게이트 드라이버. MOSFET·전류 검출·PCB가 완성된 모듈이 아닙니다.", ("motor_driver",)),
    ("DRV8301", "모터 드라이버", "3상 MOSFET 게이트 드라이버·SPI·전류검출 증폭기. 외부 전력단이 필요합니다.", ("motor_driver",)),
    ("DRV8313", "모터 드라이버", "3개 half-bridge 모터 드라이버 IC. 3상 정류·타이밍을 2단자 DC 부하로 대신하지 않습니다.", ("motor_driver",)),
    ("INA226", "전류·전압 센서", "16-bit I2C/SMBus 전류·전압·전력 모니터, bus 측정 0–36 V. bus 입력 범위는 IC 공급 전압과 다릅니다.", ()),
    ("INA3221", "전류·전압 센서", "3채널 shunt/bus 모니터 IC·I2C. 채널별 shunt와 공급 조건을 확인하세요.", ()),
    ("ADS1115", "ADC", "16-bit 4입력 multiplexed I2C ADC. differential·single-ended 범위와 PGA 설정을 구분하세요.", ("adc",)),
    ("ADS1256", "ADC", "24-bit delta-sigma ADC·SPI. 실제 샘플링률·PGA·필터를 연구 취득 조건으로 별도 설정하세요.", ("adc",)),
    ("TMP117", "온도 센서", "디지털 I2C 온도센서 IC. 센서의 정확도·응답과 보드 과열 해석은 별개입니다.", ()),
    ("LM1117", "전압 레귤레이터", "LDO 제품 선택 자료. 고정 출력/가변 출력 주문 코드·dropout·입출력 커패시터를 구분하세요.", ()),
    ("TPS5430", "DC-DC 전원", "buck 컨버터 IC. 외부 인덕터·다이오드·PCB·열 조건을 포함한 완성 전원 모듈과 다릅니다.", ()),
    ("BQ24074", "충전·배터리 관리", "1셀 Li-ion 선형 충전·power-path IC. 배터리 화학/셀 수·충전전류·열 조건을 확인하세요.", ()),
    ("BQ76920", "충전·배터리 관리", "3–5셀 배터리 모니터 AFE. FET·보호 로직·펌웨어·셀 배선이 완성된 BMS가 아닙니다.", ()),
    ("SN65HVD230", "통신 트랜시버", "3.3 V CAN 물리 계층 트랜시버. CAN H/L과 MCU TX/RX를 구분하세요.", ()),
    ("MAX3232", "통신 트랜시버", "RS-232 트랜시버. RS-232 전압을 MCU UART GPIO에 직접 연결하지 않습니다.", ()),
    ("PCA9306", "신호 레벨 변환", "양방향 I2C 레벨 변환 IC. 양쪽 기준 전원·pull-up·enable 조건을 확인하세요.", ()),
)
for model, category, summary, roles in TI_DEVICE_ROWS:
    _add("ti_" + model.lower(), category, "Texas Instruments", model + " IC", model,
         "https://www.ti.com/product/" + model, summary,
         reference_only=True, aliases=(model.lower(), "ti", "전자", "ic"), functional_roles=roles)

for model, category, summary, roles in (
    ("TMC2209", "스테퍼 드라이버", "2상 스테퍼 드라이버·STEP/DIR·UART. 패키지/방열과 peak/RMS 전류는 실제 보드별로 확인하세요.", ("motor_driver",)),
    ("TMC2130", "스테퍼 드라이버", "2상 스테퍼 드라이버·STEP/DIR·SPI, 모터 전원 4.75–46 V. 모듈 출력 정격은 PCB 방열에 따라 달라집니다.", ("motor_driver",)),
    ("TMC5160", "스테퍼 드라이버", "8–60 V 외부 MOSFET 제어형. TMC5160A-TA/WA 패키지와 외부 전력단을 선택하세요.", ("motor_driver",)),
    ("ADXL355", "IMU·가속도 센서", "디지털 3축 가속도센서·선택 범위 ±2/±4/±8 g. 진동 측정용 입력이며 하중 센서와 다릅니다.", ()),
    ("MAX31865", "온도·RTD 인터페이스", "PT100/PT1000 RTD-to-digital IC. 2/3/4선 배선·기준 저항·센서 선택을 확인하세요.", ()),
    ("LTC3780", "DC-DC 전원", "buck-boost 컨트롤러 IC·외부 MOSFET/인덕터 필요. 시중 LTC3780 모듈의 정격을 칩 자료로 보증하지 않습니다.", ()),
):
    _add("adi_" + model.lower(), category, "Analog Devices", model + " IC", model,
         "https://www.analog.com/en/products/" + model.lower() + ".html", summary,
         reference_only=True, aliases=(model.lower(), "adi", "trinamic", "ic"), functional_roles=roles)

BOSCH_SOURCE = "https://www.bosch-sensortec.com/en/products/"
for model, category, summary, product_path in (
    ("BMI270", "IMU·가속도 센서", "6축 IMU", "motion-sensors/imus/bmi270"),
    ("BMI088", "IMU·가속도 센서", "6축 IMU", "motion-sensors/imus/bmi088"),
    ("BMP390", "압력 센서", "24-bit 기압 센서", "environmental-sensors/pressure-sensors/bmp390"),
    ("BME680", "환경·가스 센서", "가스·압력·습도·온도 센서", "environmental-sensors/gas-sensors/bme680"),
):
    _add("bosch_" + model.lower(), category, "Bosch Sensortec", model, model, BOSCH_SOURCE + product_path,
         summary + " 제품 자료. breakout 보드와 bare IC는 다른 제품입니다. 패키지·전원·통신·교정 조건은 정확한 데이터시트를 확인하세요.",
         reference_only=True, aliases=(model.lower(), "bosch", "센서", "sensor"), evidence="Bosch Sensortec exact official product page and technical-data table.")


# More usable smart actuators; no stall current becomes a fixed DC load.
# T and R variants retain different TTL / RS-485 connectors in product_diagrams.
DYNAMIXEL_ROWS = (
    ("robotis_xl330_m077t", "XL330-M077-T", "xl330-m077", 5.0, "3.7–6 V", "TTL", True, False),
    ("robotis_xc330_t181t", "XC330-T181-T", "xc330-t181", 11.1, "6.5–12 V", "TTL", False, False),
    ("robotis_xc330_t288t", "XC330-T288-T", "xc330-t288", 11.1, "6.5–12 V", "TTL", False, False),
    ("robotis_xm430_w210t", "XM430-W210-T", "xm430-w210", 12.0, "10–14.8 V", "TTL", False, False),
    ("robotis_xm430_w210r", "XM430-W210-R", "xm430-w210", 12.0, "10–14.8 V", "RS-485", False, True),
    ("robotis_xh430_w350t", "XH430-W350-T", "xh430-w350", 12.0, "10–14.8 V", "TTL", False, False),
    ("robotis_xh430_w350r", "XH430-W350-R", "xh430-w350", 12.0, "10–14.8 V", "RS-485", False, True),
    ("robotis_xm540_w270t", "XM540-W270-T", "xm540-w270", 12.0, "10–14.8 V", "TTL", False, False),
    ("robotis_xm540_w270r", "XM540-W270-R", "xm540-w270", 12.0, "10–14.8 V", "RS-485", False, True),
)
for identifier, model, slug, voltage, voltage_range, bus, xl330, rs485 in DYNAMIXEL_ROWS:
    _add(identifier, "스마트 액추에이터", "ROBOTIS", "DYNAMIXEL " + model, "DYNAMIXEL X",
         "https://emanual.robotis.com/docs/en/dxl/x/" + slug + "/",
         f"입력 {voltage_range}, 권장 {voltage:g} V·{bus} half-duplex 통신. 내부 제어기·모터·위치 피드백 포함. "
         "stall 토크/전류는 연속 운전 정격과 다릅니다. 실제 소비전류·온도·부하·duty를 확인하며 펌웨어 동작을 자동 승인하지 않습니다.",
         suggested_kind="actuator", nominal_voltage_v=voltage, functional_roles=("actuator",),
         aliases=(model.lower(), "dynamixel", "다이나믹셀", "servo", "서보", "motor", "모터"),
         evidence="ROBOTIS exact model Specifications, Connector Information and Communication Circuit sections.")


# Low-voltage DC fuse entries: explicit contact model plus rating checks only.
# Opening / clearing time requires manufacturer time-current / I²t data and
# actual thermal conditions; these ratings do not make a predictive fuse model.
FUSE_218_SOURCE = "https://www.littelfuse.com/assetdocs/littelfuse_fuse_218_datasheet.pdf?assetguid=a96d72b7-5296-4815-88b4-98b2f6738874"
FUSE_451_SOURCE = "https://www.littelfuse.com/~/media/electronics/datasheets/fuses/littelfuse_fuse_451_453_datasheet.pdf.pdf"
FUSE_287_SOURCE = "https://www.littelfuse.com/assetdocs/littelfuse-datasheet-287-atof?assetguid=43dcdce8-8ca2-426f-8998-7e566f048d40"
FUSE_ROWS = (
    # Exact electrical amp code followed by the documented packaging suffix.
    ("0218.500MXP", "218", 0.5, 250.0, "ac", 0.3700, FUSE_218_SOURCE),
    ("0218.630MXP", "218", 0.63, 250.0, "ac", 0.2750, FUSE_218_SOURCE),
    ("0218.800MXP", "218", 0.8, 250.0, "ac", 0.0813, FUSE_218_SOURCE),
    ("0218001.MXP", "218", 1.0, 250.0, "ac", 0.0613, FUSE_218_SOURCE),
    ("021801.6MXP", "218", 1.6, 250.0, "ac", 0.0336, FUSE_218_SOURCE),
    ("0218002.MXP", "218", 2.0, 250.0, "ac", 0.0293, FUSE_218_SOURCE),
    ("021802.5MXP", "218", 2.5, 250.0, "ac", 0.0219, FUSE_218_SOURCE),
    ("02183.15MXP", "218", 3.15, 250.0, "ac", 0.0173, FUSE_218_SOURCE),
    ("0218004.MXP", "218", 4.0, 250.0, "ac", 0.0129, FUSE_218_SOURCE),
    ("0218005.MXP", "218", 5.0, 250.0, "ac", 0.0104, FUSE_218_SOURCE),
    ("021806.3MXP", "218", 6.3, 250.0, "ac", 0.0076, FUSE_218_SOURCE),
    ("0451.500MRL", "451", 0.5, 125.0, "ac_dc", 0.3046, FUSE_451_SOURCE),
    ("0451.750MRL", "451", 0.75, 125.0, "ac_dc", 0.1444, FUSE_451_SOURCE),
    ("0451001.MRL", "451", 1.0, 125.0, "ac_dc", 0.0780, FUSE_451_SOURCE),
    ("045101.5MRL", "451", 1.5, 125.0, "ac_dc", 0.0630, FUSE_451_SOURCE),
    ("0451002.MRL", "451", 2.0, 125.0, "ac_dc", 0.0367, FUSE_451_SOURCE),
    ("045102.5MRL", "451", 2.5, 125.0, "ac_dc", 0.0286, FUSE_451_SOURCE),
    ("0451003.MRL", "451", 3.0, 125.0, "ac_dc", 0.0227, FUSE_451_SOURCE),
    ("0451004.MRL", "451", 4.0, 125.0, "ac_dc", 0.0160, FUSE_451_SOURCE),
    ("0451005.MRL", "451", 5.0, 125.0, "ac_dc", 0.0125, FUSE_451_SOURCE),
    ("0451010.MRL", "451", 10.0, 125.0, "ac_dc", 0.0056, FUSE_451_SOURCE),
    ("0287002.U", "287", 2.0, 32.0, "dc", 0.05350, FUSE_287_SOURCE),
    ("0287003.U", "287", 3.0, 32.0, "dc", 0.03110, FUSE_287_SOURCE),
    ("0287004.U", "287", 4.0, 32.0, "dc", 0.02280, FUSE_287_SOURCE),
    ("0287005.U", "287", 5.0, 32.0, "dc", 0.01785, FUSE_287_SOURCE),
    ("0287010.U", "287", 10.0, 32.0, "dc", 0.00770, FUSE_287_SOURCE),
    ("0287015.U", "287", 15.0, 32.0, "dc", 0.00480, FUSE_287_SOURCE),
    ("0287020.U", "287", 20.0, 32.0, "dc", 0.00338, FUSE_287_SOURCE),
    ("0287030.U", "287", 30.0, 32.0, "dc", 0.00197, FUSE_287_SOURCE),
)
for model, series, current, voltage, voltage_type, cold_r, source in FUSE_ROWS:
    identifier = "littelfuse_" + model.lower().replace(".", "_")
    fuse_type = {"218": "5×20 mm 지연형", "451": "Nano² very fast-acting", "287": "ATOF blade fast-acting"}[series]
    _add(identifier, "퓨즈", "Littelfuse", model, series, source,
         f"{fuse_type}, {current:g} A·{voltage:g} V {'AC only' if voltage_type == 'ac' else 'AC/DC' if voltage_type == 'ac_dc' else 'DC'}. "
         f"공식 명목 냉간 저항 {cold_r:g} Ω. "
         "A/B는 비극성 양 끝입니다. 닫힌 접점의 냉간 근사와 과전류 경고만 사용하며 실제 용단시간·차단능력·온도 derating은 별도 확인합니다.",
         suggested_kind="switch", fuse_current_a=current, rated_voltage_v=voltage,
         voltage_rating_type=voltage_type, contact_resistance_ohm=cold_r,
         aliases=(model.lower(), series, "fuse", "퓨즈", "휴즈", f"{current:g}a"),
         evidence=f"Littelfuse {series} electrical ratings table, cold resistance and ordering suffix; AC/DC rating kept separate.")


for model, resistance in (("ERJ6ENF2200V", 220), ("ERJ6ENF3300V", 330),
                          ("ERJ6ENF4700V", 470), ("ERJ6ENF4701V", 4700),
                          ("ERJ6ENF4702V", 47000), ("ERJ6ENF1003V", 100000)):
    _add("panasonic_" + model.lower(), "저항", "Panasonic", model, "ERJ6EN",
         "https://industrial.panasonic.com/ww/products/pt/general-purpose-chip-resistors/models/" + model,
         f"{resistance:g} Ω ±1%·0805·0.125 W. 정격 전력은 실제 I²R 손실과 비교하며 온도 derating·PCB 열저항을 임의 생성하지 않습니다.",
         suggested_kind="resistor", resistance_ohm=resistance, rated_power_w=0.125,
         aliases=("resistor", "저항", "0805", f"{resistance:g}ohm"), evidence="Panasonic exact product Specification: resistance, tolerance, chip size and power rating.")

for model, capacitance, voltage in (("EEUFR1E101B", 100e-6, 25), ("EEUFR1H471B", 470e-6, 50)):
    _add("panasonic_" + model.lower(), "전해 콘덴서", "Panasonic", model, "FR-A",
         "https://industrial.panasonic.com/ww/products/pt/aluminum-cap-lead/models/" + model,
         f"{capacitance * 1e6:g} μF ±20%·{voltage:g} V·극성 전해 콘덴서. A=+, B=−. 리플 전류는 DC 소비전류가 아닙니다.",
         suggested_kind="capacitor", capacitance_f=capacitance, rated_voltage_v=voltage,
         voltage_rating_type="dc", capacitor_polarized=True,
         aliases=("capacitor", "커패시터", "캐패시터", "콘덴서", "전해", f"{capacitance * 1e6:g}uf"),
         evidence="Panasonic exact product Specification: capacitance, polarity and rated voltage.")

BOURNS_SOURCE = "https://www.bourns.com/docs/Product-Datasheets/SRR1260.pdf"
for suffix, inductance, max_r in (("100M", 10e-6, 0.020), ("150M", 15e-6, 0.027),
                                ("220M", 22e-6, 0.043), ("330M", 33e-6, 0.060),
                                ("470M", 47e-6, 0.086), ("101M", 100e-6, 0.180)):
    model = "SRR1260-" + suffix
    _add("bourns_" + model.lower().replace("-", "_"), "인덕터", "Bourns", model, "SRR1260", BOURNS_SOURCE,
         f"{inductance * 1e6:g} μH ±20%, RDC 최대 {max_r:g} Ω. "
         "DC는 문서의 최대 권선 저항을 보수적인 근사로 사용합니다. 실제 권선 온도·주파수·포화·허용 RMS 전류 조건은 별도 확인합니다.",
         suggested_kind="inductor", inductance_h=inductance, winding_resistance_ohm=max_r,
         aliases=("inductor", "인덕터", "코일", "choke", f"{inductance * 1e6:g}uh"),
         evidence="Bourns SRR1260 electrical specifications: inductance ±20%, RDC maximum (mΩ).")

EXPANDED_CATALOG_ROWS = tuple(_rows)
EXPANDED_CATALOG_IDS = tuple(row["catalog_id"] for row in EXPANDED_CATALOG_ROWS)
del _rows
