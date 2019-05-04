#!/usr/bin/env python

# /********************************************************************
# Filename: smart_random_bot.py
# Creation Date: Mar, 2019
# Author: AHN
# **********************************************************************/
#
# The fast random bot with some sanity rules to make it useful for
# finishing a game and counting.
#

from pdb import set_trace as BP
import numpy as np
import random

from agent_base import Agent
from agent_helpers import is_point_an_eye
from goboard_fast import Move
from gotypes import Point

#=================================
class SmartRandomBot(Agent):

    #---------------------
    def __init__( self):
        Agent.__init__( self)
        self.dim = None
        self.point_cache = []

    #-------------------------------
    def _update_cache( self, dim):
        self.dim = dim
        rows, cols = dim
        self.point_cache = []
        for r in range( 1, rows + 1):
            for c in range( 1, cols + 1):
                self.point_cache.append( Point(row=r, col=c))

    # See if we can escape an atari to save some stones
    #------------------------------------------------------
    def save_atari( self, game_state):
        pl = game_state.next_player
        atari_strings = game_state.board.strings_in_atari( pl)
        for astr in atari_strings:
            lib = next( iter( astr.liberties))
            cand =  Move.play( lib)
            if game_state.is_valid_move( cand):
                newstate = game_state.apply_move( cand)
                if newstate.board.get_go_string( lib).num_liberties > 1:
                    return cand
        return None

    # See if we can capture stones
    #-----------------------------------
    def capture( self, game_state):
        opp = game_state.next_player.other
        atari_strings = game_state.board.strings_in_atari( opp)
        for astr in atari_strings:
            for lib in astr.liberties:
                cand =  Move.play( lib)
                if game_state.is_valid_move( cand):
                    return cand
        return None

    # See if we can atari stones
    #-----------------------------------
    def atari( self, game_state):
        opp = game_state.next_player.other
        lib2_strings = game_state.board.strings_with_liberties( opp, 2)
        for astr in lib2_strings:
            for lib in astr.liberties:
                cand =  Move.play( lib)
                if game_state.is_valid_move( cand):
                    newstate = game_state.apply_move( cand)
                    if newstate.board.get_go_string( lib).num_liberties > 1:
                        return cand
        return None

    #--------------------------------------
    def select_move( self, game_state, _):

        cand = self.save_atari( game_state)
        if cand:
            return cand
        cand = self.capture( game_state)
        if cand:
            return cand
        cand = self.atari( game_state)
        if cand:
            return cand

        dim = (game_state.board.num_rows, game_state.board.num_cols)
        if dim != self.dim:
            self._update_cache( dim)

        idx = np.arange( len( self.point_cache))
        np.random.shuffle( idx)
        for i in idx:
            p = self.point_cache[i]
            if (game_state.is_valid_move( Move.play( p)) and
                not is_point_an_eye( game_state.board,
                                     p,
                                     game_state.next_player)):
                return Move.play( p)
        return Move.pass_turn()
