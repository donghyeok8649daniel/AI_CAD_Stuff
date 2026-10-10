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
| `st_nucleo_g474re` | ST NUCLEO-G474RE, MB1367 | 32 selected Arduino/Morpho signal, supply and reference entries | [UM2505 Rev 7, Tables 7/15/16](https://www.st.com/resource/en/user_manual/um2505-stm32g4-nucleo64-boards-mb1367-stmicroelectronics.pdf), [STM32G474RE DS12288 Rev 6, Tables 12/13](https://www.st.com/resource/en/datasheet/stm32g474re.pdf) |

## NUCLEO-G474RE selected Arduino/Morpho pins

Source check date for this board: **2026-10-10**. The 16 added GPIOs below use one
canonical STM32 key each. An Arduino socket and a Morpho socket exposing that
key are the same electrical GPIO; they are not extra independent pins. The
existing six DAQ keys/labels and supply/reference keys remain unchanged.
LQFP64 chip pad numbers are distinct from board connector numbers. Selected
alternate functions are candidates for firmware configuration.

| Key | Morpho | Arduino exposure | LQFP64 pad | Selected function |
| --- | --- | --- | ---: | --- |
| PA11 | CN10.14 | — | 45 | FDCAN1_RX, AF9 |
| PA12 | CN10.12 | — | 46 | FDCAN1_TX, AF9 |
| PB10 | CN10.25 | CN9.7 / D6 | 30 | USART3_TX, AF7 |
| PB11 | CN10.18 | — | 33 | USART3_RX, AF7 |
| PB12 | CN10.16 | — | 34 | GPIO |
| PB8 | CN10.3 | CN5.10 / D15 | 61 | I2C1_SCL, AF4; BOOT0 shared |
| PB9 | CN10.5 | CN5.9 / D14 | 62 | I2C1_SDA, AF4 |
| PC6 | CN10.4 | — | 38 | GPIO |
| PA8 | CN10.23 | CN9.8 / D7 | 42 | TIM1_CH1, AF6 |
| PA9 | CN10.21 | CN5.1 / D8 | 43 | TIM1_CH2, AF6; UCPD1_DBCC1 condition |
| PC0 | CN7.38 | CN8.6 / A5, selected route | 8 | GPIO; SB36 versus PA15/SB37 |
| PC1 | CN7.36 | CN8.5 / A4, selected route | 9 | GPIO; SB35 versus PB9/SB34 |
| PC2 | CN7.35 | — | 10 | GPIO |
| PC3 | CN7.37 | — | 11 | GPIO |
| PB0 | CN7.34 | CN8.4 / A3 | 24 | GPIO |
| PB1 | CN10.24 | — | 25 | GPIO |

Confirm the actual board revision, solder bridges and jumpers before wiring.
PC0/PC1 table entries describe the selected routing, not proof that a modified
physical board has those bridges. PB8 also depends on BOOT0/JP7/SB4 and option
bytes. UM2505 Table 15 identifies PB8 as D15; its SB2 discussion uses D14, so
the connector table governs this catalog entry. PA11/PA12 are target MCU
pins, not the ST-LINK USB connector.

I2C requires appropriate open-drain configuration and pull-ups. TIM1 channels
may use input capture or output compare/PWM; listing a channel does not prove
its direction. GPIO entries do not invent an AF number. Logic is 3.3 V; do not
infer blanket 5 V tolerance from the board's 5 V supply.

DS12288 Table 12 note 6 documents that high PA9 may enable the PB6 UCPD1_CC1
dead-battery 5.1 kΩ pull-down after reset. The exact disable condition is
**`PWR_CR3.UCPD1_DBDIS=1`**. Preserve PA9/PB6 bindings, but confirm this firmware
configuration before relying on PB6 as an unrelated digital signal. PA5 also
shares LD2 through SB6. E5V CN7.6 remains 4.75–5.25 V / 500 mA maximum, with
JP5 pins 5–6 and external power applied before USB. ADC CLKIN is separate.

These rows were checked against primary extracted document text. A local
rendered PDF/schematic and the fitted board configuration were unavailable for
independent visual confirmation. No physical configuration or firmware was
changed. Existing projects/history/source bundles are preserved; an older
firmware bundle's saved pin-reference fingerprint can become stale when this
catalog expands and needs explicit review/regeneration.

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
