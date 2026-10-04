#include <TChain.h>
#include <TF1.h>
#include <TH1D.h>
#include <TROOT.h>
#include <TString.h>
#include <TSystem.h>
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
#include <set>
#include <sstream>
#include <string>
#include <vector>

// Layer 1 of the residual-comparison workflow. Fits every MVTX chip and INTT
// sensor residual distribution and writes one CSV table per input file list.
// Runs locally only; nothing is sent to any external service.

namespace
{
  constexpr int kResidualBins = 200;
  constexpr double kMinimumEntriesForFit = 10.0;
  constexpr int kMinimumPopulatedBinsForFit = 4;
  constexpr int kCoreFitIterations = 2;
  constexpr double kCoreFitSigmaWindow = 2.0;

  struct DetectorFitConfig
  {
    const char* detectorName;
    const char* outputPrefix;
    int firstLayer;
    int numberOfLayers;
    int chipsPerStave;
    double rphiDisplayRangeMm;
    double rphiFitRangeMm;
    double zDisplayRangeMm;
    double zFitRangeMm;
  };

  // Binning and seed fit half-widths match plot_fits_overlaid_stavechip.C.
  constexpr DetectorFitConfig kMvtxConfig = {
    "MVTX", "mvtx", 0, 3, 9, 0.05, 0.015, 0.05, 0.015};
  constexpr DetectorFitConfig kInttConfig = {
    "INTT", "intt", 3, 4, 4, 0.6, 0.2, 20.0, 5.0};

  struct InputSpec
  {
    std::string listfile;
    std::string label;
  };

  struct StaveHistograms
  {
    int layer = -1;
    int stave = -1;
    // Indexed as [input][chip].
    std::vector<std::vector<TH1D*>> rphiHistograms;
    std::vector<std::vector<TH1D*>> zHistograms;
  };

  using StaveHistogramMap =
    std::map<std::pair<int, int>, StaveHistograms>;

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
      std::cerr << "ERROR: no usable ntp entries were loaded from "
                << listfile << std::endl;
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

  const DetectorFitConfig* get_detector_config(int layer)
  {
    for(const DetectorFitConfig* config : {&kMvtxConfig, &kInttConfig})
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

  TH1D* make_chip_histogram(
    const DetectorFitConfig& config,
    int layer,
    int stave,
    int chip,
    int inputIndex,
    const char* coordinateName,
    double residualDisplayRangeMm)
  {
    const TString histogramName = Form(
      "hfit_%s_L%d_stave%d_chip%d_in%d_%s",
      config.outputPrefix, layer, stave, chip, inputIndex, coordinateName);
    TH1D* histogram = new TH1D(
      histogramName.Data(), "",
      kResidualBins,
      -residualDisplayRangeMm,
      residualDisplayRangeMm);
    histogram->SetDirectory(nullptr);
    return histogram;
  }

  StaveHistograms make_stave_histograms(
    const DetectorFitConfig& config,
    int layer,
    int stave,
    int numberOfInputs)
  {
    StaveHistograms histograms;
    histograms.layer = layer;
    histograms.stave = stave;
    histograms.rphiHistograms.resize(numberOfInputs);
    histograms.zHistograms.resize(numberOfInputs);

    for(int input = 0; input < numberOfInputs; ++input)
    {
      histograms.rphiHistograms[input].reserve(config.chipsPerStave);
      histograms.zHistograms[input].reserve(config.chipsPerStave);
      for(int chip = 0; chip < config.chipsPerStave; ++chip)
      {
        histograms.rphiHistograms[input].push_back(make_chip_histogram(
          config, layer, stave, chip, input, "rphi",
          config.rphiDisplayRangeMm));
        histograms.zHistograms[input].push_back(make_chip_histogram(
          config, layer, stave, chip, input, "z", config.zDisplayRangeMm));
      }
    }

    return histograms;
  }

  void fill_silicon_histograms(
    TChain* ntp,
    int inputIndex,
    int numberOfInputs,
    StaveHistogramMap& histograms)
  {
    TTreeReader reader(ntp);
    TTreeReaderValue<Float_t> layerValue(reader, "layer");
    TTreeReaderValue<Float_t> staveValue(reader, "stave");
    TTreeReaderValue<Float_t> chipValue(reader, "chip");
    TTreeReaderValue<Float_t> residualXValue(reader, "residualX");
    TTreeReaderValue<Float_t> residualYValue(reader, "residualY");

    while(reader.Next())
    {
      int layer = -1;
      int stave = -1;
      int chip = -1;
      if(!get_integer_identifier(*layerValue, layer) ||
         !get_integer_identifier(*staveValue, stave) ||
         !get_integer_identifier(*chipValue, chip))
      {
        continue;
      }

      const DetectorFitConfig* config = get_detector_config(layer);
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

  struct ChipFitResult
  {
    std::string status = "low_stats";
    double entriesInWindow = 0.0;
    int populatedBins = 0;
    double mean = std::numeric_limits<double>::quiet_NaN();
    double meanError = std::numeric_limits<double>::quiet_NaN();
    double sigma = std::numeric_limits<double>::quiet_NaN();
    double sigmaError = std::numeric_limits<double>::quiet_NaN();
    double chi2 = std::numeric_limits<double>::quiet_NaN();
    int ndf = 0;
    double fitLowMm = std::numeric_limits<double>::quiet_NaN();
    double fitHighMm = std::numeric_limits<double>::quiet_NaN();
  };

  // Seeds a Gaussian at the peak bin with the configured half-width, then
  // refits within mean +/- kCoreFitSigmaWindow * sigma, so a shifted chip is
  // not truncated by a window fixed at zero. Binned Poisson likelihood ("L")
  // keeps low-count bins unbiased.
  ChipFitResult fit_core_gaussian(TH1D* histogram, double seedHalfWidthMm)
  {
    ChipFitResult result;
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

  void write_fit_row(
    std::ofstream& output,
    const InputSpec& input,
    const DetectorFitConfig& config,
    int layer,
    int stave,
    int chip,
    const char* coordinateName,
    const TH1D* histogram,
    const ChipFitResult& fitResult)
  {
    output << input.label << ',' << input.listfile << ','
           << config.detectorName << ',' << layer << ',' << stave << ','
           << chip << ',' << coordinateName << ','
           << histogram->GetEntries() << ','
           << fitResult.entriesInWindow << ',' << fitResult.populatedBins
           << ',' << fitResult.status << ','
           << fitResult.mean << ',' << fitResult.meanError << ','
           << fitResult.sigma << ',' << fitResult.sigmaError << ','
           << fitResult.chi2 << ',' << fitResult.ndf << ','
           << fitResult.fitLowMm << ',' << fitResult.fitHighMm << '\n';
  }
}

// Writes residual_fits_<label>.csv per input, one row per
// (layer, stave, chip, coordinate). Inputs use the same format as
// plot_fits_overlaid_stavechip.C, e.g.
//   "ntuple_list1.txt:Iter0,ntuple_list2.txt:Iter1"
void fit_residuals_to_table(
  const char* listfiles = "ntuple_list1.txt:Iter0,ntuple_list2.txt:Iter1",
  const char* outputDirectory = ".")
{
  gROOT->SetBatch(kTRUE);

  const std::vector<InputSpec> inputs = parse_input_specs(listfiles);
  if(inputs.empty())
  {
    std::cerr << "ERROR: no file lists given in '" << listfiles << "'"
              << std::endl;
    return;
  }

  std::set<std::string> outputNames;
  for(const InputSpec& input : inputs)
  {
    if(input.label.find(',') != std::string::npos ||
       input.listfile.find(',') != std::string::npos)
    {
      std::cerr << "ERROR: labels and list files must not contain commas."
                << std::endl;
      return;
    }
    if(!outputNames.insert(sanitize_for_filename(input.label)).second)
    {
      std::cerr << "ERROR: duplicate input label '" << input.label
                << "'; every input needs a distinct label." << std::endl;
      return;
    }
  }

  const int numberOfInputs = static_cast<int>(inputs.size());
  StaveHistogramMap histogramMap;
  for(int input = 0; input < numberOfInputs; ++input)
  {
    std::cout << "Input " << input << " (" << inputs[input].label << "): "
              << inputs[input].listfile << std::endl;
    TChain ntp("ntp");
    if(!load_ntuple_chain(&ntp, inputs[input].listfile.c_str()) ||
       !has_required_branches(&ntp))
    {
      return;
    }

    fill_silicon_histograms(&ntp, input, numberOfInputs, histogramMap);
  }

  gSystem->mkdir(outputDirectory, kTRUE);
  for(int input = 0; input < numberOfInputs; ++input)
  {
    const std::string outputPath =
      std::string(outputDirectory) + "/residual_fits_" +
      sanitize_for_filename(inputs[input].label) + ".csv";
    std::ofstream output(outputPath);
    if(!output.is_open())
    {
      std::cerr << "ERROR: could not write " << outputPath << std::endl;
      return;
    }

    output << std::setprecision(8)
           << "label,listfile,detector,layer,stave,chip,coord,entries,"
              "entries_in_fit_window,populated_bins,fit_status,mu_mm,"
              "mu_err_mm,sigma_mm,sigma_err_mm,chi2,ndf,fit_low_mm,"
              "fit_high_mm\n";

    int rows = 0;
    int goodFits = 0;
    for(const auto& entry : histogramMap)
    {
      const StaveHistograms& histograms = entry.second;
      const DetectorFitConfig* config = get_detector_config(histograms.layer);
      for(int chip = 0; chip < config->chipsPerStave; ++chip)
      {
        TH1D* rphiHistogram = histograms.rphiHistograms[input][chip];
        const ChipFitResult rphiFit = fit_core_gaussian(
          rphiHistogram, config->rphiFitRangeMm);
        write_fit_row(
          output, inputs[input], *config, histograms.layer, histograms.stave,
          chip, "rphi", rphiHistogram, rphiFit);

        TH1D* zHistogram = histograms.zHistograms[input][chip];
        const ChipFitResult zFit = fit_core_gaussian(
          zHistogram, config->zFitRangeMm);
        write_fit_row(
          output, inputs[input], *config, histograms.layer, histograms.stave,
          chip, "z", zHistogram, zFit);

        rows += 2;
        goodFits += (rphiFit.status == "ok") + (zFit.status == "ok");
      }
    }

    std::cout << "Wrote " << rows << " rows (" << goodFits
              << " successful fits) for " << inputs[input].label << " to "
              << outputPath << std::endl;
  }

  for(auto& entry : histogramMap)
  {
    for(auto* inputHistograms :
        {&entry.second.rphiHistograms, &entry.second.zHistograms})
    {
      for(auto& chipHistograms : *inputHistograms)
      {
        for(TH1D* histogram : chipHistograms)
        {
          delete histogram;
        }
      }
    }
  }
}
