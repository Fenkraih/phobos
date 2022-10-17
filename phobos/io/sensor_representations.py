from xml.etree import ElementTree as ET
import numpy as np

from .base import Representation, Linkable
from .representation import Pose
from .smurf_reflection import SmurfBase
from ..io import representation
from ..utils import transform
from ..utils.commandline_logging import get_logger
log = get_logger(__name__)

__IMPORTS__ = [x for x in dir() if not x.startswith("__")]


class Sensor(Representation, SmurfBase):
    def __init__(self, name: str = None, joint=None, link=None, rate=None, sensortype=None, **kwargs):
        if link is not None:
            if type(link) != str:
                link = link.name
            kwargs["link"] = link
        if joint is not None:
            if type(joint) != str:
                joint = joint.name
            kwargs["joint"] = joint
        SmurfBase.__init__(self, name=name, rate=rate, returns=["type", "rate"], **kwargs)
        self.type = sensortype

    def __str__(self):
        return self.name

    @property
    def position_offset(self):
        if self.origin is None:
            return None
        pos = self.origin.position if hasattr(self, "origin") and self.origin.position is not None else [0, 0, 0]
        return {"x": pos[0], "y": pos[1], "z": pos[2]}

    @position_offset.setter
    def position_offset(self, val):
        if self.origin is None:
            self.origin = representation.Pose()
        self.origin.xyz = [val["x"], val["y"], val["z"]]

    @property
    def orientation_offset(self):
        if self.origin is None:
            return None
        quat = transform.matrix_to_quaternion(self.origin.to_matrix()[0:3, 0:3]) if hasattr(self, "origin") else [0, 0, 0, 1]
        return {"x": quat[0], "y": quat[1], "z": quat[2], "w": quat[3]}

    @orientation_offset.setter
    def orientation_offset(self, val):
        if self.origin is None:
            self.origin = representation.Pose()
        self.origin.rotation = val

    def transform(self, transformation):
        if hasattr(self, "origin"):
            self.origin.transform(transformation)
        else:
            self.origin = Pose.from_matrix(transformation)

    def get_refl_vars(self):
        if hasattr(self, "origin") and self.origin is not None:
            if self.position_offset != {"x": 0, "y": 0, "z": 0}:
                self.returns += ["position_offset"]
            if self.orientation_offset != {"x": 0, "y": 0, "z": 0, "w": 1}:
                self.returns += ["orientation_offset"]
        return super(Sensor, self).get_refl_vars()

    def equivalent(self, other):
        return False

    def merge(self, other):
        raise NotImplementedError


class Joint6DOF(Sensor):
    _class_variables = ["name", "link"]

    def __init__(self, name=None, link=None, **kwargs):
        super().__init__(name=name, joint=None, link=link, sensortype='Joint6DOF', **kwargs)
        self.returns += ['link']
        self.sdf_type = "force_torque"
        self.blender_type = "Joint_6_DOF"


class RotatingRaySensor(Sensor):
    _class_variables = ["name", "link", "bands", "draw_rays", "horizontal_offset", "horizontal_resolution",
                        "opening_width", "lasers", "max_distance", "min_distance", "opening_height", "vertical_offset"]

    def __init__(
            self, name=None, link=None,
            bands=None, draw_rays=False,
            horizontal_offset=0, opening_width=2*np.pi, horizontal_resolution=None,
            lasers=24, max_distance=5.0, min_distance=None, opening_height=2*np.pi,
            vertical_offset=0, **kwargs):
        if "max_horizontal_angle" in kwargs:
            assert "min_horizontal_angle" in kwargs
            kwargs["opening_width"] = kwargs["max_horizontal_angle"] - kwargs["min_horizontal_angle"]
            kwargs.pop("max_horizontal_angle")
        if "max_vertical_angle" in kwargs:
            assert "min_vertical_angle" in kwargs
            kwargs["opening_height"] = kwargs["max_vertical_angle"] - kwargs["min_vertical_angle"]
            kwargs.pop("max_vertical_angle")
        if "vertical_resolution" in kwargs:
            assert lasers is not None
            if opening_height is None and "opening_height" not in kwargs:
                kwargs["opening_height"] = kwargs["vertical_resolution"] * lasers
            kwargs.pop("vertical_resolution")
        super().__init__(name=name, joint=None, link=link, sensortype='RotatingRaySensor', **kwargs)
        self.bands = bands
        self.draw_rays = draw_rays
        self.horizontal_offset = horizontal_offset
        assert self.horizontal_offset is not None
        self.horizontal_resolution = horizontal_resolution
        self.opening_width = opening_width
        assert self.opening_width is not None
        self.lasers = lasers
        assert self.lasers is not None
        self.max_distance = max_distance
        self.min_distance = min_distance
        self.opening_height = opening_height
        assert self.opening_height is not None
        self.vertical_offset = vertical_offset
        assert self.vertical_offset is not None
        self.returns += ['link', 'bands', 'draw_rays',
                         'horizontal_offset', 'horizontal_resolution', 'vertical_offset',
                         'opening_width', 'opening_height', 'max_distance', 'lasers']
        self.sdf_type = "lidar"
        self.blender_type = "Rotating_ray_sensor"

    @property
    def min_horizontal_angle(self):
        return self.horizontal_offset

    @min_horizontal_angle.setter
    def min_horizontal_angle(self, val):
        self.horizontal_offset = val

    @property
    def max_horizontal_angle(self):
        return self.horizontal_offset + self.opening_width

    @property
    def min_vertical_angle(self):
        return self.vertical_offset

    @min_vertical_angle.setter
    def min_vertical_angle(self, val):
        self.vertical_offset = val

    @property
    def max_vertical_angle(self):
        return self.vertical_offset + self.opening_height

    @property
    def vertical_resolution(self):
        return self.opening_height / self.lasers

    def equivalent(self, other):
        return (self.type and other.type and
                self.link and other.link and
                self.bands == other.bands and
                self.draw_rays == other.draw_rays and
                self.horizontal_offset == other.horizontal_offset and
                self.horizontal_resolution == other.horizontal_resolution and
                self.opening_width == other.opening_width and
                self.lasers == other.lasers and
                self.max_distance == other.max_distance and
                self.min_distance == other.min_distance and
                self.opening_height == other.opening_height and
                self.vertical_offset == other.vertical_offset)

    def merge(self, other):
        assert self.equivalent(other)
        # Nothing to do here
        pass


class CameraSensor(Sensor):
    _class_variables = ["name", "link", "height", "width", "hud_height", "hud_width", "opening_height", "opening_width",
                        "depth_image", "show_cam"]

    def __init__(
            self, name=None, link=None,
            height=480, width=640, hud_height=240, hud_width=0,
            opening_height=90, opening_width=90,
            depth_image=True, show_cam=False, frame_offset=1, origin=None, **kwargs):
        super().__init__(name=name, joint=None, link=link, sensortype='CameraSensor', origin=origin if origin is not None else Pose(), **kwargs)
        self.height = height
        self.width = width
        self.hud_height = hud_height
        self.hud_width = hud_width
        self.opening_height = opening_height if opening_height is not None else opening_width * height / width
        self.opening_width = opening_width
        self.depth_image = depth_image
        self.show_cam = show_cam
        self.frame_offset = frame_offset
        self.returns += ['link', 'height', 'width', 'hud_height', 'hud_width',
                         'opening_height', 'opening_width', 'depth_image', 'show_cam', 'frame_offset']
        self.sdf_type = "camera"
        self.blender_type = "Camera"

    @property
    def depths(self):
        return

    def equivalent(self, other):
        return (self.type and other.type and
                self.link and other.link and
                self.height == other.height and
                self.width == other.width and
                self.hud_height == other.hud_height and
                self.hud_width == other.hud_width and
                self.opening_height == other.opening_height and
                self.opening_width == other.opening_width and
                self.depth_image == other.depth_image and
                self.show_cam == other.show_cam and
                self.frame_offset == other.frame_offset)

    def merge(self, other):
        assert self.equivalent(other)
        # Nothing to do here
        pass


class IMU(Sensor):
    _class_variables = ["name", "link", "frame"]

    def __init__(self, name=None, link=None, frame=None, **kwargs):
        super().__init__(name=name, joint=None, link=link, frame=frame, sensortype='NodeIMU', **kwargs)
        self.returns += ['link', 'id']
        self.sdf_type = "imu"
        self.blender_type = "Inertial_measurement_unit"

    @property
    def id(self):
        return [self.frame]

    @id.setter
    def id(self, value):
        if type(value) in [list, set]:
            assert len(value) == 1
            self.frame = value[0]
        elif type(value) == str:
            self.frame = value


NodeIMU = IMU
__IMPORTS__ += ["NodeIMU"]


class MultiSensor(Sensor):
    _class_variables = ["name", "targets"]

    def __init__(self, name=None, targets=None, sensortype='MultiSensor', **kwargs):
        super().__init__(name=name, sensortype=sensortype, **kwargs)
        self.targets = [str(t) for t in targets if t is not None] if isinstance(targets, list) else []
        self.returns += ['id']
        self.excludes += ['_id']

    def add_target(self, target):
        if self.targets is None:
            self.targets = []
        self.targets = self.targets + [target if type(target) == str else str(target)]

    @property
    def id(self):
        return [str(t) for t in self.targets]  # if self._id else None

    @id.setter
    def id(self, targets):
        for t in targets:
            self.add_target(t)
        return

    def remove_target(self, target):
        if type(target) != list:
            target = [target]
        target = [str(t) for t in target]
        self.targets = [t for t in self.targets if str(t) not in target]

    def is_empty(self):
        return len(self.targets) == 0

    def reduce_to_match(self, targets):
        assert type(targets) == list
        _targets = [str(t) for t in targets if t is not None]
        self.targets = [t for t in self.targets if t in _targets]

    def equivalent(self, other):
        return other.type == self.type

    def merge(self, other):
        assert self.equivalent(other)
        self.targets += other.targets


class MotorCurrent(MultiSensor):
    type_dict = {"targets": "joints"}

    def __init__(self, name=None, targets=None, **kwargs):
        if targets is None:
            targets = []
        if not isinstance(targets, list):
            targets = [targets]

        super().__init__(name=name, targets=targets, sensortype='MotorCurrent', **kwargs)
        self.blender_type = "Motor_current"


class JointPosition(MultiSensor):
    type_dict = {"targets": "joints"}

    def __init__(self, name=None, targets=None, **kwargs):
        if targets is None:
            targets = []
        if not isinstance(targets, list):
            targets = [targets]

        super().__init__(name=name, targets=targets, sensortype='JointPosition', **kwargs)
        self.blender_type = "Joint_position"


class JointVelocity(MultiSensor):
    type_dict = {"targets": "joints"}

    def __init__(self, name=None, targets=None, **kwargs):
        if targets is None:
            targets = []
        if not isinstance(targets, list):
            targets = [targets]

        if not all([isinstance(t, representation.Joint) for t in targets]):
            log.error(targets)
            raise AssertionError("Parsed invalid joint")

        super().__init__(name=name, targets=targets, sensortype='JointVelocity', **kwargs)
        self.blender_type = "Joint_velocity"


class NodeContact(MultiSensor):
    _class_variables = ["name", "link", "targets"]
    type_dict = {"targets": "links"}

    def __init__(self, name=None, link=None, targets=None, **kwargs):
        if targets is None:
            targets = []
        if not isinstance(targets, list):
            targets = [targets]

        super().__init__(name=name, targets=targets, link=link, sensortype='NodeContact', **kwargs)

        self.returns += ['link']
        self.sdf_type = "contact"
        self.blender_type = "Contact"

    def equivalent(self, other):
        return other.type == self.type and self.link and other.link


class NodeContactForce(MultiSensor):
    _class_variables = ["name", "link", "targets"]
    type_dict = {"targets": "collisions"}

    def __init__(self, name=None, link=None, targets=None, **kwargs):
        if targets is None:
            targets = []
        if not isinstance(targets, list):
            targets = [targets]

        super().__init__(name=name, targets=targets, link=link, sensortype='NodeContactForce', **kwargs)

        self.returns += ['link']
        self.blender_type = "Node_contact_force"

    def equivalent(self, other):
        return other.type == self.type and self.link and other.link


class NodeCOM(MultiSensor):
    type_dict = {"targets": "links"}

    def __init__(self, name=None, targets=None, **kwargs):
        if targets is None:
            targets = []
        if not isinstance(targets, list):
            targets = [targets]

        super().__init__(name=name, targets=targets, sensortype='NodeCOM', **kwargs)
        self.blender_type = "Node_COM"


class NodePosition(MultiSensor):
    type_dict = {"targets": "links"}

    def __init__(self, name: str = None, targets=None, **kwargs):
        if targets is None:
            targets = []
        if not isinstance(targets, list):
            targets = [targets]

        super().__init__(name=name, targets=targets, sensortype='NodePosition', **kwargs)
        self.blender_type = "Node_position"


class NodeRotation(MultiSensor):
    type_dict = {"targets": "links"}

    def __init__(self, name=None, targets=None, **kwargs):
        if targets is None:
            targets = []
        if not isinstance(targets, list):
            targets = [targets]

        super().__init__(name=name, targets=targets, sensortype='NodeRotation', **kwargs)
        self.blender_type = "Node_rotation"


class SensorFactory(Representation):
    @classmethod
    def create(cls, name, _xml: ET.Element = None, link=None, sdf_type=None, origin=None, **kwargs):
        if sdf_type is None:
            if _xml is not None:
                children = [child.tag for child in _xml]
                if "camera" in children:
                    sdf_type = "camera"
                elif "lidar" in children or "ray" in children:
                    sdf_type = "lidar"
                elif "contact" in children:
                    sdf_type = "contact"
                elif "force_torque" in children:
                    sdf_type = "force_torque"
                elif "imu" in children:
                    sdf_type = "imu"
            elif "bands" in kwargs or "lasers" in kwargs:
                sdf_type = "lidar"
        if link is None and origin is not None:
            link = origin.relative_to
        if origin is None:
            origin = Pose(xyz=[0, 0, 0], rpy=[0, 0, 0], relative_to=link)
        if sdf_type == "camera":
            return CameraSensor(
                name=name,
                link=link,
                **kwargs
            )
        elif sdf_type == "contact":
            return NodeContact(
                name=name,
                **kwargs
            )
        # elif sdf_type == "imu":
        #     raise NotImplemented
        elif sdf_type == "lidar":
            return RotatingRaySensor(
                name=name,
                horizontal_offset=kwargs["min_horizontal_angle"],
                opening_width=kwargs["max_horizontal_angle"] - kwargs["min_horizontal_angle"],
                vertical_offset=kwargs["min_vertical_angle"],
                opening_height=kwargs["max_vertical_angle"] - kwargs["min_vertical_angle"],
                draw_rays="visualize" in kwargs,
                **kwargs
            )
        elif sdf_type == "force_torque":
            return Joint6DOF(
                name=name,
                **kwargs
            )
        raise RuntimeError(f"Couldn't instantiate sensor from {repr(kwargs)}")
