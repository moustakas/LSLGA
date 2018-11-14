"""
LSLGA.unwise
============

Code to generate unWISE custom coadds / mosaics.

"""
import os, pdb
import numpy as np

def _unwise_to_rgb(imgs, bands=[1,2], mn=-1, mx=100, arcsinh=1.0):
    """Support routine to generate color unWISE images.

    Note that the input images need to be in *Vega* nanomaggies!

    """
    img = imgs[0]
    H, W = img.shape

    ## FIXME
    w1,w2 = imgs

    rgb = np.zeros((H, W, 3), np.uint8)

    scale1 = 50.
    scale2 = 50.

    #mn,mx = -3.,30.
    #arcsinh = None
    img1 = w1 / scale1
    img2 = w2 / scale2

    #print('W1 99th', np.percentile(img1, 99))
    #print('W2 99th', np.percentile(img2, 99))

    if arcsinh is not None:
        def nlmap(x):
            return np.arcsinh(x * arcsinh) / np.sqrt(arcsinh)
        #img1 = nlmap(img1)
        #img2 = nlmap(img2)
        mean = (img1 + img2) / 2.
        I = nlmap(mean)
        img1 = img1 / mean * I
        img2 = img2 / mean * I
        mn = nlmap(mn)
        mx = nlmap(mx)
    img1 = (img1 - mn) / (mx - mn)
    img2 = (img2 - mn) / (mx - mn)

    rgb[:,:,2] = (np.clip(img1, 0., 1.) * 255).astype(np.uint8)
    rgb[:,:,0] = (np.clip(img2, 0., 1.) * 255).astype(np.uint8)
    rgb[:,:,1] = rgb[:, :, 0] / 2 + rgb[:, :, 2] / 2

    return rgb

def unwise_coadds(onegal, galaxy=None, radius=30, pixscale=2.75, 
                  output_dir=None, unwise_dir=None, verbose=False,
                  log=None):
    '''Generate custom unWISE cutouts.
    
    radius in arcsec
    
    pixscale: WISE pixel scale in arcsec/pixel; make this smaller than 2.75
    to oversample.

    '''
    import fitsio
    import matplotlib.pyplot as plt
    
    from astrometry.util.util import Tan
    from astrometry.util.fits import fits_table
    from astrometry.libkd.spherematch import match_radec
    from astrometry.util.resample import resample_with_wcs, ResampleError
    from wise.forcedphot import unwise_tiles_touching_wcs
    from wise.unwise import get_unwise_tractor_image
    from tractor import Tractor, Image, NanoMaggies

    from legacypipe.survey import imsave_jpeg
    from legacypipe.catalog import read_fits_catalog
    
    if galaxy is None:
        galaxy = 'galaxy'

    if output_dir is None:
        output_dir = '.'

    if unwise_dir is None:
        unwise_dir = os.environ.get('UNWISE_COADDS_DIR')

    # Initialize the WCS object.
    W = H = np.ceil(2 * radius / pixscale).astype('int') # [pixels]
    targetwcs = Tan(onegal['RA'], onegal['DEC'], (W + 1) / 2.0, (H + 1) / 2.0,
                    -pixscale / 3600.0, 0.0, 0.0, pixscale / 3600.0, float(W), float(H))

    # Read the custom Tractor catalog.
    tractorfile = os.path.join(output_dir, '{}-tractor.fits'.format(galaxy))
    if not os.path.isfile(tractorfile):
        print('Missing Tractor catalog {}'.format(tractorfile), flush=True, file=log)
        return 0
    primhdr = fitsio.read_header(tractorfile)

    T = fits_table(tractorfile)
    srcs = read_fits_catalog(T)
    print('Read {} sources from {}'.format(len(T), tractorfile), flush=True, file=log)

    # Find and remove all the objects within XX arcsec of the target
    # coordinates.
    m1, m2, d12 = match_radec(T.ra, T.dec, onegal['RA'], onegal['DEC'], 5/3600.0, nearest=False)
    if len(d12) == 0:
        print('No matching galaxies found -- probably not what you wanted.')
        #raise ValueError
        nocentral = np.ones(len(T)).astype(bool)
    else:
        nocentral = ~np.isin(T.objid, T[m1].objid)
    T_nocentral = T[nocentral]
        
    # Find and read the overlapping unWISE tiles.  Assume the targetwcs is
    # axis-aligned and that the edge midpoints yield the RA, Dec limits (true
    # for TAN).  Note: the way the roiradec box is used, the min/max order
    # doesn't matter.
    r, d = targetwcs.pixelxy2radec(np.array([1,   W,   W/2, W/2]),
                                   np.array([H/2, H/2, 1,   H  ]))
    roiradec = [r[0], r[1], d[2], d[3]]

    tiles = unwise_tiles_touching_wcs(targetwcs)

    wbands = [1, 2, 3, 4]
    wanyband = 'w'
    vega_to_ab = dict(w1=2.699, w2=3.339, w3=5.174, w4=6.620)

    # Convert the AB WISE fluxes in the Tractor catalog to Vega nanomaggies so
    # they're consistent with the coadds, below.
    for band in wbands:
        f = T.get('flux_w{}'.format(band))
        f *= 10**(0.4 * vega_to_ab['w{}'.format(band)])

    coimgs = [np.zeros((H, W), np.float32) for b in wbands]
    comods = [np.zeros((H, W), np.float32) for b in wbands]
    comods_nocentral = [np.zeros((H, W), np.float32) for b in wbands]
    con    = [np.zeros((H, W), np.uint8) for b in wbands]

    for iband, band in enumerate(wbands):

        for ii, src in enumerate(srcs):
            src.setBrightness( NanoMaggies(**{wanyband: T.get('flux_w{}'.format(band) )[ii]}) )
        srcs_nocentral = np.array(srcs)[nocentral].tolist()
        
        # The tiles have some overlap, so for each source, keep the fit in the
        # tile whose center is closest to the source.
        for tile in tiles:
            #print('Reading tile {}'.format(tile.coadd_id))
            tim = get_unwise_tractor_image(unwise_dir, tile.coadd_id, band,
                                           bandname=wanyband, roiradecbox=roiradec)
            if tim is None:
                print('Actually, no overlap with tile {}'.format(tile.coadd_id))
                continue
            print('Read image {} with shape {}'.format(tile.coadd_id, tim.shape))

            def _unwise_mod(tim, use_T, use_srcs, margin=10):
                # Select sources in play.
                wisewcs = tim.wcs.wcs
                timH, timW = tim.shape
                ok, x, y = wisewcs.radec2pixelxy(use_T.ra, use_T.dec)
                x = (x - 1.).astype(np.float32)
                y = (y - 1.).astype(np.float32)
                I = np.flatnonzero((x >= -margin) * (x < timW + margin) *
                                   (y >= -margin) * (y < timH + margin))
                #print('Found {} sources within the image + margin = {} pixels'.format(len(I), margin))

                subcat = [use_srcs[i] for i in I]
                tractor = Tractor([tim], subcat)
                mod = tractor.getModelImage(0)
                return mod

            mod = _unwise_mod(tim, T, srcs)
            mod_nocentral = _unwise_mod(tim, T_nocentral, srcs_nocentral)

            try:
                Yo, Xo, Yi, Xi, nil = resample_with_wcs(targetwcs, tim.wcs.wcs)
            except ResampleError:
                continue
            if len(Yo) == 0:
                continue

            # The models are already in AB nanomaggies, but the tiles / tims are
            # in Vega nanomaggies, so convert them here.
            coimgs[iband][Yo, Xo] += tim.getImage()[Yi, Xi] 
            comods[iband][Yo, Xo] += mod[Yi, Xi]
            comods_nocentral[iband][Yo, Xo] += mod_nocentral[Yi, Xi]
            con   [iband][Yo, Xo] += 1

        ## Convert back to nanomaggies.
        #vega2ab = vega_to_ab['w{}'.format(band)]
        #coimgs[iband] *= 10**(-0.4 * vega2ab)
        #comods[iband] *= 10**(-0.4 * vega2ab)
        #comods_nocentral[iband] *= 10**(-0.4 * vega2ab)

    for img, mod, mod_nocentral, n in zip(coimgs, comods, comods_nocentral, con):
        img /= np.maximum(n, 1)
        mod /= np.maximum(n, 1)
        mod_nocentral /= np.maximum(n, 1)
        
    coresids = [img-mod for img, mod in list(zip(coimgs, comods))]

    # Subtract the model image which excludes the central (comod_nocentral)
    # from the data (coimg) to isolate the light of the central
    # (coimg_central).
    coimgs_central = [img-mod for img, mod in list(zip(coimgs, comods_nocentral))]

    # Write out the final images with and without the central and converted into
    # AB nanomaggies.
    for coadd, imtype in zip( (coimgs, comods, comods_nocentral),
                              ('image', 'model', 'model-nocentral') ):
        for img, band in zip(coadd, wbands):
            vega2ab = vega_to_ab['w{}'.format(band)]
            fitsfile = os.path.join(output_dir, '{}-{}-W{}.fits'.format(galaxy, imtype, band))
            if verbose:
                print('Writing {}'.format(fitsfile))
            fitsio.write(fitsfile, img * 10**(-0.4 * vega2ab), clobber=True)

    # Generate color WISE images.
    kwa = dict(mn=-1, mx=100, arcsinh=0.5)
    #kwa = dict(mn=-0.05, mx=1., arcsinh=0.5)
    #kwa = dict(mn=-0.1, mx=2., arcsinh=None)

    for imgs, imtype in zip( (coimgs, comods, coresids, comods_nocentral, coimgs_central),
                             ('image', 'model', 'resid', 'model-nocentral', 'image-central') ):
        rgb = _unwise_to_rgb(imgs[:2], **kwa) # W1, W2
        jpgfile = os.path.join(output_dir, '{}-{}-W1W2.jpg'.format(galaxy, imtype))
        if verbose:
            print('Writing {}'.format(jpgfile))
        imsave_jpeg(jpgfile, rgb, origin='lower')

    return 1