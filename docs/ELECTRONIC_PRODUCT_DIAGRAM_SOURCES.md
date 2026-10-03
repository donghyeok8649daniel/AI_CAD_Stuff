# Exact electronic terminal diagrams

Checked **2026-10-03**. These lightweight records provide model-specific native
vector terminal references for electrical products registered to an actual CAD
part. They do not download or bundle manufacturer artwork. `side`/`position`
are logical drawing rows, not measured PCB positions, footprints or invented
connector pad numbers. The eight verified MCU board references remain described
in [MCU_PIN_SOURCES.md](MCU_PIN_SOURCES.md).

실제 CAD 부품에 전장 제품을 등록할 때 표시하는 단자 모식도입니다. 제조사 자료의
핀 번호·단자명·전선 색상만 사용하며 PCB 치수나 미확인 모듈 핀을 추정하지
않습니다. 내부 회로·펌웨어·프로토콜 동작은 이번 모식도의 범위가 아닙니다.

| Catalog ID | Exact model / scope | Primary evidence |
| --- | --- | --- |
| `ams_as5600_asot` | AS5600-ASOT, SOIC-8 IC; 8 actual top-view numbered pins | [Manufacturer DS000365 v1-06](https://look.ams-osram.com/m/7059eac7531a86fd/original/AS5600-DS000365.pdf), Figure 3/4 pin assignment, Figure 45 ordering, supply modes in Application Information |
| `pololu_2130` | Pololu #2130 DRV8833 Dual Motor Driver Carrier; 15 named terminal functions | [Pololu exact product](https://www.pololu.com/product/2130), Using the motor driver, Pinout table, Current limiting and carrier schematic |
| `pololu_4755` | Pololu #4755 100:1 37D 12 V motor with quadrature encoder; 6 lead colors/functions | [Pololu exact product](https://www.pololu.com/product/4755), Using the Encoder color/function table and encoder supply/output conditions |
| `vishay_1n5819` | Vishay 1N5819, DO-204AL/DO-41 axial package; anode/cathode-band polarity | [Vishay document 88525](https://www.vishay.com/docs/88525/1n5817.pdf), Mechanical Data, polarity and package |

## Interpretation and conditions

**AS5600:** `1 VDD5V`, `2 VDD3V3`, `3 OUT`, `4 GND`, `5 PGO`, `6 SDA`,
`7 SCL`, `8 DIR`. This is the exact IC and ordering code, not a generic AS5600
breakout board. VDD3V3 is a regulator bypass in 5 V mode; 3.3 V mode uses a
different supply connection. Decoupling, mode selection and I2C pull-ups must
follow the data sheet. No external load is invented from current-mode limits.

**Pololu #2130:** `VIN`, `VMM`, `GND`, `AIN1/2`, `BIN1/2`, `AOUT1/2`,
`BOUT1/2`, `nSLEEP` (board label SLP), `nFAULT` (FLT), `AISEN`, `BISEN`.
The diagram deliberately draws named functions instead of claiming all sixteen
header pads' physical order. Repeated ground pads share the named GND function.
VMM is after the reverse-protection MOSFET and is not silently joined to VIN.
Control inputs and switched motor outputs have different terminal kinds.
AISEN/BISEN are grounded on the unmodified board; current limiting requires
physical board changes. The open-drain fault output needs the appropriate
pull-up. The driver/thermal/PWM truth table is not executed by the DC solver.

**Pololu #4755:** red and black are the two motor terminals, green is encoder
ground, blue is encoder Vcc, yellow/white are encoder A/B. Red/black are not
fixed positive/negative rails: polarity changes motor direction. Encoder
supply is separate from the motor winding terminals. A/B output levels reach
encoder Vcc (3.5-20 V), so direct 3.3 V MCU compatibility is not assumed. Lead
colors are verified; a six-position connector numbering/order is not invented.
The existing motor operating-point approximation still requires user-provided
current and does not simulate the encoder.

For GPIO connection diagnostics, A/B carry a separate `encoder_vcc` reference
and the supported 3.5-20 V encoder supply range. This range is not a fixed
output-high voltage, the motor's nominal 12 V, or an MCU input rating. Product
signal notes also retain AS5600 supply-mode/I2C pull-up conditions and #2130's
open-drain nFAULT pull-up condition. These are compatibility checks to review,
not a claim that matching nominal voltages certifies a connection.

**1N5819:** the manufacturer identifies the cathode with a color band. The
diagram uses A/K names and does not assign arbitrary numbered leads. No diode
forward-drop, reverse-leakage, thermal or switching model is added. The existing
catalog's voltage/current limits remain source conditions, not a complete
operating-point equivalent.

The two new catalog entries (AS5600-ASOT and #2130) are **reference-only**. They
provide exact registration metadata and terminal references, but do not acquire
automatic DC supply/load values. Unknown product families and clone-module
layouts have no verified product diagram. Power/ground/control terminals remain
distinct until the user explicitly assigns a supported connection; a drawing
alone neither wires the real device nor certifies electrical compatibility.
