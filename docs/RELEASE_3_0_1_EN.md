# Prompt CAD Studio 3.0.1

Use the selected part's properties or **Assembly → Mechanical function** to distinguish fasteners, passive joint supports, actual motors/actuators and transmission parts. A mixed selection initially keeps each part's declaration. Legacy parts remain unspecified; names, colors and cylindrical geometry do not identify an actuator.

Mechanical purpose is stored independently of display roles/colors, joint constraints and electrical registration. Cancel, Undo, Redo and project persistence preserve these separate fields. Generated revolute housings and bushings are passive supports; shafts and outputs are transmission parts. A purpose declaration or joint status color does not certify a real product, electrical/torque rating or powered operation.

Electrical workspaces support 512 nodes. Sixteen canonical NUCLEO-G474RE GPIOs were added alongside the six existing signal rows and preserved supply/reference rows. Connector/pad labels and solder-bridge, BOOT0 and PA9/PB6 conditions are shown. Verify the actual board revision and fitted bridges separately. A wire drawn over a pin no longer prevents clicking its centre.

Large assembly previews reuse local geometry within one operation, reducing duplicate construction when the number of parts exceeds the persistent cache. Dimensions, relative Boolean operands, poses and interference checks remain in the geometric identity. Actual Open/Save As/reopen results are recorded in the release validation receipt.

Assembly pose and history validation now use scalar angle conversion. Compatibility checks compare 581 forward matrices and 1,426 inverse cases with the previous implementation, including legacy histories near singular angles. Rotation order and existing history tolerances are preserved. This change alone is not evidence that the native crash is fixed.

AI design requests validate an independent copy of the current design. Request preparation previously allowed closed-loop recomputation to change the caller's angle values slightly; this ownership boundary is corrected. Rejected requests preserve the original too, without skipping joint, geometry or history checks or widening their tolerances.

In a matched large-file experiment, native periodic stack collection produced an access violation, while the same code and input completed twelve full history validations without that collection. QA now uses Python periodic stack capture while retaining file, geometry and constraint validation and fatal-error logging. This observation applies to those diagnostic conditions; it does not establish the exact faulting native instruction or eliminate every possible native crash.

Generated firmware and external libraries remain reviewable source data. Source/wiring checks are distinct from target SDK builds and physical board/motor validation. No automatic execution, flashing or device operation is performed.
