""" simArbiter.py - "We sense a soul in search of answers"

    This Tool will simulate the desired functionality of the arbiter.  Like a simCam
    it will play back the exemplor data files to simulate a working MoCap system,
    and it will simulate cameras responding correctly to C&C messages.

    For now t will emulate a "esential" Mocap system of 10 cameras and 1 sync unit.
"""

# Workaround not being in PATH
import os, sys
_git_root_ = os.path.dirname( os.path.dirname( os.path.dirname( os.path.dirname( os.path.realpath(__file__) ) ) ) )
print( _git_root_ )
CODE_PATH = os.path.join( _git_root_, "midget", "Python" )
DATA_PATH = os.path.join( _git_root_, "rpiCap", "exampleData" )
sys.path.append( CODE_PATH )

# Logging
import logging
logging.basicConfig()
log = logging.getLogger( __name__ )
log.setLevel( logging.DEBUG )

#detailed_log = logging.Formatter( "%(asctime)s.%(msecs)04d [%(levelname)-8s][%(name)-16s] %(message)s {%(filename)s@%(lineno)s}", "%y%m%d %H:%M:%S" )
#terse_log = logging.Formatter( "%(asctime)s.%(msecs)04d [%(levelname)-8s] %(message)s", "%y%m%d %H:%M:%S" )

import numpy as np
np.set_printoptions( precision=3, suppress=True )
from queue import SimpleQueue
import struct
import threading
import zmq

import Comms
#from Comms.piComunicate import AssembleDetFrame, SimpleComms


class Arbiter( object ):

    def __init__( self, replay=None, rate=None, step=None ):
        # inits
        self.replay = replay or "calibration"
        self.rate = rate or 25
        self.step = step or 4

        # System State
        self.system = Comms.SysManager()

        # No actual system communications, hold the det/com mans queues yourself
        self.q_out  = SimpleQueue()
        self.q_misc = SimpleQueue()

        # Client Communications (ZMQ)
        self.acks = 0
        self._zctx = zmq.Context()

        self.cnc_in = self._zctx.socket( zmq.ROUTER )
        self.cnc_in.bind( "tcp://*:{}".format( Comms.ABT_PORT_SYSCNC ) )

        self.state_pub = self._zctx.socket( zmq.PUB )
        self.state_pub.bind( "tcp://*:{}".format( Comms.ABT_PORT_SYSSTATE ) )

        self.data_pub = self._zctx.socket( zmq.PUB )
        self.data_pub.bind( "tcp://*:{}".format( Comms.ABT_PORT_DATA ) )

        self.poller = zmq.Poller()
        self.poller.register( self.cnc_in, zmq.POLLIN )

        # Setup a bogus system
        _BOGO_SYS_ = {
            "Sync" : "192.168.10.100",
            "Cam1" : "192.168.10.101",
            "Cam2" : "192.168.10.102",
            "Cam3" : "192.168.10.103",
            "Cam4" : "192.168.10.104",
            "Cam5" : "192.168.10.105",
            "Cam6" : "192.168.10.106",
            "Cam7" : "192.168.10.107",
            "Cam8" : "192.168.10.108",
            "Cam9" : "192.168.10.109",
            "CamA" : "192.168.10.110",
        }

        # a clock thread to tick the data replay
        self.ticks = 0

        # Enable Running
        self.running = threading.Event()
        self.running.set()

    def _setupReplay( self ):
        # load up the replay files
        # add a radius col
        # pack to frames
        pass
    
    def handleCNC( self, dgm ):
        # currently just cameras
        verb = dgm[ 2 ]
        noun = dgm[ 3 ]

        # setting like msg?
        setting = False
        tgt_idx = 4
        if( verb == b"set" or verb == b"try" ):
            setting = True
            tgt_idx = 5

        # Multi-target flood message
        tgt_out = len( dgm ) - 1
        tgts = dgm[ tgt_idx: tgt_out ]
        for tgt in tgts:
            ip = self.system.getCamIP( int( tgt.decode("utf-8") ) )
            if( ip is None ):
                print("Unknown Cam id")
                continue
            msg = ""
            if( setting ):
                msg = "{}:set {} {}".format( ip, noun, dgm[ 4 ] )
                # todo: set on the bogo sys
            else:
                msg = "{}:{} {}".format( ip, verb, noun )
            log.info( "hCNC> " + msg )

    def execute( self ):
        # Start Services

        # run
        while( self.running.isSet() ):
            try:
                # look for commands from clients
                coms = dict( self.poller.poll( 0 ) )
                if( coms.get( self.cnc_in ) == zmq.POLLIN ):
                    dgm = self.cnc_in.recv_multipart()
                    # Should we could test the validity of the request?
                    # Acnowlage recipt, and give a "Message Number"
                    self.acks += 1
                    ack = struct.pack( "I", self.acks )
                    self.cnc_in.send_multipart( [ dgm[ 0 ], b'', ack ] )
                    self.handleCNC( dgm )

                    # Emit a pub saying msg 'ack' has been done.
                    self.data_pub.send_multipart( [ Comms.ABT_TOPIC_STATE_B, b"", b"DID", ack ] )

                # Check for Dets or Images to send out
                # TODO: In the future, merge frames from different families of cameras
                if( not self.q_out.empty() ):
                    data = self.q_out.get()
                    self.publishDets( data ) # Make this a callback in the det man?

                # Look for misc & Orphans from cameraComms
                while( not self.q_misc.empty() ):
                    _, data = self.q_misc.get( block=False, timeout=0.001 )
                    print( data )
                    dtype, timecode, msg = data
                    self.data_pub.send_multipart( [ Comms.ABT_TOPIC_STATE_B, b"", msg ] )

            except KeyboardInterrupt:
                self.running.clear()

        # while running

        self.cleanClose()

    def publishDets( self, data ):
        time, strides, dets = data
        self.data_pub.send_multipart( [ Comms.ABT_TOPIC_ROIDS_B, b"",
                                        bytes( str( time ), "utf-8" ),
                                        strides.tobytes(),
                                        dets.tobytes() ] )
        log.info( "sent dets" )

    def cleanClose( self ):
        print( self.system )
        # Close managers
        self.com_mgr.running.clear()
        self.det_mgr.running.clear()

        # Close sockets for graceful shutdown
        self.cnc_in.close()
        self.state_pub.close()
        self.data_pub.close()
        self._zctx.term()

if( __name__ == "__main__" ):
    parser = argparse.ArgumentParser()
    parser.add_argument( "-s", "--simulate", action="store", dest="replay", default="calibration",
                         help="Replay data file. Can be 'calibration' or 'rom'. Default: calibration" )
    parser.add_argument( "-r", "--rate", action="store", dest="rate", default=25,
                         help="Rate (fps). Default: 25", type=int )
    parser.add_argument( "-k", "--skip", action="store", dest="step", default=4,
                         help="Frames to skip. if data is 100fps and rate is 25 skip=3 to get realtime. Default:3",
                         type=int )

    args = parser.parse_args()

    app = Arbiter( replay=args.replay, rate=args.rate, step=args.step )
    app.execute()