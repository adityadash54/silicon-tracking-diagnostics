# coresoftware code map for residual diagnostics

Where the MVTX/INTT residuals in the `ntp` tree come from, and which code a
given kind of finding points to. Paths are relative to `coresoftware/`. Line
numbers were checked in the working tree on branch `alignment_updates` (HEAD
7e9e8e62b) and drift with later commits; always confirm with
`git show <rev>:<path>` or `git blame`.

The working tree has uncommitted changes to
`offline/packages/TrackerMillepedeAlignment/MakeMilleFiles.cc` and `.h`
(about 660 changed lines). `git log` does not show them; check `git status`
and `git diff`, since ntuples may have been produced from an uncommitted build.

## How a residual reaches the `ntp` tree

| Step | Location | What happens |
|---|---|---|
| Clustering (MVTX) | `offline/packages/mvtx/MvtxClusterizer.cc`: `are_adjacent` (l. 72, 94), `ClusterMvtx` (l. 287), `ClusterMvtxRaw` (l. 600); `offline/packages/mvtx/MvtxClusterPruner.cc` | Pixel adjacency, cluster position and size; pruning of clusters. |
| Clustering (INTT) | `offline/packages/intt/InttClusterizer.cc`: `ladder_are_adjacent` (l. 55, 78), `InitRun` (l. 108) | Strip adjacency and cluster position. |
| Cluster errors | `offline/packages/trackbase/ClusterErrorPara.cc` | Cluster position uncertainties used as fit weights. |
| Alignment parameters | `offline/packages/trackbase/AlignmentTransformation.cc`: `createMap` (l. 35) reads a local file (`alignmentParamsFile`, l. 80–90) or the CDB tag `TRACKINGALIGNMENT` (l. 96); `newMakeTransform` (l. 388); `misalignmentFactor` (l. 585); `generateRandomPerturbations` (l. 619) | Builds each sensor's transform from alignment parameters. |
| Transform storage | `offline/packages/trackbase/alignmentTransformationContainer.cc` | Holds the per-surface transforms used by geometry and fitting. |
| Acts geometry | `offline/packages/trackreco/MakeActsGeometry.cc`: `buildAllGeometry` (l. 377), `buildActsSurfaces` (l. 634) | Creates the detector surfaces (and their mapping to hitset keys). |
| Track fit | `offline/packages/trackreco/PHActsTrkFitter.cc` (also `WeightedFitter.cc`) | Produces the fitted track states. |
| Residual definition | `offline/packages/trackreco/ActsAlignmentStates.cc`: l. 149 `localResidual = localMeas - localState`; stored at l. 221 | Local residual = measurement − fitted state (sign convention). |
| `ntp` booking and fill | `offline/packages/TrackerMillepedeAlignment/MakeMilleFiles.cc`: `ntp` columns (`layer:stave:chip:residualX:residualY:...`), residual read from the alignment state, and fill at l. 174–182, 1135, 1314 in the working tree; l. 101–108, 562, 735 at HEAD 7e9e8e62b (the later columns differ) | Writes the tree read by `plot_fits_overlaid_stavechip.C` and the other plot macros; also applies track/vertex selection. |
| Related | `offline/packages/TrackerMillepedeAlignment/HelicalFitter.cc` (own `ntp` with `crosshalfmvtx`), `offline/packages/TrackingDiagnostics/TrackResiduals.cc` (`fillClusterBranchesKF`, l. 1039) | Alternative residual producers; useful for cross-checks. |

## Finding type → where to look

| Finding | Code areas | Non-code causes to rule out |
|---|---|---|
| Coherent stave/ladder-wide mean shift | `AlignmentTransformation.cc` (`createMap`, `newMakeTransform`), `alignmentTransformationContainer.cc`, `MakeActsGeometry.cc` surfaces | Alignment parameter file or `TRACKINGALIGNMENT` CDB tag changed; geometry version |
| Half-layer / half-barrel shift | As above, plus MVTX half-barrel handling (search `half`, e.g. `crosshalfmvtx` in `HelicalFitter.cc`) | Half-barrel alignment constants; stave numbering vs azimuth |
| Isolated chip/sensor mean shift | Per-sensor transform creation in `AlignmentTransformation.cc`; surface ↔ hitset-key mapping in `MakeActsGeometry.cc`; local-coordinate cluster position in the clusterizers | A single sensor's alignment parameters; mapping changes |
| Width-only change on a chip | Clusterizer adjacency/position (`MvtxClusterizer.cc`, `InttClusterizer.cc`), `MvtxClusterPruner.cc`, `ClusterErrorPara.cc`, fitter configuration | Hot/masked pixel maps, thresholds, a chip rotation not covered by the alignment parameters |
| Missing or low-statistics ladder/stave | Hit unpacking/decoding, track selection in `MakeMilleFiles.cc` | Bad-channel maps, ladder off or masked, file coverage |
| Every chip shifted or sign flipped | `ActsAlignmentStates.cc` residual definition, `MakeMilleFiles.cc` fill | Different macro or module configuration |

Most residual changes between productions come from alignment constants,
conditions-database tags or macro settings rather than code. "No code change
in range explains this" is a valid conclusion.
