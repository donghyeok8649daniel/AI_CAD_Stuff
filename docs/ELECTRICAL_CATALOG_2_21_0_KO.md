# v2.21.0 전장 카탈로그와 확인 범위

2026-10-07 공식 제조사 자료로 확인했다. 총 98개 검색 항목 중 실제 CAD 부품에 등록 가능한 항목은 55개다. 확인한 보드 헤더 11개, 제품 기능 단자 모식도 25개, 정확한 모델이지만 핀 모식도가 없는 수동 등록 항목 19개로 구분한다. 나머지 43개는 제품군 또는 미확인 제품의 자료 탐색용이다. 목록에 있다는 이유로 등록·핀 연결·시뮬레이션 지원을 주장하지 않는다.

이번에는 정확한 제품 12개와 기존 보드 2개의 핀 지도를 추가했다. 전체 시리즈나 다른 판매자 모듈에 핀 배치를 복제하지 않았다. 모식도의 좌우 순서는 화면 배치이며, 실물 패드 순서나 PCB 치수가 아니다. 제조사에서 확인한 번호만 단자 라벨에 표시한다.

| 등록 모델 | 확인한 기능과 구분 | 공식 자료 |
|---|---|---|
| TI REF5025AID SOIC-8 | AI 표준 등급 8핀 IC. 1/8 DNC, 2 VIN, 3 TEMP, 4 GND, 5 TRIM/NR, 6 VOUT, 7 NC. 원격 SENSE 없음 | [TI SBOS410O, 2025-10](https://www.ti.com/lit/ds/symlink/ref50.pdf), 표 4-1·그림 5-1·표 5-1 |
| MEAN WELL HDR-60-5 | 1–2 −V, 3–4 +V, **5 AC/L, 6 AC/N**. 5 V 모델은 32.5 W·6.5 A 용량. Class II로 FG 단자가 없음 | [HDR-60-SPEC, 2026-04-03](https://www.meanwell.com/Upload/PDF/HDR-60/HDR-60-SPEC.PDF), 2쪽 모델 열·4쪽 단자 표 |
| MEAN WELL LRS-600-24 | 1 AC/L, 2 AC/N, 3 FG, 4–6 −V, 7–9 +V. FG와 DC return 구분. 24 V·25 A 출력 용량 | [LRS-600-SPEC, 2025-09-12](https://www.meanwell.com/Upload/PDF/LRS-600/LRS-600-SPEC.PDF), 2쪽 모델 열·4쪽 단자 표 |
| Adafruit INA219 #904 | VCC/GND, I2C, Vin+/Vin− 측정 경로. 주소 점퍼를 GPIO 헤더로 만들지 않음 | [INA219 Pinouts](https://learn.adafruit.com/adafruit-ina219-current-sensor-breakout/pinouts) |
| Adafruit INA260 #4226 | VCC/GND, I2C, Alert, Vin+/Vin−, VBus. 기본 VBus–Vin+ 점퍼와 low-side 변경 구분 | [INA260 Pinouts](https://learn.adafruit.com/adafruit-ina260-current-voltage-power-sensor-breakout/pinouts) |
| Adafruit ADS1115 STEMMA QT #1085 | A0–A3는 입력, A+/A−는 전원 출력. 구형 ADDR 헤더와 QT 주소 점퍼를 구분하고 실물 버전 확인 | [ADC Pinouts](https://learn.adafruit.com/adafruit-4-channel-adc-breakouts/pinouts) |
| Adafruit MCP23017 #5346 | A/B 디지털 GPIO와 D0/D1/D2 주소 스트랩 구분. 제조사 안내에 따라 A7/B7 출력 전용으로 표시 | [MCP23017 Pinouts와 A7/B7 주의사항](https://learn.adafruit.com/adafruit-mcp23017-i2c-gpio-expander/pinouts) |
| Adafruit PCA9685 #815 | 별도 VCC/V+, GND, I2C, OE, PWM0–15. 서보 전원과 논리 전원은 별개. 채널 공통 주파수 | [PCA9685 Pinouts](https://learn.adafruit.com/16-channel-pwm-servo-driver/pinouts) |
| Adafruit DRV8871 #3190 | VM/GND, IN1/IN2, OUT1/OUT2. 별도 VCC 없음. 두 출력 모두 스위칭 모터 단자 | [DRV8871 Pinouts](https://learn.adafruit.com/adafruit-drv8871-brushed-dc-motor-driver-breakout/pinouts) |
| Adafruit SHT31-D #2857 | Vin/GND, I2C, ADR, RST, ALR. DFN IC 지도와 다른 실제 보드 단자 | [SHT31-D Pinouts](https://learn.adafruit.com/adafruit-sht31-d-temperature-and-humidity-sensor-breakout/pinouts) |
| Adafruit BME280 #2652 | SCK/SCL·SDI/SDA 공용 단자. 3Vo는 출력. SDO는 SPI MISO 또는 I2C 주소 설정 | [BME280 Pinouts](https://learn.adafruit.com/adafruit-bme280-humidity-barometric-pressure-temperature-sensor-breakout/pinouts) |
| Adafruit AS5600 #6357 | 절대각 I2C·OUT 단자. DIR은 뒷면 점퍼. OUT의 내부 VDD 기준과 I2C의 Vin 기준 구분 | [AS5600 Pinouts](https://learn.adafruit.com/adafruit-as5600-magnetic-angle-sensor/pinouts) |

Pico 2는 [공식 데이터시트 2026-07-03판](https://datasheets.raspberrypi.com/pico/pico-2-datasheet.pdf)의 그림 2·4, 3.1절을 직접 확인해 40개 가장자리 핀과 표시된 UART/I2C/SPI/ADC 기능을 추가했다. 내부 GP23/24/25/29와 SWD는 제외한다. 보드 I/O는 3.3 V로 고정되므로 RP2350 칩의 다른 I/O 전압을 보드에 적용하지 않는다.

Zero 2 W는 [공식 R1 reduced schematic](https://datasheets.raspberrypi.com/rpizero2/raspberry-pi-zero-2-w-reduced-schematics.pdf)의 J8 패드 40개와 BCM GPIO를 확인했다. J8는 DNF이므로 실제 헤더 장착 여부를 확인해야 한다. ID_SD/ID_SC는 EEPROM용 참고 핀으로 일반 GPIO 연결 대상에서 제외한다.

새 제품은 전장 부품으로 등록한 뒤 확인된 단자에 배선을 저장할 수 있다. 등록 시 CAD 형상·위치·그룹·사용자 색상을 유지하고 DC 계산은 미확인 상태로 둔다. 출력 용량, 최대 전류, 측정 범위를 소비 전류로 넣지 않는다. AC 전원 변환·회생 흡수·ESC/PWM·칩 내부 동작·MCU 펌웨어 실행은 이 모식도가 계산하지 않는다.

선택 부품의 제조사·모델 문자열이 정확히 일치하면 등록 후보를 제안할 수 있다. 후보를 찾는 일은 등록하거나 배선을 변경하는 일이 아니다. `REF5025AID SOIC8`은 칩 참고자료이며, 사용자 제작 여자 보드의 버퍼와 원격 SENSE 단자를 대신하지 않는다. 연결된 부품의 제품 모델을 바꾸려면 기존 연결 변경을 별도로 확인해야 한다.

검증: 새 제품 12개를 실제 등록하고 모든 확인된 단자를 배선한 뒤 프로젝트를 저장·재검증했다. Pico 2와 Zero 2 W의 I2C 신호 연결도 재개방 후 유지됨을 확인했다. 기존 색·형상·그룹·회로 전력 결과를 보존했다. 관련 소스 검사 92개 통과. 실물 배선·기기 구동·정격 인증 결과를 의미하지 않는다.
