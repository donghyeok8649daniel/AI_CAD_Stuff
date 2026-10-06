# CAD / circuit correspondence and AI wiring

The direct **Circuit** button immediately beside **Part color…** opens the saved physical wiring view. **Electrical workspace…** and its existing menu remain available.

## Find the real part

Selecting a CAD body highlights its associated component in an open circuit view. **Find this part in the circuit** in CAD properties opens and zooms to that component. Selecting a circuit component selects its CAD association; **Show CAD part** returns to the model and fits the actual body. The inspector shows both names and IDs, plus registered / legacy association status. A component without a body shows **No CAD association** and does not select an unrelated body.

## Link an existing circuit component

1. Select the existing circuit component and click **Link CAD body…**. The corresponding CAD properties action and **Link existing circuit ↔ CAD…** in the electrical workspace open the same dialog.
2. Choose the existing component and its actual body. Search body names / IDs; bodies used by another component are unavailable.
3. Click **Link · preview**, inspect the association, then **Save link changes**. Existing component IDs, models, pins, wires, ratings and CAD geometry are retained. The selected body receives the electrical role; its custom color stays unless default yellow is checked.

**Unlink CAD only** clears the body association without deleting the component, pins or wires. The body's role and color remain. Use the existing electrical registration / model editor to change an actual product identity or its physical pin map.

| Opened from | Final application |
| --- | --- |
| Saved main / floating circuit view or CAD properties | **Save link changes** in the association dialog |
| **Edit circuit…** | Save the association, then **Save circuit changes** in the outer editor |
| **Electrical workspace…** | Save child edits, then **Save electrical changes** in the outer workspace |

Cancel in the outer editor discards accepted child edits. The final save creates one history transaction, supports undo / redo and `.cad.json` save / reopen, and retains source sketches, parameters and imported shape data.

## Ask AI to edit wiring

Enter the desired component, pin or wire changes in **Prepare AI wiring…**. The selected component ID and terminal are included. A saved circuit view prepares the request in the main AI input immediately. An editor queues it until **Save electrical changes · prepare AI**; a surrounding electrical workspace also requires its final Save. Cancel discards the queued request.

The main panel switches to design mode and clears the previous unapplied draft. Only **Generate draft** starts a model request. An already running AI task is not overwritten. Review the electrical changes and before / after wiring in the new draft preview before applying it. AI can edit existing associations and wires with physical endpoint metadata; missing ratings, cable dimensions and manufacturer specifications must remain unknown.

Circuit correspondence describes documented connections. A motor catalog entry or pin diagram does not validate internal ESC behavior, MCU firmware execution or actual motor operation. Missing operating current, cable ratings and supply paths remain pending.
