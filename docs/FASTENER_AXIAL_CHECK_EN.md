# Preliminary axial bolt tension check

The check runs only after the user enters the **actual total axial tensile force (N)**, **number of identical load-sharing bolts**, and a **safety factor**. It does not derive a machine load from CAD geometry or fill an absent value. The user must explicitly accept the equal-load-sharing assumption.

The reference covers **ISO 898-1 steel bolts with coarse metric threads M4, M5, M6 or M8, property class 8.8 or 10.9**. It assumes pure static axial tension through the threaded section and a real bolt whose size, pitch, class and finish match the selection. The user must also confirm that a low or countersunk head does not invalidate the proof reference. The published proof-load values come from room-temperature tests; they are neither an assembly's allowable operating load nor an ultimate fracture load. For M8, the user must additionally confirm the bolt is not subject to the reduced proof load for hot-dip galvanized 6az threads.

| Coarse thread | Nominal tensile stress area `As` (mm²) | Published proof load, 8.8 (N) | Published proof load, 10.9 (N) |
| --- | ---: | ---: | ---: |
| M4×0.7 | 8.78 | 5,100 | 7,290 |
| M5×0.8 | 14.2 | 8,230 | 11,800 |
| M6×1 | 20.1 | 11,600 | 16,700 |
| M8×1.25 | 36.6 | 21,200 | 30,400 |

The source's stress under proof load `Sp` is **580 MPa** for class 8.8 and **830 MPa** for class 10.9. Given user force `F`, count `n`, and user-selected factor `S`, the checked force per bolt is `F×S/n` and tensile stress is `F×S/(n×As)`. Utilization is `max(checked stress/Sp, checked force per bolt/published proof load)`. Taking the larger ratio handles rounding in the printed load table conservatively. Margin is `1/utilization − 1`. Utilization at or below one means **only that this simplified axial case remains within the proof reference**.

The check does not cover shear, bending, eccentricity, bolt preload or tightening torque, dynamic impact or fatigue, thread pull-out, nuts, washers, substrate strength, FDM plastic joints, bolt-head failure, or actual load distribution. A simple external-force comparison without preload is not a joint design. CAD joints and hole positions do not create load estimates, and the result is not stored as a part safety approval.

The values are from Bossard's [property-class technical page](https://www.bossard.com/ch-en/knowledge-hub/resources/technical-information/screws-property-class-04-to-12/) and its linked [January 2025 PDF](https://assets.eu.ctfassets.net/0vp0u5uh75zd/1VPwGxSRcAQdDRArMtTqeY/8fe01cf6ef692e134b45f895fb69fe97/012_016_Screws_property_class46_Fastening_EN_01_2025.pdf), p. 12 for proof stress and p. 14 for nominal tensile area and proof load. Pitch comes from Bossard's separate [metric-thread technical page](https://www.bossard.com/au-en/knowledge-hub/resources/technical-information/metric-iso-threads/) and linked [January 2025 guide](https://assets.eu.ctfassets.net/0vp0u5uh75zd/2tYqENAuufvdsudjM8Qbrc/b3461eaa59c2203d3a8b9509ac24dacf/096_098_Metric_ISOthreads_Fastening_EN_01_2025.pdf), p. 97. Links were checked on 2026-10-03. The separate [ISO 898-1:2013 record](https://www.iso.org/standard/60610.html) documents the standard's scope. Only these four sizes are entered; the full source tables are not reproduced.

The implementation is [`check_axial_bolts`](../cadstudio/fastener_checks.py) and the native [`FastenerCheckDialog`](../cadstudio/native/fastener_check_dialog.py). The copied report retains the inputs, numerical references, output, excluded cases, and official source.
