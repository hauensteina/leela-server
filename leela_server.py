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

from gotypes import Point, Player
from leela_gtp_bot import LeelaGTPBot
from get_bot_app import get_bot_app
from sgf import Sgf_game
from go_utils import coords_from_point, point_from_coords
import goboard_fast as goboard
from encoder_base import get_encoder_by_name
from scoring import compute_nn_game_result

leela_cmd = './leelaz -w best-network -t 1 -p 256 -m 25 --randomtemp 2 -r 0 --noponder '
leela_gtp_bot = LeelaGTPBot( leela_cmd.split() )

# Get an app with 'select-move/<botname>' endpoints
app = get_bot_app( {'leela_gtp_bot':leela_gtp_bot} )

#----------------------------
if __name__ == '__main__':
    app.run( host='127.0.0.1', port=2718, debug=True)
