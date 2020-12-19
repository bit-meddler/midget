"""
"""
# Workaround not being in PATH
import os, sys
_git_root_ = os.path.dirname( os.path.dirname( os.path.dirname( os.path.dirname( os.path.realpath(__file__) ) ) ) )
print( _git_root_ )
CODE_PATH = os.path.join( _git_root_, "midget", "Python" )
DATA_PATH = os.path.join( _git_root_, "rpiCap", "exampleData" )
sys.path.append( CODE_PATH )

from copy import deepcopy
import json
import numpy as np
from pprint import pprint

from collections import Counter, defaultdict
from Core.labelling import labelWandFrame


def pairPermuteSorted( items ):
    # assuming sorted list of items, make tuple permutations
    num = len( items )
    ret = []
    for i in range( num ):
        for j in range( i+1, num ):
            ret.append( (items[i], items[j]) )
    return ret

def buildCaliData( frames ):
    wand_counts = Counter()
    matchings = defaultdict( list )
    wand_ids = []
    for idx, (strides, x2ds, ids) in enumerate( frames ):
        ids, report = labelWandFrame( x2ds, strides )
        if( len( report ) < 2 ):
            continue # can't do anything with 0 or 1 wands

        wand_ids.append( ids )
        wand_counts.update( report )
        for pair in pairPermuteSorted( report ):
            matchings[ pair ].append( idx )

    return ( wand_ids, wand_counts, matchings )

def matchReport( matchings ):
    pair_counts = {}
    observed_cameras = set()
    for k, v, in matchings.items():
        pair_counts[k] = len(v)
        observed_cameras.add( k[0] )
        observed_cameras.add( k[1] ) 
    return pair_counts, observed_cameras

def keyWithMax( d ):
    return max( d, key=lambda x:  d[x] )

def restrictedDict( d, exclued ):
    # sounds uncomfortable!
    ret = {}
    for k in d.keys():
        if( k[0] not in exclued and k[1] not in exclued ):
            ret[k] = d[k]
    return ret

def prioritizeDict( d, required ):
    ret = {}
    for k in d.keys():
        if( k[0]  in required or k[1]  in required ):
            ret[k] = d[k]
    return ret

def unionDict( d, keys ):
    ret = {}
    for k in d.keys():
        if( k in keys ):
            ret[k] = d[k]
    return ret

def permutePairings( A, B ):
    # assuming a & b are exclusive, pair all a-b elements
    pairings = set()
    for a in A:
        for b in B:
            option = [a,b]
            pairings.add( ( min(option), max(option) ) )

    return pairings

def findGoodMarrage( pair_counts, cams, ungrouped, grouped ):
    pairs = []
    used_cams = set()

    if( len( ungrouped ) > 0 ):
        # Prioritize marrying ungrouped cameras
        available_pairs = prioritizeDict( pair_counts, ungrouped )

        while( len(available_pairs) > 1 ):
            pair = keyWithMax( available_pairs )
            used_cams.add( pair[0] )
            used_cams.add( pair[1] )
            pairs.append( pair )
            available_pairs = restrictedDict( available_pairs, used_cams )

    if( len( grouped ) > 0 ):
        # now if there are grouped cameras not joined in the ungrouped set,
        # find the optimal pivot and make those a pair

        # if an ungrouped camera has been paired with a camera that's a member of a group,
        # restrict that group's cameras this round
        for A, B in pairs:
            used_cams.update( getListContaining( A, grouped ) )
            used_cams.update( getListContaining( B, grouped ) )

        available_pairs = restrictedDict( pair_counts, used_cams )
        available_groups = deepcopy( grouped )

        while( len( available_groups ) > 1 ):
            gp_A = available_groups.pop()
            gp_B = None
            score = -1
            for gp in available_groups:
                candidate_pairs = permutePairings( gp_A, gp )
                if( len( candidate_pairs ) < 1 ):
                    continue
                possible = unionDict( available_pairs, candidate_pairs )
                if( len( possible ) < 1 ):
                    continue
                best = keyWithMax( possible )
                if( available_pairs[best] > score ):
                    gp_B = gp
                    score = available_pairs[best]

            if( gp_B is not None ):
                # take this pairing
                pair = keyWithMax( unionDict( available_pairs, permutePairings( gp_A, gp_B ) ) )
                pairs.append( pair )
                available_groups.remove( gp_B )
                used_cams.update( gp_A )
                used_cams.update( gp_B )
                print( "Group A: {}, Group B: {}, pair: {}, wands: {}".format( gp_A, gp_B, pair, available_pairs[ pair ] ) )

    remains = list( cams - used_cams )
    return pairs, remains

def getListContaining( item, holder ):
    """ Expecting a list of lists, return the member list containing the item """
    for X in holder:
        if item in X:
            return X
    return [ item, ]

def sterioCalibrate( pairs, groups ):
    # pair A & B
    # find the groups A & B are members of
    # Calibrate A & B, locking A at RT=np.eye(4)
    # transform groupA into A's space
    # transform groupB into B's space
    # merge to a new group
    new_groups = []
    for A, B in pairs:
        gp_A = getListContaining( A, groups )
        gp_B = getListContaining( B, groups )

        if( gp_A in groups ): groups.remove( gp_A )
        if( gp_B in groups ): groups.remove( gp_B )

        # Todo: Computer Vision PhD at Oxon or Surrey

        gp_A.extend( gp_B )
        new_groups.append( gp_A )
    
    return new_groups




#########################################################################################
with open( os.path.join( DATA_PATH, "calibration.json" ), "r" ) as fh:
    frames = json.load( fh )

    ids, counts, matches = buildCaliData( frames )

    # Prime the calibration with approx matching
    pair_counts, cams = matchReport( matches )
    ungrouped = sorted( list( cams ) )
    cam_groups = []
    all_cams_grouped = False

    while( not all_cams_grouped ):
        sterio_tasks, ungrouped = findGoodMarrage( pair_counts, cams, ungrouped, cam_groups )
        cam_groups = sterioCalibrate( sterio_tasks, cam_groups )
        print( "Caled Cam Groups", cam_groups )
        if( len( cam_groups ) == 1 ):
            all_cams_grouped = True

    # Refine calibration, openCv PnP ?

print( "done" )