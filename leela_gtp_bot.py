#!/usr/bin/env python

# /*********************************
# Filename: leela_gtp_bot.py
# Creation Date: Apr, 2019
# Author: AHN
# **********************************/
#
# A wrapper bot to use several leela processes to find the next move.
# For use from a website were people can play leela.
#

from pdb import set_trace as BP
import os, sys, re
import numpy as np
import signal
import time

import subprocess
from threading import Thread,Lock,Event
import atexit

import goboard_fast as goboard
from agent_base import Agent
from agent_helpers import is_point_an_eye
from goboard_fast import Move
from gotypes import Point, Player
from go_utils import point_from_coords

g_response = None
g_handler_lock = Lock()
g_response_event = Event()
g_win_prob = ''

MOVE_TIMEOUT = 10 # seconds
#===========================
class LeelaGTPBot( Agent):
    # Listen on a stream in a separate thread until
    # a line comes in. Process line in a callback.
    #=================================================
    class Listener:
        #------------------------------------------------------------
        def __init__( self, stream, result_handler, error_handler):
            self.stream = stream
            self.result_handler = result_handler

            #--------------------------------------
            def wait_for_line( stream, callback):
                global g_response
                global g_handler_lock
                global g_response_event
                global g_win_prob
                while True:
                    line = stream.readline().decode()
                    if line:
                        result_handler( line)
                    else: # probably my process died
                        error_handler()
                        break

            self.thread = Thread( target = wait_for_line,
                                  args = (self.stream, self.result_handler))
            self.thread.daemon = True
            self.thread.start()

    #--------------------------------------
    def __init__( self, leela_cmdline):
        Agent.__init__( self)
        self.leela_cmdline = leela_cmdline
        self.last_move_color = ''

        self.leela_proc, self.leela_listener = self._start_leelaproc()
        atexit.register( self._kill_leela)

    #------------------------------
    def _start_leelaproc( self):
        proc = subprocess.Popen( self.leela_cmdline, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        listener = LeelaGTPBot.Listener( proc.stdout,
                                         self._result_handler,
                                         self._error_handler)
        return proc, listener

    #-------------------------
    def _kill_leela( self):
        if self.leela_proc.pid: os.kill( self.leela_proc.pid, signal.SIGKILL)

    # Parse leela response and trigger event to
    # continue execution.
    #---------------------------------------------
    def _result_handler( self, leela_response):
        global g_response
        global g_response_event
        global g_win_prob
        #with self.handler_lock:
        line = leela_response
        #print( '<-- ' + line)
        if 'NN eval=' in line:
            g_win_prob = line.split('=')[1]
        elif '=' in line:
            resp = line.split('=')[1].strip()
            #print( '<== ' + resp)
            g_response = self._resp2Move( resp)
            if g_response:
                #print(' >>>>>>>>>>>> trigger event')
                g_response_event.set()

    # Resurrect a dead Leela
    #---------------------------
    def _error_handler( self):
        #print( '>>>>>>>>> err handler')
        global g_handler_lock
        with g_handler_lock:
            print( 'Leela died. Resurrecting.')
            self._kill_leela()
            self.leela_proc, self.leela_listener = self._start_leelaproc()
            print( 'Leela resurrected')

    # Convert Leela response string to a Move we understand
    #------------------------------
    def _resp2Move( self, resp):
        res = None
        if 'pass' in resp:
            res = Move.pass_turn()
        elif 'resign' in resp:
            res = Move.resign()
        elif len(resp.strip()) in (2,3):
            p = point_from_coords( resp)
            res = Move.play( p)
        return res

    # Send a command to leela
    #-----------------------------
    def _leelaCmd( self, cmdstr):
        cmdstr += '\n'
        p = self.leela_proc
        p.stdin.write( cmdstr.encode('utf8'))
        p.stdin.flush()
        #print( '--> ' + cmdstr)

    # Override Agent.select_move()
    #-------------------------------------------
    def select_move( self, game_state, moves):
        global g_response
        global g_response_event
        res = None
        p = self.leela_proc
        # Reset the game
        self._leelaCmd( 'clear_board')

        # Make the moves
        color = 'b'
        for move in moves:
            self._leelaCmd( 'play %s %s' % (color, move))
            color = 'b' if color == 'w' else 'w'

        # Ask for new move
        self.last_move_color = color
        self._leelaCmd( 'genmove ' + color)
        # Hang until the move comes back
        #print( '>>>>>>>>> waiting')
        success = g_response_event.wait( MOVE_TIMEOUT)
        if not success: # I guess leela died
            self._error_handler()
            return None
        #time.sleep(2)
        #print( 'reponse: ' + str(g_response))
        if g_response:
            res = g_response
            #print( '>>>>>>>>> cleared event')
            g_response_event.clear()
        g_response = None
        return res

    # Override Agent.diagnostics()
    #------------------------------
    def diagnostics( self):
        global g_win_prob
        return { 'winprob': float(g_win_prob) if self.last_move_color=='b' else 1 - float(g_win_prob) }

    # Turn an idx 0..360 into a move
    #---------------------------------
    def _idx2move( self, idx):
        point = self.encoder.decode_point_index( idx)
        return goboard.Move.play( point)
