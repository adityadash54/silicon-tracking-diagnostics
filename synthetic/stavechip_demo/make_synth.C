// Synthetic ntp / track_ntp for checking plot_fits_overlaid_stavechip.C.
// Run: root -l -b -q make_synth.C (writes synthIter0.root and synthIter1.root
// in the current directory); synthetic/stavechip_demo/run_demo.sh runs it
// and every later step. check_demo.py encodes the truth below.
//
// Truth (Iter0 = reference, Iter1 = comparison):
//   MVTX L0 stave 0, r-phi (sigma 8 um; z: sigma 10 um, no shifts)
//     chip 3: 0 um -> +10 um                  real shift, should be flagged
//     chip 5: +300 um -> 0 um                 outside the +-50 um view, inside +-0.5 mm
//     chip 6: +30 um in both                  unchanged, should not be flagged
//     chip 7: 6 entries                       low statistics
//     chip 8: +800 um -> 0 um                 outside the +-0.5 mm histogram range
//   INTT L3 ladder 0, z: box of 20/16/16/20 mm (sensors 0-3) smeared by 0.5 mm,
//     plus 2% flat outliers; r-phi sigma 25 um, no shifts
//     sensor 2: 0 mm -> +1.5 mm               real shift, should be flagged
//   TPC-like rows (layer 20, stave = chip = 255)   must be ignored
//   track_ntp: -DCA_xy from an offset (vertex minus track origin)
//     Iter0: (+30, 0) um   -> A = 30.0 um, phi0 = 0
//     Iter1: (+20, +10) um -> A = 22.4 um, phi0 = 0.464 rad
//     -DCA_z: Gaussian, sigma 100 um, no offset
#include <TFile.h>
#include <TMath.h>
#include <TNtuple.h>
#include <TRandom3.h>

#include <cmath>

void make_one(const char* name, bool comparison, double vertexX, double vertexY,
              unsigned seed)
{
  TRandom3 random(seed);
  TFile file(name, "RECREATE");
  TNtuple ntp("ntp", "ntp", "layer:stave:chip:residualX:residualY");
  for(int chip = 0; chip < 9; ++chip)
  {
    const int entries = chip == 7 ? 6 : 2000;
    double mean = 0.0;
    if(chip == 3 && comparison) mean = 0.010;
    if(chip == 5 && !comparison) mean = 0.300;
    if(chip == 6) mean = 0.030;
    if(chip == 8 && !comparison) mean = 0.800;
    for(int i = 0; i < entries; ++i)
    {
      ntp.Fill(0, 0, chip, random.Gaus(mean, 0.008), random.Gaus(0.0, 0.010));
    }
  }

  const double stripLength[4] = {20.0, 16.0, 16.0, 20.0};
  for(int sensor = 0; sensor < 4; ++sensor)
  {
    const double shift = sensor == 2 && comparison ? 1.5 : 0.0;
    for(int i = 0; i < 3000; ++i)
    {
      double z = random.Uniform(-0.5 * stripLength[sensor],
                                0.5 * stripLength[sensor]) +
                 random.Gaus(0.0, 0.5) + shift;
      if(random.Uniform() < 0.02)
      {
        z = random.Uniform(-35.0, 35.0);
      }
      ntp.Fill(3, 0, sensor, random.Gaus(0.0, 0.025), z);
    }
  }
  for(int i = 0; i < 100; ++i)
  {
    ntp.Fill(20, 255, 255, random.Gaus(0.0, 0.2), random.Gaus(0.0, 0.2));
  }
  ntp.Write();

  // get_dca: DCA_xy = dx*sin(phi) - dy*cos(phi) with d = track origin - vertex;
  // MakeMilleFiles stores -DCA_xy.
  TNtuple trackNtp("track_ntp", "track_ntp",
                   "residual_vertexX:residual_vertexY:track_phi:track_pt");
  const double dx = -vertexX;
  const double dy = -vertexY;
  for(int i = 0; i < 40000; ++i)
  {
    const double phi = random.Uniform(-TMath::Pi(), TMath::Pi());
    const double dca = dx * std::sin(phi) - dy * std::cos(phi);
    trackNtp.Fill(-dca + random.Gaus(0.0, 0.05), random.Gaus(0.0, 0.1), phi,
                  random.Exp(0.7));
  }
  trackNtp.Write();
  file.Close();
}

void make_synth()
{
  make_one("synthIter0.root", false, 0.030, 0.000, 11);
  make_one("synthIter1.root", true, 0.020, 0.010, 22);
}
