#!/usr/bin/env python

# /*********************************
# Filename: leelabot.py
# Creation Date: Apr, 2019
# Author: AHN
# **********************************/
#
# A bot trained from leela selfplay games.
#

from pdb import set_trace as BP
import os, sys, re
import numpy as np

import keras.models as kmod
from keras import backend as K
import tensorflow as tf

import goboard_fast as goboard
from agent_base import Agent
from agent_helpers import is_point_an_eye
from goboard_fast import Move
from gotypes import Point, Player
from encoder_base import get_encoder_by_name
from scoring import compute_nn_game_result

ENCODER = 'score_threeplane_encoder'
BSZ = 19


#===========================
class LeelaBot( Agent):

    #------------------------------------------------
    def __init__( self, policy_model, score_model):
        Agent.__init__( self)
        self.policy_model = policy_model
        self.score_model = score_model
        path = os.path.dirname(__file__)
        self.encoder = get_encoder_by_name( ENCODER, BSZ)

    #--------------------------------------
    def select_move( self, game_state, _):
        best_move, best_score = self._find_move( game_state, n_best=3, n_rollouts=1, depth=10)
        return best_move
        # num_moves = BSZ * BSZ
        # move_probs = self._predict( game_state)
        # candidates = np.arange( num_moves)
        # ranked_moves = sorted( candidates, key = lambda idx: move_probs[idx], reverse=True)
        # print( 'Ranked:'); print( ranked_moves[:3])
        # print( 'Probs:'); print( sorted(move_probs, reverse=True)[:3])
        # for point_idx in ranked_moves:
        #     point = self.encoder.decode_point_index( point_idx)
        #     if (game_state.is_valid_move( goboard.Move.play( point))):
        #         if not is_point_an_eye( game_state.board, point, game_state.next_player):
        #             print( 'played: %d' % point_idx)
        #             return goboard.Move.play( point)

        # return goboard.Move.pass_turn()

    # Turn an idx 0..360 into a move
    #---------------------------------
    def _idx2move( self, idx):
        point = self.encoder.decode_point_index( idx)
        return goboard.Move.play( point)

    #---------------------------------
    def _predict( self, game_state):
        encoded_state = self.encoder.encode( game_state)
        input_tensor = np.array( [encoded_state])
        return self.policy_model.predict( input_tensor)[0]

    #-------------------------------------------------------------
    def _find_move( self, game_state, n_best, n_rollouts, depth):
        num_moves = BSZ * BSZ
        move_probs = self._predict( game_state)
        candidates = np.arange( num_moves)
        ranked_moves = sorted( candidates, key = lambda idx: move_probs[idx], reverse=True)
        good_moves = []
        for point_idx in ranked_moves:
            point = self.encoder.decode_point_index( point_idx)
            if game_state.is_valid_move( goboard.Move.play( point)):
                if not is_point_an_eye( game_state.board, point, game_state.next_player):
                    good_moves.append(point_idx)
        n_best = min( n_best, len(good_moves))
        if n_best == 0: return (goboard.Move.pass_turn(), 0)
        med_scores = []
        for mv_idx in range( n_best):
            scores = []
            for roll_idx in range( n_rollouts):
                point = self.encoder.decode_point_index( good_moves[mv_idx])
                move = goboard.Move.play( point)
                new_state = self._rollout( game_state, move, depth)
                score = self._score( new_state)
                if game_state.next_player == Player.white:
                    score = score.w
                else:
                    score = score.b
                scores.append( score)

            med_score = np.median( scores)
            med_scores.append( med_score)

        best_idx = np.argmax( med_scores)
        point = self.encoder.decode_point_index( good_moves[best_idx])
        res = (goboard.Move.play( point), med_scores[best_idx])
        return res

    # Roll out one move to the given depth
    #----------------------------------------------
    def _rollout( self, game_state, move, depth):
        num_moves = BSZ * BSZ
        candidates = np.arange( num_moves)
        game_state = game_state.apply_move( move)
        for d in range(depth):
            move_probs = self._predict(game_state)
            # Pick next move from policy net distribution
            move_idx = np.random.choice( candidates, 1, p=move_probs)[0]
            move = self._idx2move( move_idx)
            game_state = game_state.apply_move( move)
        return game_state

    # Estimate score for a game state
    #------------------------------------
    def _score( self, game_state):
        feat = np.array( [ self.encoder.encode( game_state) ] )
        lab  = self.score_model.predict( [feat], batch_size=1)
        territory, res = compute_nn_game_result( lab, game_state.next_player)
        return res
