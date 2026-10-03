# Registering CAD parts as electrical models

Registering an actual board, motor or sensor model links a 3D CAD part ID to an electrical circuit component, product reference and pin/terminal diagram. The registration is a persistent feature stored with the part in the project. Changing a part's color to yellow or assigning an electrical role is a separate operation.

Select one 3D part and open electrical model registration. Choose an exact model or a custom component kind, and set its circuit name. New registrations begin with **Ratings pending · excluded from DC**. Enable the supported DC calculation only when the actual supply voltage and operating current for the intended conditions are known. After saving, open the registration feature under that part to view or edit its model and diagram.

Open **Drawing / analysis → CAD part · electrical registration / diagram…**, or choose electrical registration in the selected part's properties. Use **Register electrical feature · preview** to inspect the private draft, then **Save to design** to commit it. **Edit ratings / power / signal terminals…** edits operating inputs and wiring; **MCU pin connections…** opens the physical pin editor. Double-click the **Electrical feature** entry under the part to reopen it.

Registration is a non-geometric CAD feature. Registration and diagram edits preserve the existing body, assembly placement and grouping. Custom part colors remain unchanged by default; applying the electrical role color is optional. Cancel discards the current dialog's edits. Saved registration changes participate in normal undo/redo and `.cad.json` project save/reopen.

## Connecting power and signals

1. After registering a model, enter its actual source/battery, switch, feed wire and return path in the electrical circuit. Registration alone does not automatically power the part.
2. For an MCU, choose a physical header pin in the exact board diagram. For a motor, sensor or driver, use a supported product terminal diagram or an explicitly entered signal terminal. An IC and a retail module with a similar product name may have different terminals.
3. Choose a target component terminal or another MCU signal pin. Power and signal terminals are separate. Enter supply and return nodes for the actual power path. Documented product terminals are not automatically connected to a shared voltage rail.
4. Save diagram and circuit edits before committing them to the CAD design. See the [MCU pin wiring guide](MCU_PIN_CONNECTIONS_EN.md) for pin selection and save/cancel steps.

## Pending operating data

A model with unknown current or supply conditions can still be registered as product and terminal reference data. This is not a **completed analysis**, **working device** or **zero-current load**. Do not replace board consumption with a recommended adapter current, or treat rated, starting and stall motor currents as interchangeable. The applicable DC scenario needs actual entered operating values.

A manufacturer reference does not make every device a supported resistor model. H-bridge drivers, diodes and encoders provide terminal references; driver control, diode nonlinear behavior and encoder waveforms are not simulated. Unsupported devices are not silently converted into unverified operating models.

## Official diagram coverage

MCU boards use the [official pin sources and coverage](MCU_PIN_SOURCES.md). Additional product diagrams retain the exact order code and official source. SOIC IC pin numbers, carrier-board terminal names, motor wire colors and diode polarity use different conventions. The app does not invent missing physical pin numbers or mechanical dimensions.

| Additional product | Diagram coverage |
| --- | --- |
| ams AS5600-ASOT | Eight pins of the exact SOIC-8 IC; distinct from an unknown AS5600 module header |
| Pololu #2130 DRV8833 carrier | Fifteen documented terminal names; no invented physical order/numbers for the sixteen pads |
| Pololu #4755 motor with encoder | Six documented wire colors/functions; motor and encoder supplies are separate |
| Vishay 1N5819 | Anode and band-marked cathode; no invented pin 1/2 numbering |

Read the [official product terminal references and conditions](ELECTRONIC_PRODUCT_DIAGRAM_SOURCES.md). AS5600 supply-pin connections depend on the power mode. The #4755 encoder output reaches its encoder supply voltage, so compatibility with a 3.3 V MCU is not assumed.

Connecting a product signal to an MCU displays the signal's voltage or pull-up conditions below the diagram. For example, #4755 warns that its encoder has a separate 3.5–20 V supply and its A/B outputs swing to that supply. Check the actual signal voltage and input limits, and add level translation when necessary. Confirmation to discard existing pin assignments applies only to the particular model change being confirmed.

Diagrams explain connectivity. They do not generate a dimensioned PCB outline, connector placement, mounting geometry or cable route, and do not certify full-device operation. Checks cover passive continuity of saved wiring and initial analysis of supported DC inputs. Firmware, communication protocols and electromechanical co-simulation are outside this scope.
