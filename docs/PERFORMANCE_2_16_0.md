# Metadata-edit preview optimization

The measured workload contains 12 cylinders, 30 mm diameter × 20 mm height, placed 50 mm apart. Seven warmed name/color updates include design validation. The same geometry result is checked against a full preview. Rendering, autosave and file I/O are excluded.

| Path | Median calculation time |
| --- | ---: |
| Full preview, including validation | 174.09 ms |
| Verified geometry reuse, including validation | 0.521 ms |

The reduction is 99.70% for this calculation step on the build machine. It is not a whole-app speedup or a startup/RAM claim. Individual PCs and designs differ. [Raw samples](metadata2160-benchmark.json) accompany this document. The benchmark source remains in `work/benchmark-metadata2160.py` in the development workspace.

Only document name/electrical metadata and per-part name/color/role are excluded from the geometric-input comparison. Poses, dimensions, features, references, constraints, parameter expressions, sketches, assets and groups remain in the comparison. Any change to those inputs takes the normal exact-kernel preview path. The existing preview must match every part ID. Native actors are updated in place only after this check.

Regression checks cover retained actor identity, updated names/colors, undo/redo, actual dimension/hole changes, and refusing reuse after non-metadata changes. The local BRep cache also ignores display-only metadata while retaining geometry and relative boolean-tool placements. No CAD feature or numerical validation is removed. New electrical/standards tools add no third-party dependencies.

AI repair also retains one exact collision result for the unchanged original design within that repair session. It validates a copy, keys the cache by all geometric inputs, checks cancellation, and invalidates changes to dimensions, poses, features or joints. Each candidate's exact collisions, motion sampling and measured repair feedback still run.

Nine alternating trials using 12 cylinders with 11 existing overlaps measured repeated baseline review at 62.10 ms uncached versus 0.879 ms cached median (98.58% reduction for that step). Candidate preview was computed identically in advance for both paths. [Raw samples and source hashes](draft-baseline2160-benchmark.json) specify the scope. This is not total AI generation time.

The dependency audit found no byte-identical binary duplicates in the 742.68 MiB internal checkpoint bundle. Geometry, solvers and graphics dominate its size. Different BLAS libraries use different ABIs; Qt and VTK plugins have dependent libraries. They are retained to preserve functions. No reduction in installation size or peak RAM is claimed from these calculation optimizations.
