/// @file imcontsub.cc
///
/// @brief Image based Continuum subtraction
///
/// @copyright (c) 2019 CSIRO
/// Australia Telescope National Facility (ATNF)
/// Commonwealth Scientific and Industrial Research Organisation (CSIRO)
/// PO Box 76, Epping NSW 1710, Australia
/// atnf-enquiries@csiro.au
///
/// This file is part of the ASKAP software distribution.
///
/// The ASKAP software distribution is free software: you can redistribute it
/// and/or modify it under the terms of the GNU General Public License as
/// published by the Free Software Foundation; either version 2 of the License,
/// or (at your option) any later version.
///
/// This program is distributed in the hope that it will be useful,
/// but WITHOUT ANY WARRANTY; without even the implied warranty of
/// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
/// GNU General Public License for more details.
///
/// You should have received a copy of the GNU General Public License
/// along with this program; if not, write to the Free Software
/// Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307 USA
///
/// @author Mark Wieringa

// Include package level header file
#include <askap/askap_synthesis.h>


// ASKAPsoft includes
#include <askap/AskapLogging.h>
#include <askap/AskapError.h>
#include <askap/Application.h>
#include <askap/StatReporter.h>
#include <askapparallel/AskapParallel.h>
#include <askap/imageaccess/FitsImageAccessParallel.h>
#include <Common/ParameterSet.h>

// casacore includes
#include <casacore/scimath/Fitting/LinearFitSVD.h>
#include <casacore/scimath/Functionals/Polynomial.h>
#include <casacore/casa/OS/CanonicalConversion.h>

// robust contsub C++ version

ASKAP_LOGGER(logger, ".imcontsub");

//using namespace std;
using namespace askap;
using namespace askap::accessors;
//using namespace casacore;
//using namespace askap::synthesis;

class ImContSubApp : public askap::Application
{
public:
    virtual int run(int argc, char* argv[])
    {
        // This class must have scope outside the main try/catch block
        askapparallel::AskapParallel comms(argc, const_cast<const char**>(argv));

        try {
            StatReporter stats;
            LOFAR::ParameterSet subset(config().makeSubset("imcontsub."));

            ASKAPLOG_INFO_STR(logger, "ASKAP image based continuum subtraction application " << ASKAP_PACKAGE_VERSION);

            casa::String infile = subset.getString("inputfitscube","");
            casa::String outfile = subset.getString("outputfitscube","");
            size_t pos = infile.rfind(".fits");
            if (pos==std::string::npos) {
                infile += ".fits";
            }
            if (outfile=="") {
                pos = infile.rfind(".fits");
                outfile = infile.substr(0,pos) + ".contsub.fits";
            }
            float threshold = subset.getFloat("threshold",2.0);
            int order = subset.getInt("order",2);

            FitsImageAccessParallel accessor;

            if (comms.isMaster()) {
                ASKAPLOG_INFO_STR(logger,"In = "<<infile <<", Out = "<<
                                      outfile <<", threshold = "<<threshold << ", order = "<< order);
                ASKAPLOG_INFO_STR(logger,"master creates the new output file and copies header");
                accessor.copy_header(infile, outfile);
            }

            // All wait for header to be written
            comms.barrier();

            // Now process the rest of the file in parallel
            // Specify axis of cube to distribute over: 1=y -> array dimension returned: (nx,n,nchan)
            const int iax = 1;
            casa::Cube<casa::Float> arr = accessor.read_all(comms,infile,iax);

            // Process spectrum by spectrum
            ASKAPLOG_INFO_STR(logger,"Process the spectra");
            for (uint y = 0; y< arr.shape()(1); y++ ) {
                for (uint x = 0; x < arr.shape()(0); x++ ) {
                    casa::Vector<casa::Float> spec(arr(casa::Slice(x,1),casa::Slice(y,1),casa::Slice()));
                    process_spectrum(spec, threshold, order);
                }
            }

            // Write results to output file - make sure you use the same axis as for reading
            accessor.write_all(comms,outfile,arr,iax);
            ASKAPLOG_INFO_STR(logger,"Done");
            // Done
            stats.logSummary();
            } catch (const AskapError& x) {
                ASKAPLOG_FATAL_STR(logger, "Askap error in " << argv[0] << ": " << x.what());
                std::cerr << "Askap error in " << argv[0] << ": " << x.what() << std::endl;
                exit(1);
            } catch (const std::exception& x) {
                ASKAPLOG_FATAL_STR(logger, "Unexpected exception in " << argv[0] << ": " << x.what());
                std::cerr << "Unexpected exception in " << argv[0] << ": " << x.what() << std::endl;
                exit(1);
            }
            return 0;
        }


        void process_spectrum(casa::Vector<casa::Float>& vec, float threshold, int order) {
            size_t n = vec.nelements();

            // first remove spectral index

            // take every 10th point
            const int inc = casa::min(n/10,10);
            const int n1 = n/inc;
            casa::Vector<casa::Float> y1(n1);
            for (int i=0; i<n1; i++) y1(i) = vec(i*inc);

            // mask out NaNs and extreme outliers
            casa::Float q5 = casa::fractile(y1,0.05f);
            casa::Float q95 = casa::fractile(y1,0.95f);
            casa::Vector<casa::Bool> mask1(n1);
            int ngood = 0;
            for (int i=0; i<n1; i++) {
                mask1(i) = !casa::isNaN(y1(i)) & (y1(i) >= q5) & (y1(i) <= q95);
                if (mask1(i)) ngood++;
            }
            //ASKAPLOG_INFO_STR(logger,"q5="<<q5<<", q95="<<q95<< ", y1="<< y1);
            //ASKAPLOG_INFO_STR(logger,"n1="<<n1<<", ngood="<<ngood);
            casa::Vector<casa::Float> x(ngood), y(ngood);
            for (int i=0, j=0; i<n1; i++) {
                if (mask1(i)) {
                    y(j) = vec(i*inc);
                    x(j++) = i*inc;
                }
            }

            casa::Float xmean = 0;
            casa::Float offset = 0;
            casa::Float slope = 0;

            if (ngood > 0) {
                xmean = mean(x);
                x -= xmean;
                // fit line to spectrum and subtract it
                offset = sum(y) / ngood;
                slope = sum(x * y) / sum(x * x);
            }

            casa::Vector<casa::Float> x_full(n), y_full(n);
            indgen(x_full);
            x_full -= xmean;
            for (int i = 0; i<n; i++) y_full(i) = vec(i) - (offset + slope * x_full(i));
            //y_full = x_full;
            //y_full *= -slope;
            //y_full -= offset;
            //y_full += vec;
            //ASKAPLOG_INFO_STR(logger," offset = "<<offset<<", slope = "<<slope);

            // now select data within threshold of median
            casa::Float q15 = casa::fractile(y_full, 0.15f);
            casa::Float q50 = casa::fractile(y_full, 0.50f);
            casa::Float iqr = (1/1.35)*2*(q50-q15); // just copying python version - iqr should really be 2*(q50-q25)
            casa::Vector<casa::Bool> mask = (y_full >= q50 - threshold * iqr ) & ( y_full <= q50 + threshold * iqr);

            // fit polynomial of given order
            //casa::LinearFitSVD<casa::Float> fitter;

            // using AutoDiff - slow
            // casa::Polynomial<casa::AutoDiff<casa::Float> > func(order+1);
            // for (int i=0; i<order+1; i++) {
            //     func.setCoefficient( i, 1.0);
            // }
            // fitter.setFunction(func);
            // ASKAPLOG_INFO_STR(logger,"Fitting spectrum");
            // casa::Vector<casa::Float> solution = fitter.fit(x_full, vec, &mask);
            // subtract continuum model from data
            // casa::Vector<casa::Float> model(n);
            // ASKAPLOG_INFO_STR(logger,"Subtracting model");
            // bool ok = fitter.residual(model, x_full, casa::True);
            // vec -= model;

            // using coefficients table - segv
            // fitter.set(order+1);
            // casa::Matrix<casa::Float> xx(n, order+1);
            // for (int i=0; i<n; i++) {
            //     xx(i,0) = 1;
            //     for (int j=1; j<order+1; j++) xx(i,j) = xx(i,j-1)*casa::Float(i+1);
            // }
            // casa::Vector<casa::Float> solution = fitter.fit(xx, vec, &mask);
            // casa::Vector<casa::Float> model(n);
            // // ASKAPLOG_INFO_STR(logger,"Subtracting model");
            // bool ok = fitter.residual(model, xx, casa::True);
            // vec -= model;

            // using LSQaips - need invert before solve
            // Note: fitter uses double internally, giving float inputs just results in internal copying
            //       and is slower
            casa::LSQaips fitter(order+1);
            casa::Vector<casa::Double> xx(order+1);
            casa::VectorSTLIterator<casa::Double> it(xx);
            for (int i=0; i<n; i++) {
                if (mask(i)) {
                    xx(0) = 1;
                    for (int j=1; j<order+1; j++) {
                        xx(j) = xx(j-1) * i;
                    }
                    //ASKAPLOG_INFO_STR(logger,"makeNorm "<<i<<" "<<vec(i));
                    fitter.makeNorm(it,1.0,casa::Double(vec(i)));
                    //fitter.makeNorm(it,1.0f,vec(i));
                }
            }
            casa::uInt nr1;
            //cout << "Invert = " << fitter.invert(nr1);
            //cout << ", rank=" << nr1 << endl;
            casa::Vector<casa::Double> solution(order+1);
            fitter.invert(nr1);
            fitter.solve(solution);
            // cout << "Sol : ";
            // for (uInt i=0; i<order+1; i++) {
            //   cout << solution[i] << " ";
            // }
            // cout << endl;

            casa::Vector<casa::Float> model(n);
            for (int i=0; i<n; i++) {
                model(i)=solution(order);
                for (int j=order-1; j>=0; j--) {
                    model(i) = i * model(i) + solution(j);
                }
            }
            vec -= model;
        }

    };

// Main function
int main(int argc, char* argv[])
{
    ImContSubApp app;
    return app.main(argc, argv);
}
