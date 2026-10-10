# Prompt CAD Studio v3.1.0

Select CAD parts, preview their print layout, and export one or several build plates. Printing operates on a copy and preserves source geometry, assembly constraints, electronics and project history.

Open **File → 3D printing · STL preview…**, or choose the **3D printing** workspace and then click **STL preview**. If no CAD parts were selected, all parts start checked; review the output checklist. Use Current selection, Select all, Clear selection and the part checklist. **Exclude bolts and nuts** lists excluded parts and classification reasons. Washers, pins and unknown fasteners remain selected. Explicit product subtype takes precedence; separate-word name hints are editable selection aids, not verified product identity.

Enter the printer's X/Y/Z build volume and spacing; the default is 220×220×250 mm. A large selection is packed across multiple plates. **Auto orient / arrange (less support)** compares actual geometry candidates using estimated support demand, bed contact, center-of-mass stability and build-volume fit. Expand **Automatic orientation details** to inspect the current part’s recommended rotation, before/after support estimates, contact area, stability and build-volume fit. These are geometry estimates rather than actual sliced support volume or a print-success guarantee.

Pick a preview plate, enter per-part XYZ rotations and XY positions or drag parts in the top view, and move parts between plates. Manual changes remain editable after the recommendation and survive ordinary preview refreshes. Clicking automatic orientation again applies a fresh recommendation and layout. Automatic layout reset clears output-only manual poses.

The workflow references [Bambu Studio's auto-orientation, arrangement and multiple plates](https://github.com/bambulab/BambuStudio/blob/master/README.md). Final printer/material/support/layer settings and slicing should be checked in Bambu Studio or another slicer.

**Save current plate STL** exports the visible checked plate. **Save all plate STLs as ZIP** exports separate `plate-001.stl` files and a relative-path `print-index.json`. Export uses the checked preview solids. Oversized individual parts and overlaps block that plate and the full ZIP; other valid plates can still be exported individually. Individual bodies are not automatically sliced into unvalidated joints. Supports, infill, layers and G-code belong in your slicer; printer clearance is not applied twice.

Changing settings invalidates an old preview. Cancelling the save dialog or closing during export preserves the source project; cancellation is checked before replacing existing output.

This release also preserves full floating-point precision for motion ratios, offsets and limits, adds explicit editing of an existing motion link, and blocks incomplete or stale input. It does not certify actuator ratings, screw lead or strength.

Actual source/native verification is recorded in `VALIDATION.md` and `docs/native310-validation.json`. Historical test counts are labelled by version. Synthetic print checks do not approve manufacturing, hardware motion or structural capacity.
