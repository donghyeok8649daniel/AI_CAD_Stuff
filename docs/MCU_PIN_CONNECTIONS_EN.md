# MCU board selection and pin wiring

Open **Electrical circuit → View schematic… → Select MCU / pin connections…** to select a board and connect its physical pins to modeled component terminals. A yellow CAD part or an electrical role alone does not register a circuit component or MCU.

The electrical editor also has a direct **Select MCU / pin connections…** button. With this path, save the pin editor and then choose **Save to design** in the electrical editor.

1. Use **Add MCU…** and choose the exact board model. Enter a name, the actual supply and return nodes, supply voltage and operating current for your intended conditions. A recommended power adapter current is not the board's operating current. Confirm an unknown operating current before saving. Optionally associate the board with an existing CAD part.
2. Select the board to view a **pin diagram** and pin list. Check the signal name, physical header and pin number, displayed functions and assigned net. Click a pin in the diagram or select its row.
3. Choose a real circuit component terminal or another MCU physical pin in **Target component · terminal**, then choose **Connect selected pin**. The selected pin is assigned to the target's net. Add a missing target component in the electrical editor first. A direct named-node connection is also available.
4. Select a pin and another target to change the connection. **Disconnect pin** removes only that pin's assignment. Save the pin editor, choose **Save schematic changes** in the schematic, then **Save to design** in the electrical editor to commit the circuit and history. Canceling a dialog preserves the circuit saved before that dialog was opened.
5. Recalculate the circuit and inspect supply/return paths, continuity and warnings. Saving a `.cad.json` project preserves the board model and pin assignments for reopening and editing.

Sensors, encoders and drivers need signal terminals separate from their two supply terminals. In the component editor, select a general load or motor and enter one `TERMINAL=NET` line in **Additional signal terminals = net · sensor / driver**, such as `OUT_A=ENCODER_A` or `PWM=MOTOR_PWM`. The MCU target chooser can then select that component's `OUT_A` or `PWM` terminal. The schematic displays it on a signal row separate from the power branch. Naming a terminal does not simulate an encoder waveform or driver logic.

## Built-in pin diagram coverage

| Board | Coverage |
| --- | --- |
| Raspberry Pi 3 Model B+, 4 Model B | 40-pin J8 header, BCM GPIO names and physical pin numbers |
| Arduino UNO Rev3 | Main power, digital and analog headers |
| Arduino Mega 2560 Rev3 | Main power, digital and analog headers |
| NUCLEO-F103RB, NUCLEO-F401RE, NUCLEO-F446RE | Arduino-compatible headers; excludes ST Morpho and ST-LINK |
| Raspberry Pi Pico | 40 edge pins; excludes SWD and internal board GPIOs |

For example, Raspberry Pi 4 `GPIO17` is physical `J8.11`; Arduino UNO `D2` uses a different naming system. Separate physical header pins sharing a documented signal are handled according to their verified connection. A board without pin data is not given guessed official pin numbers. Existing user-defined pin names are preserved and shown as custom pins. An unknown pin on a known board remains distinct from official pins.

The diagram explains pin relationships. It is not a dimensioned PCB outline or a guarantee of connector orientation, placement or mechanical size. Open the board's official reference to check the exact revision and physical header orientation.

The [official references and verification record](MCU_PIN_SOURCES.md) document pin numbers and coverage. Nucleo solder-bridge settings can change signal paths; a displayed default mapping does not establish the physical wiring state of your board.

## What the check establishes

Pin checks are **passive continuity and DC connectivity reviews** of saved nodes and modeled wires/switches. Assigning the same net does not establish that a digital signal or peripheral works. Different MCU signal voltage levels require a review of level translation and input limits. GPIO pins must not directly power high-current motor loads.

The app does not execute firmware, configure GPIO direction or alternate functions, simulate communication timing, pull-up/pull-down behavior or motor-driver control. Displayed `UART` or `I2C` functions do not replace the board configuration and code. Before powering physical hardware, confirm the wiring, polarity, pin voltage/current limits and protection against the exact component documentation.
