#include <TFile.h>
#include <TMath.h>
#include <TNtuple.h>
#include <TRandom3.h>
#include <TString.h>

#include <cmath>
#include <fstream>
#include <iostream>
#include <set>
#include <sstream>
#include <string>
#include <vector>

// Writes synthetic ROOT files in the MakeMilleFiles format, one per label
// (synth_Iter0.root, synth_Iter1.root, synth_Iter2.root), with the injected
// changes listed in injections.csv. They let the whole pipeline run without
// real data:
//   make_synthetic_ntp.C -> macros/plot_fits_overlaid_stavechip.C
//   -> stdiag.compare_runs -> synthetic.check_against_truth -> triage
// See synthetic/run_full_pipeline.sh.
//
// Trees (only the branches plot_fits_overlaid_stavechip.C reads):
//   ntp       layer:stave:chip:residualX:residualY, one row per cluster;
//             residualX is the local r-phi residual and residualY the local z
//             residual, in mm (measurement - fitted state).
//   track_ntp residual_vertexX:residual_vertexY:track_phi:track_pt, one row per
//             track; residual_vertexX/Y = (-DCA_xy, -DCA_z) in mm.
//
// Model, per chip/sensor and coordinate (the same as
// synthetic/make_synthetic_fit_tables.py, but as clusters instead of fit
// results):
//   - a baseline offset (Gaussian, 0.25 x nominal width) and width spread
//     (+-10%) shared by all labels, so they cancel in a comparison;
//   - entries ~ Poisson(Poisson(nominal)), the inner Poisson shared by all
//     labels; an injection with "entries" sets the count of the whole
//     chip/sensor (both coordinates) in every label;
//   - MVTX and INTT r-phi residuals are Gaussian; INTT z residuals are the
//     strip length (20/16/16/20 mm for sensors 0-3, type B/A/A/B) smeared by
//     a 0.5 mm Gaussian, plus 2% flat outliers;
//   - injected offsets add to the mean, sigma scales multiply the width
//     (for INTT z, the smearing and the box length), "missing" drops the
//     chip from that label.
// Nominal widths are approximately pitch/sqrt(12) from public specifications
// (ALPIDE 26.88 x 29.24 um pixels; INTT 78 um strip pitch, 16/20 mm strips),
// slightly widened for the track uncertainty. Geometry: MVTX 12/16/20 staves
// x 9 chips, INTT 12/12/16/16 ladders x 4 sensors. No real-data values are
// used. A few rows from other layers (TPC-like) check that the plot macro
// ignores them.
//
// The vertex model is the same in every label: a (+30, 0) um offset between
// the event vertex and the point the tracks point back to, which gives
// -DCA_xy = 30 um * sin(phi) per track, smeared by 40 um; -DCA_z is a
// 100 um Gaussian.
//
// Usage (ROOT, from any directory):
//   root -l -b -q 'make_synthetic_ntp.C+("injections.csv", "out")'
// injections.csv is written by
//   python -m synthetic.make_synthetic_fit_tables --out-dir <dir>
// (or use synthetic/reference/injections.csv).
// entriesScale scales every entry count (1 = the statistics of the fit-table
// generator, about 2.7M clusters per file).

namespace
{
  constexpr const char* kLabels[] = {"Iter0", "Iter1", "Iter2"};
  constexpr int kNumberOfLabels = 3;

  constexpr double kBaselineOffsetFraction = 0.25;
  constexpr double kWidthSpreadLow = 0.9;
  constexpr double kWidthSpreadHigh = 1.1;

  constexpr double kInttStripLengthMm[] = {20.0, 16.0, 16.0, 20.0};
  constexpr double kInttZSmearMm = 0.5;
  constexpr double kInttOutlierFraction = 0.02;
  constexpr double kInttOutlierHalfRangeMm = 35.0;

  constexpr int kTracksPerLabel = 50000;
  constexpr double kVertexOffsetXMm = 0.030;
  constexpr double kVertexOffsetYMm = 0.0;
  constexpr double kDcaXyResolutionMm = 0.040;
  constexpr double kDcaZResolutionMm = 0.100;
  constexpr double kTrackPtSlopeGeV = 0.7;

  constexpr int kOtherDetectorRows = 2000;
  constexpr int kOtherDetectorFirstLayer = 7;
  constexpr int kOtherDetectorLastLayer = 54;

  struct DetectorGeometry
  {
    const char* name;
    int firstLayer;
    std::vector<int> stavesPerLayer;
    int chipsPerStave;
    double rphiSigmaMm;
    double zSigmaMm;
    bool zIsStripBox;
    double nominalEntries;
  };

  const std::vector<DetectorGeometry>& detectors()
  {
    static const std::vector<DetectorGeometry> geometry = {
      {"MVTX", 0, {12, 16, 20}, 9, 0.007, 0.008, false, 3000.0},
      {"INTT", 3, {12, 12, 16, 16}, 4, 0.025, 4.6, true, 6000.0}};
    return geometry;
  }

  struct Injection
  {
    std::string name;
    std::set<std::string> labels;
    std::string detector;
    int layer = -1;
    bool allStaves = true;
    std::set<int> staves;
    bool allChips = true;
    std::set<int> chips;
    std::string coord = "both";
    double offsetMm = 0.0;
    double sigmaScale = 1.0;
    int entries = -1;
    bool missing = false;
  };

  // One baseline per chip/sensor, shared by all labels.
  struct ChipBaseline
  {
    const DetectorGeometry* detector = nullptr;
    int layer = -1;
    int stave = -1;
    int chip = -1;
    double rphiOffsetMm = 0.0;
    double zOffsetMm = 0.0;
    double rphiSigmaMm = 0.0;
    double zSigmaMm = 0.0;
    double entries = 0.0;
  };

  // Splits one CSV line; handles double-quoted fields (pandas quotes fields
  // that contain commas).
  std::vector<std::string> split_csv_line(const std::string& line)
  {
    std::vector<std::string> fields(1);
    bool quoted = false;
    for(std::string::size_type index = 0; index < line.size(); ++index)
    {
      const char character = line[index];
      if(character == '"')
      {
        if(quoted && index + 1 < line.size() && line[index + 1] == '"')
        {
          fields.back() += '"';
          ++index;
        }
        else
        {
          quoted = !quoted;
        }
      }
      else if(character == ',' && !quoted)
      {
        fields.emplace_back();
      }
      else if(character != '\r')
      {
        fields.back() += character;
      }
    }
    return fields;
  }

  std::vector<std::string> split(const std::string& text, char separator)
  {
    std::vector<std::string> parts;
    std::stringstream stream(text);
    std::string part;
    while(std::getline(stream, part, separator))
    {
      if(!part.empty())
      {
        parts.push_back(part);
      }
    }
    return parts;
  }

  // "all" means every stave/chip; otherwise a ';'-separated list.
  bool parse_selection(const std::string& field, bool& all, std::set<int>& values)
  {
    all = field == "all";
    if(all)
    {
      return true;
    }
    try
    {
      for(const std::string& part : split(field, ';'))
      {
        values.insert(std::stoi(part));
      }
    }
    catch(const std::exception&)
    {
      return false;
    }
    return !values.empty();
  }

  const std::vector<std::string> kInjectionColumns = {
    "name", "labels", "detector", "layer", "staves", "chips", "coord",
    "offset_mm", "sigma_scale", "entries", "missing"};

  bool read_injections(const char* path, std::vector<Injection>& injections)
  {
    std::ifstream input(path);
    if(!input)
    {
      std::cerr << "ERROR: cannot open " << path << std::endl;
      return false;
    }

    std::string line;
    std::getline(input, line);
    const std::vector<std::string> header = split_csv_line(line);
    for(std::size_t column = 0; column < kInjectionColumns.size(); ++column)
    {
      if(column >= header.size() || header[column] != kInjectionColumns[column])
      {
        std::cerr << "ERROR: " << path << " does not have the columns "
                  << "written by make_synthetic_fit_tables.py" << std::endl;
        return false;
      }
    }

    int lineNumber = 1;
    while(std::getline(input, line))
    {
      ++lineNumber;
      if(line.empty())
      {
        continue;
      }
      const std::vector<std::string> fields = split_csv_line(line);
      Injection injection;
      bool ok = fields.size() >= kInjectionColumns.size();
      try
      {
        if(ok)
        {
          injection.name = fields[0];
          for(const std::string& label : split(fields[1], ';'))
          {
            injection.labels.insert(label);
          }
          injection.detector = fields[2];
          injection.layer = std::stoi(fields[3]);
          ok = parse_selection(fields[4], injection.allStaves,
                               injection.staves) &&
               parse_selection(fields[5], injection.allChips,
                               injection.chips);
          injection.coord = fields[6];
          injection.offsetMm = std::stod(fields[7]);
          injection.sigmaScale = std::stod(fields[8]);
          injection.entries = fields[9].empty() ? -1 :
            static_cast<int>(std::stod(fields[9]));
          injection.missing = fields[10] == "True";
        }
      }
      catch(const std::exception&)
      {
        ok = false;
      }
      if(!ok || (injection.coord != "both" && injection.coord != "rphi" &&
                 injection.coord != "z"))
      {
        std::cerr << "ERROR: cannot parse line " << lineNumber << " of "
                  << path << std::endl;
        return false;
      }
      injections.push_back(injection);
    }

    return true;
  }

  // coord "" matches any coordinate (used for per-chip properties).
  bool matches(const Injection& injection, const std::string& label,
               const ChipBaseline& chip, const std::string& coord)
  {
    return injection.labels.count(label) &&
           injection.detector == chip.detector->name &&
           injection.layer == chip.layer &&
           (injection.allStaves || injection.staves.count(chip.stave)) &&
           (injection.allChips || injection.chips.count(chip.chip)) &&
           (coord.empty() || injection.coord == "both" ||
            injection.coord == coord);
  }

  std::vector<ChipBaseline> make_baselines(unsigned int seed)
  {
    TRandom3 random(seed);
    std::vector<ChipBaseline> baselines;
    for(const DetectorGeometry& detector : detectors())
    {
      for(std::size_t layerIndex = 0;
          layerIndex < detector.stavesPerLayer.size(); ++layerIndex)
      {
        const int layer = detector.firstLayer + static_cast<int>(layerIndex);
        for(int stave = 0; stave < detector.stavesPerLayer[layerIndex];
            ++stave)
        {
          for(int chip = 0; chip < detector.chipsPerStave; ++chip)
          {
            ChipBaseline baseline;
            baseline.detector = &detector;
            baseline.layer = layer;
            baseline.stave = stave;
            baseline.chip = chip;
            baseline.rphiOffsetMm = random.Gaus(
              0.0, kBaselineOffsetFraction * detector.rphiSigmaMm);
            baseline.zOffsetMm = random.Gaus(
              0.0, kBaselineOffsetFraction * detector.zSigmaMm);
            baseline.rphiSigmaMm = detector.rphiSigmaMm *
              random.Uniform(kWidthSpreadLow, kWidthSpreadHigh);
            baseline.zSigmaMm = (detector.zIsStripBox ? kInttZSmearMm :
                                 detector.zSigmaMm) *
              random.Uniform(kWidthSpreadLow, kWidthSpreadHigh);
            baseline.entries = random.PoissonD(detector.nominalEntries);
            baselines.push_back(baseline);
          }
        }
      }
    }
    return baselines;
  }

  // Entry override of a chip: applies to every label (both inputs share the
  // statistics) and to both coordinates, since a cluster has both residuals.
  int entries_override(const std::vector<Injection>& injections,
                       const ChipBaseline& chip)
  {
    for(const Injection& injection : injections)
    {
      if(injection.entries < 0)
      {
        continue;
      }
      for(const std::string& label : injection.labels)
      {
        if(matches(injection, label, chip, ""))
        {
          return injection.entries;
        }
      }
    }
    return -1;
  }

  struct ChipChange
  {
    bool missing = false;
    double rphiOffsetMm = 0.0;
    double zOffsetMm = 0.0;
    double rphiScale = 1.0;
    double zScale = 1.0;
  };

  ChipChange injected_change(const std::vector<Injection>& injections,
                             const std::string& label,
                             const ChipBaseline& chip)
  {
    ChipChange change;
    for(const Injection& injection : injections)
    {
      if(injection.missing && matches(injection, label, chip, ""))
      {
        change.missing = true;
      }
      if(matches(injection, label, chip, "rphi"))
      {
        change.rphiOffsetMm += injection.offsetMm;
        change.rphiScale *= injection.sigmaScale;
      }
      if(matches(injection, label, chip, "z"))
      {
        change.zOffsetMm += injection.offsetMm;
        change.zScale *= injection.sigmaScale;
      }
    }
    return change;
  }

  long fill_clusters(TNtuple& ntp, TRandom3& random,
                     const std::vector<ChipBaseline>& baselines,
                     const std::vector<Injection>& injections,
                     const std::string& label, double entriesScale)
  {
    long clusters = 0;
    for(const ChipBaseline& chip : baselines)
    {
      const ChipChange change = injected_change(injections, label, chip);
      // An entry override is exact; it does not scale with entriesScale.
      const int entryOverride = entries_override(injections, chip);
      const int entries = entryOverride >= 0 ? entryOverride :
        static_cast<int>(random.PoissonD(entriesScale * chip.entries));
      if(change.missing)
      {
        continue;
      }

      const double rphiMean = chip.rphiOffsetMm + change.rphiOffsetMm;
      const double rphiSigma = chip.rphiSigmaMm * change.rphiScale;
      const double zMean = chip.zOffsetMm + change.zOffsetMm;
      const double zSigma = chip.zSigmaMm * change.zScale;
      const double stripLength = chip.detector->zIsStripBox ?
        kInttStripLengthMm[chip.chip] * change.zScale : 0.0;
      for(int cluster = 0; cluster < entries; ++cluster)
      {
        const double rphi = random.Gaus(rphiMean, rphiSigma);
        double z = 0.0;
        if(!chip.detector->zIsStripBox)
        {
          z = random.Gaus(zMean, zSigma);
        }
        else if(random.Uniform() < kInttOutlierFraction)
        {
          z = random.Uniform(-kInttOutlierHalfRangeMm,
                             kInttOutlierHalfRangeMm);
        }
        else
        {
          z = zMean + random.Uniform(-0.5 * stripLength, 0.5 * stripLength) +
              random.Gaus(0.0, zSigma);
        }
        ntp.Fill(chip.layer, chip.stave, chip.chip, rphi, z);
        ++clusters;
      }
    }

    // Rows from other detectors (TPC-like layers), which the plot macro
    // must ignore.
    for(int row = 0; row < kOtherDetectorRows; ++row)
    {
      const int layer = kOtherDetectorFirstLayer + static_cast<int>(
        random.Integer(kOtherDetectorLastLayer - kOtherDetectorFirstLayer + 1));
      ntp.Fill(layer, 0, 0, random.Gaus(0.0, 0.2), random.Gaus(0.0, 0.2));
    }
    return clusters;
  }

  // MakeMilleFiles stores -DCA_xy with DCA_xy = dx*sin(phi) - dy*cos(phi),
  // d = track origin - event vertex.
  void fill_tracks(TNtuple& trackNtp, TRandom3& random)
  {
    const double dx = -kVertexOffsetXMm;
    const double dy = -kVertexOffsetYMm;
    for(int track = 0; track < kTracksPerLabel; ++track)
    {
      const double phi = random.Uniform(-TMath::Pi(), TMath::Pi());
      const double dca = dx * std::sin(phi) - dy * std::cos(phi);
      trackNtp.Fill(-dca + random.Gaus(0.0, kDcaXyResolutionMm),
                    random.Gaus(0.0, kDcaZResolutionMm), phi,
                    random.Exp(kTrackPtSlopeGeV));
    }
  }
}  // namespace

void make_synthetic_ntp(
  const char* injectionsCsv = "injections.csv",
  const char* outputDirectory = ".",
  double entriesScale = 1.0,
  unsigned int seed = 20261001)
{
  std::vector<Injection> injections;
  if(!read_injections(injectionsCsv, injections))
  {
    return;
  }
  if(!(entriesScale > 0.0))
  {
    std::cerr << "ERROR: entriesScale must be positive" << std::endl;
    return;
  }

  const std::vector<ChipBaseline> baselines = make_baselines(seed);
  for(int labelIndex = 0; labelIndex < kNumberOfLabels; ++labelIndex)
  {
    const std::string label = kLabels[labelIndex];
    const TString path = Form("%s/synth_%s.root", outputDirectory,
                              label.c_str());
    TFile file(path, "RECREATE");
    if(file.IsZombie())
    {
      std::cerr << "ERROR: cannot write " << path << std::endl;
      return;
    }

    TRandom3 random(seed + 1000u * static_cast<unsigned int>(labelIndex + 1));
    TNtuple ntp("ntp", "synthetic silicon residuals",
                "layer:stave:chip:residualX:residualY");
    const long clusters = fill_clusters(ntp, random, baselines, injections,
                                        label, entriesScale);
    ntp.Write();

    TNtuple trackNtp("track_ntp", "synthetic track-to-vertex residuals",
                     "residual_vertexX:residual_vertexY:track_phi:track_pt");
    fill_tracks(trackNtp, random);
    trackNtp.Write();
    file.Close();

    std::cout << "Wrote " << path << ": " << clusters << " silicon clusters, "
              << kTracksPerLabel << " tracks" << std::endl;
  }
}
