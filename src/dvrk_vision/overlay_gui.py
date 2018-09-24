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

class vtkRosTextureActor(vtk.vtkActor):
    ''' Attaches texture to the actor. Texture is received by subscribing to a ROS topic and then converted to vtk image
        Input: vtk.Actor
        Output: Updates the input actor with the texture
    '''

    def __init__(self,topic, color = (1,0,0)):
        self.bridge = CvBridge()
        self.vtkImage = None

        #Subscriber
        sub = rospy.Subscriber(topic, Image, self.imageCB, queue_size=1)
        self.texture = vtk.vtkTexture()
        self.texture.EdgeClampOff()
        self.color = color
        self.textureOnOff(False)

    #Subscriber callback function
    def imageCB(self, msg):
        try:
            # Convert your ROS Image message to OpenCV2
            cv2_img = self.bridge.imgmsg_to_cv2(msg, "bgr8")
        except CvBridgeError, e:
            print(e)
        else:
            self.setTexture(cv2_img)

    def setTexture(self, img):
        if type(self.vtkImage) == type(None):
            self.vtkImage = vtktools.makeVtkImage(img.shape)
        vtktools.numpyToVtkImage(img, self.vtkImage)
        if vtk.VTK_MAJOR_VERSION <= 5:
            self.texture.SetInput(self.vtkImage)
        else:
            self.texture.SetInputData(self.vtkImage)

    def textureOnOff(self, data):
        if data:
            self.SetTexture(self.texture)
            self.GetProperty().SetColor(1, 1, 1)
            self.GetProperty().LightingOff()
        else:
            self.SetTexture(None)
            self.GetProperty().SetColor(self.color)
            self.GetProperty().LightingOn()

class OverlayWidget(QWidget):
    bridge = CvBridge()
    def __init__(self, camera, texturePath=None, meshPath=None, scale=1, masterWidget=None, parent=None):
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

        self.masterWidget = masterWidget
        self.otherWindows = []
        if type(self.masterWidget) != type(None):
            self.masterWidget.otherWindows.append(self)
            self.otherWindows.append(self.masterWidget) 
        
        self.vtkWidget.Initialize()
        self.vtkWidget.start()

    def setMeshPath(self, meshPath, scale):
        self.meshPath = meshPath
        self.scale = scale
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
        transform.Scale(scale, scale, scale)
        transformFilter = vtk.vtkTransformFilter()
        transformFilter.SetTransform(transform)
        transformFilter.SetInputConnection(meshReader.GetOutputPort())
        transformFilter.Update()
        color = (0,0,1)
        self._updateActorPolydata(self.actor_moving,
                                  polydata=transformFilter.GetOutput(),
                                  color = color)
        if image is not None:
            # Set texture to default
            image = cv2.imread(cleanResourcePath(self.texturePath))
            self.actor_moving.setTexture(image)
            self.actor_moving.textureOnOff(True)



    def renderSetup(self):
        if type(self.masterWidget) != type(None):
            self.actor_moving = self.masterWidget.actor_moving

        else:
            color = (0,0,1)
            self.actor_moving = vtkRosTextureActor("stiffness_texture", color = color)
            self.actor_moving.GetProperty().BackfaceCullingOn()
            if self.meshPath is not None:
                self.setMeshPath(self.meshPath, self.scale)
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
        transform.SetMatrix(mat.ravel())
        self.actor_moving.SetPosition(transform.GetPosition())
        self.actor_moving.SetOrientation(transform.GetOrientation())
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
