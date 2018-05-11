#!/usr/bin/env python
import sys
import os
import vtk
import numpy as np
import rospy
import rospkg
import cv2
# Which PyQt we use depends on our vtk version. QT4 causes segfaults with vtk > 6
if(int(vtk.vtkVersion.GetVTKVersion()[0]) >= 6):
    from PyQt5.QtWidgets import QWidget, QVBoxLayout, QApplication
    from PyQt5 import uic
    _QT_VERSION = 5
else:
    from PyQt4.QtGui import QWidget, QVBoxLayout, QApplication
    from PyQt4 import uic
    _QT_VERSION = 4
import dvrk_vision.vtktools as vtktools
from sensor_msgs.msg import Image, CameraInfo
from visualization_msgs.msg import Marker
from cv_bridge import CvBridge, CvBridgeError
from tf import transformations
from dvrk_vision.vtk_stereo_viewer import StereoCameras, QVTKStereoViewer
from dvrk_vision.clean_resource_path import cleanResourcePath
from dvrk_vision.vtktools import vtkRosTextureActor

class OverlayWidget(QWidget):
    bridge = CvBridge()
    def __init__(self, camera, texturePath, meshPath, scale=1, masterWidget=None, parent=None):
        super(OverlayWidget, self).__init__()
        uiPath = cleanResourcePath("package://dvrk_vision/src/dvrk_vision/overlay_widget.ui")
        # Get CV image from path
        uic.loadUi(uiPath, self)

        self.meshPath = meshPath
        self.scale = scale
        self.texturePath = texturePath

        self.vtkWidget = QVTKStereoViewer(camera, parent=self)

        self.vtkWidget.renderSetup = self.renderSetup

        # Add vtk widget
        self.vl = QVBoxLayout()
        self.vl.addWidget(self.vtkWidget)
        self.vtkFrame.setLayout(self.vl)

        self.otherWindows = []
        if type(masterWidget) != type(None):
            masterWidget.otherWindows.append(self)
            self.otherWindows.append(masterWidget) 
        
        self.vtkWidget.Initialize()
        self.vtkWidget.start()

    def renderSetup(self):
        # Set up 3D actor for organ
        meshPath = cleanResourcePath(self.meshPath)
        extension = os.path.splitext(meshPath)[1]
        if extension == ".stl" or extension == ".STL":
            meshReader = vtk.vtkSTLReader()
        elif extension == ".obj" or extension == ".OBJ":
            meshReader = vtk.vtkOBJReader()
        else:
            ROS_FATAL("Mesh file has invalid extension (" + extension + ")")
        meshReader.SetFileName(meshPath)
        # Scale STL
        transform = vtk.vtkTransform()
        transform.Scale(self.scale,self.scale,self.scale)
        transformFilter = vtk.vtkTransformFilter()
        transformFilter.SetTransform(transform)
        transformFilter.SetInputConnection(meshReader.GetOutputPort())
        transformFilter.Update()
        color = (0,0,1)
        self.actor_moving = vtkRosTextureActor("stiffness_texture", color = color)
        self.actor_moving.GetProperty().BackfaceCullingOn()
        self._updateActorPolydata(self.actor_moving,
                                  polydata=transformFilter.GetOutput(),
                                  color = color)
        # Set texture to default
        image = cv2.imread(cleanResourcePath(self.texturePath))
        self.actor_moving.setTexture(image)
        self.actor_moving.textureOnOff(True)

        # Hide actor
        self.actor_moving.VisibilityOff()
        # Add actor
        self.vtkWidget.ren.AddActor(self.actor_moving)
        # Setup interactor
        self.iren = self.vtkWidget.GetRenderWindow().GetInteractor()
        self.iren.RemoveObservers('LeftButtonPressEvent')
        self.iren.RemoveObservers('LeftButtonReleaseEvent')
        self.iren.RemoveObservers('MouseMoveEvent')
        self.iren.RemoveObservers('MiddleButtonPressEvent')
        self.iren.RemoveObservers('MiddleButtonPressEvent')

        # Set up subscriber for registered organ position
        poseSubTopic = "registration_marker"
        self.poseSub = rospy.Subscriber(poseSubTopic, Marker, self.poseCallback)

        # Set up QT slider for opacity
        self.opacitySlider.valueChanged.connect(self.sliderChanged) 
        self.textureCheckBox.stateChanged.connect(self.checkBoxChanged)

    def sliderChanged(self):
        self.actor_moving.GetProperty().SetOpacity(self.opacitySlider.value() / 255.0)
        for window in self.otherWindows:
            window.opacitySlider.setValue(self.opacitySlider.value())

    def checkBoxChanged(self):
        self.actor_moving.textureOnOff(self.textureCheckBox.isChecked())
        for window in self.otherWindows:
            window.textureCheckBox.setChecked(self.textureCheckBox.isChecked())

    def poseCallback(self, data):
        pos = data.pose.position
        rot = data.pose.orientation
        mat = transformations.quaternion_matrix([rot.x,rot.y,rot.z,rot.w])
        mat[0:3,3] = [pos.x,pos.y,pos.z]
        transform = vtk.vtkTransform()
        transform.Identity()
        transform.SetMatrix(mat.ravel())
        self.actor_moving.SetUserTransform(transform)
        self.actor_moving.VisibilityOn()             

    def _updateActorPolydata(self,actor,polydata,color=None):
        # Modifies an actor with new polydata
        bounds = polydata.GetBounds()
        # Visualization
        mapper = actor.GetMapper()
        if mapper == None:
            mapper = vtk.vtkPolyDataMapper()
        if vtk.VTK_MAJOR_VERSION <= 5:
            mapper.SetInput(polydata)
        else:
            mapper.SetInputData(polydata)
        actor.SetMapper(mapper)
        if type(color) !=  type(None):
            actor.GetProperty().SetColor(color[0], color[1], color[2])
        else:
            actor.GetProperty().SetColor(1, 0, 0)
        self.sliderChanged()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    rosThread = vtktools.QRosThread()
    rosThread.start()
    meshPath = "package://oct_15_demo/resources/largeProstate.obj"
    texturePath = "package://oct_15_demo/resources/largeProstate.png"
    stlScale = 1.06
    frameRate = 15
    slop = 1.0 / frameRate
    cams = StereoCameras("stereo/left/image_rect",
                         "stereo/right/image_rect",
                         "stereo/left/camera_info",
                         "stereo/right/camera_info",
                         slop = slop)
    windowL = OverlayWidget(cams.camL, texturePath, meshPath, scale=stlScale)
    windowL.show()
    # windowR = OverlayWidget(cams.camR, meshPath, scale=stlScale, masterWidget=windowL)
    sys.exit(app.exec_())
