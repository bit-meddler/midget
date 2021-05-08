#import ctypes
import sys
import numpy as np

# Workaround not being in PATH
import os, sys
_git_root_ = os.path.dirname( os.path.dirname( os.path.dirname( os.path.realpath(__file__) ) ) )
CODE_PATH = os.path.join( _git_root_, "Python" )
print( CODE_PATH )
sys.path.append( CODE_PATH )

from Core.math3D import *
from GUI.shaders import ShaderHelper

import cv2

from PySide2 import QtCore, QtGui, QtWidgets
from shiboken2 import VoidPtr
from OpenGL import GL

from textwrap import TextWrapper


class OGLWindow( QtWidgets.QWidget ):

    def __init__( self, parent=None ):
        super( OGLWindow, self ).__init__( parent )
        self.setWindowTitle( "Testing OpenGL" )

        self.glWidget = GLVP()
        self.glWidget.setSizePolicy( QtWidgets.QSizePolicy.MinimumExpanding, QtWidgets.QSizePolicy.MinimumExpanding )
        mainLayout = QtWidgets.QHBoxLayout()
        mainLayout.addWidget( self.glWidget )

        toolLayout = QtWidgets.QVBoxLayout()
        mainLayout.addLayout( toolLayout )

        but = QtWidgets.QPushButton( "Change BG Colour", self )
        but.clicked.connect( self._onSetCol )
        toolLayout.addWidget( but )

        self.setLayout( mainLayout )

    def _onSetCol( self ):
        colour = QtWidgets.QColorDialog.getColor( QtGui.QColor.fromRgbF( *self.glWidget.DEFAULT_BG ),
                    self, "Select Background Colour",
                    options=QtWidgets.QColorDialog.ShowAlphaChannel|QtWidgets.QColorDialog.DontUseNativeDialog
        )
        self.glWidget.bgcolour = colour.getRgbF()


class PackedColourTexture( ShaderHelper ):
    shader_path = os.path.join( CODE_PATH, "GUI", "Shaders" )
    vtx_f = "simpleVCTpack.vert"
    frg_f = "simpleCTadd.frag"


class SimpleColour( ShaderHelper ):
    shader_path = os.path.join( CODE_PATH, "GUI", "Shaders" )
    vtx_f = "simpleVuC.vert"
    frg_f = "simpleC.frag"


def genFloorGridData( divs, size=100.0, y_height=0.0 ):
    """ Generate a Floor plane, -1, 1 spread into divisions of size at y_height

    :param divs: int or [int,int] of X,Z shape of grind
    :param size: spacing of 'tiles' 100 = 1m, 30.5 = 1ft
    :param y_height: hight of grid (default=0.0)
    :return: (vtx, indxs) vertex array, index array
    """
    vtx_np, idx_np = None, None
    dims = [2,2]
    if( type( divs ) in (list, tuple) ):
        dims[0], dims[1] = divs[0], divs[1]
    else:
        dims[0] = dims[1] = divs

    h_x = dims[0]//2
    h_z = dims[1]//2

    # Vertexs
    step_x = 1.0 / (h_x)
    step_z = 1.0 / (h_z)

    vtx = []
    for z in range( dims[1] + 1 ):
        z_point = (step_z * z) - 1.0
        for x in range( dims[0] + 1 ):
            vtx.append( [(step_x * x) - 1.0, 0.0, z_point] )

    vtx_np = np.asarray( vtx, dtype=FLOAT_T )
    vtx_np[:,0] *= size * h_x
    vtx_np[:,2] *= size * h_z

    # insert y_height
    height = np.ones( vtx_np.shape[0], dtype=FLOAT_T )
    height *= y_height
    vtx_np[:,1] = height


    # Indexs
    # line in/out pairs to draw each grid, slice list for the parimiter, the major axis

    return (vtx_np, idx_np)


class NavCam( object ):

    UP = QtGui.QVector3D( 0.0, 1.0, 0.0 )

    def __init__( self ):
        # locked camera
        self.locked = False

        # Camera extrinsics
        self.pos = QtGui.QVector3D( 0.0, 180.0, 200.0 ) #

        self.rot = QtGui.QVector3D( 0.0, 0.0, 0.0 ) # Roll, Pitch, Yaw
        self.int = QtGui.QVector3D( 0.0, 0.0, 0.0 ) # Compute from above?
        self.dst = 0.0 # Distance to interest

        # camera intrinsics
        self.vFoV   = 90.0  # Generic
        self.aspect = 1.777 # 16:9

        # GL Darwing
        self.nr_clip = 0.1
        self.fr_clip = 10000.0

        # GL Matrixes
        self.view = QtGui.QMatrix4x4()
        self.proj = QtGui.QMatrix4x4()

    def lookAtInterest( self ):
        if( self.locked ):
            return

        self.view.lookAt( self.pos, self.int, self.UP )
        self.dst = self.pos.distanceToPoint( self.int )
        print( self.dst )

    def updateProjection( self ):
        if (self.locked):
            return

        self.proj.perspective( self.vFoV, self.aspect, self.nr_clip, self.fr_clip )


class GLVP( QtWidgets.QOpenGLWidget ):

    DEFAULT_BG = ( 0.0, 0.1, 0.1, 1.0 )
    NAVIGATION_MODES = ( "TUMBLE", "TRUCK", "DOLLY", "ZOOM" )

    def __init__( self, parent=None ):
        # Odd Super call required with multi inheritance
        QtWidgets.QOpenGLWidget.__init__( self, parent )

        # Lock out GLPaint
        self.configured = False

        # OpenGL setup
        self.bgcolour = self.DEFAULT_BG
        self.buffers = {}
        self.shaders = {}
        self.f = None # glFunctions

        # Shader registry
        self.shader_sources = {
            "packedCT" : PackedColourTexture(),
#            "simpleC"  : SimpleColour(),
        }

        # canvas size
        self.wh = ( self.geometry().width(), self.geometry().height() )
        self.aspect = float(self.wh[0]) / float(self.wh[1])

        # Transform & MVP
        self.rot = 0.0

        # Navigation Camera
        self.camera = NavCam()
        self.camera.aspect = self.aspect
        self.nav_mode = None

        # ticks for redraws / updates
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect( self.update )

    def _confBuffer( self, kind, pattern, data=None ):

        gl_buf = QtGui.QOpenGLBuffer( kind )
        gl_buf.create()
        gl_buf.setUsagePattern( pattern )

        if( data is not None ):
            gl_buf.bind()
            gl_buf.allocate( data.tobytes(), data.nbytes )
            gl_buf.release()

        return gl_buf

    def _prepareResources( self ):
        #        positions         colors          texture coords
        cube = [-0.5, -0.5, 0.5,   1.0, 0.0, 0.0,  0.0, 0.0,
                 0.5, -0.5, 0.5,   0.0, 1.0, 0.0,  1.0, 0.0,
                 0.5,  0.5, 0.5,   0.0, 0.0, 1.0,  1.0, 1.0,
                -0.5,  0.5, 0.5,   1.0, 1.0, 1.0,  0.0, 1.0,

                -0.5, -0.5, -0.5,  1.0, 0.0, 0.0,  0.0, 0.0,
                 0.5, -0.5, -0.5,  0.0, 1.0, 0.0,  1.0, 0.0,
                 0.5,  0.5, -0.5,  0.0, 0.0, 1.0,  1.0, 1.0,
                -0.5,  0.5, -0.5,  1.0, 1.0, 1.0,  0.0, 1.0,

                 0.5, -0.5, -0.5,  1.0, 0.0, 0.0,  0.0, 0.0,
                 0.5,  0.5, -0.5,  0.0, 1.0, 0.0,  1.0, 0.0,
                 0.5,  0.5,  0.5,  0.0, 0.0, 1.0,  1.0, 1.0,
                 0.5, -0.5,  0.5,  1.0, 1.0, 1.0,  0.0, 1.0,

                -0.5,  0.5, -0.5,  1.0, 0.0, 0.0,  0.0, 0.0,
                -0.5, -0.5, -0.5,  0.0, 1.0, 0.0,  1.0, 0.0,
                -0.5, -0.5,  0.5,  0.0, 0.0, 1.0,  1.0, 1.0,
                -0.5,  0.5,  0.5,  1.0, 1.0, 1.0,  0.0, 1.0,

                -0.5, -0.5, -0.5,  1.0, 0.0, 0.0,  0.0, 0.0,
                 0.5, -0.5, -0.5,  0.0, 1.0, 0.0,  1.0, 0.0,
                 0.5, -0.5,  0.5,  0.0, 0.0, 1.0,  1.0, 1.0,
                -0.5, -0.5,  0.5,  1.0, 1.0, 1.0,  0.0, 1.0,

                 0.5,  0.5, -0.5,  1.0, 0.0, 0.0,  0.0, 0.0,
                -0.5,  0.5, -0.5,  0.0, 1.0, 0.0,  1.0, 0.0,
                -0.5,  0.5,  0.5,  0.0, 0.0, 1.0,  1.0, 1.0,
                 0.5,  0.5,  0.5,  1.0, 1.0, 1.0,  0.0, 1.0,
        ]
        obj = np.array( cube, dtype=np.float32 )

        indices = [
             0,  1,  2,  2,  3,  0,
             4,  5,  6,  6,  7,  4,
             8,  9, 10, 10, 11,  8,
            12, 13, 14, 14, 15, 12,
            16, 17, 18, 18, 19, 16,
            20, 21, 22, 22, 23, 20,
        ]

        indices = np.array( indices, dtype=np.uint )


        # Generate a Floor Grid
        floor_vtx, floor_idx = genFloorGridData( 4, 100.0 )

        # Generate OGL Buffers

        # Main VAO
        self.vao = QtGui.QOpenGLVertexArrayObject()
        self.vao.create()
        vao_lock = QtGui.QOpenGLVertexArrayObject.Binder( self.vao )

        # Cube Data
        self.buffers["cube.vbo"] = self._confBuffer( QtGui.QOpenGLBuffer.VertexBuffer,
                                                     QtGui.QOpenGLBuffer.StaticDraw,
                                                     data=obj )
        self.buffers["cube.ibo"] = self._confBuffer( QtGui.QOpenGLBuffer.IndexBuffer,
                                                     QtGui.QOpenGLBuffer.StaticDraw,
                                                     data=indices )
        self.buffers["cube.ibo.in"] = 0
        self.buffers["cube.ibo.idxs"] = len( indices )

        # Grid Data
        self.buffers[ "grid.vbo" ] = self._confBuffer( QtGui.QOpenGLBuffer.VertexBuffer,
                                                       QtGui.QOpenGLBuffer.StaticDraw,
                                                       data=floor_vtx )
        self.buffers[ "grid.ibo" ] = self._confBuffer( QtGui.QOpenGLBuffer.IndexBuffer,
                                                       QtGui.QOpenGLBuffer.StaticDraw,
                                                       data=floor_idx )
        self.buffers[ "grid.ibo.in" ] = 0
        self.buffers[ "grid.ibo.idxs" ] = len( floor_vtx ) #<-----------

        # Load Texture Image
        img = cv2.imread( "wood.jpg", cv2.IMREAD_COLOR )
        rgb_img = cv2.cvtColor( img, cv2.COLOR_BGR2RGB )
        i_h, i_w, _ = rgb_img.shape

        # convert cv2 Image to QImage
        q_img = QtGui.QImage( rgb_img.data, i_w, i_h, (3 * i_w), QtGui.QImage.Format_RGB888 )

        # Create Texture
        self.texture = QtGui.QOpenGLTexture( QtGui.QOpenGLTexture.Target2D ) # Target2D === GL_TEXTURE_2D
        self.texture.create()
        self.texture.bind()
        self.texture.setData( q_img )
        self.texture.setMinMagFilters( QtGui.QOpenGLTexture.Linear, QtGui.QOpenGLTexture.Linear )
        self.texture.setWrapMode( QtGui.QOpenGLTexture.DirectionS, QtGui.QOpenGLTexture.ClampToEdge )
        self.texture.setWrapMode( QtGui.QOpenGLTexture.DirectionT, QtGui.QOpenGLTexture.ClampToEdge )
        self.texture.release()

        # Release the VAO Mutex Binder
        del( vao_lock )

    # Generic GL Config --------------------------------------------------------
    def _configureShaders( self ):

        for sname, helper in self.shader_sources.items():

            self.shaders[ sname ] = QtGui.QOpenGLShaderProgram( self.context() )

            self.shaders[ sname ].addShaderFromSourceCode( QtGui.QOpenGLShader.Vertex, helper.vtx_src  )
            self.shaders[ sname ].addShaderFromSourceCode( QtGui.QOpenGLShader.Fragment, helper.frg_src )

            # Bind attrs
            for aname, location in helper.attr_locs.items():
                self.shaders[ sname ].bindAttributeLocation( aname, location )

            # Link Shader
            is_linked = self.shaders[ sname ].link()
            if( not is_linked ):
                print( "Error linking shader!" )

            # Locate uniforms
            for uniform, data in helper.vtx_uniforms.items():
                location = self.shaders[ sname ].uniformLocation( uniform )
                helper.vtx_unis[ uniform ] = location
                print( "Vtx uniform '{}' ({}{}) bound @ {}".format(
                       uniform, data[ "type"  ], data[ "shape" ], location )
                )

    def _configureAttribBindings( self ):
        self._configureVertexAttribs( self.vao, self.buffers[ "cube.vbo" ], self.shader_sources["packedCT"] )
        #self._configureVertexAttribs( self.vao, self.buffers[ "grid.vbo" ], self.shader_sources["simpleC"] )


    def _configureVertexAttribs( self, vao, buffer, shader_info ):
        vao_lock = QtGui.QOpenGLVertexArrayObject.Binder( vao )
        buffer.bind()
        for name, num, offset in shader_info.layout:
            location = shader_info.attr_locs[ name ]
            print( "Setting VAP on '{}' @ {} with {} elems from {}b".format(
                name, location, num, offset )
            )
            os_ptr = VoidPtr( offset )
            self.f.glEnableVertexAttribArray( location )
            self.f.glVertexAttribPointer(  location,
                                           num,
                                           GL.GL_FLOAT,
                                           GL.GL_FALSE,
                                           shader_info.line_size,
                                           os_ptr )
        buffer.release()
        del( vao_lock )

    def getGlInfo( self, show_ext=False ):
        print( "Getting GL Info" )

        ven = self.f.glGetString( GL.GL_VENDOR )
        ren = self.f.glGetString( GL.GL_RENDERER )
        ver = self.f.glGetString( GL.GL_VERSION )
        slv = self.f.glGetString( GL.GL_SHADING_LANGUAGE_VERSION )
        ext = self.f.glGetString( GL.GL_EXTENSIONS )

        exts = ""
        if (show_ext):
            pad = "            "
            w = TextWrapper( width=100, initial_indent="", subsequent_indent=pad )
            lines = w.wrap( ext )
            exts = "\n".join( lines )

        else:
            exts = "{} installed".format( len( ext.split() ) )

        info = "Vendor: {}\nRenderer: {}\nOpenGL Version: {}\nShader Version: {}\nExtensions: {}".format(
            ven, ren, ver, slv, exts )

        # Get context Info?

        return info

    def _onClosing( self ):
        """ Clean close of OGL resources """
        print( "Clean Close" )
        self.context().makeCurrent()

        for buff in self.buffers.values():
            buff.destroy()

        self.texture.destroy()
        self.vao.destroy()

        for shader in self.shaders.items():
            del( shader )

        self.doneCurrent()

    # Navigation funcs ---------------------------------------------------------
    def _beginNav( self, mode ):
        """ begin or change a navigation interaction """
        if( self.nav_mode == mode ):
            return # still in the same mode

        # Complete the last interaction
        self._endNav()

        self.nav_mode = mode

    def _endNav( self ):
        self.nav_mode = None

    # Qt funcs -----------------------------------------------------------------
    def mousePressEvent(self, event):
        """ Determine what interactions we're making with the scene. """
        buttons = event.buttons()
        modifiers = event.modifiers()

        # All interactions need to calculate a delta from the start point
        self._last_x, self._last_y = event.x(), event.y()

        lmb = bool( buttons & QtCore.Qt.LeftButton  )
        mmb = bool( buttons & QtCore.Qt.MidButton   )
        rmb = bool( buttons & QtCore.Qt.RightButton )

        if( bool(modifiers & QtCore.Qt.AltModifier) ):
            # 3D Navigation has begun
            if( lmb ):
                if( rmb ):
                    self._beginNav( "TRUCK" )

                else:
                    self._beginNav( "TUMBLE" )

            elif( rmb ):
                self._beginNav( "DOLLY" )

            elif( mmb ):
                self._beginNav( "ZOOM" )

    def mouseReleaseEvent( self, event ):
        buttons = event.buttons()

        if( buttons == 0 ):
            self._endNav()
            #super( GLVP, self ).mouseReleaseEvent( event ) #???

        else:
            # use the new button mask to change tools,
            # e.g. toggle between Truck & Tumble
            self.mousePressEvent( event )

    def mouseMoveEvent( self, event ):
        """ The real meat of navigation goes on here. """
        if( self.nav_mode is None ):
            return

        # mouse motion computations
        new_x, new_y = event.x(), event.y()
        d_x, d_y = new_x - self._last_x, new_y - self._last_y

        if(   self.nav_mode == "TRUCK" ):
            """ Move camera position in X and Y, move interest to match. """
            offset = QtGui.QVector3D( d_x * 0.1, d_y * 0.1, 0.0 )
            self.camera.pos += offset
            self.camera.int += offset
            self.camera.lookAtInterest()

        elif( self.nav_mode == "TUMBLE" ):
            """ Arc Ball interaction? move camera position around surface of ball
                centred at interest, with r being interest distance.
            """
            pass

        elif( self.nav_mode == "DOLLY" ):
            """ Translate along the vector from camera pos to interest, move
                interest away an equal amount.
            """
            pass

        elif( self.nav_mode == "ZOOM" ):
            """ Narrow the FoV """
            pass

        self._last_x, self._last_y = new_x, new_y

    def minimumSizeHint( self ):
        return QtCore.QSize( 400, 400 )

    def sizeHint( self ):
        return QtCore.QSize( 400, 400 )


    # gl funs ------------------------------------------------------------------
    def initializeGL( self ):
        super( GLVP, self ).initializeGL()

        # init GL Context
        ctx = self.context()
        ctx.aboutToBeDestroyed.connect( self._onClosing )

        # get Context bound GL Funcs
        self.f = QtGui.QOpenGLFunctions( ctx )
        self.f.initializeOpenGLFunctions()

        # shaders
        self._configureShaders()

        # buffers & Textures
        self.f.glEnable( GL.GL_TEXTURE_2D )
        self._prepareResources()

        # Attrs
        self._configureAttribBindings()

        # misc
        self.f.glClearColor( *self.bgcolour )

        self.f.glEnable( GL.GL_DEPTH_TEST )
        self.f.glDepthFunc( GL.GL_LESS )

        self.f.glEnable( GL.GL_BLEND )
        self.f.glBlendFunc( GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA )

        self.f.glEnable( GL.GL_POINT_SMOOTH )
        self.f.glHint( GL.GL_POINT_SMOOTH_HINT, GL.GL_NICEST )

        # Setup Camera
        self.camera.lookAtInterest()
        self.camera.updateProjection()

        # Start auto updates
        self.timer.start( 16 )  # approx 60fps

        self.configured = True

    def paintGL( self ):
        # guard against early drawing
        if( not self.configured ):
            return

        # Going to try overpainting again...
        painter = QtGui.QPainter()
        painter.begin( self )

        # Enable GL
        painter.beginNativePainting()

        # gl Viewport
        self.f.glEnable( GL.GL_DEPTH_TEST ) # Has to be reset because painter :(
        self.f.glClearColor( *self.bgcolour )
        #self.f.glViewport( 0, 0, self.wh[0], self.wh[1] )

        # attach VAO
        vao_lock = QtGui.QOpenGLVertexArrayObject.Binder( self.vao )

        # Cube Drawing
        shader = self.shaders["packedCT"]
        helper = self.shader_sources["packedCT"]
        shader.bind()

        self.buffers["cube.vbo"].bind()
        self.buffers["cube.ibo"].bind()
        self.texture.bind()

        # Move the Cube
        transform = QtGui.QMatrix4x4() # Remember these are transpose

        # start drawing
        self.f.glClear( GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT )

        # Update View / Projection mats
        pv = self.camera.proj * self.camera.view

        # striding data
        ptr = VoidPtr( self.buffers[ "cube.ibo.in" ] )
        num_idx = self.buffers[ "cube.ibo.idxs" ]

        # Draw a field of cubes
        scale = 30.5
        for i in range( 10 ):
            y_rot = (self.rot/11.0) + (i*6.0)
            for j in range( 10 ):
                for k in range( 10 ):
                    x = (i-5) * 4.5
                    y = (j-5) * 4.5
                    z = (-1-k) * 4.5

                    x *= scale
                    y *= scale
                    z *= scale
                    #print( x, y, z )
                    transform.setToIdentity()
                    transform.translate( x, y, z )
                    transform.rotate( self.rot, 1.0, 0.0, 0.0 ) # ang, axis
                    transform.rotate( y_rot, 0.0, 1.0, 0.0 )
                    transform.rotate( i+j+k, 0.0, 0.0, 1.0 )
                    transform.scale( 18.0 )

                    mvp = pv * transform

                    shader.setUniformValue( helper.vtx_unis[ "u_mvp" ], mvp )

                    self.f.glDrawElements( GL.GL_TRIANGLES, num_idx, GL.GL_UNSIGNED_INT, ptr )

        self.rot += 1.0

        # Done Cubes
        self.buffers["cube.vbo"].release()
        self.buffers["cube.ibo"].release()
        self.texture.release()
        shader.release()
        helper = None

        # # Draw Grid
        # shader = self.shaders["simpleC"]
        # helper = self.shader_sources["simpleC"]
        # shader.bind()
        # self.buffers[ "grid.vbo" ].bind()
        #
        # transform.setToIdentity()
        #
        # mvp = pv * transform
        #
        # shader.setUniformValue( helper.vtx_unis[ "u_mvp" ], mvp )
        # shader.setUniformValue( helper.vtx_unis[ "u_colour" ], 1.0, 1.0, 1.0 )
        #
        # #self.f.glDrawArrays( GL.GL_POINTS, self.buffers[ "grid.ibo.in" ], self.buffers[ "grid.ibo.idxs" ] )
        #
        # # Done Grid
        # self.buffers[ "grid.vbo" ].release()
        # shader.release()


        # Done with GL
        del( vao_lock )
        self.f.glDisable( GL.GL_DEPTH_TEST )
        painter.endNativePainting()

        # Try drawing some text
        painter.setRenderHint( QtGui.QPainter.TextAntialiasing )
        painter.setPen( QtCore.Qt.white )
        painter.drawText( 10, 10, "Ha Ha I'm using the Internet" )

        painter.end()

    def resizeGL( self, width, height ):
        self.wh = ( width, height )

        self.aspect = float( self.wh[ 0 ] ) / float( self.wh[ 1 ] )
        self.camera.aspect = self.aspect
        self.f.glViewport( 0, 0, self.wh[ 0 ], self.wh[ 1 ] )
    
    
if( __name__ == "__main__" ):
    app = QtWidgets.QApplication( sys.argv )

    mainWindow = OGLWindow()
    mainWindow.resize( mainWindow.sizeHint() )
    mainWindow.show()

    res = app.exec_()
    sys.exit( res )
