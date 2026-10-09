# 2.24.0 · Codex firmware · BOM design · CAD file opening

Generate a source candidate from an exact registered board, its documented pins, saved wires and a behavior request. This uses the existing ChatGPT-subscription Codex connection. Code upload, wiring traces and declared DC safety checks remain available.

**Design from BOM…** in the AI panel imports CSV/TSV/XLSX or pasted tables. Review quantities, exact models and explicit dimensions, then save the BOM as design input. Actual CAD instances are mapped with `bom_bind`, compared in the **BOM comparison** preview tab, and stored in project history. Missing specifications remain pending; mismatches block applying the candidate. A BOM is not manufacturer shape, fit or strength certification. See the [BOM guide](BOM_DESIGN_KO.md).

New projects default to the dedicated `.pcad` extension. `Install.ps1` creates a desktop shortcut and registers its open action, preserving existing default-app choices and ordinary JSON associations. Legacy `.cad.json` files remain readable; ordinary Save keeps an existing file's path. A missing legacy path can also find its renamed `.pcad` counterpart in the same folder. Registration can be managed from **File → CAD file opening…**.

## Open and generate

Open **the circuit menu beside selected-part color → Codex firmware · generate / review…**, or the matching button in the electrical workbench. Register an actual CAD part as an exact supported board first. A product family or manually invented pin map is not a supported target.

1. Select the registered board and its supported STM32 HAL, Arduino or Raspberry Pi Python target.
2. Check the connection and select a model and reasoning effort returned by your Codex account. Selection alone does not start generation.
3. Describe the behavior and generate. The main AI panel's time limit applies. Unlimited mode continues validation repairs; interrupted communication waits for reconnection. Authentication and usage problems are not retried forever.
4. Review the source files, pins/wiring and unknowns/check results.
5. **Save all code changes** stores the reviewed drafts in the private workbench or project. When opened inside the electrical workbench, save the outer workbench too. Cancelling the outer workbench discards the child changes.

GitHub/file references already attached in the main AI panel are passed as factual text and citations. Links are not automatically fetched and source is not executed. Oversized reference sets are rejected with an explanation instead of silently omitted.

## Example request

> Generate a fatigue-test controller source candidate for the selected board and saved wiring. Start idle. Separate armed, running and latched-fault states. Emergency stop, stale feedback and timeout must inhibit restart until deliberate reset. Keep unknown motor, encoder, calibration, travel and frequency parameters unconfigured. Distinguish virtual data from measurements and use physical seconds and Hz. Explicitly identify missing SDK and device adapters.

**B-G431B-ESC1** context includes documented external connectors only. It does not establish internal GPIO/timer mappings, an MCSDK project or validated motor commutation parameters.

## Portable review and save

Sources, documentation, the request/model/UTC generation record, board/wiring fingerprints and file SHA values are embedded in `.pcad`. External source folders are not needed to reopen them. Changes use normal project history and undo/redo while preserving existing dimensions, colors and history.

Switching boards or saved code keeps edits inside the dialog. Saving reviews and applies all changed code together. Detach is also an explicit saved change. Board/wiring edits preserve the old source and mark its binding stale; regenerate and review against current wiring.

Pin checks cover recognized constants and GPIO APIs. Dynamic expressions, SDK internals and all runtime paths remain unverified. Editing source invalidates previous syntax results.

Code storage allows 16 bundles per project, 32 files / 2 MiB per bundle, and 256 KiB UTF-8 per file. These are code-attachment limits, **not the former 32 MB CAD project save limit**.

## Check and export

**Build / source check** parses Python without importing or executing it. An explicitly selected installed GNU/Clang C/C++ compiler runs a fixed syntax-only check. Missing SDK headers or tools stay pending. Syntax success does not mean a complete target build, link or hardware validation. Generated build/upload hooks are not executed.

**Export to new folder…** atomically writes sources and their binding manifest to a new directory. Existing directories are not overwritten; failed/cancelled exports do not publish a partial result. Use the exact board IDE/SDK project for later target builds and device testing.

## Validation scope

An actual subscription request with an owned Raspberry Pi 4 / GPIO18 wire fixture returned five source files and a README. Pin auditing, Python syntax, portable project save/reopen, undo/redo and atomic export passed. The generated program was not executed; no paid API or hardware was used.

An actual subscription BOM request succeeded on the first attempt in 17.125 seconds. Two white plates measured 60×35×4 mm each, with a measured 100 mm gap. Quantities, mappings, four history actions and portable save/reopen matched. This does not establish arbitrary BOM success or manufacturing suitability.

Final source/native Windows EXE counts are in [validation evidence](native2240-validation.json). Full firmware/Linux/FOC emulation, physical device operation and fatigue load/frequency/stroke ratings are outside this verification.

New users install the Windows ZIP from the release. Existing users run `PromptCADStudioUpdater.exe` to update the same installation. Save and close all CAD windows before updating.
