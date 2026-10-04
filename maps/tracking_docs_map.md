# Tracking references for checking coresoftware expert answers

Read the local snapshot in `tracking_docs/` first (made by
`fetch_tracking_docs.py`; see `tracking_docs/SOURCES.json`). Fetch live only
when the snapshot lacks something, and say so when you do.

## Versions

- **ACTS 45.0.0**: `sPHENIX` branch of `github.com/sPHENIX-Collaboration/acts`,
  commit 2f27de2d0f (2026-06-01). This is the fork sPHENIX builds against;
  `coresoftware` itself does not pin a version. Upstream `main` is a newer,
  different API. If you rely on anything not in the snapshot, read it at
  this commit (`raw.githubusercontent.com/sPHENIX-Collaboration/acts/2f27de2d0f.../<path>`),
  not at `main`, and confirm the version from `tracking_docs/acts/version_number`.
- **Millepede-II V04-17-06**: draft manual by V. Blobel, Doxygen edition by
  C. Kleinwort.

## Millepede-II (`tracking_docs/millepede/draftman_page.txt`, anchors as `{#anchor}`)

| Topic | Anchor | Live URL |
|---|---|---|
| Measurements, residual z = y − f(x), local/global derivatives, sigma; sign consistency | `{#ssec-meapar}` | https://www.desy.de/~kleinwrt/MP2/doc/html/draftman_page.html#ssec-meapar |
| Large problems: global vs local parameters | `{#ssec_large}` | ...#ssec_large |
| Outliers | `{#sssec-outlow}`, `outlierdownweighting`, `chisqcut`, `dwfractioncut` | ...#sssec-outlow |
| Linear constraints, weak modes | `{#ssec-lincon}` | ...#ssec-lincon |
| Text (steering, constraint, parameter) files; `entries` cut | `{#ssec-textfiles}` | ...#ssec-textfiles |
| Solution methods (inversion, diagonalization, MINRES, ...) | `{#sssec-methods}` | ...#sssec-methods |
| Global fit output and checks | `{#ssec-globalfit}` | ...#ssec-globalfit |
| Track-based alignment | `{#ssec-align}` | ...#ssec-align |

## ACTS 45.0.0 (`tracking_docs/acts/`)

| Topic | Snapshot path |
|---|---|
| Geometry context (how alignment enters transforms) | `docs/groups/context.md`; `Core/include/Acts/Geometry/GeometryContext.hpp` |
| Geometry, surfaces, local frames | `docs/groups/detector_descr/geometry.md`; `docs/old/core/geometry/surfaces.md`, `concepts.md`, `geometry_id.md`; `Core/include/Acts/Surfaces/` |
| Measurements and track parameters (loc0/loc1, bound parameters) | `docs/groups/eventdata/measurement.md`, `tracks.md`; `docs/old/core/eventdata/measurements.md`, `parametrization.md`; `Core/include/Acts/EventData/` |
| Track fitting (KF, GX2F, GSF) | `docs/groups/track_fitting.md`; `docs/old/core/reconstruction/track_fitting.md`; `Core/include/Acts/TrackFitting/` |
| Alignment example (ACTS's own approach) | `docs/old/examples/alignment.md` |
| Versioning policy | `docs/pages/versioning.md` |

## sPHENIX code that uses them (`coresoftware/`, read-only)

| What | Where |
|---|---|
| Mille binary writer (sPHENIX's own copy) | `offline/packages/TrackerMillepedeAlignment/Mille.cc`, `Mille.h` |
| Global parameter labels | `offline/packages/TrackerMillepedeAlignment/AlignmentDefs.h` (`getMvtxGlobalLabels`, `getInttGlobalLabels`, vertex labels 60000000–60000002) and `AlignmentDefs.cc` |
| Residuals and derivatives written to Mille and `ntp` | `offline/packages/TrackerMillepedeAlignment/MakeMilleFiles.cc`; `HelicalFitter.cc` |
| Residual definition from the ACTS fit | `offline/packages/trackreco/ActsAlignmentStates.cc` (`localMeas - localState`) |
| Alignment parameters into ACTS transforms | `offline/packages/trackbase/AlignmentTransformation.cc`, `alignmentTransformationContainer.cc` |
| ACTS geometry building and fitting | `offline/packages/trackreco/MakeActsGeometry.cc`, `PHActsTrkFitter.cc` |
