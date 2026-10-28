#include <TAxis.h>
#include <TCanvas.h>
#include <TChain.h>
#include <TColor.h>
#include <TF1.h>
#include <TFitResult.h>
#include <TFitResultPtr.h>
#include <TGraphErrors.h>
#include <TH1D.h>
#include <TH1F.h>
#include <TLegend.h>
#include <TLatex.h>
#include <TMath.h>
#include <TROOT.h>
#include <TString.h>
#include <TStyle.h>
#include <TSystem.h>
#include <TPad.h>
#include <TTreeReader.h>
#include <TTreeReaderValue.h>

#include <algorithm>
#include <cctype>
#include <cmath>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <limits>
#include <map>
#include <memory>
#include <set>
#include <sstream>
#include <string>
#include <vector>

// Layer 1 of the residual-comparison workflow and the residual plots, in one
// macro so that the fitted numbers and the plots always come from the same
// histograms and the same fit. Fills every MVTX chip and INTT sensor local
// residual distribution and the track-to-vertex residuals from track_ntp,
// fits them, and writes
//   - one CSV table per input file list (writeToCsv), read by compare_runs.py,
//     and, with track_ntp, one table per input with the A*sin(phi - phi0) + c
//     fit to <-DCA_xy> vs track phi;
//   - a PDF (plus PNGs) with one page per stave and coordinate and a final
//     track-to-vertex residual page (makePlots).
// Runs locally only; nothing is sent to any external service.

namespace
{
  constexpr int kResidualBins = 200;
  constexpr double kMinimumEntriesForFit = 10.0;
  constexpr int kMinimumPopulatedBinsForFit = 4;
  constexpr int kCoreFitIterations = 2;
  constexpr double kCoreFitSigmaWindow = 2.0;
  // More than this fraction of the entries in the under/overflow gives
  // fit_status out_of_range instead of a fit.
  constexpr double kMaximumOutOfRangeFraction = 0.5;
  // The box fit has five parameters, so it needs more data than the Gaussian.
  constexpr double kMinimumEntriesForBoxFit = 50.0;
  constexpr int kMinimumPopulatedBinsForBoxFit = 10;
  constexpr int kBoxFitIterations = 2;
  constexpr double kBoxFitWindowScale = 0.75;
  constexpr int kMinimumPhiBinsForModulationFit = 4;
  constexpr int kInputColors[] = {
    kBlack, kRed + 1, kBlue + 1, kGreen + 2,
    kMagenta + 1, kOrange + 7, kCyan + 2, kViolet + 1};
  constexpr int kInputMarkerStyles[] = {20, 24, 21, 25, 22, 26, 23, 32};

  struct DetectorConfig
  {
    const char* detectorName;
    const char* outputPrefix;
    const char* panelLabel;
    const char* combinedTitle;
    int firstLayer;
    int numberOfLayers;
    int chipsPerStave;
    int canvasColumns;
    int canvasRows;
    double rphiDisplayRangeMm;
    double rphiHistogramRangeMm;
    double rphiFitRangeMm;
    double zDisplayRangeMm;
    double zHistogramRangeMm;
    double zFitRangeMm;
    bool zUsesBoxFit;
  };

  // The display ranges are the plotted half-widths. The histogram ranges are
  // the filled and fitted half-widths, wide enough that a misaligned chip
  // stays inside them; the bin width is the same in both (kResidualBins over
  // the display range). The fit ranges are the half-widths of the Gaussian
  // seed fit window. INTT z residuals are dominated by the 16 or 20 mm strip
  // length, so they get the box fit (fit_box_gaussian) instead, which does not
  // use zFitRangeMm.
  constexpr DetectorConfig kMvtxConfig = {
    "MVTX", "mvtx", "Chip", "All chips combined", 0, 3, 9, 5, 2,
    0.05, 0.5, 0.015, 0.05, 0.5, 0.015, false};
  constexpr DetectorConfig kInttConfig = {
    "INTT", "intt", "Sensor", "All sensors combined", 3, 4, 4, 3, 2,
    0.6, 3.0, 0.2, 20.0, 40.0, 5.0, true};

  // Track-to-vertex residuals from track_ntp, stored by MakeMilleFiles as
  // (-DCA_xy, -DCA_z) in mm. Ranges follow plot_fits_overlaid.C
  // (+-0.2 cm displayed, +-0.05 cm fitted).
  constexpr const char* kVertexDetectorName = "VERTEX";
  constexpr double kVertexDisplayRangeMm = 2.0;
  constexpr double kVertexFitRangeMm = 0.5;
  constexpr int kVertexPhiBins = 14;

  struct InputSpec
  {
    std::string listfile;
    std::string label;
  };

  // model is "gaus" (core Gaussian) or "box_gaus" (box convolved with a
  // Gaussian, see fit_box_gaussian); the box parameters stay NaN for "gaus".
  struct ChipFitResult
  {
    std::string model = "gaus";
    std::string status = "low_stats";
    double entriesInWindow = 0.0;
    int populatedBins = 0;
    double amplitude = std::numeric_limits<double>::quiet_NaN();
    double mean = std::numeric_limits<double>::quiet_NaN();
    double meanError = std::numeric_limits<double>::quiet_NaN();
    double sigma = std::numeric_limits<double>::quiet_NaN();
    double sigmaError = std::numeric_limits<double>::quiet_NaN();
    double chi2 = std::numeric_limits<double>::quiet_NaN();
    int ndf = 0;
    double fitLowMm = std::numeric_limits<double>::quiet_NaN();
    double fitHighMm = std::numeric_limits<double>::quiet_NaN();
    double boxLength = std::numeric_limits<double>::quiet_NaN();
    double boxLengthError = std::numeric_limits<double>::quiet_NaN();
    double edgeSigma = std::numeric_limits<double>::quiet_NaN();
    double edgeSigmaError = std::numeric_limits<double>::quiet_NaN();
    double background = std::numeric_limits<double>::quiet_NaN();
  };

  // <-DCA_xy> vs track phi fitted with A*sin(phi - phi0) + c (see
  // fit_phi_modulation). offsetX/Y = A*(cos phi0, sin phi0) is the event
  // vertex minus the point the tracks point back to.
  struct PhiModulationFit
  {
    std::string status = "low_stats";
    int phiBinsUsed = 0;
    double amplitude = std::numeric_limits<double>::quiet_NaN();
    double amplitudeError = std::numeric_limits<double>::quiet_NaN();
    double phi0 = std::numeric_limits<double>::quiet_NaN();
    double phi0Error = std::numeric_limits<double>::quiet_NaN();
    double constant = std::numeric_limits<double>::quiet_NaN();
    double constantError = std::numeric_limits<double>::quiet_NaN();
    double offsetX = std::numeric_limits<double>::quiet_NaN();
    double offsetXError = std::numeric_limits<double>::quiet_NaN();
    double offsetY = std::numeric_limits<double>::quiet_NaN();
    double offsetYError = std::numeric_limits<double>::quiet_NaN();
    double chi2 = std::numeric_limits<double>::quiet_NaN();
    int ndf = 0;
  };

  struct StaveHistograms
  {
    int layer = -1;
    int stave = -1;
    // Indexed as [input][chip].
    std::vector<std::vector<TH1D*>> rphiHistograms;
    std::vector<std::vector<TH1D*>> zHistograms;
    std::vector<std::vector<ChipFitResult>> rphiFits;
    std::vector<std::vector<ChipFitResult>> zFits;
    // Sums over all chips of the stave, indexed as [input]; built by
    // build_stave_sums after every input is filled. Written to the CSV with
    // chip = -1.
    std::vector<TH1D*> rphiStaveHistograms;
    std::vector<TH1D*> zStaveHistograms;
    std::vector<ChipFitResult> rphiStaveFits;
    std::vector<ChipFitResult> zStaveFits;
  };

  using StaveHistogramMap =
    std::map<std::pair<int, int>, StaveHistograms>;

  struct VertexHistograms
  {
    // Indexed as [input]; the phi-binned ones as [input][phi bin].
    std::vector<TH1D*> transverseHistograms;
    std::vector<TH1D*> longitudinalHistograms;
    std::vector<std::vector<TH1D*>> transversePhiHistograms;
    std::vector<std::vector<TH1D*>> longitudinalPhiHistograms;
    std::vector<ChipFitResult> transverseFits;
    std::vector<ChipFitResult> longitudinalFits;
    std::vector<std::vector<ChipFitResult>> transversePhiFits;
    std::vector<std::vector<ChipFitResult>> longitudinalPhiFits;
    std::vector<PhiModulationFit> transversePhiModulationFits;
  };

  // ---------------------------------------------------------------------------
  // Inputs
  // ---------------------------------------------------------------------------

  std::string trim(const std::string& text)
  {
    const std::string::size_type first = text.find_first_not_of(" \t");
    if(first == std::string::npos)
    {
      return "";
    }

    const std::string::size_type last = text.find_last_not_of(" \t");
    return text.substr(first, last - first + 1);
  }

  std::string default_input_label(const std::string& listfile)
  {
    std::string label = listfile;
    const std::string::size_type slash = label.find_last_of('/');
    if(slash != std::string::npos)
    {
      label = label.substr(slash + 1);
    }

    const std::string::size_type dot = label.find_last_of('.');
    if(dot != std::string::npos && dot > 0)
    {
      label = label.substr(0, dot);
    }

    return label;
  }

  // Parses "list1.txt:Label1,list2.txt:Label2"; a missing label defaults to
  // the list filename without directory and extension.
  std::vector<InputSpec> parse_input_specs(const char* listfiles)
  {
    std::vector<InputSpec> inputs;
    std::stringstream stream(listfiles);
    std::string token;
    while(std::getline(stream, token, ','))
    {
      token = trim(token);
      if(token.empty())
      {
        continue;
      }

      InputSpec input;
      const std::string::size_type colon = token.find(':');
      input.listfile = trim(token.substr(0, colon));
      input.label =
        colon == std::string::npos ? "" : trim(token.substr(colon + 1));
      if(input.listfile.empty())
      {
        continue;
      }
      if(input.label.empty())
      {
        input.label = default_input_label(input.listfile);
      }
      inputs.push_back(input);
    }

    return inputs;
  }

  std::string sanitize_for_filename(const std::string& text)
  {
    std::string sanitized;
    for(const char character : text)
    {
      const bool keep =
        std::isalnum(static_cast<unsigned char>(character)) ||
        character == '-' || character == '_' || character == '.';
      sanitized += keep ? character : '_';
    }

    return sanitized.empty() ? "input" : sanitized;
  }

  // Labels name the CSV files and fill a CSV column, so they must be distinct
  // after sanitizing and must not contain commas.
  bool validate_csv_labels(const std::vector<InputSpec>& inputs)
  {
    std::set<std::string> outputNames;
    for(const InputSpec& input : inputs)
    {
      if(input.label.find(',') != std::string::npos ||
         input.listfile.find(',') != std::string::npos)
      {
        std::cerr << "ERROR: labels and list files must not contain commas."
                  << std::endl;
        return false;
      }
      if(!outputNames.insert(sanitize_for_filename(input.label)).second)
      {
        std::cerr << "ERROR: duplicate input label '" << input.label
                  << "'; every input needs a distinct label." << std::endl;
        return false;
      }
    }

    return true;
  }

  bool load_ntuple_chain(TChain* chain, const char* listfile)
  {
    std::ifstream infile(listfile);
    if(!infile.is_open())
    {
      std::cerr << "ERROR: could not open " << listfile << std::endl;
      return false;
    }

    std::string filename;
    int filesAdded = 0;
    while(infile >> filename)
    {
      std::cout << "Adding " << filename << std::endl;
      const int added = chain->Add(filename.c_str());
      if(added > 0)
      {
        filesAdded += added;
      }
      else
      {
        std::cerr << "WARNING: failed to add " << filename << std::endl;
      }
    }

    if(filesAdded == 0 || chain->GetEntries() == 0)
    {
      std::cerr << "ERROR: no usable " << chain->GetName()
                << " entries were loaded from " << listfile << std::endl;
      return false;
    }

    return true;
  }

  bool has_required_branches(TChain* chain)
  {
    const std::vector<std::string> requiredBranches = {
      "layer", "stave", "chip", "residualX", "residualY"};

    chain->LoadTree(0);
    for(const auto& branch : requiredBranches)
    {
      if(!chain->GetBranch(branch.c_str()))
      {
        std::cerr << "ERROR: required branch '" << branch
                  << "' is missing from tree ntp." << std::endl;
        return false;
      }
    }

    return true;
  }

  bool has_required_vertex_branches(TChain* chain)
  {
    const std::vector<std::string> requiredBranches = {
      "residual_vertexX", "residual_vertexY", "track_phi", "track_pt"};

    chain->LoadTree(0);
    for(const auto& branch : requiredBranches)
    {
      if(!chain->GetBranch(branch.c_str()))
      {
        std::cerr << "WARNING: branch '" << branch
                  << "' is missing from tree track_ntp." << std::endl;
        return false;
      }
    }

    return true;
  }

  const DetectorConfig* get_detector_config(int layer)
  {
    for(const DetectorConfig* config : {&kMvtxConfig, &kInttConfig})
    {
      if(layer >= config->firstLayer &&
         layer < config->firstLayer + config->numberOfLayers)
      {
        return config;
      }
    }

    return nullptr;
  }

  bool get_integer_identifier(Float_t value, int& identifier)
  {
    const double doubleValue = static_cast<double>(value);
    if(!std::isfinite(value) ||
       doubleValue < static_cast<double>(std::numeric_limits<int>::min()) ||
       doubleValue > static_cast<double>(std::numeric_limits<int>::max()))
    {
      return false;
    }

    const int integerValue = static_cast<int>(value);
    if(std::fabs(value - integerValue) > 1e-5)
    {
      return false;
    }

    identifier = integerValue;
    return true;
  }

  // ---------------------------------------------------------------------------
  // Histograms
  // ---------------------------------------------------------------------------

  int input_color(int inputIndex)
  {
    return kInputColors[
      inputIndex % (sizeof(kInputColors) / sizeof(kInputColors[0]))];
  }

  int input_marker_style(int inputIndex)
  {
    return kInputMarkerStyles[
      inputIndex %
      (sizeof(kInputMarkerStyles) / sizeof(kInputMarkerStyles[0]))];
  }

  void style_input_histogram(TH1* histogram, int inputIndex)
  {
    histogram->GetXaxis()->SetTitleSize(0.055);
    histogram->GetYaxis()->SetTitleSize(0.055);
    histogram->GetXaxis()->SetLabelSize(0.045);
    histogram->GetYaxis()->SetLabelSize(0.045);
    histogram->SetLineWidth(2);
    histogram->SetLineColor(input_color(inputIndex));
    histogram->SetMarkerColor(input_color(inputIndex));
    histogram->SetMarkerStyle(input_marker_style(inputIndex));
    histogram->SetMarkerSize(0.8);
  }

  TH1D* make_chip_histogram(
    const DetectorConfig& config,
    int layer,
    int stave,
    int chip,
    int inputIndex,
    const char* coordinateName,
    const char* residualLabel,
    double residualDisplayRangeMm,
    double residualHistogramRangeMm)
  {
    const TString histogramName = Form(
      "h_%s_L%d_stave%d_chip%d_in%d_%s",
      config.outputPrefix, layer, stave, chip, inputIndex, coordinateName);
    // Same bin width as kResidualBins over the display range.
    const int bins = static_cast<int>(std::lround(
      kResidualBins * residualHistogramRangeMm / residualDisplayRangeMm));
    TH1D* histogram = new TH1D(
      histogramName.Data(),
      Form("%s %d", config.panelLabel, chip),
      bins,
      -residualHistogramRangeMm,
      residualHistogramRangeMm);
    histogram->SetDirectory(nullptr);
    histogram->GetXaxis()->SetTitle(
      Form("local %s residual [mm]", residualLabel));
    histogram->GetYaxis()->SetTitle("Entries");
    style_input_histogram(histogram, inputIndex);
    return histogram;
  }

  StaveHistograms make_stave_histograms(
    const DetectorConfig& config,
    int layer,
    int stave,
    int numberOfInputs)
  {
    StaveHistograms histograms;
    histograms.layer = layer;
    histograms.stave = stave;
    histograms.rphiHistograms.resize(numberOfInputs);
    histograms.zHistograms.resize(numberOfInputs);
    histograms.rphiFits.assign(
      numberOfInputs, std::vector<ChipFitResult>(config.chipsPerStave));
    histograms.zFits.assign(
      numberOfInputs, std::vector<ChipFitResult>(config.chipsPerStave));
    histograms.rphiStaveFits.resize(numberOfInputs);
    histograms.zStaveFits.resize(numberOfInputs);

    for(int input = 0; input < numberOfInputs; ++input)
    {
      histograms.rphiHistograms[input].reserve(config.chipsPerStave);
      histograms.zHistograms[input].reserve(config.chipsPerStave);
      for(int chip = 0; chip < config.chipsPerStave; ++chip)
      {
        histograms.rphiHistograms[input].push_back(make_chip_histogram(
          config, layer, stave, chip, input, "rphi", "r-#phi",
          config.rphiDisplayRangeMm, config.rphiHistogramRangeMm));
        histograms.zHistograms[input].push_back(make_chip_histogram(
          config, layer, stave, chip, input, "z", "Z",
          config.zDisplayRangeMm, config.zHistogramRangeMm));
      }
    }

    return histograms;
  }

  // With minimumPtGeV > 0, only clusters whose track has track_pt at or above
  // the cut are filled (a non-finite pT fails the comparison, as for the
  // vertex residuals); the caller checks that ntp has track_pt. At 0 the
  // branch is not read, so ntuples without it are unaffected.
  void fill_silicon_histograms(
    TChain* ntp,
    int inputIndex,
    int numberOfInputs,
    double minimumPtGeV,
    StaveHistogramMap& histograms)
  {
    TTreeReader reader(ntp);
    TTreeReaderValue<Float_t> layerValue(reader, "layer");
    TTreeReaderValue<Float_t> staveValue(reader, "stave");
    TTreeReaderValue<Float_t> chipValue(reader, "chip");
    TTreeReaderValue<Float_t> residualXValue(reader, "residualX");
    TTreeReaderValue<Float_t> residualYValue(reader, "residualY");
    std::unique_ptr<TTreeReaderValue<Float_t>> ptValue;
    if(minimumPtGeV > 0.0)
    {
      ptValue = std::make_unique<TTreeReaderValue<Float_t>>(
        reader, "track_pt");
    }

    while(reader.Next())
    {
      if(ptValue && !(**ptValue >= minimumPtGeV))
      {
        continue;
      }

      int layer = -1;
      int stave = -1;
      int chip = -1;
      if(!get_integer_identifier(*layerValue, layer) ||
         !get_integer_identifier(*staveValue, stave) ||
         !get_integer_identifier(*chipValue, chip))
      {
        continue;
      }

      const DetectorConfig* config = get_detector_config(layer);
      if(!config || stave < 0 || chip < 0 || chip >= config->chipsPerStave)
      {
        continue;
      }

      const std::pair<int, int> key(layer, stave);
      auto iterator = histograms.find(key);
      if(iterator == histograms.end())
      {
        iterator = histograms.emplace(
          key, make_stave_histograms(
            *config, layer, stave, numberOfInputs)).first;
      }

      if(std::isfinite(*residualXValue))
      {
        iterator->second.rphiHistograms[inputIndex][chip]->Fill(
          *residualXValue);
      }
      if(std::isfinite(*residualYValue))
      {
        iterator->second.zHistograms[inputIndex][chip]->Fill(
          *residualYValue);
      }
    }
  }

  TH1D* sum_chip_histograms(
    const DetectorConfig& config,
    int layer,
    int stave,
    int inputIndex,
    const char* coordinateName,
    const std::vector<TH1D*>& chipHistograms)
  {
    TH1D* staveHistogram = static_cast<TH1D*>(
      chipHistograms.front()->Clone(Form(
        "h_%s_L%d_stave%d_allchips_in%d_%s",
        config.outputPrefix, layer, stave, inputIndex, coordinateName)));
    staveHistogram->SetDirectory(nullptr);
    for(int chip = 1; chip < config.chipsPerStave; ++chip)
    {
      staveHistogram->Add(chipHistograms[chip]);
    }
    staveHistogram->SetTitle(config.combinedTitle);
    return staveHistogram;
  }

  // Sums every stave's chip histograms per input; the sums are fitted with
  // the chips and feed both the chip = -1 CSV rows and the combined panel.
  void build_stave_sums(StaveHistogramMap& histograms, int numberOfInputs)
  {
    for(auto& entry : histograms)
    {
      StaveHistograms& stave = entry.second;
      const DetectorConfig* config = get_detector_config(stave.layer);
      for(int input = 0; input < numberOfInputs; ++input)
      {
        stave.rphiStaveHistograms.push_back(sum_chip_histograms(
          *config, stave.layer, stave.stave, input, "rphi",
          stave.rphiHistograms[input]));
        stave.zStaveHistograms.push_back(sum_chip_histograms(
          *config, stave.layer, stave.stave, input, "z",
          stave.zHistograms[input]));
      }
    }
  }

  TH1D* make_vertex_histogram(
    const TString& histogramName,
    const char* residualLabel,
    int inputIndex)
  {
    TH1D* histogram = new TH1D(
      histogramName.Data(),
      "",
      kResidualBins,
      -kVertexDisplayRangeMm,
      kVertexDisplayRangeMm);
    histogram->SetDirectory(nullptr);
    histogram->GetXaxis()->SetTitle(Form("%s [mm]", residualLabel));
    histogram->GetYaxis()->SetTitle("Entries");
    style_input_histogram(histogram, inputIndex);
    return histogram;
  }

  VertexHistograms make_vertex_histograms(int numberOfInputs)
  {
    VertexHistograms histograms;
    histograms.transversePhiHistograms.resize(numberOfInputs);
    histograms.longitudinalPhiHistograms.resize(numberOfInputs);
    histograms.transverseFits.resize(numberOfInputs);
    histograms.longitudinalFits.resize(numberOfInputs);
    histograms.transversePhiFits.assign(
      numberOfInputs, std::vector<ChipFitResult>(kVertexPhiBins));
    histograms.longitudinalPhiFits.assign(
      numberOfInputs, std::vector<ChipFitResult>(kVertexPhiBins));
    histograms.transversePhiModulationFits.resize(numberOfInputs);
    for(int input = 0; input < numberOfInputs; ++input)
    {
      histograms.transverseHistograms.push_back(make_vertex_histogram(
        Form("h_vertex_in%d_dca_xy", input), "#minusDCA_{xy}", input));
      histograms.longitudinalHistograms.push_back(make_vertex_histogram(
        Form("h_vertex_in%d_dca_z", input), "#minusDCA_{z}", input));
      for(int phiBin = 0; phiBin < kVertexPhiBins; ++phiBin)
      {
        histograms.transversePhiHistograms[input].push_back(
          make_vertex_histogram(
            Form("h_vertex_phibin%d_in%d_dca_xy", phiBin, input),
            "#minusDCA_{xy}", input));
        histograms.longitudinalPhiHistograms[input].push_back(
          make_vertex_histogram(
            Form("h_vertex_phibin%d_in%d_dca_z", phiBin, input),
            "#minusDCA_{z}", input));
      }
    }

    return histograms;
  }

  // Same selection as plot_fits_overlaid.C: both components finite and pT at
  // or above the cut (a non-finite pT fails the comparison). Phi bins are
  // kVertexPhiBins equal bins over [-pi, pi); in the CSV the phi-bin index is
  // the chip id of the VERTEX rows.
  void fill_vertex_histograms(
    TChain* trackNtp,
    int inputIndex,
    double minimumPtGeV,
    VertexHistograms& histograms)
  {
    const TAxis phiAxis(kVertexPhiBins, -TMath::Pi(), TMath::Pi());
    TTreeReader reader(trackNtp);
    TTreeReaderValue<Float_t> transverseValue(reader, "residual_vertexX");
    TTreeReaderValue<Float_t> longitudinalValue(reader, "residual_vertexY");
    TTreeReaderValue<Float_t> phiValue(reader, "track_phi");
    TTreeReaderValue<Float_t> ptValue(reader, "track_pt");

    while(reader.Next())
    {
      if(!std::isfinite(*transverseValue) ||
         !std::isfinite(*longitudinalValue) ||
         !(*ptValue >= minimumPtGeV))
      {
        continue;
      }

      histograms.transverseHistograms[inputIndex]->Fill(*transverseValue);
      histograms.longitudinalHistograms[inputIndex]->Fill(*longitudinalValue);
      if(!std::isfinite(*phiValue))
      {
        continue;
      }

      const int phiBin = phiAxis.FindFixBin(*phiValue) - 1;
      if(phiBin < 0 || phiBin >= kVertexPhiBins)
      {
        continue;
      }
      histograms.transversePhiHistograms[inputIndex][phiBin]->Fill(
        *transverseValue);
      histograms.longitudinalPhiHistograms[inputIndex][phiBin]->Fill(
        *longitudinalValue);
    }
  }

  void delete_histograms(std::vector<TH1D*>& histograms)
  {
    for(TH1D* histogram : histograms)
    {
      delete histogram;
    }
    histograms.clear();
  }

  void delete_all_histograms(
    StaveHistogramMap& staveHistograms,
    VertexHistograms& vertexHistograms)
  {
    for(auto& entry : staveHistograms)
    {
      for(auto& chipHistograms : entry.second.rphiHistograms)
      {
        delete_histograms(chipHistograms);
      }
      for(auto& chipHistograms : entry.second.zHistograms)
      {
        delete_histograms(chipHistograms);
      }
      delete_histograms(entry.second.rphiStaveHistograms);
      delete_histograms(entry.second.zStaveHistograms);
    }
    staveHistograms.clear();

    delete_histograms(vertexHistograms.transverseHistograms);
    delete_histograms(vertexHistograms.longitudinalHistograms);
    for(auto& phiHistograms : vertexHistograms.transversePhiHistograms)
    {
      delete_histograms(phiHistograms);
    }
    for(auto& phiHistograms : vertexHistograms.longitudinalPhiHistograms)
    {
      delete_histograms(phiHistograms);
    }
  }

  // ---------------------------------------------------------------------------
  // Fits and summary statistics (shared by the CSV tables and the plots)
  // ---------------------------------------------------------------------------

  struct WindowSummary
  {
    double entries = 0.0;
    int populatedBins = 0;
  };

  WindowSummary summarize_window(
    const TH1D* histogram,
    double lowMm,
    double highMm)
  {
    WindowSummary summary;
    const TAxis* axis = histogram->GetXaxis();
    const int firstBin = std::max(1, axis->FindFixBin(lowMm));
    const int lastBin = std::min(axis->GetNbins(), axis->FindFixBin(highMm));
    for(int bin = firstBin; bin <= lastBin; ++bin)
    {
      const double binContent = histogram->GetBinContent(bin);
      summary.entries += binContent;
      if(binContent > 0.0)
      {
        ++summary.populatedBins;
      }
    }

    return summary;
  }

  double out_of_range_entries(const TH1D* histogram)
  {
    return histogram->GetBinContent(0) +
           histogram->GetBinContent(histogram->GetNbinsX() + 1);
  }

  // A distribution mostly outside the histogram range (a chip misaligned by
  // more than the histogram half-width) is reported as out_of_range, not as
  // low_stats, so it is never mistaken for a chip without data.
  bool mark_out_of_range(const TH1D* histogram, ChipFitResult& result)
  {
    const double entries = histogram->GetEntries();
    if(entries < kMinimumEntriesForFit ||
       out_of_range_entries(histogram) <=
         kMaximumOutOfRangeFraction * entries)
    {
      return false;
    }

    result.status = "out_of_range";
    return true;
  }

  // Seeds a Gaussian at the peak bin with the configured half-width, then
  // refits within mean +/- kCoreFitSigmaWindow * sigma, so a shifted chip is
  // not truncated by a window fixed at zero. Binned Poisson likelihood ("L")
  // keeps low-count bins unbiased. The function is not stored in the
  // histogram ("N"), so later clones carry no fit.
  ChipFitResult fit_core_gaussian(TH1D* histogram, double seedHalfWidthMm)
  {
    ChipFitResult result;
    if(mark_out_of_range(histogram, result))
    {
      return result;
    }

    const TAxis* axis = histogram->GetXaxis();
    const double axisLow = axis->GetXmin();
    const double axisHigh = axis->GetXmax();
    const double peak = axis->GetBinCenter(histogram->GetMaximumBin());
    double low = std::max(axisLow, peak - seedHalfWidthMm);
    double high = std::min(axisHigh, peak + seedHalfWidthMm);

    TF1 fit(Form("f_%s", histogram->GetName()), "gaus", low, high);
    fit.SetParameters(histogram->GetMaximum(), peak, 0.5 * seedHalfWidthMm);
    for(int iteration = 0; iteration <= kCoreFitIterations; ++iteration)
    {
      const WindowSummary windowSummary = summarize_window(
        histogram, low, high);
      result.entriesInWindow = windowSummary.entries;
      result.populatedBins = windowSummary.populatedBins;
      result.fitLowMm = low;
      result.fitHighMm = high;
      if(windowSummary.entries < kMinimumEntriesForFit ||
         windowSummary.populatedBins < kMinimumPopulatedBinsForFit)
      {
        // Enough data for the seed fit but not for the narrowed core window
        // means the fit did not converge to a usable width.
        result.status = iteration == 0 ? "low_stats" : "fit_failed";
        return result;
      }

      fit.SetRange(low, high);
      const int fitStatus = histogram->Fit(&fit, "RLQN0");
      const double mean = fit.GetParameter(1);
      const double sigma = std::fabs(fit.GetParameter(2));
      if(fitStatus != 0 || !std::isfinite(mean) || !std::isfinite(sigma) ||
         sigma <= 0.0)
      {
        result.status = "fit_failed";
        return result;
      }

      result.status = "ok";
      result.amplitude = fit.GetParameter(0);
      result.mean = mean;
      result.meanError = fit.GetParError(1);
      result.sigma = sigma;
      result.sigmaError = fit.GetParError(2);
      result.chi2 = fit.GetChisquare();
      result.ndf = fit.GetNDF();
      low = std::max(axisLow, mean - kCoreFitSigmaWindow * sigma);
      high = std::min(axisHigh, mean + kCoreFitSigmaWindow * sigma);
    }

    return result;
  }

  // Box of full length [2] centred at [1], convolved with a Gaussian of width
  // [3], with plateau height [0] and a flat background [4] for outliers.
  constexpr const char* kBoxGaussianFormula =
    "[0]*0.5*(TMath::Erf((x-[1]+0.5*[2])/(sqrt(2.0)*[3]))"
    "-TMath::Erf((x-[1]-0.5*[2])/(sqrt(2.0)*[3])))+[4]";

  // For residuals dominated by the strip length (INTT z): the residual is
  // flat over the strip, smeared by the track pointing resolution, so a
  // Gaussian core fit does not describe it and its window wanders. Seeds the
  // box from the mean and RMS of the in-range entries (RMS = L/sqrt(12) for a
  // box), then refits twice within centre +/- kBoxFitWindowScale * L by binned
  // Poisson likelihood. mean is the box centre; sigma is the RMS of the
  // fitted shape, sqrt(L^2/12 + s^2), so it means the same as the Gaussian
  // sigma of the other rows.
  ChipFitResult fit_box_gaussian(TH1D* histogram)
  {
    ChipFitResult result;
    result.model = "box_gaus";
    if(mark_out_of_range(histogram, result))
    {
      return result;
    }

    const TAxis* axis = histogram->GetXaxis();
    const double axisLow = axis->GetXmin();
    const double axisHigh = axis->GetXmax();
    const double binWidth = axis->GetBinWidth(1);
    const double centre = histogram->GetMean();
    const double length = std::max(
      4.0 * binWidth, std::sqrt(12.0) * histogram->GetStdDev());
    double low = std::max(axisLow, centre - kBoxFitWindowScale * length);
    double high = std::min(axisHigh, centre + kBoxFitWindowScale * length);

    const double maximum = histogram->GetMaximum();
    const double plateau = std::max(
      1.0, summarize_window(histogram, low, high).entries * binWidth / length);
    TF1 fit(Form("f_box_%s", histogram->GetName()), kBoxGaussianFormula,
            low, high);
    fit.SetParameters(plateau, centre, length, 0.1 * length, 0.01 * plateau);
    fit.SetParLimits(0, 0.0, 10.0 * maximum + 1.0);
    fit.SetParLimits(1, axisLow, axisHigh);
    fit.SetParLimits(2, binWidth, axisHigh - axisLow);
    fit.SetParLimits(3, 0.1 * binWidth, axisHigh - axisLow);
    fit.SetParLimits(4, 0.0, maximum + 1.0);
    for(int iteration = 0; iteration <= kBoxFitIterations; ++iteration)
    {
      const WindowSummary windowSummary = summarize_window(
        histogram, low, high);
      result.entriesInWindow = windowSummary.entries;
      result.populatedBins = windowSummary.populatedBins;
      result.fitLowMm = low;
      result.fitHighMm = high;
      if(windowSummary.entries < kMinimumEntriesForBoxFit ||
         windowSummary.populatedBins < kMinimumPopulatedBinsForBoxFit)
      {
        result.status = iteration == 0 ? "low_stats" : "fit_failed";
        return result;
      }

      fit.SetRange(low, high);
      const TFitResultPtr fitResult = histogram->Fit(&fit, "RLQN0S");
      const int fitStatus = fitResult;
      const double mean = fit.GetParameter(1);
      const double boxLength = fit.GetParameter(2);
      const double edgeSigma = fit.GetParameter(3);
      if(fitStatus != 0 || !fitResult.Get() || !std::isfinite(mean) ||
         !(boxLength > 0.0) || !(edgeSigma > 0.0))
      {
        result.status = "fit_failed";
        return result;
      }

      // sigma = sqrt(L^2/12 + s^2); its error from the (L, s) covariance.
      const double sigma =
        std::sqrt(boxLength * boxLength / 12.0 + edgeSigma * edgeSigma);
      const double dSigmaDLength = boxLength / (12.0 * sigma);
      const double dSigmaDEdge = edgeSigma / sigma;
      const double sigmaVariance =
        dSigmaDLength * dSigmaDLength * fitResult->CovMatrix(2, 2) +
        2.0 * dSigmaDLength * dSigmaDEdge * fitResult->CovMatrix(2, 3) +
        dSigmaDEdge * dSigmaDEdge * fitResult->CovMatrix(3, 3);

      result.status = "ok";
      result.amplitude = fit.GetParameter(0);
      result.mean = mean;
      result.meanError = fit.GetParError(1);
      result.sigma = sigma;
      result.sigmaError = std::sqrt(std::max(0.0, sigmaVariance));
      result.chi2 = fit.GetChisquare();
      result.ndf = fit.GetNDF();
      result.boxLength = boxLength;
      result.boxLengthError = fit.GetParError(2);
      result.edgeSigma = edgeSigma;
      result.edgeSigmaError = fit.GetParError(3);
      result.background = fit.GetParameter(4);
      low = std::max(axisLow, mean - kBoxFitWindowScale * boxLength);
      high = std::min(axisHigh, mean + kBoxFitWindowScale * boxLength);
    }

    return result;
  }

  ChipFitResult fit_residual(
    TH1D* histogram,
    double seedHalfWidthMm,
    bool useBoxFit)
  {
    return useBoxFit ? fit_box_gaussian(histogram)
                     : fit_core_gaussian(histogram, seedHalfWidthMm);
  }

  void fit_all_histograms(
    StaveHistogramMap& staveHistograms,
    VertexHistograms& vertexHistograms,
    int numberOfInputs)
  {
    for(auto& entry : staveHistograms)
    {
      StaveHistograms& histograms = entry.second;
      const DetectorConfig* config = get_detector_config(histograms.layer);
      for(int input = 0; input < numberOfInputs; ++input)
      {
        for(int chip = 0; chip < config->chipsPerStave; ++chip)
        {
          histograms.rphiFits[input][chip] = fit_core_gaussian(
            histograms.rphiHistograms[input][chip], config->rphiFitRangeMm);
          histograms.zFits[input][chip] = fit_residual(
            histograms.zHistograms[input][chip], config->zFitRangeMm,
            config->zUsesBoxFit);
        }
        histograms.rphiStaveFits[input] = fit_core_gaussian(
          histograms.rphiStaveHistograms[input], config->rphiFitRangeMm);
        histograms.zStaveFits[input] = fit_residual(
          histograms.zStaveHistograms[input], config->zFitRangeMm,
          config->zUsesBoxFit);
      }
    }

    for(int input = 0; input < numberOfInputs; ++input)
    {
      vertexHistograms.transverseFits[input] = fit_core_gaussian(
        vertexHistograms.transverseHistograms[input], kVertexFitRangeMm);
      vertexHistograms.longitudinalFits[input] = fit_core_gaussian(
        vertexHistograms.longitudinalHistograms[input], kVertexFitRangeMm);
      for(int phiBin = 0; phiBin < kVertexPhiBins; ++phiBin)
      {
        vertexHistograms.transversePhiFits[input][phiBin] = fit_core_gaussian(
          vertexHistograms.transversePhiHistograms[input][phiBin],
          kVertexFitRangeMm);
        vertexHistograms.longitudinalPhiFits[input][phiBin] =
          fit_core_gaussian(
            vertexHistograms.longitudinalPhiHistograms[input][phiBin],
            kVertexFitRangeMm);
      }
    }
  }

  struct TruncatedMean
  {
    double entries = 0.0;
    double mean = std::numeric_limits<double>::quiet_NaN();
    double meanError = std::numeric_limits<double>::quiet_NaN();
  };

  // Unbinned mean and its uncertainty (RMS / sqrt(N)) of the fills inside the
  // histogram axis range (the histogram range, not the display range),
  // taken from the histogram statistics. The vertex <-DCA> vs phi points on
  // the plot are these values for the phi bins.
  TruncatedMean truncated_mean(const TH1D* histogram)
  {
    TruncatedMean result;
    double stats[4] = {0.0, 0.0, 0.0, 0.0};
    histogram->GetStats(stats);
    const double sumWeights = stats[0];
    result.entries = sumWeights;
    if(sumWeights < 2.0)
    {
      return result;
    }

    result.mean = stats[2] / sumWeights;
    const double variance =
      std::max(0.0, stats[3] / sumWeights - result.mean * result.mean);
    result.meanError = std::sqrt(variance / sumWeights);
    return result;
  }

  // <residual> per track-phi bin, from the same per-bin histograms and the
  // same truncated mean that are written to the CSV (trunc_mean_mm); bins
  // with fewer than two entries are skipped.
  TGraphErrors* make_phi_profile_graph(
    const std::vector<TH1D*>& phiHistograms,
    int inputIndex,
    double& entries)
  {
    TGraphErrors* graph = new TGraphErrors();
    const double binWidth = 2.0 * TMath::Pi() / kVertexPhiBins;
    entries = 0.0;
    for(int phiBin = 0; phiBin < kVertexPhiBins; ++phiBin)
    {
      const TruncatedMean truncatedMean = truncated_mean(phiHistograms[phiBin]);
      entries += truncatedMean.entries;
      if(!std::isfinite(truncatedMean.mean))
      {
        continue;
      }

      const int point = graph->GetN();
      graph->SetPoint(
        point, -TMath::Pi() + (phiBin + 0.5) * binWidth, truncatedMean.mean);
      graph->SetPointError(point, 0.5 * binWidth, truncatedMean.meanError);
    }

    graph->SetLineWidth(2);
    graph->SetLineColor(input_color(inputIndex));
    graph->SetMarkerColor(input_color(inputIndex));
    graph->SetMarkerStyle(input_marker_style(inputIndex));
    graph->SetMarkerSize(0.8);
    return graph;
  }

  // Fits a*sin(phi) + b*cos(phi) + c to the plotted <-DCA_xy> points (linear
  // in the parameters, so the minimum is unique; the phi-bin half-widths are
  // not errors, "EX0") and rewrites it as A*sin(phi - phi0) + c with
  // A = sqrt(a^2 + b^2) and phi0 = atan2(-b, a).
  // TrackAnalysisUtils::get_dca gives DCA_xy = dx*sin(phi) - dy*cos(phi) for
  // a track whose origin is displaced by (dx, dy) from the event vertex, and
  // MakeMilleFiles stores -DCA_xy, so (a, -b) = A*(cos phi0, sin phi0) is the
  // event vertex minus the point the tracks point back to, and A is the size
  // of that transverse offset. A is biased upwards when it is comparable to
  // its error.
  PhiModulationFit fit_phi_modulation(TGraphErrors* graph)
  {
    PhiModulationFit result;
    result.phiBinsUsed = graph->GetN();
    if(result.phiBinsUsed < kMinimumPhiBinsForModulationFit)
    {
      return result;
    }

    TF1 fit("f_phi_modulation", "[0]*sin(x)+[1]*cos(x)+[2]",
            -TMath::Pi(), TMath::Pi());
    fit.SetParameters(0.0, 0.0, 0.0);
    const TFitResultPtr fitResult = graph->Fit(&fit, "QN0S EX0");
    const int fitStatus = fitResult;
    const double sinCoefficient = fit.GetParameter(0);
    const double cosCoefficient = fit.GetParameter(1);
    const double amplitude = std::hypot(sinCoefficient, cosCoefficient);
    if(fitStatus != 0 || !fitResult.Get() || !std::isfinite(amplitude))
    {
      result.status = "fit_failed";
      return result;
    }

    const double varianceSin = fitResult->CovMatrix(0, 0);
    const double varianceCos = fitResult->CovMatrix(1, 1);
    const double covariance = fitResult->CovMatrix(0, 1);
    result.status = "ok";
    result.amplitude = amplitude;
    result.phi0 = std::atan2(-cosCoefficient, sinCoefficient);
    result.constant = fit.GetParameter(2);
    result.constantError = fit.GetParError(2);
    result.offsetX = sinCoefficient;
    result.offsetXError = std::sqrt(varianceSin);
    result.offsetY = -cosCoefficient;
    result.offsetYError = std::sqrt(varianceCos);
    result.chi2 = fit.GetChisquare();
    result.ndf = fit.GetNDF();
    if(amplitude > 0.0)
    {
      const double a = sinCoefficient;
      const double b = cosCoefficient;
      result.amplitudeError = std::sqrt(std::max(0.0,
        (a * a * varianceSin + 2.0 * a * b * covariance +
         b * b * varianceCos) / (amplitude * amplitude)));
      result.phi0Error = std::sqrt(std::max(0.0,
        (b * b * varianceSin - 2.0 * a * b * covariance +
         a * a * varianceCos) / std::pow(amplitude, 4)));
    }

    return result;
  }

  void fit_phi_modulations(
    VertexHistograms& vertexHistograms,
    int numberOfInputs)
  {
    for(int input = 0; input < numberOfInputs; ++input)
    {
      double entries = 0.0;
      TGraphErrors* graph = make_phi_profile_graph(
        vertexHistograms.transversePhiHistograms[input], input, entries);
      vertexHistograms.transversePhiModulationFits[input] =
        fit_phi_modulation(graph);
      delete graph;
    }
  }

  // ---------------------------------------------------------------------------
  // CSV tables
  // ---------------------------------------------------------------------------

  // chip is the chip/sensor id for MVTX/INTT (-1 = whole stave/ladder); for
  // VERTEX rows it is the track-phi bin (-1 = all tracks). minimumPtGeV is the
  // track pT cut that applied to the row.
  void write_fit_row(
    std::ofstream& output,
    const InputSpec& input,
    const char* detectorName,
    int layer,
    int stave,
    int chip,
    const char* coordinateName,
    const TH1D* histogram,
    const ChipFitResult& fitResult,
    double minimumPtGeV)
  {
    const TruncatedMean truncatedMean = truncated_mean(histogram);
    output << input.label << ',' << input.listfile << ','
           << detectorName << ',' << layer << ',' << stave << ','
           << chip << ',' << coordinateName << ','
           << histogram->GetEntries() << ','
           << fitResult.entriesInWindow << ',' << fitResult.populatedBins
           << ',' << fitResult.status << ','
           << fitResult.mean << ',' << fitResult.meanError << ','
           << fitResult.sigma << ',' << fitResult.sigmaError << ','
           << fitResult.chi2 << ',' << fitResult.ndf << ','
           << fitResult.fitLowMm << ',' << fitResult.fitHighMm << ','
           << truncatedMean.mean << ',' << truncatedMean.meanError << ','
           << fitResult.model << ','
           << histogram->GetBinContent(0) << ','
           << histogram->GetBinContent(histogram->GetNbinsX() + 1) << ','
           << fitResult.boxLength << ',' << fitResult.boxLengthError << ','
           << fitResult.edgeSigma << ',' << fitResult.edgeSigmaError << ','
           << minimumPtGeV << '\n';
  }

  // Writes one vertex row per coordinate; returns the number of successful
  // fits. phiBin (-1 = all tracks) is written as the chip id.
  int write_vertex_rows(
    std::ofstream& output,
    const InputSpec& input,
    int phiBin,
    const TH1D* transverseHistogram,
    const ChipFitResult& transverseFit,
    const TH1D* longitudinalHistogram,
    const ChipFitResult& longitudinalFit,
    double minimumPtGeV)
  {
    write_fit_row(
      output, input, kVertexDetectorName, -1, -1, phiBin, "dca_xy",
      transverseHistogram, transverseFit, minimumPtGeV);
    write_fit_row(
      output, input, kVertexDetectorName, -1, -1, phiBin, "dca_z",
      longitudinalHistogram, longitudinalFit, minimumPtGeV);
    return (transverseFit.status == "ok") + (longitudinalFit.status == "ok");
  }

  // Writes residual_fits_<label>.csv per input, one row per
  // (layer, stave, chip, coordinate) and per (layer, stave, coordinate) for
  // the whole stave (chip = -1), plus the VERTEX rows when any input had
  // track_ntp. Returns false if a file could not be written.
  bool write_csv_tables(
    const std::vector<InputSpec>& inputs,
    const StaveHistogramMap& staveHistograms,
    const VertexHistograms& vertexHistograms,
    bool writeVertexRows,
    double residualMinimumPtGeV,
    double vertexMinimumPtGeV,
    const char* outputDirectory)
  {
    gSystem->mkdir(outputDirectory, kTRUE);
    const int numberOfInputs = static_cast<int>(inputs.size());
    for(int input = 0; input < numberOfInputs; ++input)
    {
      const std::string outputPath =
        std::string(outputDirectory) + "/residual_fits_" +
        sanitize_for_filename(inputs[input].label) + ".csv";
      std::ofstream output(outputPath);
      if(!output.is_open())
      {
        std::cerr << "ERROR: could not write " << outputPath << std::endl;
        return false;
      }

      // chip: chip/sensor id for MVTX/INTT (-1 = whole stave/ladder),
      // track-phi bin for VERTEX rows. The columns after trunc_mean_err_mm
      // are new; compare_runs.py reads columns by name, so it ignores them.
      // min_pt_gev is the ntp track pT cut for MVTX/INTT rows and the
      // track_ntp pT cut for VERTEX rows.
      output << std::setprecision(8)
             << "label,listfile,detector,layer,stave,chip,coord,entries,"
                "entries_in_fit_window,populated_bins,fit_status,mu_mm,"
                "mu_err_mm,sigma_mm,sigma_err_mm,chi2,ndf,fit_low_mm,"
                "fit_high_mm,trunc_mean_mm,trunc_mean_err_mm,fit_model,"
                "n_underflow,n_overflow,box_length_mm,box_length_err_mm,"
                "edge_sigma_mm,edge_sigma_err_mm,min_pt_gev\n";

      int rows = 0;
      int goodFits = 0;
      for(const auto& entry : staveHistograms)
      {
        const StaveHistograms& histograms = entry.second;
        const DetectorConfig* config = get_detector_config(histograms.layer);
        for(int chip = 0; chip < config->chipsPerStave; ++chip)
        {
          const ChipFitResult& rphiFit = histograms.rphiFits[input][chip];
          write_fit_row(
            output, inputs[input], config->detectorName, histograms.layer,
            histograms.stave, chip, "rphi",
            histograms.rphiHistograms[input][chip], rphiFit,
            residualMinimumPtGeV);

          const ChipFitResult& zFit = histograms.zFits[input][chip];
          write_fit_row(
            output, inputs[input], config->detectorName, histograms.layer,
            histograms.stave, chip, "z",
            histograms.zHistograms[input][chip], zFit, residualMinimumPtGeV);

          rows += 2;
          goodFits += (rphiFit.status == "ok") + (zFit.status == "ok");
        }

        // chip id = -1: all chips of the stave combined.
        const ChipFitResult& rphiStaveFit = histograms.rphiStaveFits[input];
        write_fit_row(
          output, inputs[input], config->detectorName, histograms.layer,
          histograms.stave, -1, "rphi",
          histograms.rphiStaveHistograms[input], rphiStaveFit,
          residualMinimumPtGeV);
        const ChipFitResult& zStaveFit = histograms.zStaveFits[input];
        write_fit_row(
          output, inputs[input], config->detectorName, histograms.layer,
          histograms.stave, -1, "z",
          histograms.zStaveHistograms[input], zStaveFit,
          residualMinimumPtGeV);
        rows += 2;
        goodFits +=
          (rphiStaveFit.status == "ok") + (zStaveFit.status == "ok");
      }

      if(writeVertexRows)
      {
        // chip id = -1: all tracks; chip id = phiBin: one track-phi bin.
        goodFits += write_vertex_rows(
          output, inputs[input], -1,
          vertexHistograms.transverseHistograms[input],
          vertexHistograms.transverseFits[input],
          vertexHistograms.longitudinalHistograms[input],
          vertexHistograms.longitudinalFits[input], vertexMinimumPtGeV);
        rows += 2;
        for(int phiBin = 0; phiBin < kVertexPhiBins; ++phiBin)
        {
          goodFits += write_vertex_rows(
            output, inputs[input], phiBin,
            vertexHistograms.transversePhiHistograms[input][phiBin],
            vertexHistograms.transversePhiFits[input][phiBin],
            vertexHistograms.longitudinalPhiHistograms[input][phiBin],
            vertexHistograms.longitudinalPhiFits[input][phiBin],
            vertexMinimumPtGeV);
          rows += 2;
        }
      }

      std::cout << "Wrote " << rows << " rows (" << goodFits
                << " successful fits) for " << inputs[input].label << " to "
                << outputPath << std::endl;
    }

    return true;
  }

  // Writes vertex_phi_fit_<label>.csv per input: one row with the
  // A*sin(phi - phi0) + c fit to <-DCA_xy> vs track phi, to track A and phi0
  // from one iteration to the next. Returns false if a file could not be
  // written.
  bool write_phi_modulation_tables(
    const std::vector<InputSpec>& inputs,
    const VertexHistograms& vertexHistograms,
    const char* outputDirectory)
  {
    gSystem->mkdir(outputDirectory, kTRUE);
    for(std::size_t input = 0; input < inputs.size(); ++input)
    {
      const std::string outputPath =
        std::string(outputDirectory) + "/vertex_phi_fit_" +
        sanitize_for_filename(inputs[input].label) + ".csv";
      std::ofstream output(outputPath);
      if(!output.is_open())
      {
        std::cerr << "ERROR: could not write " << outputPath << std::endl;
        return false;
      }

      const PhiModulationFit& fit =
        vertexHistograms.transversePhiModulationFits[input];
      output << std::setprecision(8)
             << "label,listfile,coord,fit_status,phi_bins_used,amplitude_mm,"
                "amplitude_err_mm,phi0_rad,phi0_err_rad,constant_mm,"
                "constant_err_mm,vertex_minus_track_x_mm,"
                "vertex_minus_track_x_err_mm,vertex_minus_track_y_mm,"
                "vertex_minus_track_y_err_mm,chi2,ndf\n"
             << inputs[input].label << ',' << inputs[input].listfile
             << ",dca_xy," << fit.status << ',' << fit.phiBinsUsed << ','
             << fit.amplitude << ',' << fit.amplitudeError << ','
             << fit.phi0 << ',' << fit.phi0Error << ','
             << fit.constant << ',' << fit.constantError << ','
             << fit.offsetX << ',' << fit.offsetXError << ','
             << fit.offsetY << ',' << fit.offsetYError << ','
             << fit.chi2 << ',' << fit.ndf << '\n';
      std::cout << "Wrote the <-DCA_xy> vs phi fit for "
                << inputs[input].label << " to " << outputPath << std::endl;
    }

    return true;
  }

  // ---------------------------------------------------------------------------
  // Plots
  // ---------------------------------------------------------------------------

  // First and last bin of the displayed window [-displayRangeMm,
  // displayRangeMm] of a histogram filled over a wider range.
  std::pair<int, int> display_bin_range(
    const TH1D* histogram,
    double displayRangeMm)
  {
    const TAxis* axis = histogram->GetXaxis();
    const double halfBin = 0.5 * axis->GetBinWidth(1);
    return {axis->FindFixBin(-displayRangeMm + halfBin),
            axis->FindFixBin(displayRangeMm - halfBin)};
  }

  // Draws the fit written to the CSV (core Gaussian or box) over its final
  // fit window clipped to the displayed range, with the amplitude scaled like
  // the displayed (possibly unit-area normalized) histogram. Returns the
  // legend text.
  TString draw_core_fit(
    const TH1D* rawHistogram,
    const TH1D* displayHistogram,
    const ChipFitResult& fitResult,
    double scale,
    double displayRangeMm,
    std::vector<TObject*>& ownedObjects)
  {
    if(fitResult.status == "low_stats")
    {
      return Form("too few in fit range (%.0f, %d bins)",
                  fitResult.entriesInWindow, fitResult.populatedBins);
    }
    if(fitResult.status == "out_of_range")
    {
      return Form("beyond #pm%g mm, no fit",
                  rawHistogram->GetXaxis()->GetXmax());
    }
    if(fitResult.status != "ok")
    {
      return fitResult.model == "box_gaus" ? "box fit failed"
                                           : "Gaussian fit failed";
    }

    const bool isBoxFit = fitResult.model == "box_gaus";
    const TString legendText = isBoxFit
      ? Form("#mu=%.3f, L=%.2f, s=%.2f", fitResult.mean,
             fitResult.boxLength, fitResult.edgeSigma)
      : Form("#mu=%.4f, #sigma=%.4f", fitResult.mean, fitResult.sigma);
    const double drawLow = std::max(fitResult.fitLowMm, -displayRangeMm);
    const double drawHigh = std::min(fitResult.fitHighMm, displayRangeMm);
    if(!(drawHigh > drawLow))
    {
      return legendText;
    }

    TF1* fit = new TF1(
      Form("f_%s", displayHistogram->GetName()),
      isBoxFit ? kBoxGaussianFormula : "gaus", drawLow, drawHigh);
    ownedObjects.push_back(fit);
    if(isBoxFit)
    {
      fit->SetParameters(
        fitResult.amplitude * scale, fitResult.mean, fitResult.boxLength,
        fitResult.edgeSigma, fitResult.background * scale);
    }
    else
    {
      fit->SetParameters(
        fitResult.amplitude * scale, fitResult.mean, fitResult.sigma);
    }
    fit->SetLineColor(displayHistogram->GetLineColor());
    fit->SetLineWidth(2);
    fit->Draw("same");
    return legendText;
  }

  // Draws one curve per input in the current pad, zoomed to
  // +-displayRangeMm, with a legend carrying the input label, entry count,
  // the share of entries outside the view and (optionally) the fit result.
  // fitResults is indexed like rawHistograms and is used only if
  // includeGaussianFit is set. Unit-area normalization uses every entry in
  // the histogram range, not only the displayed ones.
  void draw_overlay_panel(
    const std::vector<TH1D*>& rawHistograms,
    const std::vector<ChipFitResult>& fitResults,
    const std::vector<InputSpec>& inputs,
    const TString& panelText,
    double displayRangeMm,
    bool includeGaussianFit,
    bool drawHistogramsAsMarkers,
    bool normalizeToUnitArea,
    std::vector<TObject*>& ownedObjects)
  {
    constexpr double leftMargin = 0.20;
    constexpr double bottomMargin = 0.13;
    constexpr double topMargin = 0.11;
    gPad->SetGrid(1, 1);
    gPad->SetLeftMargin(leftMargin);
    gPad->SetRightMargin(0.05);
    gPad->SetBottomMargin(bottomMargin);
    gPad->SetTopMargin(topMargin);

    const int numberOfInputs = static_cast<int>(rawHistograms.size());
    std::vector<TH1D*> displayHistograms;
    std::vector<double> scales;
    displayHistograms.reserve(numberOfInputs);
    scales.reserve(numberOfInputs);
    double maximum = 0.0;
    for(TH1D* rawHistogram : rawHistograms)
    {
      TH1D* displayHistogram = static_cast<TH1D*>(rawHistogram->Clone(
        Form("%s_display", rawHistogram->GetName())));
      displayHistogram->SetDirectory(nullptr);
      ownedObjects.push_back(displayHistogram);
      // Integral over the full histogram range: no axis range is set yet.
      const double integral = displayHistogram->Integral();
      const double scale =
        normalizeToUnitArea && integral > 0.0 ? 1.0 / integral : 1.0;
      if(scale != 1.0)
      {
        displayHistogram->Scale(scale);
      }
      const std::pair<int, int> displayBins =
        display_bin_range(displayHistogram, displayRangeMm);
      displayHistogram->GetXaxis()->SetRange(
        displayBins.first, displayBins.second);
      displayHistogram->GetYaxis()->SetTitle(
        normalizeToUnitArea ? "Normalized entries" : "Entries");
      // GetMaximum is taken over the displayed bins only.
      maximum = std::max(maximum, displayHistogram->GetMaximum());
      displayHistograms.push_back(displayHistogram);
      scales.push_back(scale);
    }

    // Leave headroom so the tallest curve stays below the legend.
    constexpr double legendTop = 0.88;
    constexpr double legendRowHeight = 0.065;
    const double legendBottom = legendTop - legendRowHeight * numberOfInputs;
    const double frameHeight = 1.0 - topMargin - bottomMargin;
    const double usableFraction = std::max(
      0.3, (legendBottom - 0.02 - bottomMargin) / frameHeight);
    displayHistograms.front()->SetMaximum(
      maximum > 0.0 ? maximum / usableFraction : 1.0);
    displayHistograms.front()->GetYaxis()->SetTitleOffset(1.6);

    const TString drawOption = drawHistogramsAsMarkers ? "P" : "HIST";
    for(int input = 0; input < numberOfInputs; ++input)
    {
      displayHistograms[input]->Draw(
        input == 0 ? drawOption : drawOption + " same");
    }

    TLegend* legend = new TLegend(
      leftMargin + 0.02, legendBottom, 0.94, legendTop);
    ownedObjects.push_back(legend);
    legend->SetBorderSize(0);
    legend->SetFillStyle(0);
    legend->SetTextFont(42);
    legend->SetTextSize(0.036);
    legend->SetMargin(0.10);
    for(int input = 0; input < numberOfInputs; ++input)
    {
      const TH1D* rawHistogram = rawHistograms[input];
      const double entries = rawHistogram->GetEntries();
      TString entryText = Form(
        "%s (%.0f)", inputs[input].label.c_str(), entries);
      // Entries outside the view, including the under/overflow.
      const std::pair<int, int> displayBins =
        display_bin_range(rawHistogram, displayRangeMm);
      const double outsideView = entries -
        rawHistogram->Integral(displayBins.first, displayBins.second);
      if(entries > 0.0 && outsideView > 0.01 * entries)
      {
        entryText += Form(" [%.0f%% off-scale]",
                          100.0 * outsideView / entries);
      }
      if(includeGaussianFit)
      {
        entryText += ": ";
        entryText += draw_core_fit(
          rawHistogram, displayHistograms[input], fitResults[input],
          scales[input], displayRangeMm, ownedObjects);
      }
      legend->AddEntry(
        displayHistograms[input], entryText.Data(),
        drawHistogramsAsMarkers ? "p" : "l");
    }
    legend->Draw();

    TLatex label;
    label.SetNDC();
    label.SetTextFont(42);
    label.SetTextSize(0.052);
    label.DrawLatex(leftMargin + 0.03, 0.90, panelText.Data());
  }

  // Draws one <residual> vs track-phi graph per input in the current pad.
  // Error bars are the uncertainty on the mean. The y range covers every
  // point's mean +- error, with headroom kept free for the legend. With
  // modulationFits (indexed by input), the A*sin(phi - phi0) + c fits are
  // drawn and A and phi0 are added to the legend.
  void draw_phi_profile_panel(
    const std::vector<std::vector<TH1D*>>& inputPhiHistograms,
    const std::vector<InputSpec>& inputs,
    const TString& panelText,
    const char* yAxisTitle,
    const std::vector<PhiModulationFit>* modulationFits,
    std::vector<TObject*>& ownedObjects)
  {
    constexpr double leftMargin = 0.20;
    constexpr double bottomMargin = 0.13;
    constexpr double topMargin = 0.11;
    gPad->SetGrid(1, 1);
    gPad->SetLeftMargin(leftMargin);
    gPad->SetRightMargin(0.05);
    gPad->SetBottomMargin(bottomMargin);
    gPad->SetTopMargin(topMargin);

    const int numberOfInputs = static_cast<int>(inputPhiHistograms.size());
    std::vector<TGraphErrors*> graphs;
    std::vector<double> entries(numberOfInputs, 0.0);
    double low = std::numeric_limits<double>::infinity();
    double high = -std::numeric_limits<double>::infinity();
    for(int input = 0; input < numberOfInputs; ++input)
    {
      TGraphErrors* graph = make_phi_profile_graph(
        inputPhiHistograms[input], input, entries[input]);
      ownedObjects.push_back(graph);
      graphs.push_back(graph);
      for(int point = 0; point < graph->GetN(); ++point)
      {
        low = std::min(low, graph->GetY()[point] - graph->GetEY()[point]);
        high = std::max(high, graph->GetY()[point] + graph->GetEY()[point]);
      }
    }
    if(!(high > low))
    {
      // No points, or a single value: fall back to a small window.
      const double centre = std::isfinite(low) ? low : 0.0;
      low = centre - 0.01;
      high = centre + 0.01;
    }
    const double margin = 0.2 * (high - low);
    low -= margin;
    high += margin;

    constexpr double legendTop = 0.88;
    constexpr double legendRowHeight = 0.065;
    const double legendBottom = legendTop - legendRowHeight * numberOfInputs;
    const double frameHeight = 1.0 - topMargin - bottomMargin;
    const double usableFraction = std::max(
      0.3, (legendBottom - 0.02 - bottomMargin) / frameHeight);

    // The frame is owned by the pad. Graphs without points keep their legend
    // entry but are not drawn.
    TH1F* frame = gPad->DrawFrame(
      -TMath::Pi(), low, TMath::Pi(), low + (high - low) / usableFraction);
    frame->GetXaxis()->SetTitle("track #phi [rad]");
    frame->GetYaxis()->SetTitle(yAxisTitle);
    frame->GetXaxis()->SetTitleSize(0.055);
    frame->GetYaxis()->SetTitleSize(0.055);
    frame->GetXaxis()->SetLabelSize(0.045);
    frame->GetYaxis()->SetLabelSize(0.045);
    frame->GetYaxis()->SetTitleOffset(1.6);
    for(TGraphErrors* graph : graphs)
    {
      if(graph->GetN() > 0)
      {
        graph->Draw("P");
      }
    }

    // Drawn as A*sin(phi - phi0) + c, the form written to the CSV.
    if(modulationFits)
    {
      for(int input = 0; input < numberOfInputs; ++input)
      {
        const PhiModulationFit& modulationFit = (*modulationFits)[input];
        if(modulationFit.status != "ok")
        {
          continue;
        }

        TF1* curve = new TF1(
          Form("f_phi_modulation_%s_in%d", gPad->GetName(), input),
          "[0]*sin(x-[1])+[2]", -TMath::Pi(), TMath::Pi());
        ownedObjects.push_back(curve);
        curve->SetParameters(
          modulationFit.amplitude, modulationFit.phi0,
          modulationFit.constant);
        curve->SetLineColor(input_color(input));
        curve->SetLineWidth(2);
        curve->Draw("same");
      }
    }

    TLegend* legend = new TLegend(
      leftMargin + 0.02, legendBottom, 0.94, legendTop);
    ownedObjects.push_back(legend);
    legend->SetBorderSize(0);
    legend->SetFillStyle(0);
    legend->SetTextFont(42);
    legend->SetTextSize(0.036);
    legend->SetMargin(0.10);
    for(int input = 0; input < numberOfInputs; ++input)
    {
      TString entryText = Form(
        "%s (%.0f)", inputs[input].label.c_str(), entries[input]);
      if(modulationFits)
      {
        const PhiModulationFit& modulationFit = (*modulationFits)[input];
        entryText += modulationFit.status == "ok"
          ? Form(": A=%.1f#pm%.1f #mum, #phi_{0}=%.2f#pm%.2f",
                 1000.0 * modulationFit.amplitude,
                 1000.0 * modulationFit.amplitudeError,
                 modulationFit.phi0, modulationFit.phi0Error)
          : Form(": no sine fit (%d #phi bins)", modulationFit.phiBinsUsed);
      }
      legend->AddEntry(graphs[input], entryText.Data(), "lp");
    }
    legend->Draw();

    TLatex label;
    label.SetNDC();
    label.SetTextFont(42);
    label.SetTextSize(0.052);
    label.DrawLatex(leftMargin + 0.03, 0.90, panelText.Data());
  }

  // Shrinks every pad so that the top pageTitleHeight of the canvas stays free
  // for the page title.
  void reserve_page_title_space(
    TCanvas* canvas,
    int numberOfPads,
    double pageTitleHeight)
  {
    for(int padIndex = 1; padIndex <= numberOfPads; ++padIndex)
    {
      TVirtualPad* pad = canvas->GetPad(padIndex);
      if(!pad)
      {
        continue;
      }

      const double xLow = pad->GetXlowNDC();
      const double yLow = pad->GetYlowNDC();
      const double width = pad->GetWNDC();
      const double height = pad->GetHNDC();
      pad->SetPad(
        xLow, yLow * (1.0 - pageTitleHeight), xLow + width,
        (yLow + height) * (1.0 - pageTitleHeight));
    }
  }

  void draw_page_title(
    TCanvas* canvas,
    double pageTitleHeight,
    const TString& title)
  {
    canvas->cd();
    TLatex pageTitle;
    pageTitle.SetNDC();
    pageTitle.SetTextFont(62);
    pageTitle.SetTextSize(0.030);
    pageTitle.SetTextAlign(22);
    pageTitle.DrawLatex(0.5, 1.0 - 0.5 * pageTitleHeight, title.Data());
  }

  void print_and_delete_page(
    TCanvas* canvas,
    const char* outputPdf,
    const char* outputPng,
    std::vector<TObject*>& ownedObjects)
  {
    canvas->Print(outputPdf);
    canvas->SaveAs(outputPng);
    delete canvas;
    // Delete in reverse so legends and fits go before the histograms they use.
    for(auto object = ownedObjects.rbegin(); object != ownedObjects.rend();
        ++object)
    {
      delete *object;
    }
    ownedObjects.clear();
  }

  void draw_chip_residual_page(
    const DetectorConfig& config,
    int layer,
    int stave,
    const std::vector<std::vector<TH1D*>>& inputChipHistograms,
    const std::vector<std::vector<ChipFitResult>>& inputChipFits,
    const std::vector<TH1D*>& staveHistograms,
    const std::vector<ChipFitResult>& staveFits,
    const std::vector<InputSpec>& inputs,
    const char* coordinateName,
    const char* residualLabel,
    double residualDisplayRangeMm,
    double minimumPtGeV,
    bool includeGaussianFit,
    bool drawHistogramsAsMarkers,
    bool normalizeToUnitArea,
    const char* outputPdf,
    const char* outputPng)
  {
    const TString canvasName = Form(
      "c_%s_L%d_stave%d_%s",
      config.outputPrefix, layer, stave, coordinateName);
    const TString canvasTitle = Form(
      "%s layer %d, stave %d: local %s residual",
      config.detectorName, layer, stave, residualLabel);
    const int numberOfInputs = static_cast<int>(inputs.size());
    std::vector<TObject*> ownedObjects;

    TCanvas* canvas = new TCanvas(
      canvasName.Data(), canvasTitle.Data(),
      450 * config.canvasColumns, 500 * config.canvasRows);
    canvas->Divide(config.canvasColumns, config.canvasRows, 0.001, 0.001);
    constexpr double pageTitleHeight = 0.055;
    reserve_page_title_space(
      canvas, config.canvasColumns * config.canvasRows, pageTitleHeight);
    for(int chip = 0; chip < config.chipsPerStave; ++chip)
    {
      canvas->cd(chip + 1);
      std::vector<TH1D*> chipHistograms;
      std::vector<ChipFitResult> chipFits;
      chipHistograms.reserve(numberOfInputs);
      chipFits.reserve(numberOfInputs);
      for(int input = 0; input < numberOfInputs; ++input)
      {
        chipHistograms.push_back(inputChipHistograms[input][chip]);
        chipFits.push_back(inputChipFits[input][chip]);
      }
      draw_overlay_panel(
        chipHistograms, chipFits, inputs,
        Form("%s %d", config.panelLabel, chip), residualDisplayRangeMm,
        includeGaussianFit, drawHistogramsAsMarkers, normalizeToUnitArea,
        ownedObjects);
    }

    // The stave sums and their fits are the chip = -1 rows of the CSV.
    canvas->cd(config.chipsPerStave + 1);
    draw_overlay_panel(
      staveHistograms, staveFits, inputs,
      Form("%ss 0-%d combined", config.panelLabel, config.chipsPerStave - 1),
      residualDisplayRangeMm, includeGaussianFit, drawHistogramsAsMarkers,
      normalizeToUnitArea, ownedObjects);

    TString title = Form(
      "%s layer %d, stave %d: local %s residuals",
      config.detectorName, layer, stave, residualLabel);
    if(minimumPtGeV > 0.0)
    {
      title += Form(" (p_{T} #geq %g GeV/c)", minimumPtGeV);
    }
    draw_page_title(canvas, pageTitleHeight, title);
    print_and_delete_page(canvas, outputPdf, outputPng, ownedObjects);
  }

  int draw_detector_pages(
    const DetectorConfig& config,
    const StaveHistogramMap& histogramMap,
    const std::vector<InputSpec>& inputs,
    const char* outputPdf,
    double minimumPtGeV,
    bool includeGaussianFit,
    bool drawHistogramsAsMarkers,
    bool normalizeToUnitArea)
  {
    int populatedStaves = 0;

    for(const auto& entry : histogramMap)
    {
      const StaveHistograms& histograms = entry.second;
      if(histograms.layer < config.firstLayer ||
         histograms.layer >= config.firstLayer + config.numberOfLayers)
      {
        continue;
      }

      ++populatedStaves;
      const TString outputBase = Form(
        "%s_residual_fits_L%d_stave%d", config.outputPrefix,
        histograms.layer, histograms.stave);
      draw_chip_residual_page(
        config, histograms.layer, histograms.stave,
        histograms.rphiHistograms, histograms.rphiFits,
        histograms.rphiStaveHistograms, histograms.rphiStaveFits, inputs,
        "rphi", "r-#phi", config.rphiDisplayRangeMm, minimumPtGeV,
        includeGaussianFit, drawHistogramsAsMarkers, normalizeToUnitArea,
        outputPdf, (outputBase + "_rphi.png").Data());
      draw_chip_residual_page(
        config, histograms.layer, histograms.stave,
        histograms.zHistograms, histograms.zFits,
        histograms.zStaveHistograms, histograms.zStaveFits, inputs, "z", "Z",
        config.zDisplayRangeMm, minimumPtGeV, includeGaussianFit,
        drawHistogramsAsMarkers, normalizeToUnitArea, outputPdf,
        (outputBase + "_z.png").Data());
    }

    return populatedStaves;
  }

  // One page: <-DCA> vs track phi (top) and the -DCA distributions (bottom),
  // transverse on the left and longitudinal on the right.
  void draw_vertex_residual_page(
    const VertexHistograms& histograms,
    const std::vector<InputSpec>& inputs,
    double minimumPtGeV,
    bool includeGaussianFit,
    bool drawHistogramsAsMarkers,
    bool normalizeToUnitArea,
    const char* outputPdf,
    const char* outputPng)
  {
    std::vector<TObject*> ownedObjects;
    constexpr int canvasColumns = 2;
    constexpr int canvasRows = 2;
    TCanvas* canvas = new TCanvas(
      "c_vertex_residuals", "Track-to-vertex residuals",
      450 * canvasColumns, 500 * canvasRows);
    canvas->Divide(canvasColumns, canvasRows, 0.001, 0.001);
    constexpr double pageTitleHeight = 0.055;
    reserve_page_title_space(
      canvas, canvasColumns * canvasRows, pageTitleHeight);

    canvas->cd(1);
    draw_phi_profile_panel(
      histograms.transversePhiHistograms, inputs,
      "#LT#minusDCA_{xy}#GT vs track #phi", "#LT#minusDCA_{xy}#GT [mm]",
      &histograms.transversePhiModulationFits, ownedObjects);
    canvas->cd(2);
    draw_phi_profile_panel(
      histograms.longitudinalPhiHistograms, inputs,
      "#LT#minusDCA_{z}#GT vs track #phi", "#LT#minusDCA_{z}#GT [mm]",
      nullptr, ownedObjects);
    canvas->cd(3);
    draw_overlay_panel(
      histograms.transverseHistograms, histograms.transverseFits, inputs,
      "#minusDCA_{xy}", kVertexDisplayRangeMm, includeGaussianFit,
      drawHistogramsAsMarkers, normalizeToUnitArea, ownedObjects);
    canvas->cd(4);
    draw_overlay_panel(
      histograms.longitudinalHistograms, histograms.longitudinalFits, inputs,
      "#minusDCA_{z}", kVertexDisplayRangeMm, includeGaussianFit,
      drawHistogramsAsMarkers, normalizeToUnitArea, ownedObjects);

    TString title = "Track-to-vertex residuals";
    if(minimumPtGeV > 0.0)
    {
      title += Form(" (p_{T} #geq %g GeV/c)", minimumPtGeV);
    }
    draw_page_title(canvas, pageTitleHeight, title);
    print_and_delete_page(canvas, outputPdf, outputPng, ownedObjects);
  }
}

// Fills, fits and writes the residuals of every populated MVTX and INTT
// stave and the track-to-vertex residuals.
//
// Inputs: comma-separated file lists with optional legend labels, e.g.
//   "ntuple_list1.txt:Iter0,ntuple_list2.txt:Iter1"
// Each file list must contain one ROOT filename per line.
//
// writeToCsv: writes residual_fits_<label>.csv per input into
//   csvOutputDirectory, one row per (layer, stave, chip, coordinate), read by
//   compare_runs.py. Every stave/ladder also gets one row per coordinate
//   with chip = -1 for the sum of all its chips/sensors, fitted like the
//   chips (the "combined" panel of the plots), to tell whole-stave from
//   single-chip shifts. If any input has a usable track_ntp, every table also
//   gets detector=VERTEX rows (layer = stave = -1, coord = dca_xy or dca_z).
//   Their chip id is the track-phi bin: chip = -1 for the integrated
//   distribution and chip = 0..13 for the phi bins over [-pi, pi).
//   Chip residuals are filled over a histogram range wider than the plotted
//   range (MVTX +-0.5 mm; INTT r-phi +-3 mm, z +-40 mm); n_underflow and
//   n_overflow count the entries outside it, and a distribution with more
//   than half of its entries outside gets fit_status out_of_range.
//   fit_model is "gaus" (core Gaussian) or, for INTT z, "box_gaus" (strip
//   box convolved with a Gaussian): mu_mm is the box centre, sigma_mm the
//   RMS of the fitted shape sqrt(L^2/12 + s^2), and box_length_mm (L) and
//   edge_sigma_mm (s) its parameters. chi2 is the Baker-Cousins likelihood
//   chi2 of the binned Poisson fit.
//   trunc_mean_mm / trunc_mean_err_mm hold the unbinned mean of the residuals
//   inside the histogram range (+-2 mm for VERTEX).
//   min_pt_gev is the track pT cut of the row: residualMinimumPtGeV for
//   MVTX/INTT rows, vertexMinimumPtGeV for VERTEX rows.
//   With track_ntp, vertex_phi_fit_<label>.csv holds the fit of
//   A*sin(phi - phi0) + c to <-DCA_xy> vs track phi: A is the transverse
//   offset between the event vertex and the point the tracks point back to,
//   and A*(cos phi0, sin phi0) is that offset (vertex minus track origin).
// makePlots: writes outputPdf (plus PNGs) with two pages per populated stave
//   (local r-phi and local Z) and, last, a track-to-vertex residual page with
//   <-DCA> vs track phi (with the A*sin(phi - phi0) + c fit for -DCA_xy) and
//   the -DCA distributions. Each panel overlays one curve per input. With
//   includeGaussianFit the legend shows the same fit that is written to the
//   CSV.
// vertexMinimumPtGeV: minimum track pT for the track-to-vertex residuals.
// residualMinimumPtGeV: minimum track pT for the MVTX/INTT residuals in ntp.
//   It needs a track_pt branch in ntp (not written by MakeMilleFiles as of
//   this version); a cut above 0 without it is an error. At 0 the branch is
//   not read. Last parameter, so existing positional calls are unchanged.
void plot_fits_overlaid_stavechip(
  //const char* listfile = "ntuple_list.txt",
  const char* listfiles = "ntuple_list_short.txt",
  const char* outputPdf = "silicon_stavechip_residual_fits.pdf",
  bool includeGaussianFit = false,
  bool drawHistogramsAsMarkers = true,
  bool normalizeToUnitArea = true,
  double vertexMinimumPtGeV = 0.0,
  bool writeToCsv = true,
  const char* csvOutputDirectory = ".",
  bool makePlots = true,
  double residualMinimumPtGeV = 0.0)
{
  gROOT->SetBatch(kTRUE);
  gStyle->SetOptStat(0);
  gStyle->SetOptFit(0);

  if(!writeToCsv && !makePlots)
  {
    std::cerr << "ERROR: writeToCsv and makePlots are both false; nothing "
                 "to do." << std::endl;
    return;
  }

  const std::vector<InputSpec> inputs = parse_input_specs(listfiles);
  if(inputs.empty())
  {
    std::cerr << "ERROR: no file lists given in '" << listfiles << "'"
              << std::endl;
    return;
  }
  if(writeToCsv && !validate_csv_labels(inputs))
  {
    return;
  }

  const int numberOfInputs = static_cast<int>(inputs.size());
  StaveHistogramMap histogramMap;
  // Created for every input up front, so an input without track_ntp still
  // gets an (empty) legend entry and low_stats VERTEX rows.
  VertexHistograms vertexHistograms = make_vertex_histograms(numberOfInputs);
  int inputsWithVertexResiduals = 0;
  for(int input = 0; input < numberOfInputs; ++input)
  {
    std::cout << "Input " << input << " (" << inputs[input].label << "): "
              << inputs[input].listfile << std::endl;
    TChain ntp("ntp");
    if(!load_ntuple_chain(&ntp, inputs[input].listfile.c_str()) ||
       !has_required_branches(&ntp))
    {
      delete_all_histograms(histogramMap, vertexHistograms);
      return;
    }
    if(residualMinimumPtGeV > 0.0 && !ntp.GetBranch("track_pt"))
    {
      std::cerr << "ERROR: residualMinimumPtGeV = " << residualMinimumPtGeV
                << " needs branch 'track_pt' in tree ntp, which "
                << inputs[input].listfile << " does not have." << std::endl;
      delete_all_histograms(histogramMap, vertexHistograms);
      return;
    }

    fill_silicon_histograms(
      &ntp, input, numberOfInputs, residualMinimumPtGeV, histogramMap);

    // track_ntp is optional: without it only this input's vertex results stay
    // empty. MakeMilleFiles fills it only when the event-vertex constraint
    // is enabled.
    TChain trackNtp("track_ntp");
    if(load_ntuple_chain(&trackNtp, inputs[input].listfile.c_str()) &&
       has_required_vertex_branches(&trackNtp))
    {
      fill_vertex_histograms(
        &trackNtp, input, vertexMinimumPtGeV, vertexHistograms);
      ++inputsWithVertexResiduals;
    }
    else
    {
      std::cerr << "WARNING: no usable track_ntp for '" << inputs[input].label
                << "'; continuing without its track-to-vertex residuals."
                << std::endl;
    }
  }
  const bool hasVertexResiduals = inputsWithVertexResiduals > 0;
  build_stave_sums(histogramMap, numberOfInputs);

  // One set of fits feeds both the CSV and the plot legends.
  if(writeToCsv || (makePlots && includeGaussianFit))
  {
    fit_all_histograms(histogramMap, vertexHistograms, numberOfInputs);
  }
  if(hasVertexResiduals)
  {
    fit_phi_modulations(vertexHistograms, numberOfInputs);
    for(int input = 0; input < numberOfInputs; ++input)
    {
      const PhiModulationFit& fit =
        vertexHistograms.transversePhiModulationFits[input];
      std::cout << inputs[input].label
                << ": <-DCA_xy> vs phi = A*sin(phi - phi0) + c: ";
      if(fit.status == "ok")
      {
        std::cout << "A = " << 1000.0 * fit.amplitude << " +- "
                  << 1000.0 * fit.amplitudeError << " um, phi0 = "
                  << fit.phi0 << " +- " << fit.phi0Error << " rad, c = "
                  << 1000.0 * fit.constant << " +- "
                  << 1000.0 * fit.constantError << " um, chi2/ndf = "
                  << fit.chi2 << "/" << fit.ndf << std::endl;
      }
      else
      {
        std::cout << fit.status << " (" << fit.phiBinsUsed
                  << " phi bins with entries)" << std::endl;
      }
    }
  }

  if(writeToCsv &&
     (!write_csv_tables(inputs, histogramMap, vertexHistograms,
                        hasVertexResiduals, residualMinimumPtGeV,
                        vertexMinimumPtGeV, csvOutputDirectory) ||
      (hasVertexResiduals &&
       !write_phi_modulation_tables(
         inputs, vertexHistograms, csvOutputDirectory))))
  {
    delete_all_histograms(histogramMap, vertexHistograms);
    return;
  }

  if(makePlots)
  {
    const TString pdfName(outputPdf);
    TCanvas pdfBookend("c_silicon_stavechip_bookend", "", 1, 1);
    pdfBookend.Print((pdfName + "[").Data());

    const int mvtxStaves = draw_detector_pages(
      kMvtxConfig, histogramMap, inputs, pdfName.Data(), residualMinimumPtGeV,
      includeGaussianFit, drawHistogramsAsMarkers, normalizeToUnitArea);
    const int inttStaves = draw_detector_pages(
      kInttConfig, histogramMap, inputs, pdfName.Data(), residualMinimumPtGeV,
      includeGaussianFit, drawHistogramsAsMarkers, normalizeToUnitArea);
    const int populatedStaves = mvtxStaves + inttStaves;
    if(hasVertexResiduals)
    {
      draw_vertex_residual_page(
        vertexHistograms, inputs, vertexMinimumPtGeV, includeGaussianFit,
        drawHistogramsAsMarkers, normalizeToUnitArea, pdfName.Data(),
        "vertex_residual_fits.png");
    }

    pdfBookend.Print((pdfName + "]").Data());

    if(populatedStaves == 0)
    {
      std::cerr << "WARNING: no populated MVTX or INTT staves passed the "
                   "selection." << std::endl;
    }
    else
    {
      std::cout << "Wrote " << 2 * populatedStaves << " pages for "
                << mvtxStaves << " populated MVTX and " << inttStaves
                << " populated INTT staves from " << numberOfInputs
                << " input list(s) to " << outputPdf << std::endl;
    }
    if(hasVertexResiduals)
    {
      std::cout << "Wrote 1 track-to-vertex residual page from "
                << inputsWithVertexResiduals << " of " << numberOfInputs
                << " input list(s) to " << outputPdf << std::endl;
    }
  }

  if(!hasVertexResiduals)
  {
    std::cerr << "WARNING: no input had usable track_ntp entries; no "
                 "track-to-vertex residual page or VERTEX rows were written."
              << std::endl;
  }

  delete_all_histograms(histogramMap, vertexHistograms);
}
