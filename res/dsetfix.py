#!/usr/bin/python
# -*- coding: utf-8 -*-
# ====================================================================
# @author: Joe Del Rocco
# @since: 06/25/2018
# @summary: Script to search/tweak SpectralSkyViewer exported datasets.
# ====================================================================
import sys
import os
import csv
import argparse
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns


def FindDuplicates(args):
    samples = {}
    with open(args.file, 'r') as f:
        reader = csv.reader(f, delimiter=',')
        header = next(reader, None)
        args.wavesidx = header.index("350")
        isi = header.index("SamplePatternIndex")
        idt = header.index("Date")
        itm = header.index("Time")
        PrintRow(args, header)
        for row in reader:
            key = str(row[idt]) + " " + str(row[itm]) + " " + str(row[isi])
            if key in samples:
                #Log(args, samples[key])
                PrintRow(args, row)
            else:
                samples[key] = row

def FindBySky(args):
    with open(args.file, 'r') as f:
        reader = csv.reader(f, delimiter=',')
        header = next(reader, None)
        args.wavesidx = header.index("350")
        isc = header.index("SkyCover")
        if args.count:
            n = 0
            n = sum(1 for row in reader if int(row[isc]) == args.skycover)
            print("Samples: " + str(n))
        else:
            PrintRow(args, header)
            for row in reader:
                if int(row[isc]) == args.skycover:
                    PrintRow(args, row)

def DataDistribution(args):
    values = []
    with open(args.file, 'r') as f:
        reader = csv.reader(f, delimiter=',')
        header = next(reader, None)
        idx = header.index(args.variance)
        for row in reader:
            values.append(float(row[idx]))

    variance = np.var(values, ddof=1)
    stddev = np.std(values, ddof=1)
    print('Variance: {0:.4f}'.format(variance))
    print('StdDev  : {0:.4f}'.format(stddev))

    fig = plt.figure()
    sns.distplot(values)
    plt.suptitle(args.variance + ' Distribution')
    plt.savefig('dist_'+args.variance, dpi=600, bbox_inches='tight')
    plt.close(fig)

def CountSamples(args):
    n = 0
    with open(args.file, 'r') as f:
        reader = csv.reader(f, delimiter=',')
        next(reader, None)
        n = sum(1 for row in reader)
    print("Samples: " + str(n))

def PrintRow(args, row):
    if args.hidewaves:
        print(*row[0:args.wavesidx], sep=',')
    else:
        print(*row, sep=',')

#---------------------------------------------------------------------

def main():
    # handle command line args
    parser = argparse.ArgumentParser(description='Script to search/tweak SpectralSkyViewer exported datasets. This script does not make any changes to the original file. All results are written to standard out.', formatter_class=argparse.RawTextHelpFormatter)
    parser.add_help = True
    parser.add_argument('file', help='a sky data export file')
    parser.add_argument('-w', '--hidewaves', dest='hidewaves', action='store_true', help='hide wavelength data (easier to read)')
    parser.add_argument('-n', '--count', dest='count', action='store_true', help='count number of samples')
    parser.add_argument('-d', '--dups', dest='dups', action='store_true', help='find duplicates')
    parser.add_argument('-s', '--skycover', dest='skycover', type=int, help='find data by skycover')
    parser.add_argument('-v', '--variance', dest='variance', type=str, help='compute variance, stddev, distibution')
    args = parser.parse_args()

    # file required as parameter
    if not args.file:
        print("Error: no data file specified.")
        sys.exit(2)
    # file not found
    elif not os.path.exists(args.file):
        print("Error: data file not found: '" + args.file + "'")
        sys.exit(2)

    # do it
    if args.dups:
        FindDuplicates(args)
    elif args.skycover:
        FindBySky(args)
    elif args.variance:
        DataDistribution(args)
    elif args.count:
        CountSamples(args)


if __name__ == "__main__":
    main()
