# MCU board pin references / MCU 보드 핀 출처

The native MCU diagram uses verified header names and pin coordinates for exact
board models. The left/right rows are a functional schematic, not a dimensioned
PCB drawing or a component-footprint library. GPIO logic voltage is separate
from supply-input voltage and current ratings. Source check date: **2026-10-03**.

MCU 모식도는 아래의 정확한 보드 모델에 대해 헤더 이름과 핀 번호를 표시합니다.
화면의 좌우 배치는 연결용 모식도이며 PCB의 실제 치수·풋프린트가 아닙니다.
GPIO 논리 전압과 보드 전원 입력 전압·소비 전류는 서로 다른 값입니다.

| Catalog ID | Exact board | Included header pins | Verified primary source |
| --- | --- | ---: | --- |
| `rpi3bplus` | Raspberry Pi 3 Model B+ | 40, J8 | [Raspberry Pi GPIO usage white paper, Figure 1](https://pip-assets.raspberrypi.com/categories/685-app-notes-guides-whitepapers/documents/RP-006553-WP/A-history-of-GPIO-usage-on-Raspberry-Pi-devices-and-current-best-practices) |
| `rpi4b` | Raspberry Pi 4 Model B | 40, J8 | [Raspberry Pi GPIO usage white paper, Figure 1](https://pip-assets.raspberrypi.com/categories/685-app-notes-guides-whitepapers/documents/RP-006553-WP/A-history-of-GPIO-usage-on-Raspberry-Pi-devices-and-current-best-practices) |
| `arduino_uno_r3` | Arduino UNO Rev3, A000066 | 32, main JANALOG/JDIGITAL | [Arduino UNO R3 user manual, sections 5.1-5.2](https://docs.arduino.cc/resources/datasheets/A000066-datasheet.pdf) and [official detailed pinout](https://content.arduino.cc/assets/Pinout-UNOrev3_latest.pdf) |
| `arduino_mega2560_r3` | Arduino Mega 2560 Rev3, A000067 | 86, main JANALOG/JDIGITAL + XIO LHS/RHS | [Arduino Mega user manual, sections 5.1, 5.2, 5.5, 5.6](https://docs.arduino.cc/resources/datasheets/A000067-datasheet.pdf) and [official detailed pinout](https://content.arduino.cc/assets/Pinout-Mega2560rev3_latest.pdf) |
| `nucleo_f401re` | ST NUCLEO-F401RE, MB1136 | 32, Arduino CN5/CN9/CN6/CN8 | [ST UM1724 Rev 17, Table 16](https://www.st.com/resource/en/user_manual/um1724-stm32-nucleo64-boards-mb1136-stmicroelectronics.pdf) |
| `nucleo_f446re` | ST NUCLEO-F446RE, MB1136 | 32, Arduino CN5/CN9/CN6/CN8 | [ST UM1724 Rev 17, Table 19](https://www.st.com/resource/en/user_manual/um1724-stm32-nucleo64-boards-mb1136-stmicroelectronics.pdf) |
| `nucleo_f103rb` | ST NUCLEO-F103RB, MB1136 | 32, Arduino CN5/CN9/CN6/CN8 | [ST UM1724 Rev 17, Table 12](https://www.st.com/resource/en/user_manual/um1724-stm32-nucleo64-boards-mb1136-stmicroelectronics.pdf) |
| `rpi_pico` | Original Raspberry Pi Pico, RP2040 | 40 edge pins | [Raspberry Pi Pico R3 A4 official pinout](https://datasheets.raspberrypi.com/pico/Pico-R3-A4-Pinout.pdf) |

## Numbering and shared signals

- Raspberry Pi uses physical J8 coordinates and BCM GPIO names together: physical
  **J8.11 is GPIO17**, not GPIO11. GPIO0/GPIO1 at physical 27/28 are HAT EEPROM
  references and are not offered as ordinary assignable signal pins here.
- Arduino `JANALOG` and `JDIGITAL` numbers follow the exact product manual's
  connector tables. Mega `XIO LHS/RHS.1-18` numbers follow sections 5.5/5.6's row
  numbering. They do not claim an invented chip-package pin number.
- UNO's separate SDA/SCL sockets duplicate A4/A5 electrically. Mega's SDA/SCL
  sockets duplicate D20/D21. The catalog retains each physical socket, with
  `SAME_NET:<canonical key>` connectivity metadata. Separate sockets are not
  independent GPIOs and must not be assigned contradictory nets.
- UNO and Mega display their main usable external headers. ICSP, ATmega16U2
  programming/debug pads and board-internal GPIO are excluded from this first
  pin-reference set.
- Nucleo Arduino header labels include both the header signal and STM32 port,
  for example **CN5.6 / D13 / PA5**. The default analog routing is A4=PC1 and
  A5=PC0. Moving to I2C PB9/PB8 requires checking and modifying solder bridges;
  it does not follow automatically from selecting a software function. UM1724
  Table 10 documents SB56/SB51 vs SB46/SB52.
- Nucleo D0/D1 USART2 header access also depends on SB62/SB63 and ST-LINK VCP
  bridges SB13/SB14. The drawing records the connector table mapping and flags
  the bridge requirement; it cannot inspect a physical board's solder bridges.
  Morpho, ST-LINK and SWD headers are not included.
- Pico displays edge GP0-GP22 and GP26-GP28; its internal GP23-GP25 and SWD pads
  are excluded. RUN, ADC_VREF and 3V3_EN are control/reference pins, not ordinary
  GPIO. This record is not asserted for Pico W or Pico 2.

## Scope

Power, ground, reset and reference pads are visible for orientation. They do not
become a GPIO, and a physical 3V3/5V/VIN/VSYS pin is not automatically equated
with the MCU's abstract DC supply terminals. The existing power-path workbench
still requires the actual supply route and operating current.

Peripheral labels identify documented available functions; firmware, pin mux,
board bridges, OS settings and bus termination must be configured separately.
This reference set does not execute MCU firmware, simulate protocols, prove
input/output drive direction, or certify voltage compatibility. Unverified
product families, clones and similar variants return no exact pinout rather
than inheriting a guessed family layout. A generic legacy signal label remains
distinct from a verified physical-board binding.

전원·접지·리셋·참조 핀은 위치 확인용으로 표시합니다. 3V3/5V/VIN/VSYS 핀을
자동으로 MCU 전원 두 단자에 묶지 않습니다. 전원 경로와 실제 소비 전류는 따로
설정해야 합니다. 펌웨어 실행·프로토콜·GPIO 구동 방향·전압 호환 인증은 이번
핀 모식도의 범위가 아닙니다. 정확한 보드가 확인되지 않은 제품군·복제 보드에
핀 배치를 추정해서 넣지 않습니다.

The application draws its own functional diagram; the linked manufacturer
artwork is not bundled. Arduino's linked detailed artwork identifies its own
CC BY-SA 4.0 license and attribution. Pin mappings were cross-checked against
both its user-manual tables and detailed artwork; firmware alternate functions
were not extrapolated from a similar Arduino model.
