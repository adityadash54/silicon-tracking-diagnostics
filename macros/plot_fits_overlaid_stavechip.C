#include <TCanvas.h>
#include <TChain.h>
#include <TColor.h>
#include <TCut.h>
#include <TF1.h>
#include <TH1D.h>
#include <TLegend.h>
#include <TLatex.h>
#include <TROOT.h>
#include <TString.h>
#include <TStyle.h>
#include <TPad.h>
#include <TTreeReader.h>
#include <TTreeReaderValue.h>

#include <algorithm>
#include <cmath>
#include <fstream>
#include <iostream>
#include <limits>
#include <map>
#include <sstream>
#include <string>
#include <vector>

namespace
{
  constexpr int kResidualBins = 200;
  constexpr double kMinimumEntriesForFit = 10.0;
  constexpr int kMinimumPopulatedBinsForFit = 4;
  constexpr int kInputColors[] = {
    kBlack, kRed + 1, kBlue + 1, kGreen + 2,
    kMagenta + 1, kOrange + 7, kCyan + 2, kViolet + 1};
  constexpr int kInputMarkerStyles[] = {20, 24, 21, 25, 22, 26, 23, 32};

  struct DetectorPlotConfig
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
    double rphiFitRangeMm;
    double zDisplayRangeMm;
    double zFitRangeMm;
  };

  constexpr DetectorPlotConfig kMvtxConfig = {
    "MVTX", "mvtx", "Chip", "All chips combined", 0, 3, 9, 5, 2,
    0.05, 0.015, 0.05, 0.015};
  constexpr DetectorPlotConfig kInttConfig = {
    "INTT", "intt", "Sensor", "All sensors combined", 3, 4, 4, 3, 2,
    0.6, 0.2, 20.0, 5.0};

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

  const DetectorPlotConfig* get_detector_config(int layer)
  {
    for(const DetectorPlotConfig* config : {&kMvtxConfig, &kInttConfig})
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

  struct FitRangeSummary
  {
    double entries = 0.0;
    int populatedBins = 0;
  };

  FitRangeSummary summarize_fit_range(
    const TH1D* histogram,
    double fitRangeMm)
  {
    FitRangeSummary summary;
    const TAxis* axis = histogram->GetXaxis();
    const int firstBin = std::max(1, axis->FindFixBin(-fitRangeMm));
    const int lastBin = std::min(axis->GetNbins(), axis->FindFixBin(fitRangeMm));
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

  // Fits the raw-count histogram so the fit uncertainties follow Poisson
  // statistics, then rescales only the drawn amplitude to match the displayed
  // (possibly unit-area normalized) histogram. Returns the legend text.
  TString draw_gaussian_fit(
    TH1D* rawHistogram,
    const TH1D* displayHistogram,
    double fitRangeMm,
    std::vector<TObject*>& ownedObjects)
  {
    const FitRangeSummary fitRangeSummary = summarize_fit_range(
      rawHistogram, fitRangeMm);
    if(fitRangeSummary.entries < kMinimumEntriesForFit ||
       fitRangeSummary.populatedBins < kMinimumPopulatedBinsForFit)
    {
      return Form("too few in fit range (%.0f, %d bins)",
                  fitRangeSummary.entries, fitRangeSummary.populatedBins);
    }

    TF1* fit = new TF1(
      Form("f_%s", rawHistogram->GetName()),
      "gaus",
      -fitRangeMm,
      fitRangeMm);
    ownedObjects.push_back(fit);
    const int fitStatus = rawHistogram->Fit(fit, "RQ0");
    if(fitStatus != 0)
    {
      return "Gaussian fit failed";
    }

    const double rawIntegral = rawHistogram->Integral();
    if(rawIntegral > 0.0)
    {
      fit->SetParameter(
        0, fit->GetParameter(0) * displayHistogram->Integral() / rawIntegral);
    }
    fit->SetLineColor(displayHistogram->GetLineColor());
    fit->SetLineWidth(2);
    fit->Draw("same");
    return Form("#mu=%.4f, #sigma=%.4f", fit->GetParameter(1),
                fit->GetParameter(2));
  }

  TH1D* make_chip_histogram(
    const DetectorPlotConfig& config,
    int layer,
    int stave,
    int chip,
    int inputIndex,
    const char* coordinateName,
    const char* residualLabel,
    double residualDisplayRangeMm)
  {
    const TString histogramName = Form(
      "h_%s_L%d_stave%d_chip%d_in%d_%s",
      config.outputPrefix, layer, stave, chip, inputIndex, coordinateName);
    TH1D* histogram = new TH1D(
      histogramName.Data(),
      Form("%s %d", config.panelLabel, chip),
      kResidualBins,
      -residualDisplayRangeMm,
      residualDisplayRangeMm);
    histogram->SetDirectory(nullptr);
    histogram->GetXaxis()->SetTitle(
      Form("local %s residual [mm]", residualLabel));
    histogram->GetYaxis()->SetTitle("Entries");
    histogram->GetXaxis()->SetTitleSize(0.055);
    histogram->GetYaxis()->SetTitleSize(0.055);
    histogram->GetXaxis()->SetLabelSize(0.045);
    histogram->GetYaxis()->SetLabelSize(0.045);
    histogram->SetLineWidth(2);
    const int color = kInputColors[
      inputIndex % (sizeof(kInputColors) / sizeof(kInputColors[0]))];
    histogram->SetLineColor(color);
    histogram->SetMarkerColor(color);
    histogram->SetMarkerStyle(kInputMarkerStyles[
      inputIndex %
      (sizeof(kInputMarkerStyles) / sizeof(kInputMarkerStyles[0]))]);
    histogram->SetMarkerSize(0.8);
    return histogram;
  }

  StaveHistograms make_stave_histograms(
    const DetectorPlotConfig& config,
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
          config, layer, stave, chip, input, "rphi", "r-#phi",
          config.rphiDisplayRangeMm));
        histograms.zHistograms[input].push_back(make_chip_histogram(
          config, layer, stave, chip, input, "z", "Z",
          config.zDisplayRangeMm));
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

      const DetectorPlotConfig* config = get_detector_config(layer);
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

  // Draws one curve per input in the current pad, with a legend carrying the
  // input label, entry count and (optionally) the Gaussian fit result.
  void draw_overlay_panel(
    const std::vector<TH1D*>& rawHistograms,
    const std::vector<InputSpec>& inputs,
    const TString& panelText,
    double residualFitRangeMm,
    bool includeGaussianFit,
    bool drawHistogramsAsMarkers,
    bool normalizeToUnitArea,
    std::vector<TObject*>& ownedObjects)
  {
    constexpr double leftMargin = 0.14;
    constexpr double bottomMargin = 0.13;
    constexpr double topMargin = 0.11;
    gPad->SetGrid(1, 1);
    gPad->SetLeftMargin(leftMargin);
    gPad->SetRightMargin(0.05);
    gPad->SetBottomMargin(bottomMargin);
    gPad->SetTopMargin(topMargin);

    const int numberOfInputs = static_cast<int>(rawHistograms.size());
    std::vector<TH1D*> displayHistograms;
    displayHistograms.reserve(numberOfInputs);
    double maximum = 0.0;
    for(TH1D* rawHistogram : rawHistograms)
    {
      TH1D* displayHistogram = static_cast<TH1D*>(rawHistogram->Clone(
        Form("%s_display", rawHistogram->GetName())));
      displayHistogram->SetDirectory(nullptr);
      ownedObjects.push_back(displayHistogram);
      const double integral = displayHistogram->Integral();
      if(normalizeToUnitArea && integral > 0.0)
      {
        displayHistogram->Scale(1.0 / integral);
      }
      displayHistogram->GetYaxis()->SetTitle(
        normalizeToUnitArea ? "Normalized entries" : "Entries");
      maximum = std::max(maximum, displayHistogram->GetMaximum());
      displayHistograms.push_back(displayHistogram);
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
      TString entryText = Form(
        "%s (%.0f)", inputs[input].label.c_str(),
        rawHistograms[input]->GetEntries());
      if(includeGaussianFit)
      {
        entryText += ": ";
        entryText += draw_gaussian_fit(
          rawHistograms[input], displayHistograms[input],
          residualFitRangeMm, ownedObjects);
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
    label.DrawLatex(0.17, 0.90, panelText.Data());
  }

  void draw_chip_residual_page(
    const DetectorPlotConfig& config,
    int layer,
    int stave,
    const std::vector<std::vector<TH1D*>>& inputChipHistograms,
    const std::vector<InputSpec>& inputs,
    const char* coordinateName,
    const char* residualLabel,
    double residualFitRangeMm,
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

    // Build the per-input stave sums before any chip histogram is fitted, so
    // the clones do not inherit fit functions.
    std::vector<TH1D*> combinedHistograms;
    combinedHistograms.reserve(numberOfInputs);
    for(int input = 0; input < numberOfInputs; ++input)
    {
      const std::vector<TH1D*>& chipHistograms = inputChipHistograms[input];
      TH1D* combinedHistogram = static_cast<TH1D*>(
        chipHistograms.front()->Clone(Form(
          "h_%s_L%d_stave%d_allchips_in%d_%s",
          config.outputPrefix, layer, stave, input, coordinateName)));
      combinedHistogram->SetDirectory(nullptr);
      for(int chip = 1; chip < config.chipsPerStave; ++chip)
      {
        combinedHistogram->Add(chipHistograms[chip]);
      }
      combinedHistogram->SetTitle(config.combinedTitle);
      ownedObjects.push_back(combinedHistogram);
      combinedHistograms.push_back(combinedHistogram);
    }

    TCanvas* canvas = new TCanvas(
      canvasName.Data(), canvasTitle.Data(),
      450 * config.canvasColumns, 500 * config.canvasRows);
    canvas->Divide(config.canvasColumns, config.canvasRows, 0.001, 0.001);
    constexpr double pageTitleHeight = 0.055;
    const int numberOfPads = config.canvasColumns * config.canvasRows;
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
    for(int chip = 0; chip < config.chipsPerStave; ++chip)
    {
      canvas->cd(chip + 1);
      std::vector<TH1D*> chipHistograms;
      chipHistograms.reserve(numberOfInputs);
      for(int input = 0; input < numberOfInputs; ++input)
      {
        chipHistograms.push_back(inputChipHistograms[input][chip]);
      }
      draw_overlay_panel(
        chipHistograms, inputs, Form("%s %d", config.panelLabel, chip),
        residualFitRangeMm, includeGaussianFit, drawHistogramsAsMarkers,
        normalizeToUnitArea, ownedObjects);
    }

    canvas->cd(config.chipsPerStave + 1);
    draw_overlay_panel(
      combinedHistograms, inputs,
      Form("%ss 0-%d combined", config.panelLabel, config.chipsPerStave - 1),
      residualFitRangeMm, includeGaussianFit, drawHistogramsAsMarkers,
      normalizeToUnitArea, ownedObjects);

    canvas->cd();
    TLatex pageTitle;
    pageTitle.SetNDC();
    pageTitle.SetTextFont(62);
    pageTitle.SetTextSize(0.030);
    pageTitle.SetTextAlign(22);
    pageTitle.DrawLatex(
      0.5, 1.0 - 0.5 * pageTitleHeight,
      Form("%s layer %d, stave %d: local %s residuals",
           config.detectorName, layer, stave, residualLabel));

    canvas->Print(outputPdf);
    canvas->SaveAs(outputPng);
    delete canvas;
    // Delete in reverse so legends and fits go before the histograms they use.
    for(auto object = ownedObjects.rbegin(); object != ownedObjects.rend();
        ++object)
    {
      delete *object;
    }
  }

  int draw_detector_pages(
    const DetectorPlotConfig& config,
    const StaveHistogramMap& histogramMap,
    const std::vector<InputSpec>& inputs,
    const char* outputPdf,
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
        histograms.rphiHistograms, inputs, "rphi", "r-#phi",
        config.rphiFitRangeMm, includeGaussianFit, drawHistogramsAsMarkers,
        normalizeToUnitArea, outputPdf,
        (outputBase + "_rphi.png").Data());
      draw_chip_residual_page(
        config, histograms.layer, histograms.stave,
        histograms.zHistograms, inputs, "z", "Z", config.zFitRangeMm,
        includeGaussianFit, drawHistogramsAsMarkers, normalizeToUnitArea,
        outputPdf, (outputBase + "_z.png").Data());
    }

    return populatedStaves;
  }
}

// Creates two pages per populated MVTX and INTT stave: local r-phi and local-Z.
// Each panel overlays one curve per input file list. Pass the lists as a
// comma-separated string with optional legend labels, e.g.
//   "ntuple_list1.txt:Iter0,ntuple_list2.txt:Iter1"
// Each file list must contain one ROOT filename per line.
void plot_fits_overlaid_stavechip(
  //const char* listfile = "ntuple_list.txt",
  const char* listfiles = "ntuple_list_short.txt",
  const char* outputPdf = "silicon_stavechip_residual_fits.pdf",
  bool includeGaussianFit = false,
  bool drawHistogramsAsMarkers = true,
  bool normalizeToUnitArea = true)
{
  gROOT->SetBatch(kTRUE);
  gStyle->SetOptStat(0);
  gStyle->SetOptFit(0);

  const std::vector<InputSpec> inputs = parse_input_specs(listfiles);
  if(inputs.empty())
  {
    std::cerr << "ERROR: no file lists given in '" << listfiles << "'"
              << std::endl;
    return;
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

  const TString pdfName(outputPdf);
  TCanvas pdfBookend("c_silicon_stavechip_bookend", "", 1, 1);
  pdfBookend.Print((pdfName + "[").Data());

  const int mvtxStaves = draw_detector_pages(
    kMvtxConfig, histogramMap, inputs, pdfName.Data(), includeGaussianFit,
    drawHistogramsAsMarkers, normalizeToUnitArea);
  const int inttStaves = draw_detector_pages(
    kInttConfig, histogramMap, inputs, pdfName.Data(), includeGaussianFit,
    drawHistogramsAsMarkers, normalizeToUnitArea);
  const int populatedStaves = mvtxStaves + inttStaves;

  pdfBookend.Print((pdfName + "]").Data());

  if(populatedStaves == 0)
  {
    std::cerr << "WARNING: no populated MVTX or INTT staves passed the selection."
              << std::endl;
  }
  else
  {
    std::cout << "Wrote " << 2 * populatedStaves << " pages for "
              << mvtxStaves << " populated MVTX and " << inttStaves
              << " populated INTT staves from " << numberOfInputs
              << " input list(s) to " << outputPdf << std::endl;
  }
}
