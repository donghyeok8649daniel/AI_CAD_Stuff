# Electrical workbench coverage

`cadstudio.electrical_readiness.build_electrical_readiness(design, language="ko")`
returns a JSON-serializable `ElectricalReadinessReport`. A validated `Design`
is inspected directly, without copying its geometry assets, running a DC solve,
opening a renderer, contacting a service, or changing the project/history.

The report distinguishes actual CAD product registrations, legacy loose links,
and circuit items with no CAD body. Candidate bodies use their explicit
`electrical` role or an actual stored circuit link. Names and yellow colors never
infer a product or role. `electrical_parts`/`unregistered_parts` count only the
explicit electrical role; `candidate_parts` includes linked bodies of other roles.
`registered_parts` counts all real registered bodies, whereas
`registered_electrical_parts` counts coverage within the electrical role.

`parts` and `components` include stable identifiers and localized issues, with
machine-readable `code`, `severity` and `next_action`. Part issues must be shown
alongside a linked component's issues: duplicate links or a role mismatch are
not hidden by a valid circuit component. `issues` is the flattened report.

Models are classified `exact`, `family`, `unknown` or `custom`. Exact physical
diagrams supply terminal identities, not a runtime behavior model. Custom
registrations remain custom even if the user supplies a plausible product name.
Reference-only devices may have real terminals while remaining excluded from DC
calculations. Missing operating values must be supplied for the actual operating
point; a recommended power supply's capacity is not a board's consumption.

`available_terminals` counts supported named endpoints. A physical diagram can
display additional reserved/debug/reference pads which are not assignable.
Unused GPIOs are counted in `unassigned_terminals` and are not missing-wire
faults. Named board/product/custom pads exclude spare abstract DC A/B endpoints.
Two-terminal custom items without named pads retain their stored A/B endpoints.

Passive connectivity uses stored nets and closed wires/switches only. A load,
MCU, driver or regulator is never treated as a through-wire. `power_status`
describes stored physical supply/return assignments, not energization or
approval. The current terminal type `power` does not establish direction: input,
output, reference and bypass terminals require manufacturer data review.
`physical_supply_missing` means unassigned power-labelled diagram terminals;
it is not a requirement to connect every such pad to a battery.
`supply_path_connected` and `return_path_connected` indicate a passive
path to a declared source endpoint; they do not determine voltage, direction,
board jumper settings or internal regulator behavior. Named motor phase/Hall
pads do not imply an internal ESC path to a battery. Exact optional outputs are
not all required to be connected.

Explicit physical wire endpoint metadata is checked against current terminals
and branch nets. Deleted endpoints and stale net metadata are blocked review
issues; old wires without endpoint metadata remain readable and are marked
undocumented. Opening/removing a conductor preserves its assigned pad labels
and can expose isolated endpoints without editing the design.

`status` is `empty`, `needs_attention` or `review_only`; there is deliberately
no hardware-ready success status. The report always states
`hardware_execution_supported=false`, `firmware_execution_supported=false`, and
`dc_calculation_performed=false`. GPIO logic, motor commutation, firmware
execution, live instrumentation, hardware operation and safety require separate
validation. A zero pending-item count would still not approve hardware.
