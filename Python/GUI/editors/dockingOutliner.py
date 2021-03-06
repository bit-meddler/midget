"""
Docking Outliner.
This will need more functionality possibly?  Search for nodes?  Filter nodes?

"""

import logging
from PySide2 import QtCore, QtGui, QtWidgets, QtOpenGL

from GUI import getStdIcon

class QDockingOutliner( QtWidgets.QDockWidget ):

    def __init__( self, parent ):
        super( QDockingOutliner, self ).__init__( "Outliner", parent )
        self.setObjectName( "OutlineDockWidget" )
        self.setAllowedAreas( QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea )
        self._buildUI()

    def _expandChildren( self, item ):
        """Todo: make this work with the MVC model"""
        """for i in range( item.childCount() ):
            self._expandChildren( item.child( i ) )
        self.tree.expandItem( item )"""
        return None

    def _buildUI( self ):
        self.tree = QtWidgets.QTreeView()
        self.tree.setHeaderHidden( True )
        self.tree.setSelectionBehavior( QtWidgets.QAbstractItemView.SelectRows )
        self.tree.setSelectionMode( QtWidgets.QAbstractItemView.ExtendedSelection )

        self.setWidget( self.tree )

    def setModels( self, item_model, selection_model ):
        old = self.tree.selectionModel()
        self.tree.setModel( item_model )
        self.tree.setSelectionModel( selection_model )
        del( old )