# 2.13.0 update

The AI panel's research references dialog connects a GitHub repository, previews selected documents, and attaches them to design or Q&A requests. Local PDF/text attachments are supported. Codex retries transient disconnections with cancellable backoff and retains the interrupted request and validation context.

**F2** renames a part. **Ctrl+F** searches parts, features, groups, sketches, joints and commands. **View → AI design completion notifications** toggles Windows notifications (on by default).

[Connection instructions, reading limits and reconnect behavior](RESEARCH_REFERENCES_EN.md)

[2.12.0 · AI / usage / roles / research](RESEARCH_AI_EN.md)

# 2.11.0 update

Mouse-wheel zoom keeps the hovered part surface under the pointer; empty space uses the focal plane. Sketch zoom also preserves the cursor coordinate.

Assembly → Physical spur gear drive creates two real external involute gears with integral shafts, a bored support plate, two revolute joints and a tooth-ratio motion link. The AI tool catalogue also supports spur_gear and motion_link. Defaults: module 2, 20/40 teeth, 0.2 mm pair backlash and 0.2 mm diametral shaft clearance. This is a prototype with radial root relief, not a certified hob profile or rated gearbox. Add axial retention, motor coupling and load-appropriate bearings as needed. Editing tooth counts later requires matching centers, phase and motion ratio.

Print preview allows direct part dragging and per-part bed-center X/Y plus XYZ rotation. Printer/automatic layout options are collapsible. Every placement change invalidates export until the latest solids are checked. Interference or an out-of-bed part blocks export. The STL uses the same checked layout, in mm; the original assembly is unchanged. Layout remains local to this dialog. Use a slicer for support, infill, layers and G-code.

J toggles joint glyphs: green means current-pose coaxial shaft/bore support with positive clearance and no connected-part volume interference; amber means unverified; red means interference/structural error; gray means rigid. Green is NOT full-travel, retention, assembly-path or load certification. Inspect the joint to read measured diametral clearance and axial overlap. Motion edits continue to use sampled path collision checks.

# Prompt CAD Studio — English quick guide

## Starting and navigating

Start with a blank document. New sketch creates an XY/XZ/YZ sketch; select a planar face and use Sketch on face to sketch on a body. Finish sketch remains available above the drawing area. Select a closed region and use E to extrude or cut. Open sketches remain editable.

Drag to orbit, middle-drag to pan, scroll to zoom. F fits the model; 1/2/3/4 select isometric/top/front/right views. Click or drag the bottom XYZ marker to orient the camera. Esc clears selection and returns to orbit-only mode; click Orbit again or choose a selection filter to resume selecting geometry.

Shift+click toggles additional parts. B enables box selection. Group selection chooses whole groups or individual members. Ctrl+G groups; Ctrl+Shift+G ungroups. Isolate / Show all / Explode inspect parts without changing assembly constraints. M opens move/rotate; J displays joints. Export parts writes separate STEP/STL files in one ZIP, with local floor/origin or assembly positions.

## Printer allowances

File or Assembly → **3D printer · project allowances**. The requested PLA starting values are bore diameter +0.2 mm, shaft reduction 0 mm and new-joint axial clearance 0.2 mm. Set all to zero is available. These are user-selected starting values, not calibrated accuracy guarantees.

Select supported dimensions in the table or Link all / Selected parts only. Review before/after diameters and actual CAD geometry before Apply. Only listed dimensions are linked. Bore +0.2 mm means radius +0.1 mm per side. Existing clearance remains, so compensation is additional. Repeated updates are not cumulative. Uncheck a row to restore its original value/formula; disabling allowances preserves links with zero compensation. Undo/redo and project save/load preserve settings. Save/load a JSON profile to reuse it on another project.

In a project with a printer profile, a new plain hole uses the entered diameter as nominal and adds the hole allowance in its preview. Counterbore/countersink holes are not automatically linked. New physical joint hardware inherits the project profile. Axial clearance is a creation default and does not move existing joints. Review deviation ± is independent: it supplies limits for new shaft/bore tolerance studies without altering geometry. Its initial zero means no measured deviation entered, not perfect printing. Threaded bodies, imported meshes, linked copies and linked/constrained sketches require editing at their source. Avoid applying the same compensation again in a slicer. STEP/STL contains the evaluated geometry shown in the preview.

## Electronics mounting seats and reference specifications

Select a planar face → Model or Assembly → **Electronics mounting seat**. Enter the measured dimensions of a battery, controller or actuator. Choose rectangular/circular seat, pocket depth and total clearance. Optionally add four through mounting holes and a cable pass-through. Hole pitch is center-to-center. Total clearance 0.2 is 0.1 per side. The preview must form a valid solid before Apply; the results are ordinary editable sketch-cut features.

Use **Import specs from product URL** or Assembly → Product specs to read a public manufacturer/retailer HTML page. Review candidates, original evidence, URL, units and product variant. Use selected dimensions maps dimension 1 to width and 2 to length; check their order. Component height is never automatically used as pocket depth. Unknown bolt patterns are disabled. Applied source data remains in operation history.

Prepare AI request puts the source and selected dimensions in the AI panel. It does not call a model until you press Generate draft. Web text is treated as untrusted reference data. Login pages, PDF/image drawings and JavaScript-only specifications require manual source review. This is not a complete parts catalogue or a fastening, thermal or electrical-safety certification tool.

## Assembly and physical joints

Assembly → Joint from faces: choose a reference planar face, then a planar face on a different moving part. Choose revolute, slider, cylindrical, rigid, ball, planar or pin-slot behavior. Face centers/normals define the joint frame; use Joint from anchors for other positions. Drive joint changes the allowed axes. J shows existing joint locations.

Physical joint hardware creates seven editable bodies linked by ordinary joints. Select a revolute joint and add shaft/housing hardware to attach it to that frame. It is a mechanical concept: fastening screws/keys, bearing selection, certified tolerance grades and load ratings still require engineering.

## Display, language, version and file formats

View → Show grid / Show axes toggles each independently in 3D and sketches. **1 grid = … mm** gives the real cell size; sketch zoom updates the adaptive spacing. Grid snapping is a separate sketch setting.

View → Language → English / 한국어 switches the main UI and persists on restart. User names, saved history and AI-generated text are not translated. Some legacy tree category names and engineering diagnostics remain Korean. Version appears in the title/status bar and Help → Version / about.

STEP/STL exports are direct. IPT requires Inventor; F3D uses a prepared STEP and script executed in Fusion. These transfer geometry rather than rebuilding the original feature timeline. Keep `.cad.json` for the editable native history.

Fillet rounds selected edges using a radius; chamfer bevels them. Use Model → 3D fillet / chamfer. Large radii may be invalid for the selected geometry.

## Common shortcuts

| Shortcut | Action |
| --- | --- |
| Ctrl+N / O / S / Shift+S | New / Open / Save / Save as |
| Ctrl+Z / Y | Undo / Redo |
| Ctrl+C / X / V | Copy / Cut / Paste parts |
| Ctrl+A / D | Select all / Duplicate |
| Ctrl+G / Ctrl+Shift+G | Group / Ungroup |
| Ctrl+K | Find tool |
| Shift+1…6 | Selection filters |
| E / H / I / T / U | Extrude / Hole / Measure / Thread / Parameters |
| M / J / B / F | Move / Show joints / Box select / Fit |
| Esc | Clear selection and orbit; sketch selection tool |
| Ctrl+Enter | Finish sketch |
| F1 | This guide |

Text fields retain normal typing and clipboard shortcuts. AI proposals require validation and Apply; a successful preview is not a guarantee that a design is manufacturable or meets every requirement.


## v2.10 — interference, printing and AI review

The viewport interference badge stays visible whenever exact solid intersections exist; click it to see the affected parts and overlap volume. Groups and hidden parts remain in the check. Preview workflows block newly introduced or increased overlaps, while edits reducing pre-existing overlap can proceed with a warning. Retained union/intersection tool bodies are classified separately from assembly interference.

Joint drive samples intermediate poses at up to 2 degrees / 0.5 mm intervals based on independent and propagated endpoint changes. A detected collision blocks Apply and previews the first collision. Use last checked pose rechecks the proposed stop. This is a discrete check, not a continuous swept-volume or manufacturing certificate; thin obstacles and nonlinear loop motion require further review. New revolute hardware provides separate 0.2 mm rotating, insertion and axial allowances. Active printer compensation adds to nominal assembly allowances.

Choose the 3D printing workspace or File → 3D printing / STL preview. Select parts, print orientation, build dimensions and spacing. Bodies are separated, placed on Z=0 and arranged in rows. Oversized or overlapping layouts cannot export. Save this preview as STL writes the actual checked solids without changing the source assembly. Import as millimetres in a slicer; STL carries no unit metadata. Supports, infill, layers and G-code remain slicer tasks. The existing Export parts action creates separate files when needed.

The AI panel now has Design and Questions modes. Questions can discuss the current design or general topics, retaining up to five exchanges; answers cannot apply geometry. Provider/model changes start a fresh conversation. AI preview / apply opens a Before/After geometry comparison and operation summary. Closing it preserves the design; stale drafts are rejected. New overlaps are sent back for AI repair, with at most three validation attempts. All configured provider usage/billing rules still apply; there is no added web search.

Codex shows a green ✓ only after a successful account and selected-model check or completed request. Saved configuration alone is unverified. Check Codex connection performs account/model discovery without asking for a design. Reopening the app requires a new check. This indicates the last check, not a persistent connection or a usage-balance guarantee.

View → Grid / axes colors, brightness, width lets you choose a grid color and individual XYZ colors, brightness (0–100%) and widths (0.5–5 px). Changes preview in 2D and 3D immediately. Save persists across restarts; Cancel restores the prior appearance, and Restore defaults resets the palette. Visibility and snapping remain independent.


### Concentric shaft / bore repair (2.10)
Assembly → Align joint shaft / bore axes lets you select the actual cylindrical faces of an existing revolute/cylindrical joint. Review measured eccentricity, axis tilt and interference before applying. Current axial placement and clocking are retained by default; turn this off to enter axial gap/angle. Existing limits are preserved. Descendants follow their parent, so check collars and other hardware separately. Cut cylinders or ambiguous references require reselection. Cancel leaves the project unchanged.

New AI face features use the selected face bounding-box midpoint, avoiding the shift in area centroid caused by asymmetric holes. Tilted AI joints must bind to actual measured cylindrical axes. Old documents keep their existing geometry and can be repaired explicitly. Neither alignment nor sampled travel is a manufacturing or continuous collision certificate.


## Graphics startup recovery (2.10.1)

The app tests native rendering in a disposable process before opening the CAD viewport. If the default OpenGL driver fails or hangs, it tests the already-bundled software renderer and falls back automatically. Both failing shows a recovery window with retry and diagnostic buttons. The software renderer uses the CPU; large assemblies may display more slowly, while CAD geometry and project saving remain unchanged. No system graphics drivers or DLLs are replaced.

Use **Help → Graphics startup diagnostics** to inspect the current backend. Diagnostic files live in `%LOCALAPPDATA%/PromptCADStudio`. For troubleshooting, `PromptCADStudio.exe --renderer software` forces the software path. Autosaved projects are not automatically restored or overwritten. This guards the reproduced startup failure and does not guarantee against every native driver/runtime crash.


## Repair an AI draft with interference

Renderable rejected drafts are retained separately from your document. Use **Preview / repair**, select a collision pair, optionally add instructions, and choose **Continue AI interference repair**. Apply stays disabled until validation passes. Repair resumes from the original request and baseline, with measured world/local overlap bounds and additional cutting tools. A cancelled or interrupted repair preserves the previous candidate. This is static geometry validation, not load, fatigue-life or manufacturing certification.
