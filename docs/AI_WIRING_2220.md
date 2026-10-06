# AI wiring plans in the native CAD app

The AI design pipeline can register an existing CAD body, link a circuit item
that already exists to its corresponding body, and create or edit saved wires
between real diagram terminals. These are structured CAD actions. A text answer
describing a circuit does not create a circuit.

Generate a draft, inspect its circuit changes and diagram in the private preview,
then apply the draft. Application uses the normal document history. The original
design stays unchanged while the draft is generated or while a validation fails.
Saving and reopening retains the device IDs, endpoint labels, wire IDs and undo
history. Electrical-only actions do not rebuild unchanged CAD geometry.

## Device identity and CAD correspondence

Use `electrical_register` to register a body which has no corresponding circuit
item. Select an exact catalog ID when the model is known; a family is not an
exact product. A custom device can keep its manually declared ports without
pretending to be an exact bare IC or board. Unknown ratings remain pending.

Use `electrical_bind` when the circuit item already exists. Its `target` is the
actual CAD body ID and `args.component_id` is the existing circuit item ID. This
preserves that item, all ratings, pins, wires and diagram positions. It marks the
body's role as electrical and keeps its custom color unless
`apply_default_color: true` is requested. A body cannot be linked to two circuit
items. Binding an exact legacy board also checks the saved pin names against
that board; mismatched names are rejected without clearing the old circuit.

`electrical_unbind` removes only the CAD link. Its `target` is the circuit item
ID and its arguments are empty. The circuit item and wires remain.
`electrical_unregister` removes the registration's circuit item; it should be
used only when removal is explicitly requested.

## Actual wires and passive node assignments

`electrical_wire_add` creates a saved wire component with two physical endpoint
references. It accepts a circuit item ID or an unambiguous registered CAD body
ID for its source and destination. A body ID is useful for a registration made
earlier in the same plan: the AI does not need to guess a generated circuit ID.

Terminal labels come from the actual context:

- `pin:GPIO17`: a documented signal pin, not a physical pin number.
- `supply:5V_2` and `supply:GND_6`: specific Raspberry Pi header power pads.
- `port:AIN1`: an exact product terminal or an existing custom named port.
- `a` / `b`: the declared two-terminal DC model, separate from board pads.

For example, after registering the existing `pi` and `driver` bodies:

```json
{
  "tool": "electrical_wire_add",
  "target": "pi",
  "args": {
    "source_terminal": "pin:GPIO17",
    "target_id": "driver",
    "target_terminal": "port:AIN1",
    "name": "Command signal",
    "wire_color": "#12AB34",
    "analysis_enabled": false
  }
}
```

When cable length and area are unknown, their defaults are zero and DC analysis
is disabled for the new wire. The drawing and passive connection exist, but no
voltage-drop or ampacity result is fabricated. Enable DC only with positive
physical length and conductor area. A wire calculation never fills unknown
motor, board or supply operating ratings.

The older `electrical_connect` action still performs its passive node-label
assignment for compatibility. It does **not** create a saved wire component. An
AI request to draw or add a cable should use `electrical_wire_add`.
Reassigning a pin with an existing physical wire is rejected if it would detach
that wire's saved branch; use `electrical_wire_edit` to change the cable's end.

`electrical_wire_edit` keeps the selected wire's ID, ordering and unrequested
metadata. Each changed end requires both `source_id` / `source_terminal` or
`target_id` / `target_terminal`. Property edits also support old wires without
endpoint metadata; defining physical endpoints for such a wire requires both
ends. `electrical_wire_delete` removes one wire only, preserving devices, other
wires and named nets. Disconnected old pads remain visible.

Duplicate physical pairs and nonexistent terminals are rejected. A new wire may
fan out to a pin already used by another wire without changing that old branch.
If inserting into a shared node would detach a pin used by an older physical
wire, the action is rejected atomically; edit the existing wire or select another
pad. Boolean state must be explicit `true` / `false`.

## Review limits

AI context includes actual circuit items even when they have no CAD link, their
supported endpoints and current nets, plus saved physical wire references.
Bounded lists report omitted counts. Unlisted reserved pins and internal board
rail connections are not inferred. GPIO-to-power topology warnings stay visible
in the result and preview. These actions do not execute firmware, energize
hardware, qualify an ESC loop or approve a fatigue-test controller.

Offline provider tests execute real registration, binding, power-pad, signal and
motor-terminal wire actions through the common local-AI pipeline. They also
verify private previews, failed-plan atomicity, wire edits, deletion, reopen and
undo/redo. A live model's interpretation still depends on the supplied part
identities, specifications and requested connections.
