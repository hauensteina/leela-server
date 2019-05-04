#!/usr/bin/env python

# /********************************************************************
# Filename: leela_server.py
# Author: AHN
# Creation Date: Apr, 2019
# **********************************************************************/
#
# A back end API to run leela and the keras scoring network.
#

from pdb import set_trace as BP
import os, sys, re
import numpy as np
from datetime import datetime
import uuid
from io import BytesIO

import flask
from flask import jsonify,request,Response,send_file

import keras.models as kmod
from keras import backend as K
import tensorflow as tf

from gotypes import Point
from smart_random_bot import SmartRandomBot
from leelabot import LeelaBot
from leela_gtp_bot import LeelaGTPBot
from get_bot_app import get_bot_app
from sgf import Sgf_game
from go_utils import coords_from_point, point_from_coords
import goboard_fast as goboard
from encoder_base import get_encoder_by_name
from scoring import compute_nn_game_result

#----------------------------
def setup_models():
    global SCOREMODEL
    global LEELABOTMODEL

    num_cores = 8
    GPU = 0

    if GPU:
        pass
    else:
        num_CPU = 1
        num_GPU = 0
        config = tf.ConfigProto( intra_op_parallelism_threads=num_cores,\
                                 inter_op_parallelism_threads=num_cores, allow_soft_placement=True,\
                                 device_count = {'CPU' : num_CPU, 'GPU' : num_GPU})
        session = tf.Session( config=config)
        K.set_session( session)

        #path = os.path.dirname(__file__)
        SCOREMODEL = kmod.load_model( 'static/models/nn_score.hd5')
        SCOREMODEL._make_predict_function()
        LEELABOTMODEL = kmod.load_model( 'static/models/nn_leelabot.hd5')
        LEELABOTMODEL._make_predict_function()


setup_models()
smart_random_agent = SmartRandomBot()
leelabot = LeelaBot( LEELABOTMODEL, SCOREMODEL )
leela_cmd = './leelaz -w best-network -t 1 -p 1 -m 50 --randomvisits -1 --noponder --cpu-only'
leela_gtp_bot = LeelaGTPBot( leela_cmd.split() )

# Get an app with 'select-move/<botname>' endpoints
app = get_bot_app( {'smartrandom':smart_random_agent, 'leelabot':leelabot, 'leela_gtp_bot':leela_gtp_bot} )


'''
@app.after_request
#---------------------
def add_header(r):
    """
    Add headers to both force latest IE rendering engine or Chrome Frame,
    and also to cache the rendered page for 10 minutes.
    """
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    r.headers['Cache-Control'] = 'public, max-age=0'
    return r
'''

#--------------------------------------
# Add some more endpoints to the app
#--------------------------------------

@app.route('/nnscore', methods=['POST'])
# Score the current position using our convolutional network
#-------------------------------------------------------------
def nnscore():
    content = request.json
    board_size = content['board_size']
    game_state = goboard.GameState.new_game( board_size)
    # Replay the game up to this point.
    for move in content['moves']:
        if move == 'pass':
            next_move = goboard.Move.pass_turn()
        elif move == 'resign':
            next_move = goboard.Move.resign()
        else:
            next_move = goboard.Move.play( point_from_coords(move))
        game_state = game_state.apply_move( next_move)

    enc  = get_encoder_by_name( 'score_threeplane_encoder', board_size)
    feat = np.array( [ enc.encode( game_state) ] )
    lab  = SCOREMODEL.predict( [feat], batch_size=1)

    territory, res = compute_nn_game_result( lab, game_state.next_player)
    white_probs = lab[0].tolist()
    return jsonify( {'result':res, 'territory':territory.__dict__ , 'white_probs':white_probs} )
