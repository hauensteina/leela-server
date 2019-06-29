#!/usr/bin/env python

# /********************************************************************
# Filename: scoring.py
# Author: AHN
# Creation Date: Mar, 2019
# **********************************************************************/
#
# Count a go position. All dead stones must have been removed already.
#

from __future__ import absolute_import
from pdb import set_trace as BP
from collections import namedtuple
from gotypes import Player, Point
import goboard_fast
import numpy as np


#===================
class Territory:

    #----------------------------------------
    def __init__( self, territory_map):
        self.n_intersections = len( territory_map)
        self.num_black_territory = 0
        self.num_white_territory = 0
        self.num_black_stones = 0
        self.num_white_stones = 0
        self.num_dame = 0
        self.dame_points = []
        self.black_points = []
        self.white_points = []
        for point, status in territory_map.items():
            if status == Player.black:
                self.num_black_stones += 1
                self.black_points.append( point)
            elif status == Player.white:
                self.num_white_stones += 1
                self.white_points.append( point)
            elif status == 'territory_b':
                self.num_black_territory += 1
                self.black_points.append( point)
            elif status == 'territory_w':
                self.num_white_territory += 1
                self.white_points.append( point)
            elif status == 'dame':
                self.num_dame += 1
                self.dame_points.append( point)

    # Turn yourself into a 1D np array of 0 for b territory or stone, else 1.
    # So 1 denotes w territory or dame.
    # This is the label we use to train a territory estimator using
    # sigmoid activation.
    #------------------------------------------------------------
    def encode_sigmoid( self):
        bsz = int( round( np.sqrt( self.n_intersections)))
        res = np.full( (bsz, bsz), 1, dtype='int8')
        for p in self.black_points:
            res[p.row - 1, p.col - 1] = 0
        return res

#=========================================================
class GameResult( namedtuple( 'GameResult', 'b w komi')):
    @property
    def winner(self):
        if self.b > self.w + self.komi:
            return Player.black
        return Player.white

    @property
    def winning_margin(self):
        w = self.w + self.komi
        return abs(self.b - w)

    def __str__(self):
        w = self.w + self.komi
        if self.b > w:
            return 'B+%.1f' % (self.b - w,)
        return 'W+%.1f' % (w - self.b,)

# Map a board into territory and dame.
# Any points that are completely surrounded by a single color are
# counted as territory; it makes no attempt to identify even
# trivially dead groups.
#-------------------------------
def evaluate_territory( board):
    status = {}
    for r in range( 1, board.num_rows + 1):
        for c in range( 1, board.num_cols + 1):
            p = Point(row=r, col=c)
            if p in status:  # <a>
                continue
            stone = board.get(p)
            if stone is not None:  # <b>
                status[p] = board.get(p)
            else:
                group, neighbors = _collect_region(p, board)
                if len(neighbors) == 1:  # <c>
                    neighbor_stone = neighbors.pop()
                    stone_str = 'b' if neighbor_stone == Player.black else 'w'
                    fill_with = 'territory_' + stone_str
                else:
                    fill_with = 'dame'  # <d>
                for pos in group:
                    status[pos] = fill_with
    return Territory( status)

# <a> Skip the point, if you already visited this as part of a different group.
# <b> If the point is a stone, add it as status.
# <c> If a point is completely surrounded by black or white stones, count it as territory.
# <d> Otherwise the point has to be a neutral point, so we add it to dame.
# end::scoring_evaluate_territory[]


# Find the contiguous section of a board containing a point. Also
# identify all the boundary points.
# This is like finding strings, but also for empty intersections.
#------------------------------------------------------------------
def _collect_region( start_pos, board, visited=None):
    if visited is None:
        visited = {}
    if start_pos in visited:
        return [], set()
    all_points = [start_pos]
    all_borders = set()
    visited[start_pos] = True
    here = board.get( start_pos)
    deltas = [(-1, 0), (1, 0), (0, -1), (0, 1)]
    for delta_r, delta_c in deltas:
        next_p = Point( row=start_pos.row + delta_r, col=start_pos.col + delta_c)
        if not board.is_on_grid(next_p):
            continue
        neighbor = board.get( next_p)
        if neighbor == here:
            points, borders = _collect_region( next_p, board, visited)
            all_points += points
            all_borders |= borders
        else:
            all_borders.add( neighbor)
    return all_points, all_borders

# Naive Tromp Taylor result
#--------------------------------------
def compute_game_result( game_state):
    territory = evaluate_territory( game_state.board)
    return (territory,
            GameResult(
                territory.num_black_territory + territory.num_black_stones,
                territory.num_white_territory + territory.num_white_stones,
                komi=7.5)
    )

# Transform probs (0.0 == B, 1.0 == W) into territory map
#-----------------------------------------------------------
def probs2terr( white_probs, game_state):
    BSZ = game_state.board.num_rows

    #-------------------
    def color( wprob):
        NEUTRAL_THRESH = 0.30 # 0.40 0.15
        if abs(0.5 - wprob) < NEUTRAL_THRESH: return 'n'
        elif wprob > 0.5: return 'w'
        else: return 'b'

    # Fix terrmap such that all stones in a string are alive or dead.
    # Decide by average score.
    #----------------------------------------------------------------
    def enforce_strings( terrmap):
        strs = game_state.board.get_go_strings()
        for gostr in strs:
            avg_col = 0.0
            for idx,point in enumerate(gostr.stones):
                prob_white = white_probs[ (point.row-1)*BSZ + point.col - 1]
                avg_col = avg_col * (idx/(idx+1)) + prob_white / (idx+1)

            truecolor = 'territory_b' if avg_col < 0.5 else 'territory_w'

            for point in gostr.stones:
                terrmap[point] = truecolor

        colcounts = {'territory_b':0, 'territory_w':0, 'dame':0}
        for p in terrmap: colcounts[terrmap[p]] += 1
        return colcounts['territory_b'],colcounts['territory_w'],colcounts['dame']

    terrmap = {}
    for r in range( 1, BSZ+1):
        for c in range( 1, BSZ+1):
            p = Point( row=r, col=c)
            prob_white = white_probs[ (r-1)*BSZ + c - 1]
            if color( prob_white) == 'w':
                terrmap[p] = 'territory_w'
            elif color( prob_white) == 'b':
                terrmap[p] = 'territory_b'
            else:
                terrmap[p] = 'dame'

    bpoints, wpoints, dame = enforce_strings( terrmap)

    # Split neutral points evenly between players
    player = game_state.next_player
    for i in range(dame):
        if player == Player.black:
            bpoints += 1
        else:
            wpoints += 1
        player = player.other

    return terrmap, bpoints, wpoints, dame

# Some dead stones might actually be seki. Find them and fix.
#--------------------------------------------------------------
def fix_seki( white_probs, game_state, terrmap):
    white_probs_out = white_probs.copy()
    strs = game_state.board.get_go_strings()
    for gostr in strs:
        for p in gostr.stones: break # get any from set
        terrcol = terrmap[p]
        dead = (((gostr.color == Player.white) and (terrcol == 'territory_b')) or
                  ((gostr.color == Player.black) and (terrcol == 'territory_w')))
        if not dead: continue
        # Kludge for bent four
        if len(gostr.stones) < 4: continue

        # Try to fill the liberties of the supposedly dead string
        gs = game_state
        gs.next_player = gostr.color.other
        couldfill = True
        seki = False
        while( couldfill):
            couldfill = False
            gstr = gs.board.get_go_string( p)
            if gstr is None: # we captured them, they were dead alright
                break
            # Play all moves that aren't self-atari
            for lib in gstr.liberties:
                move = goboard_fast.Move( lib)
                if not gs.is_move_self_capture( gostr.color.other, move):
                    temp = gs.apply_move( move)
                    oppstr = temp.board.get_go_string(lib)
                    if len(oppstr.liberties) > 1: # not self atari
                        gs = temp # let's actually play there
                        couldfill = True
                    gs.next_player = gostr.color.other # reset whose turn

            if couldfill: continue
            gstr = gs.board.get_go_string( p)

            # Maybe self atari is all we can do
            if gstr is not None: # we didn't capture without self atari
                for lib in gstr.liberties:
                    move = goboard_fast.Move( lib)
                    temp = gs.apply_move( move)
                    oppstr = temp.board.get_go_string(lib)
                    if len(oppstr.stones) > 6: # not nakade, it's a seki
                        seki = True
                    break

        if seki:
            myprob = 1.0 if gostr.color == Player.white else 0.0
            # All the dead stones are alive
            for s in gostr.stones:
                white_probs_out[ point2idx(s)] = myprob
            # All the liberties are neutral
            for lib in gostr.liberties:
                white_probs_out[ point2idx(lib)] = 0.5
    return white_probs_out

# Turn nn output into the expected scoring format.
# Any points close to 0.5 probability are neutral.
# They get split evenly between b and w.
#----------------------------------------------------
def compute_nn_game_result( labels, game_state):
    BSZ = game_state.board.num_rows
    white_probs = labels[0,:]
    terrmap,_,_,_ = probs2terr( white_probs, game_state)
    white_probs = fix_seki( white_probs, game_state, terrmap)
    terrmap, bpoints, wpoints, dame = probs2terr( white_probs, game_state)

    territory = Territory( terrmap)
    return (territory, GameResult( bpoints, wpoints, komi=0))

# Turn a board point into an integer index
#--------------------------------------------
def point2idx( point, bsz=19):
    return bsz * (point.row - 1) + (point.col - 1)
