#!/usr/bin/python
# -*- coding: utf-8 -*-
# ====================================================================
# @author: Joe Del Rocco
# @since: 11/02/2017
# @summary: A module that handles loading/checking sky data from the data directory.
# ====================================================================
import math
import os
import json
import itertools
from datetime import datetime
import numpy as np
from PIL import Image
import exifread
import spa
import common
import utility
import utility_angles


GaussianKernels = {}


# - configuration -------------------------------------------------------------
# - configuration -------------------------------------------------------------
# - configuration -------------------------------------------------------------

def loadAppSettings():
    if os.path.exists(common.AppSettings["Filename"]):
        loaded = []
        with open(common.AppSettings["Filename"], 'r') as file:
            loaded = json.load(file)
        for key in loaded:
            if (key in common.AppSettings):
                common.AppSettings.update({key: loaded[key]})

    # validate settings
    common.AppSettings["ExportOptions"]["Features"].sort()
    if len(common.AppSettings["DataDirectory"]) > 0 and not os.path.exists(common.AppSettings["DataDirectory"]):
        common.AppSettings["DataDirectory"] = ""
        return False

    return True

'''
Function to load data directory configuration. Contains all information about the data capture.
'''
def loadDataConfig():
    # config file must be in root of data directory
    cfgFile = os.path.join(common.AppSettings["DataDirectory"], common.DefDataConfig["Filename"])
    if not os.path.exists(cfgFile):
        return False

    # load config file
    loaded = []
    with open(cfgFile, 'r') as file:
        loaded = json.load(file)
    if not loaded or len(loaded) <= 0:
        return False

    # update in-memory collection with loaded config
    for key in loaded:
        if (key in common.DataConfig):
            common.DataConfig.update({key: loaded[key]})

    # extract capture epsilon
    common.CaptureEpsilon = common.DataConfig["CaptureEpsilon"]

    # extract spectroradiometer spectral range
    start = common.DataConfig["SpectrumStart"]
    end = common.DataConfig["SpectrumEnd"]
    common.SpectrumRange = (start, end)
    if start > end:
        return False

    # extract sampling pattern
    common.SamplingPattern[:] = [(float(azi), float(alt)) for [azi, alt] in common.DataConfig["SamplingPattern"]]
    common.SamplingPatternRads = [(math.radians(s[0]), math.radians(s[1])) for s in common.SamplingPattern]
    common.SamplingPatternAlts = list(set([s[1] for s in common.SamplingPattern]))
    common.SamplingPatternAlts = sorted(common.SamplingPatternAlts)
    if len(common.SamplingPattern) < 1:
        return False

    # extract exposures
    common.Exposures[:] = [float(e) for e in common.DataConfig["Exposures"]]
    common.ExposureIdxMap = {common.Exposures[i]: i for i in range(0, len(common.Exposures))}
    if len(common.Exposures) < 1:
        return False

    # extract lens warp/linearity data
    common.LensIdeal = tuple([0,0,0,1/(math.pi/2.0),0])
    common.LensIdealInv = tuple([0,0,0,(math.pi/2.0),0])
    common.LensWarp = tuple(common.DataConfig["Lens"]["Linearity"])
    common.LensWarpInv = tuple(common.DataConfig["Lens"]["Inverse"])

    # extract sky cover data
    dtfmtstr = "%m/%d/%Y %H:%M"
    common.SkyCoverData.clear()
    for sc in common.DataConfig["SkyCover"]:
        try:
            common.SkyCoverData.append((
                datetime.strptime(sc[0] + " " + sc[1], dtfmtstr),
                datetime.strptime(sc[0] + " " + sc[2], dtfmtstr),
                common.SkyCover[sc[3]]
            ))
        except ValueError or IndexError:
            return False

    # extract SPA data
    # create spa data and fill with default values from their example
    data = spa.spa_data()
    data.year = 2003
    data.month = 10
    data.day = 17
    data.hour = 12
    data.minute = 30
    data.second = 30
    data.time_zone = -7.0
    data.delta_ut1 = 0
    data.delta_t = 67
    data.longitude = -105.1786
    data.latitude = 39.742476
    data.elevation = 1830.14
    data.pressure = 820
    data.temperature = 11
    data.slope = 30
    data.azm_rotation = -10
    data.atmos_refract = 0.5667
    data.function = spa.SPA_ZA
    # overwrite with config values
    data.time_zone = float(common.DataConfig["SPA"]["time_zone"])
    data.delta_ut1 = float(common.DataConfig["SPA"]["delta_ut1"])
    data.delta_t = float(common.DataConfig["SPA"]["delta_t"])
    data.longitude = float(common.DataConfig["SPA"]["longitude"])
    data.latitude = float(common.DataConfig["SPA"]["latitude"])
    data.elevation = float(common.DataConfig["SPA"]["elevation"])
    data.pressure = float(common.DataConfig["SPA"]["pressure"])
    data.temperature = float(common.DataConfig["SPA"]["temperature"])
    data.slope = float(common.DataConfig["SPA"]["slope"])
    data.azm_rotation = float(common.DataConfig["SPA"]["azm_rotation"])
    data.atmos_refract = float(common.DataConfig["SPA"]["atmos_refract"])
    common.SPASiteData = data

    return True

# - HDR -----------------------------------------------------------------------
# - HDR -----------------------------------------------------------------------
# - HDR -----------------------------------------------------------------------

# debugging
# for row in range(0, kernel.shape[0]):
#     for col in range(0, kernel.shape[1]):
#         print("%.4f " % round(kernel[row, col, 0], 4), end='')
#     print()
# print(np.sum(kernel))
# for row in range(0, utility_data.KernelGauss5x5SD1.shape[0]):
#     for col in range(0, utility_data.KernelGauss5x5SD1.shape[1]):
#         print("%.4f " % round(utility_data.KernelGauss5x5SD1[row, col, 0], 4), end='')
#     print()
# print(np.sum(utility_data.KernelGauss5x5SD1)

'''
Function to search for and retrieve the filepath of a capture image.
:param datadir: The data directory to search in.
:param capture: The (datetime) capture timestamp.
:param exposure: The exposure value of the image.
:param extension: The extension of the image.
:return: A filepath of the specific image.
'''
def findHDRFile(datadir, capture, exposure, extension):
    datestr = datetime.strftime(capture, "%Y-%m-%d")
    timestr = datetime.strftime(capture, "%H.%M.%S")
    expidx = common.ExposureIdxMap[exposure]

    # find image path of capture timestamp
    path = os.path.join(datadir, datestr, "HDR", timestr)
    if not os.path.exists(path):
        return ''

    # gather all exposure photos taken at capture timestamp
    photos = utility.findFiles(path, mode=1, ext=[extension])
    if len(photos) <= 0:
        return ''

    # is there a photo for the currently selected exposure?
    if expidx >= len(photos):
        return ''

    return photos[expidx]

'''
Function to compute and retrieve a list of (x, y) points in a specific image given (azimuth, altitude) coordinates.
:param imgfile: Filepath to an image.
:param coords: A list of (azimuth, altitude) coordinates.
:return: A list of (x, y) points corresponding to the coordinates provided. 
'''
def computePointsInImage(imgfile, coords):
    if not os.path.exists(imgfile) or not coords:
        return []

    # load image and retrieve stats
    image = Image.open(imgfile)
    center = (int(image.width / 2), int(image.height / 2))
    diameter = image.height
    radius = diameter / 2
    image.close()

    # compute each coordinate in the image
    points = []
    for c in coords:
        u, v = utility_angles.SkyCoord2FisheyeUV(c[0], c[1])
        x = (center[0] - radius) + (u * diameter)
        y = (center[1] - radius) + (v * diameter)
        points.append((int(x), int(y)))

    return points

'''
Function to retrieve the pixels of specific points of an image.
:param points: A list of (x, y) points to lookup in the image file.
:param file: Optional path to the image file.
:param pixels: Optional numpy array of pixels in format [[[R G B (A)]]].
:param regions: A list of ints for size of (n x n) pixel region/kernel used during pixel convolution.
:param weighting: Pixel weighting convolution algorithm.
:return: A list of (R,G,B(,A)) tuples representing the pixel colors.
:note: Length of regions must match length of points.
:note: Coordinates MUST be within image bounds or this function will throw an exception!
:note: Alpha component may or may not be included, depending on image format.
'''
def collectPixels(points, regions, file='', pixels=None, weighting=common.PixelWeighting.Gaussian):
    if len(regions) != len(points):
        return []

    if pixels is None:
        if not os.path.exists(file) or not points:
            return []
        image = Image.open(file)
        #imgPixels = img.load()
        pixels = np.array(image)
        image.close()

    result = []
    for i, p in enumerate(points):
        if regions[i] == 1:
            result.append(pixels[int(p[1]), int(p[0])])
        else:
            if weighting == common.PixelWeighting.Mean:
                result.append(pixelWeightedMean(pixels, p, regions[i]))
            elif weighting == common.PixelWeighting.Median:
                result.append(pixelWeightedMean(pixels, p, regions[i]))
            elif weighting == common.PixelWeighting.Gaussian:
                result.append(pixelWeightedGaussian(pixels, p, GaussianKernels[regions[i]]))
    return result

def pixelWeightedMean(pixels, coord, dim):
    radius = int(dim / 2)
    scale = 1.0 / (dim * dim)
    pixelset = pixels[coord[1]-radius:coord[1]+radius+1, coord[0]-radius:coord[0]+radius+1]
    pixelset = pixelset * scale
    pixelset = np.sum(pixelset, axis=0)
    pxl = np.sum(pixelset, axis=0)
    # pxl = np.zeros(pixels.shape[2], np.float32)
    # for j in dim:
    #     for i in dim:
    #         pxl += scale * pixels[coord[1]+j-radius, coord[0]+i-radius]
    pxl = np.around(pxl, decimals=1, out=pxl)
    pxl = pxl.astype(np.uint8, copy=False)
    return pxl

def pixelWeightedMedian(pixels, coord, dim):
    return None

def pixelWeightedGaussian(pixels, coord, kernel):
    radius = int(kernel.shape[1] / 2)
    pixelset = pixels[coord[1]-radius:coord[1]+radius+1, coord[0]-radius:coord[0]+radius+1]
    pixelset = pixelset * kernel
    pixelset = np.sum(pixelset, axis=0)
    pxl = np.sum(pixelset, axis=0)
    # pxl = np.zeros(pixels.shape[2], np.float32)
    # for j in range(0, kernel.shape[0]):
    #     for i in range(0, kernel.shape[1]):
    #         pxl += kernel[j][i] * pixels[coord[1]+j-radius, coord[0]+i-radius]
    pxl = np.around(pxl, decimals=1, out=pxl)
    pxl = pxl.astype(np.uint8, copy=False)
    return pxl

def gaussianKernel(width):
    kernel = np.zeros(shape=(width,width,1), dtype=np.float32)
    radius = int(width/2)
    # sigma = 1.0
    sigma = radius/2.0  # for [-2*sigma, 2*sigma]
    total = 0.0
    # gaussian function
    #gaussian = lambda x: x + 1
    #kernel = gaussian(kernel)
    for row in range(0, width):
        for col in range(0, width):
            kernel[row,col,0] = math.exp(-0.5 * (pow((col - radius) / sigma, 2.0) + pow((row - radius) / sigma, 2.0))) / (2 * math.pi * sigma * sigma)
            total += kernel[row,col,0]
    # normalize
    kernel = kernel / total
    return kernel
GaussianKernels = {w:gaussianKernel(w) for w in range(common.PixelRegionMin+2, common.PixelRegionMax+1, 2)}

'''
Function to check if a raw data photo is available, given a path to an existing photo.
:param hdrImgpath: Path to a photo in the HDR folder of a capture date in the data directory.
:note: This assumes the raw data file is the same name (but different extension) of given file.
'''
def isHDRRawAvailable(hdrImgPath):
    if not os.path.exists(hdrImgPath):
        return False
    pathSplit = os.path.splitext(hdrImgPath.lower())
    for ext in common.HDRRawExts:
        if pathSplit[1] == ext:
            return True
        elif os.path.exists(pathSplit[0] + ext):
            return True
    return False

# - ASD -----------------------------------------------------------------------
# - ASD -----------------------------------------------------------------------
# - ASD -----------------------------------------------------------------------

'''
Function to search for and retrieve the filepaths of ASD files, given capture timestamp.
:param datadir: The data directory to search in.
:param capture: The (datetime) capture timestamp.
:return: A list of filepaths of the ASD files.
'''
def findASDFiles(datadir, capture):
    # find corresponding ASD dir
    datestr = datetime.strftime(capture, "%Y-%m-%d")
    pathASD = os.path.join(datadir, datestr, "ASD")
    if not os.path.exists(pathASD):
        return []

    # find all capture time dirs
    captureDirs = utility.findFiles(pathASD, mode=2)
    captureDirs[:] = [dir for dir in captureDirs if utility.verifyDateTime(os.path.basename(dir), "%H.%M.%S")]
    if len(captureDirs) <= 0:
        return []

    # find an ASD capture time within small threshold of HDR capture time
    pathCapture = None
    for dir in captureDirs:
        timestr = datestr + " " + os.path.basename(dir)
        time = datetime.strptime(timestr, "%Y-%m-%d %H.%M.%S")
        delta = (capture - time).total_seconds()
        if abs(delta) <= common.CaptureEpsilon:
            pathCapture = os.path.join(pathASD, os.path.basename(dir))
            break
    if not os.path.exists(pathCapture):
        return []

    # gather all .txt versions of ASD files taken at capture timestamp
    return utility.findFiles(pathCapture, mode=1, ext=["txt"])

'''
Function to search for and retrieve the filepath of the specified ASD file.
:param datadir: The data directory to search in.
:param capture: The (datetime) capture timestamp.
:param sampleidx: The sample pattern index of the sample in question.
:return: A filepath of the specific ASD file.
'''
def findASDFile(datadir, capture, sampleidx):
    asdfiles = findASDFiles(datadir, capture)

    # none found
    if len(asdfiles) <= 0:
        return ''
    # number of files doesnt match sampling pattern... how can we index it with sample index?
    if len(asdfiles) != len(common.SamplingPattern):
        return ''

    # find specific file by sample pattern index
    file = asdfiles[sampleidx]

    # make sure by checking first token of file name
    fnametoks = os.path.basename(file).split('_')
    if int(fnametoks[0]) != sampleidx:
       return ''

    return file

'''
Function to load a ViewSpecPro spectroradiometer ASD file.
:param filepath: Path to TXT file with ASD data
:param step: Indicates which rows of the file to load
:note: File format should be a TXT with the following data per line: Wavelength, Reading
:note: The TXT files were converted from ViewSpecPro's software in the order .asd to .asd.rad to .asd.rad.txt .
       That may not be a requirement for ASD data of future projects.
:return: 2 lists, Xs (wavelengths) and Ys (radiance values)        
'''
def loadASDFile(filepath, step=1):
    if not os.path.exists(filepath):
        return [], []
    wavelengths = []
    radiances = []
    with open(filepath) as f:
        iter = itertools.islice(f, 1, None, step)
        data = np.genfromtxt(iter)  #skip_header=1
        wavelengths = data[:,0]
        radiances = data[:,1]
        #wavelengths, radiances = np.loadtxt(filepath, skiprows=1, unpack=True)
    return wavelengths, radiances

# - sky cover -----------------------------------------------------------------
# - sky cover -----------------------------------------------------------------
# - sky cover -----------------------------------------------------------------

'''
Function to find the first instance found of sky cover assessment of a particular capture time.
:param capture: Capture (datetime) timestamp.
:param skycovers: List of SkyCover conditions.
:return: A sky cover. SkyCover.UNK is returned if none found. 
'''
def findCaptureSkyCover(capture, skycovers):
    capture = capture.replace(second=0)
    sky = common.SkyCover.UNK
    for sc in skycovers:
        if capture >= sc[0] and capture <= sc[1]:
            sky = sc[2]
            break
    return sky

# - SPA -----------------------------------------------------------------------
# - SPA -----------------------------------------------------------------------
# - SPA -----------------------------------------------------------------------

'''
Function to deep copy a spa_data object. This function is useful because SWIG didn't create pickling code for deep copy.
:param src: source spa_data object
:note: NREL SPA can be found at https://midcdmz.nrel.gov/spa/
:return: A destination spa_data object
'''
def deepcopySPAData(src):
    dest = spa.spa_data()
    # input values
    dest.year = src.year
    dest.month = src.month
    dest.day = src.day
    dest.hour = src.hour
    dest.minute = src.minute
    dest.second = src.second
    dest.time_zone = src.time_zone
    dest.delta_ut1 = src.delta_ut1
    dest.delta_t = src.delta_t
    dest.longitude = src.longitude
    dest.latitude = src.latitude
    dest.elevation = src.elevation
    dest.pressure = src.pressure
    dest.temperature = src.temperature
    dest.slope = src.slope
    dest.azm_rotation = src.azm_rotation
    dest.atmos_refract = src.atmos_refract
    dest.function = src.function
    # intermediate values not important
    # output values
    dest.zenith = src.zenith
    dest.azimuth_astro = src.azimuth_astro
    dest.azimuth = src.azimuth
    dest.incidence = src.incidence
    dest.suntransit = src.suntransit
    dest.sunrise = src.sunrise
    dest.sunset = src.sunset
    return dest

'''
Function to fill a spa_data object from NREL SPA with specified date and time.
:param spadata: spa_data object
:param dt: datetime object
:note: NREL SPA can be found at https://midcdmz.nrel.gov/spa/
'''
def fillSPADateTime(spadata, dt):
    if spadata is None or dt is None:
        return
    spadata.year = dt.year
    spadata.month = dt.month
    spadata.day = dt.day
    spadata.hour = dt.hour
    spadata.minute = dt.minute
    spadata.second = dt.second

'''
Function to compute the (azimuth, altitude) position of the sun using NREL SPA.
:param spadata: spa_data object with site info and date
:note: NREL SPA can be found at https://midcdmz.nrel.gov/spa/
:return: A single (azimuth, altitude) tuple of solar position.
'''
def computeSunPosition(spadata):
    spa.spa_calculate(spadata)
    altitude = 90 - spadata.zenith   # this application uses altitude (90 - zenith)
    return (spadata.azimuth, altitude)

'''
Function to compute the (azimuth, altitude) points above horizon for each hour of the day using NREL SPA.
:param spadata: spa_data object with site info and date
:note: NREL SPA can be found at https://midcdmz.nrel.gov/spa/
:return: A list of (azimuth, altitude, datetime) tuples with solar position and timestamp
'''
def computeSunPath(spadata):
    sunpath = []
    spadata2 = deepcopySPAData(spadata)
    spadata2.function = spa.SPA_ZA
    spadata2.minute = 0
    spadata2.second = 0
    # for each hour of the day, compute a sunpath point
    for i in range(0, 24):
        spadata2.hour = i
        spa.spa_calculate(spadata2)
        altitude = 90 - spadata2.zenith   # this application uses altitude (90 - zenith)
        # we only care about altitude when sun is visible (not on other side of Earth)
        if altitude >= 0 and altitude <= 90:
            dt = datetime(spadata2.year, spadata2.month, spadata2.day, spadata2.hour, spadata2.minute, int(spadata2.second))
            sunpath.append((spadata2.azimuth, altitude, dt))
    return sunpath

# - EXIF ----------------------------------------------------------------------
# - EXIF ----------------------------------------------------------------------
# - EXIF ----------------------------------------------------------------------

'''
Function to extract the "DateTimeOriginal" EXIF value of an image.
:param filepath: Path to image
'''
def imageEXIFDateTime(filepath):
    strDateTime = imageEXIFTag(filepath, "EXIF DateTimeOriginal")
    if strDateTime is None or len(strDateTime) <= 0:
        return datetime.min
    return datetime.strptime(strDateTime, '%Y:%m:%d %H:%M:%S')

'''
Function to extract the EXIF value of a particular tag.
:param filepath: Path to image
:param tag: EXIF tagname (not code) provided by module exifread
'''
def imageEXIFTag(filepath, tag):
    result = None
    with open(filepath, 'rb') as f:
        tags = exifread.process_file(f, details=False, stop_tag=tag)
        if tag in tags.keys():
            result = tags[tag]
    return str(result) if result is not None else None

'''
Function to extract all important EXIF data from an image.
:param filepath: Path to image
:return: A dict of key,value pairs for each EXIF metadata tag
'''
def imageEXIF(filepath):
    data = {}
    with open(filepath, 'rb') as f:
        data = exifread.process_file(f, details=False)
    return data
