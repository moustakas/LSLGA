"""
LSLGA.io
========

Code to read and write the various LSLGA files.

"""
import os, warnings
import pickle, pdb
import numpy as np
import numpy.ma as ma
from glob import glob

import fitsio
from astropy.table import Table, Column, hstack
from astropy.io import fits

def LSLGA_dir():
    if 'LSLGA_DIR' not in os.environ:
        print('Required ${LSLGA_DIR environment variable not set.')
        raise EnvironmentError
    return os.path.abspath(os.getenv('LSLGA_DIR'))

def analysis_dir():
    adir = os.path.join(LSLGA_dir(), 'analysis')
    if not os.path.isdir(adir):
        os.makedirs(adir, exist_ok=True)
    return adir

def sample_dir(version=None):
    sdir = os.path.join(LSLGA_dir(), 'sample')
    if not os.path.isdir(sdir):
        os.makedirs(sdir, exist_ok=True)
    if version:
        sdir = os.path.join(LSLGA_dir(), 'sample', version)
        if not os.path.isdir(sdir):
            os.makedirs(sdir, exist_ok=True)
    return sdir

def paper1_dir(figures=True):
    pdir = os.path.join(LSLGA_dir(), 'science', 'paper1')
    if not os.path.ipdir(pdir):
        os.makedirs(pdir, exist_ok=True)
    if figures:
        pdir = os.path.join(pdir, 'figures')
        if not os.path.ipdir(pdir):
            os.makedirs(pdir, exist_ok=True)
    return pdir

def html_dir():
    #if 'NERSC_HOST' in os.environ:
    #    htmldir = '/global/project/projectdirs/cosmo/www/temp/ioannis/LSLGA'
    #else:
    #    htmldir = os.path.join(LSLGA_dir(), 'html')

    htmldir = os.path.join(LSLGA_dir(), 'html')
    if not os.path.isdir(htmldir):
        os.makedirs(htmldir, exist_ok=True)
    return htmldir

def missing_files_groups(args, sample, size, htmldir=None):
    """Simple task-specific wrapper on missing_files.

    """
    if args.coadds:
        if args.sdss:
            suffix = 'sdss-coadds'
        else:
            suffix = 'coadds'
    elif args.custom_coadds:
        if args.sdss:
            suffix = 'sdss-custom-coadds'
        else:
            suffix = 'custom-coadds'
    elif args.ellipse:
        if args.sdss:
            suffix = 'sdss-ellipse'
        else:
            suffix = 'ellipse'
    elif args.sersic:
        suffix = 'sersic'
    elif args.sky:
        suffix = 'sky'
    elif args.htmlplots:
        suffix = 'html'
    else:
        suffix = ''        

    if suffix != '':
        groups = missing_files(sample, filetype=suffix, size=size, sdss=args.sdss,
                               clobber=args.clobber, htmldir=htmldir)
    else:
        groups = []        

    return suffix, groups

def missing_files(sample, filetype='coadds', size=1, htmldir=None,
                  sdss=False, clobber=False):
    """Find missing data of a given filetype."""    

    if filetype == 'coadds':
        filesuffix = '-pipeline-resid-grz.jpg'
    elif filetype == 'custom-coadds':
        filesuffix = '-custom-resid-grz.jpg'
    elif filetype == 'ellipse':
        filesuffix = '-ellipsefit.p'
    elif filetype == 'sersic':
        filesuffix = '-sersic-single.p'
    elif filetype == 'html':
        filesuffix = '-ccdpos.png'
        #filesuffix = '-sersic-exponential-nowavepower.png'
    elif filetype == 'sdss-coadds':
        filesuffix = '-sdss-image-gri.jpg'
    elif filetype == 'sdss-custom-coadds':
        filesuffix = '-sdss-resid-gri.jpg'
    elif filetype == 'sdss-ellipse':
        filesuffix = '-sdss-ellipsefit.p'
    else:
        print('Unrecognized file type!')
        raise ValueError

    if type(sample) is astropy.table.row.Row:
        ngal = 1
    else:
        ngal = len(sample)
    indices = np.arange(ngal)
    todo = np.ones(ngal, dtype=bool)

    if filetype == 'html':
        galaxy, _, galaxydir = get_galaxy_galaxydir(sample, htmldir=htmldir, html=True)
    else:
        galaxy, galaxydir = get_galaxy_galaxydir(sample, htmldir=htmldir)

    for ii, (gal, gdir) in enumerate( zip(np.atleast_1d(galaxy), np.atleast_1d(galaxydir)) ):
        checkfile = os.path.join(gdir, '{}{}'.format(gal, filesuffix))
        if os.path.exists(checkfile) and clobber is False:
            todo[ii] = False

    if np.sum(todo) == 0:
        return list()
    else:
        indices = indices[todo]
        
    return np.array_split(indices, size)

def read_all_ccds(dr='dr8'):
    """Read the CCDs files, treating DECaLS and BASS+MzLS separately.

    """
    from astrometry.libkd.spherematch import tree_open
    #survey = LegacySurveyData()

    drdir = os.path.join(sample_dir(), dr)

    kdccds_north = []
    for camera in ('90prime', 'mosaic'):
        ccdsfile = os.path.join(drdir, 'survey-ccds-{}-{}.kd.fits'.format(camera, dr))
        ccds = tree_open(ccdsfile, 'ccds')
        print('Read {} CCDs from {}'.format(ccds.n, ccdsfile))
        kdccds_north.append((ccdsfile, ccds))

    ccdsfile = os.path.join(drdir, 'survey-ccds-decam-{}.kd.fits'.format(dr))
    ccds = tree_open(ccdsfile, 'ccds')
    print('Read {} CCDs from {}'.format(ccds.n, ccdsfile))
    kdccds_south = (ccdsfile, ccds)

    return kdccds_north, kdccds_south

def get_run(onegal, radius_mosaic, pixscale, kdccds_north, kdccds_south, log=None):
    """Determine the "run", i.e., determine whether we should use the BASS+MzLS CCDs
    or the DECaLS CCDs file when running the pipeline.

    """
    from astrometry.util.util import Tan
    from astrometry.libkd.spherematch import tree_search_radec
    from legacypipe.survey import ccds_touching_wcs
    
    ra, dec = onegal['RA'], onegal['DEC']
    if dec < 25:
        run = 'decam'
    elif dec > 40:
        run = '90prime-mosaic'
    else:
        width = LSLGA.coadds._mosaic_width(radius_mosaic, pixscale)
        wcs = Tan(ra, dec, width/2+0.5, width/2+0.5,
                  -pixscale/3600.0, 0.0, 0.0, pixscale/3600.0, 
                  float(width), float(width))

        # BASS+MzLS
        TT = []
        for fn, kd in kdccds_north:
            I = tree_search_radec(kd, ra, dec, 1.0)
            if len(I) == 0:
                continue
            TT.append(fits_table(fn, rows=I))
        if len(TT) == 0:
            inorth = []
        else:
            ccds = merge_tables(TT, columns='fillzero')
            inorth = ccds_touching_wcs(wcs, ccds)
        
        # DECaLS
        fn, kd = kdccds_south
        I = tree_search_radec(kd, ra, dec, 1.0)
        if len(I) > 0:
            ccds = fits_table(fn, rows=I)
            isouth = ccds_touching_wcs(wcs, ccds)
        else:
            isouth = []

        if len(inorth) > len(isouth):
            run = '90prime-mosaic'
        else:
            run = 'decam'
        print('Cluster RA, Dec={:.6f}, {:.6f}: run={} ({} north CCDs, {} south CCDs).'.format(
            ra, dec, run, len(inorth), len(isouth)), flush=True, file=log)

    return run

def check_and_read_ccds(galaxy, survey, debug=False, logfile=None):
    """Read the CCDs file generated by the pipeline coadds step.

    """
    ccdsfile_south = os.path.join(survey.output_dir, '{}-ccds-decam.fits'.format(galaxy))
    ccdsfile_north = os.path.join(survey.output_dir, '{}-ccds-90prime-mosaic.fits'.format(galaxy))
    if os.path.isfile(ccdsfile_south):
        ccdsfile = ccdsfile_south
    elif os.path.isfile(ccdsfile_north):
        ccdsfile = ccdsfile_north
    else:
        if debug:
            print('CCDs file {} not found.'.format(ccdsfile_south), flush=True)
            print('CCDs file {} not found.'.format(ccdsfile_north), flush=True)
            print('ERROR: galaxy {}; please check the logfile.'.format(galaxy), flush=True)
        else:
            with open(logfile, 'w') as log:
                print('CCDs file {} not found.'.format(ccdsfile_south), flush=True, file=log)
                print('CCDs file {} not found.'.format(ccdsfile_north), flush=True, file=log)
                print('ERROR: galaxy {}; please check the logfile.'.format(galaxy), flush=True, file=log)
        return False
    survey.ccds = survey.cleanup_ccds_table(fits_table(ccdsfile))

    # Check that coadds in all three grz bandpasses were generated in the
    # previous step.
    if ('g' not in survey.ccds.filter) or ('r' not in survey.ccds.filter) or ('z' not in survey.ccds.filter):
        if debug:
            print('Missing grz coadds...skipping.', flush=True)
            print('ERROR: galaxy {}; please check the logfile.'.format(galaxy), flush=True)
        else:
            with open(logfile, 'w') as log:
                print('Missing grz coadds...skipping.', flush=True, file=log)
                print('ERROR: galaxy {}; please check the logfile.'.format(galaxy), flush=True, file=log)
        return False
    return True

def get_galaxy_galaxydir(cat, analysisdir=None, htmldir=None, html=False):
    """Retrieve the galaxy name and the (nested) directory.

    """
    import astropy
    import healpy as hp
    from LSLGA.misc import radec2pix
    
    nside = 8 # keep hard-coded
    
    if analysisdir is None:
        analysisdir = analysis_dir()
    if htmldir is None:
        htmldir = html_dir()

    def get_healpix_subdir(nside, pixnum, analysisdir):
        subdir = os.path.join(str(pixnum // 100), str(pixnum))
        return os.path.abspath(os.path.join(analysisdir, str(nside), subdir))

    if type(cat) is astropy.table.row.Row:
        ngal = 1
        galaxy = [cat['GALAXY']]
        pixnum = [radec2pix(nside, cat['RA'], cat['DEC'])]
    else:
        ngal = len(cat)
        galaxy = np.array([gg.decode('utf-8') for gg in cat['GALAXY'].data])
        pixnum = radec2pix(nside, cat['RA'], cat['DEC']).data

    galaxydir = np.array([os.path.join(get_healpix_subdir(nside, pix, analysisdir), gal)
                          for pix, gal in zip(pixnum, galaxy)])
    if html:
        htmlgalaxydir = np.array([os.path.join(get_healpix_subdir(nside, pix, htmldir), gal)
                                  for pix, gal in zip(pixnum, galaxy)])

    if ngal == 1:
        galaxy = galaxy[0]
        galaxydir = galaxydir[0]
        if html:
            htmlgalaxydir = htmlgalaxydir[0]

    if html:
        return galaxy, galaxydir, htmlgalaxydir
    else:
        return galaxy, galaxydir

def parent_version(version=None):
    """Version of the parent catalog.

    These are the archived versions. For DR9 we reset the counter to start at v3.0!

    #version = 'v1.0' # 18may13
    #version = 'v2.0' # 18nov14
    #version = 'v3.0' # 19sep26
    #version = 'v4.0' # 19dec23
    #version = 'v5.0' # 20jan30 (dr9e)
    #version = 'v6.0' # 20feb25 (DR9-SV)
    version = 'v7.0'  # 20apr18 (DR9)

    """
    if version is None:
        #version = 'v1.0' # 18may13
        #version = 'v2.0' # DR8 (18nov14)
        version = 'v3.0' # DR9
    return version

def get_parentfile(version=None, kd=False):

    if kd:
        suffix = 'kd.fits'
    else:
        suffix = 'fits'
        
    parentfile = os.path.join(sample_dir(version=version), 'LSLGA-{}.{}'.format(version, suffix))

    return parentfile

def read_parent(columns=None, verbose=False, first=None, last=None,
                version=None, chaos=False):
    """Read the LSLGA parent catalog.

    """
    if version is None:
        version = parent_version()
    
    parentfile = get_parentfile(version=version)

    if first and last:
        if first > last:
            print('Index first cannot be greater than index last, {} > {}'.format(first, last))
            raise ValueError()
    ext = 1
    info = fitsio.FITS(parentfile)
    nrows = info[ext].get_nrows()

    rows = None
    
    # Read the CHAOS sample.
    if chaos:
        allgals = info[1].read(columns='GALAXY')
        rows = np.hstack( [np.where(np.isin(allgals, chaosgal.encode('utf-8')))[0]
                           for chaosgal in ('NGC0628', 'NGC5194', 'NGC5457', 'NGC3184')] )
        rows = np.sort(rows)
        nrows = len(rows)

        nrows = info[1].get_nrows()

    if first is None:
        first = 0
    if last is None:
        last = nrows
        if rows is None:
            rows = np.arange(first, last)
        else:
            rows = rows[np.arange(first, last)]
    else:
        if last >= nrows:
            print('Index last cannot be greater than the number of rows, {} >= {}'.format(last, nrows))
            raise ValueError()
        if rows is None:
            rows = np.arange(first, last+1)
        else:
            rows = rows[np.arange(first, last+1)]

    parent = Table(info[ext].read(rows=rows, upper=True, columns=columns))
    if verbose:
        if len(rows) == 1:
            print('Read galaxy index {} from {}'.format(first, parentfile))
        else:
            print('Read galaxy indices {} through {} (N={}) from {}'.format(
                first, last, len(parent), parentfile))

    ## Temporary hack to add the data release number, PSF size, and distance.
    #if chaos:
    #    parent.add_column(Column(name='DR', dtype='S3', length=len(parent)))
    #    gal2dr = {'NGC0628': 'DR7', 'NGC5194': 'DR6', 'NGC5457': 'DR6', 'NGC3184': 'DR6'}
    #    for ii, gal in enumerate(np.atleast_1d(parent['GALAXY'])):
    #        if gal in gal2dr.keys():
    #            parent['DR'][ii] = gal2dr[gal]
        
    return parent

def read_desi_tiles(verbose=False):
    """Read the latest DESI tile file.
    
    """
    tilefile = os.path.join(sample_dir(), 'catalogs', 'desi-tiles.fits')
    tiles = Table(fitsio.read(tilefile, ext=1, upper=True))
    tiles = tiles[tiles['IN_DESI'] > 0]
    
    if verbose:
        print('Read {} DESI tiles from {}'.format(len(tiles), tilefile))
    
    return tiles

def read_tycho(magcut=99, verbose=False):
    """Read the Tycho 2 catalog.
    
    """
    tycho2 = os.path.join(sample_dir(), 'catalogs', 'tycho2.kd.fits')
    tycho = Table(fitsio.read(tycho2, ext=1, upper=True))
    tycho = tycho[np.logical_and(tycho['ISGALAXY'] == 0, tycho['MAG_BT'] <= magcut)]
    if verbose:
        print('Read {} Tycho-2 stars with B<{:.1f}.'.format(len(tycho), magcut), flush=True)
    
    # Radius of influence; see eq. 9 of https://arxiv.org/pdf/1203.6594.pdf
    #tycho['RADIUS'] = (0.0802*(tycho['MAG_BT'])**2 - 1.860*tycho['MAG_BT'] + 11.625) / 60 # [degree]

    # From https://github.com/legacysurvey/legacypipe/blob/large-gals-only/py/legacypipe/runbrick.py#L1668
    # Note that the factor of 0.262 has nothing to do with the DECam pixel scale!
    tycho['RADIUS'] = np.minimum(1800., 150. * 2.5**((11. - tycho['MAG_BT']) / 4) ) * 0.262 / 3600

    #import matplotlib.pyplot as plt
    #oldrad = (0.0802*(tycho['MAG_BT'])**2 - 1.860*tycho['MAG_BT'] + 11.625) / 60 # [degree]
    #plt.scatter(tycho['MAG_BT'], oldrad*60, s=1) ; plt.scatter(tycho['MAG_BT'], tycho['RADIUS']*60, s=1) ; plt.show()
    #pdb.set_trace()
    
    return tycho

def read_hyperleda(verbose=False, allwise=False, version=None):
    """Read the Hyperleda catalog.

    These are the archived versions. For DR9 we reset the counter to start at v3.0!

    if version == 'v1.0':
        hyperfile = 'hyperleda-d25min10-18may13.fits'
    elif version == 'v2.0':
        hyperfile = 'hyperleda-d25min10-18nov14.fits'
    elif version == 'v3.0':
        hyperfile = 'hyperleda-d25min10-18nov14.fits'
    elif version == 'v4.0':
        hyperfile = 'hyperleda-d25min10-18nov14.fits'
    elif version == 'v5.0':
        hyperfile = 'hyperleda-d25min10-18nov14.fits'
    elif version == 'v6.0':
        hyperfile = 'hyperleda-d25min10-18nov14.fits'
    elif version == 'v7.0':
        hyperfile = 'hyperleda-d25min10-18nov14.fits'
    else:
        print('Unknown version!')
        raise ValueError
    
    """
    if version is None:
        version = parent_version()
        
    if version == 'v1.0':
        hyperfile = 'hyperleda-d25min10-18may13.fits'
        ref = 'LEDA-20180513'
    elif version == 'v2.0':
        hyperfile = 'hyperleda-d25min10-18nov14.fits'
        ref = 'LEDA-20181114'
    elif version == 'v3.0':
        hyperfile = 'hyperleda-d25min10-18nov14.fits'
        ref = 'LEDA-20181114'
    else:
        print('Unknown version!')
        raise ValueError

    hyperledafile = os.path.join(sample_dir(), 'hyperleda', hyperfile)
    allwisefile = hyperledafile.replace('.fits', '-allwise.fits')

    leda = Table(fitsio.read(hyperledafile, ext=1, upper=True))
    #leda.add_column(Column(name='GROUPID', dtype='i8', length=len(leda)))
    if verbose:
        print('Read {} objects from {}'.format(len(leda), hyperledafile), flush=True)

    if allwise:
        wise = Table(fitsio.read(allwisefile, ext=1, upper=True))
        if verbose:
            print('Read {} objects from {}'.format(len(wise), allwisefile), flush=True)

        # Merge the tables
        wise.rename_column('RA', 'WISE_RA')
        wise.rename_column('DEC', 'WISE_DEC')

        leda = hstack( (leda, wise) )
        leda.add_column(Column(name='IN_WISE', data=np.zeros(len(leda)).astype(bool)))

        haswise = np.where(wise['CNTR'] != -1)[0]
        #nowise = np.where(wise['CNTR'] == 0)[0]
        #print('unWISE match: {}/{} ({:.2f}%) galaxies.'.format(len(haswise), len(leda)))

        #print('EXT_FLG summary:')
        #for flg in sorted(set(leda['EXT_FLG'][haswise])):
        #    nn = np.sum(flg == leda['EXT_FLG'][haswise])
        #    print('  {}: {}/{} ({:.2f}%)'.format(flg, nn, len(haswise), 100*nn/len(haswise)))
        #print('Need to think this through a bit more; look at:')
        #print('  http://wise2.ipac.caltech.edu/docs/release/allsky/expsup/sec4_4c.html#xsc')
        #leda['INWISE'] = (np.array(['NULL' not in dd for dd in wise['DESIGNATION']]) * 
        #                  np.isfinite(wise['W1SIGM']) * np.isfinite(wise['W2SIGM']) )
        leda['IN_ALLWISE'][haswise] = True

        print('  Identified {}/{} ({:.2f}%) objects with AllWISE photometry.'.format(
            np.sum(leda['IN_ALLWISE']), len(leda), 100*np.sum(leda['IN_ALLWISE'])/len(leda) ))

    # Assign a unique ID and also fix infinite PA and B/A.
    leda.add_column(Column(name='ID', length=len(leda), dtype='i8'), index=0)
    leda['ID'] = np.arange(len(leda))
    leda['BYHAND'] = np.zeros(len(leda), bool)
    leda['REF'] = ref
    
    fix = np.isnan(leda['PA'])
    if np.sum(fix) > 0:
        leda['PA'][fix] = 0.0
    fix = np.isnan(leda['BA'])
    if np.sum(fix) > 0:
        leda['BA'][fix] = 1.0
    fix = np.isnan(leda['Z'])
    if np.sum(fix) > 0:
        leda['Z'][fix] = -99.0

    return leda

def read_multiband(galaxy, galaxydir, band=('g', 'r', 'z'), refband='r',
                   pixscale=0.262, galex_pixscale=1.5, unwise_pixscale=2.75,
                   maskfactor=2.0):
    """Read the multi-band images, construct the residual image, and then create a
    masked array from the corresponding inverse variances image.  Finally,
    convert to surface brightness by dividing by the pixel area.

    """
    from scipy.stats import sigmaclip
    from scipy.ndimage.morphology import binary_dilation

    # Dictionary mapping between filter and filename coded up in coadds.py,
    # galex.py, and unwise.py (see the LSLGA product, too).
    filt2imfile = {
        'g':   ['custom-image', 'custom-model-nocentral', 'invvar'],
        'r':   ['custom-image', 'custom-model-nocentral', 'invvar'],
        'z':   ['custom-image', 'custom-model-nocentral', 'invvar'],
        'FUV': ['image', 'model-nocentral'],
        'NUV': ['image', 'model-nocentral'],
        'W1':  ['image', 'model-nocentral'],
        'W2':  ['image', 'model-nocentral'],
        'W3':  ['image', 'model-nocentral'],
        'W4':  ['image', 'model-nocentral']}
        
    filt2pixscale =  {
        'g':   pixscale,
        'r':   pixscale,
        'z':   pixscale,
        'FUV': galex_pixscale,
        'NUV': galex_pixscale,
        'W1':  unwise_pixscale,
        'W2':  unwise_pixscale,
        'W3':  unwise_pixscale,
        'W4':  unwise_pixscale}

    found_data = True
    for filt in band:
        for ii, imtype in enumerate(filt2imfile[filt]):
            for suffix in ('.fz', ''):
                imfile = os.path.join(galaxydir, '{}-{}-{}.fits{}'.format(galaxy, imtype, filt, suffix))
                if os.path.isfile(imfile):
                    filt2imfile[filt][ii] = imfile
                    break
            if not os.path.isfile(imfile):
                print('File {} not found.'.format(imfile))
                found_data = False

    #tractorfile = os.path.join(galaxydir, '{}-tractor.fits'.format(galaxy))
    #if os.path.isfile(tractorfile):
    #    cat = Table(fitsio.read(tractorfile, upper=True))
    #    print('Read {} sources from {}'.format(len(cat), tractorfile))
    #else:
    #    print('Missing Tractor catalog {}'.format(tractorfile))
    #    found_data = False

    data = dict()
    if not found_data:
        return data

    for filt in band:
        image = fitsio.read(filt2imfile[filt][0])
        model = fitsio.read(filt2imfile[filt][1])

        if len(filt2imfile[filt]) == 3:
            invvar = fitsio.read(filt2imfile[filt][2])

            # Mask pixels with ivar<=0. Also build an object mask from the model
            # image, to handle systematic residuals.
            mask = (invvar <= 0) # True-->bad, False-->good
            
            #if np.sum(mask) > 0:
            #    invvar[mask] = 1e-3
            #snr = model * np.sqrt(invvar)
            #mask = np.logical_or( mask, (snr > 1) )

            #sig1 = 1.0 / np.sqrt(np.median(invvar))
            #mask = np.logical_or( mask, (image - model) > (3 * sig1) )

        else:
            mask = np.zeros_like(image).astype(bool)

        # Can give a divide-by-zero error for, e.g., GALEX imaging
        #with np.errstate(divide='ignore', invalid='ignore'):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            with np.errstate(all='ignore'):
                model_clipped, _, _ = sigmaclip(model, low=4.0, high=4.0)

        #print(filt, 1-len(model_clipped)/image.size)
        #if filt == 'W1':
        #    pdb.set_trace()
            
        if len(model_clipped) > 0:
            mask = np.logical_or( mask, model > 3 * np.std(model_clipped) )
            #model_clipped = model
        
        mask = binary_dilation(mask, iterations=1) # True-->bad

        thispixscale = filt2pixscale[filt]
        data[filt] = (image - model) / thispixscale**2 # [nanomaggies/arcsec**2]
        
        #data['{}_mask'.format(filt)] = mask # True->bad
        data['{}_masked'.format(filt)] = ma.masked_array(data[filt], mask)
        ma.set_fill_value(data['{}_masked'.format(filt)], 0)

    data['band'] = band
    data['refband'] = refband
    data['pixscale'] = pixscale

    if 'NUV' in band:
        data['galex_pixscale'] = galex_pixscale
    if 'W1' in band:
        data['unwise_pixscale'] = unwise_pixscale

    return data

def write_ellipsefit(galaxy, galaxydir, ellipsefit, verbose=False, noellipsefit=True):
    """Pickle a dictionary of photutils.isophote.isophote.IsophoteList objects (see,
    e.g., ellipse.fit_multiband).

    """
    if noellipsefit:
        suffix = '-fixed'
    else:
        suffix = ''
        
    ellipsefitfile = os.path.join(galaxydir, '{}-ellipsefit{}.p'.format(galaxy, suffix))
    if verbose:
        print('Writing {}'.format(ellipsefitfile))
    with open(ellipsefitfile, 'wb') as ell:
        pickle.dump(ellipsefit, ell)

def read_ellipsefit(galaxy, galaxydir, verbose=True, noellipsefit=True):
    """Read the output of write_ellipsefit.

    """
    if noellipsefit:
        suffix = '-fixed'
    else:
        suffix = ''

    ellipsefitfile = os.path.join(galaxydir, '{}-ellipsefit{}.p'.format(galaxy, suffix))
    try:
        with open(ellipsefitfile, 'rb') as ell:
            ellipsefit = pickle.load(ell)
    except:
        #raise IOError
        if verbose:
            print('File {} not found!'.format(ellipsefitfile))
        ellipsefit = dict()

    return ellipsefit

def read_localgroup_dwarfs():
    """Read the sample generated by bin/LSLGA-localgroup-dwarfs.

    """
    dwarfsfile = os.path.join(sample_dir(), 'catalogs', 'LSLGA-dwarfs.fits')
    dwarfs = Table(fitsio.read(dwarfsfile, upper=True))
    print('Read {} Local Group dwarfs from {}'.format(len(dwarfs), dwarfsfile))

    return dwarfs