# Electrical workspace

Open **Electrical workspace…** on the top toolbar or under **Drawing / analysis**. Its dropdown retains direct access to the schematic, MCU pins, power path, acquisition and drive tools.

The project list includes electrical-role CAD bodies, existing circuit links and circuit-only items. Unregistered CAD bodies remain visible. Search by name, ID or model and filter by kind, registration or inspection state. Enable **All CAD bodies** to register a body with another role. Color does not establish a product identity.

Select an item to inspect its model, physical terminals, assigned signal/power nets and the next steps. Use **Register / edit**, **Schematic / pin wiring** and **Power / rating editor** to modify the draft. **Show CAD part** selects its linked 3D body. Child editor saves remain in the outer draft: only **Save electrical changes** applies one CAD history operation. Cancel preserves the original. Undo, redo and project save/reopen retain the changes without automatically modifying geometry, placement or custom colors.

The product tab separates verified board pins, product terminals, exact models with manual terminals and discovery-only references. The catalogue has 98 entries: 55 registerable models (11 board pinouts, 25 product terminal diagrams and 19 exact models with manual terminals) and 43 discovery-only references. Select an exact product and review its official source. **Find from product metadata** suggests an exact manufacturer/model match stored on the CAD body, without changing registration or wiring. A custom carrier containing a known chip must not be replaced by the bare chip's terminal model; surrounding circuitry and manually declared ports remain separate.

Inspection identifies missing/duplicate registrations, missing bodies, undocumented model/terminal mappings, stale wire endpoints, inconsistent nets, isolated assigned pads and unresolved declared supply/return paths. Unused GPIOs are not faults. An electronics enclosure is not automatically a powered device.

This is static inspection of saved connections, not a DC operating-point calculation or hardware/firmware execution. Use the existing DC tool with explicit inputs. Power-labelled terminals do not establish direction, voltage compatibility, internal regulator connections or motor operation. Unknown values stay pending. The AI receives bounded registration and power-path findings without fabricated operating data or approval.
