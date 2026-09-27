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
