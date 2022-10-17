import os

import numpy as np

from .base import Representation
from .smurf_reflection import SmurfBase
from .xml_factory import singular as _singular, plural as _plural
from ..geometry.geometry import identical
from ..geometry.io import import_mesh, import_mars_mesh
from ..utils.misc import trunc, execute_shell_command
from ..utils.transform import matrix_to_rpy, round_array, rpy_to_matrix
from ..utils import urdf as urdf_utils, transform

from ..utils.commandline_logging import get_logger
log = get_logger(__name__)

__IMPORTS__ = [x for x in dir() if not x.startswith("__")]


class Pose(Representation, SmurfBase):
    _class_variables = ["xyz", "rpy", "relative_to"]

    def __init__(self, xyz=None, rpy=None, vec=None, extra=None, relative_to=None, **kwargs):
        Representation.__init__(self)
        SmurfBase.__init__(self, returns=["rotation", "position"])
        self.excludes += ["xyz", "rpy"]
        self.xyz = xyz
        self.rotation = rpy
        self.relative_to = relative_to
        if vec is not None:
            assert isinstance(vec, list)
            count = len(vec)
            if count == 3:
                self.xyz = vec
            else:
                self.from_vec(vec)
        elif extra is not None:
            assert xyz is None, "Cannot specify 6-length vector and 3-length vector"  # noqa
            assert len(extra) == 3, "Invalid length"
            self.rpy = extra
        self.rpy = np.array(self.rpy) if self.rpy is not None else None
        self.xyz = np.array(self.xyz) if self.xyz is not None else None

    def check_valid(self):
        assert (self.xyz is None or len(self.xyz) == 3) and \
               (self.rpy is None or len(self.rpy) == 3)

    # Aliases for backwards compatibility
    @property
    def rotation(self):
        return self.rpy

    @rotation.setter
    def rotation(self, value):
        if type(value) == int:
            self.rpy = [0, 0, value]
        elif type(value) in [list, np.ndarray] and len(value) == 3:
            self.rpy = value
        elif type(value) in [list, np.ndarray] and len(value) == 4:
            self.rpy = transform.quaternion_to_rpy(value)
        elif type(value) == dict and len(value) == 3:
            if all([k in "rpy" for k in value.keys()]):
                self.rpy = [value["r"], value["p"], value["y"]]
            elif all([k in "xyz" for k in value.keys()]):
                self.rpy = [value["x"], value["y"], value["z"]]
            else:
                raise ValueError("Can't parse rotation" + str(value))
        elif type(value) == dict and len(value) == 4:
            self.rpy = [value["x"], value["y"], value["z"], value["w"]]
        elif type(value) in [list, np.ndarray]:
            self.rpy = transform.matrix_to_rpy(value)
        elif value is None:
            self.rpy = [0, 0, 0]
        else:
            raise ValueError("Can't parse rotation " + str(value))
        # if we have an pi or pi/2, pi/4 approximation let's make pi or pi/2, pi/4 out of it
        for i in range(3):
            if type(self.rpy[i]) in [float, np.float64, np.float32] and "e" not in str(self.rpy[i]).lower():
                in_decimals = len(str(self.rpy[i]).split(".")[1])
                if in_decimals >= 3:
                    for div in [1, 2, 4]:
                        if str(self.rpy[i]) == f"%.{in_decimals}f" % (np.pi / div) or \
                               self.rpy[i] == np.round(np.pi/div, decimals=in_decimals) or \
                               self.rpy[i] == trunc(np.pi/div, decimals=in_decimals):
                            self.rpy[i] = np.pi / div
        self.rpy = np.array(self.rpy)

    @property
    def position(self):
        return self.xyz

    @position.setter
    def position(self, value):
        assert type(value) in [list, np.ndarray] and len(value) == 3
        self.xyz = np.array(value)

    def from_vec(self, vec):
        assert len(vec) == 6, "Invalid length"
        self.xyz = np.array(vec[:3])
        self.rpy = np.array(vec[3:6])

    @property
    def vec(self):
        xyz = self.xyz if self.xyz is not None else [0, 0, 0]
        rpy = self.rpy if self.rpy is not None else [0, 0, 0]
        return xyz.tolist() + rpy.tolist()

    @staticmethod
    def from_matrix(T, dec=16, relative_to=None):
        xyz = T[0:3, 3]
        rpy = matrix_to_rpy(T[0:3, 0:3])
        return Pose(xyz=xyz, rpy=rpy, dec=dec, relative_to=relative_to)

    def to_matrix(self):
        R = rpy_to_matrix(self.rpy if hasattr(self, "rpy") else [0.0, 0.0, 0.0])
        p = np.array(self.xyz if hasattr(self, "xyz") else [0.0, 0.0, 0.0])
        T = np.identity(4)
        T[0:3, 3] = p
        T[0:3, 0:3] = R
        T[3, 3] = 1.0
        return T

    def transform(self, T):
        """T.dot(this)"""
        return Pose.from_matrix(
            T.dot(self.to_matrix()),
            self.relative_to
        )

    def stringable(self):
        return False


class Color(Representation):
    _class_variables = ["rgba"]

    def __init__(self, *args, rgba=None, **kwargs):
        super().__init__()
        # What about named colors?
        count = len(args)
        if rgba is not None:
            self.rgba = rgba
        elif count == 4 or count == 3:
            self.rgba = args
        elif count == 1:
            self.rgba = args[0]
        elif count == 0:
            self.rgba = None
        if self.rgba is not None:
            if len(self.rgba) == 3 and type(args) is list:
                self.rgba += [1.]
            elif len(self.rgba) == 3 and type(args) is tuple:
                self.rgba += (1.,)
                self.rgba = list(self.rgba)
            if len(self.rgba) != 4:
                raise Exception(f'Invalid color argument count for argument "{self.rgba}"')
        # round everything
        self.rgba = [int(x * 255) / 255 for x in self.rgba]

    def get_hex_color(self):
        return "#" + "".join([hex(int(x * 255))[2:] for x in self.rgba])

    def stringable(self):
        return False


class Texture(Representation):
    filename = None

    def __init__(self, filename=None, **kwargs):
        super().__init__()
        self.filename = filename

    def __str__(self):
        return self.filename


class Material(Representation, SmurfBase):
    _class_variables = ["name", "color", "texture"]

    def __init__(self, name=None, color=None, texture=None, **kwargs):
        if color is None and "diffuseColor" in kwargs:
            color = Color([
                kwargs["diffuseColor"]["r"],
                kwargs["diffuseColor"]["g"],
                kwargs["diffuseColor"]["b"],
                kwargs["diffuseColor"]["a"] if "a" in kwargs["diffuseColor"] else 1.
            ])
        self.color = _singular(color)
        self.texture = _singular(texture)
        self.original_name = name
        if len(name) == 0 or name is None:
            name = self.color.get_hex_color() + (os.path.basename(self.texture.filename) if texture is not None else "")
        self.name = name
        if "diffuseColor" not in kwargs and self.color is not None:
            kwargs["diffuseColor"] = {"r": self.color.rgba[0], "g": self.color.rgba[1], "b": self.color.rgba[2],
                                      "a": self.color.rgba[3]}
        if "diffuseTexture" not in kwargs and self.texture is not None:
            kwargs["diffuseTexture"] = self.texture.filename
        SmurfBase.__init__(self, returns=["name"], **kwargs)
        self.excludes += ["color"]

    def check_valid(self):
        if self.color is None and self.texture is None:
            raise Exception("Material has neither a color nor texture.")

    def equivalent(self, other):
        return other.texture == self.texture and other.color.rgba == self.color.rgba

    def is_delegate(self):
        return self.color is None and self.texture is None


class Box(Representation):
    _class_variables = ["size"]

    def __init__(self, size=None, **kwargs):
        super().__init__()
        self.size = size

    def scale_geometry(self, x=1, y=1, z=1):
        self.size = (v * s for v, s in zip(self.size, [x, y, z]))

    def get_corners(self):

        return [
            np.array([-self.size[0] / 2, -self.size[1] / 2, -self.size[2] / 2]),
            np.array([ self.size[0] / 2, -self.size[1] / 2, -self.size[2] / 2]),
            np.array([-self.size[0] / 2,  self.size[1] / 2, -self.size[2] / 2]),
            np.array([ self.size[0] / 2,  self.size[1] / 2, -self.size[2] / 2]),
            np.array([-self.size[0] / 2, -self.size[1] / 2,  self.size[2] / 2]),
            np.array([ self.size[0] / 2, -self.size[1] / 2,  self.size[2] / 2]),
            np.array([-self.size[0] / 2,  self.size[1] / 2,  self.size[2] / 2]),
            np.array([ self.size[0] / 2,  self.size[1] / 2,  self.size[2] / 2]),
        ]

    def __str__(self):
        return "box"


class Cylinder(Representation):
    _class_variables = ["radius", "length"]

    def __init__(self, radius=0.0, length=0.0, **kwargs):
        super().__init__()
        self.radius = radius
        self.length = length

    def scale_geometry(self, x=1, y=1, z=1):
        assert x == y
        self.radius *= x
        self.length *= z

    def __str__(self):
        return "cylinder"


class Sphere(Representation):
    _class_variables = ["radius"]

    def __init__(self, radius=0.0, **kwargs):
        super().__init__()
        self.radius = radius

    def scale_geometry(self, x=1, y=1, z=1):
        assert x == y == z
        self.radius *= x

    def __str__(self):
        return "sphere"


class Mesh(Representation):
    _class_variables = ["filename", "scale"]

    def __init__(self, filename=None, scale=None, filepath=None, **kwargs):
        if scale is None:
            scale = [1.0, 1.0, 1.0]
        self._filename = None
        super().__init__()
        if filepath:
            self.filename = filepath
        else:
            self.filename = filename
        self.scale = scale

    def __str__(self):
        return self.filename

    def set_unique_name(self, value):
        raise Exception("Can't set unique name of mesh")

    @property
    def filename(self):
        if self._related_robot_instance is None or self._related_robot_instance.xmlfile is None:
            return self._filename
        else:
            return os.path.relpath(self._filename,
                                   os.path.dirname(os.path.abspath(self._related_robot_instance.xmlfile)))

    @filename.setter
    def filename(self, new_val):
        if self._related_robot_instance is None or self._related_robot_instance.xmlfile is None:
            self._filename = new_val
        elif not os.path.isabs(new_val):
            self._filename = urdf_utils.read_urdf_filename(new_val, self._related_robot_instance.xmlfile)
        else:
            self._filename = new_val

    @property
    def filepath(self):
        return self._filename

    @property
    def name(self):
        name, _ = os.path.splitext(os.path.dirname(self._filename))
        return name

    def scale_geometry(self, x=1, y=1, z=1, overwrite=False):
        if overwrite or self.scale is None:
            self.scale = [x, y, z]
        else:
            self.scale = [v * s for v, s in zip(self.scale, [x, y, z])]

    def load_mesh(self, urdf_path=None, mars_mesh=False):
        if mars_mesh:
            return import_mars_mesh(self.filename, urdf_path)
        return import_mesh(self.filename, urdf_path)

    def link_with_robot(self, robot, check_linkage_later=False):
        super(Mesh, self).link_with_robot(robot, check_linkage_later=True)
        assert os.path.isabs(self._filename) or (self._related_robot_instance is not None and self._related_robot_instance.xmlfile is not None)
        self.filename = self._filename
        if not check_linkage_later:
            self.check_linkage()

    def equivalent(self, other):
        return other._filepath == self._filepath or identical(self.load_mesh(), other.load_mesh())


class GeometryFactory(Representation):
    @classmethod
    def create(cls, *args, **kwargs):
        if kwargs["type"] == "mesh":
            return Mesh(**kwargs)
        elif kwargs["type"] == "box":
            return Box(**kwargs)
        elif kwargs["type"] == "cylinder":
            return Cylinder(**kwargs)
        elif kwargs["type"] == "sphere":
            return Sphere(**kwargs)
        raise Exception("Can't create geometry from: "+repr(kwargs))


class Collision(Representation, SmurfBase):
    _class_variables = ["name", "link", "geometry", "origin", "bitmask"]

    def __init__(self, name=None, link=None, geometry=None, origin=None, bitmask=None, noDataPackage=False,
                 reducedDataPackage=False, ccfm=None, **kwargs):
        if type(link) is str:
            link = link
        elif link is not None:
            link = link.name
        self.original_name = name
        if name is None or len(name) == 0:
            if link is not None:
                name = str(link) + "_collision"
            elif "_parent_xml" in kwargs:
                link = kwargs["_parent_xml"].attrib["name"]
                name = link + "_collision"
            else:
                name = None
        SmurfBase.__init__(self, name=name, link=link, returns=['name', 'link'], **kwargs)
        self.geometry = _singular(geometry)
        if origin is None:
            origin = Pose()
        self.origin = _singular(origin)
        assert isinstance(self.origin, Pose)
        self.bitmask = bitmask
        if noDataPackage is not None:
            self.noDataPackage = noDataPackage
        if reducedDataPackage is not None:
            self.reducedDataPackage = reducedDataPackage
        if ccfm is not None:
            self.ccfm = ccfm
        if bitmask is not None:
            self.returns += ['bitmask']


class Visual(Representation, SmurfBase):
    _class_variables = ["name", "geometry", "material", "origin"]

    def __init__(self, geometry=None, material=None, material_: Material = None, origin=None, name=None, **kwargs):
        super().__init__()
        self.original_name = name
        if name is None or len(name) == 0:
            if "_parent_xml" in kwargs:
                link = kwargs["_parent_xml"].attrib["name"]
                name = link + "_collision"
            else:
                name = None
        self.name = name
        self.geometry = _singular(geometry)
        material_ = _singular(material_)
        material = _singular(material)
        if type(material) == str:
            self.material = material
            if material_ is not None:
                assert isinstance(material_, Material) and material_.original_name == material
                self.material = material_
        elif isinstance(material, Material):
            assert material_ is None or material_.equivalent(material)
            self.material = material_
        if origin is None:
            origin = Pose()
        self.origin = _singular(origin)
        assert isinstance(self.origin, Pose)

    @property
    def material_(self):
        return None

    def equivalent(self, other):
        return self.geometry.equivalent(other.geometry) and self._material.equivalent(other._material) and \
               self.origin == other.origin


class Inertia(Representation):
    _class_variables = ['ixx', 'ixy', 'ixz', 'iyy', 'iyz', 'izz']

    def __init__(self, ixx=1e-16, ixy=0.0, ixz=0.0, iyy=1e-16, iyz=0.0, izz=1e-16, **kwargs):
        super().__init__()
        assert type(ixx) != str and ixx is not None
        self.ixx = ixx
        self.ixy = ixy
        self.ixz = ixz
        self.iyy = iyy
        self.iyz = iyz
        self.izz = izz

    def to_matrix(self):
        return [[self.ixx, self.ixy, self.ixz],
                [self.ixy, self.iyy, self.iyz],
                [self.ixz, self.iyz, self.izz]]

    def to_list(self):
        return [self.ixx, self.ixy, self.ixz, self.iyy, self.iyz, self.izz]

    @staticmethod
    def from_mass_matrix(M):
        I = M[3::, 3::]
        inertias = {
            'ixx': I[0, 0],
            'ixy': I[0, 1],
            'ixz': I[0, 2],
            'iyy': I[1, 1],
            'iyz': I[1, 2],
            'izz': I[2, 2]
        }

        return Inertia(**inertias)


class Inertial(Representation):
    _class_variables = ["mass", "inertia", "origin"]

    def __init__(self, mass=0.0, inertia=None, origin=None, **kwargs):
        super().__init__()
        self.mass = mass
        self.inertia = _singular(inertia)
        if origin is None:
            origin = Pose()
        self.origin = _singular(origin)
        assert type(self.origin) == Pose, f"{origin} is not Pose"

    @staticmethod
    def from_mass_matrix(M, origin: Pose):
        return Inertial(
            mass=M[0, 0],
            inertia=Inertia.from_mass_matrix(M),
            origin=origin
        )

    def to_mass_matrix(self):
        m = self.mass

        I = np.array(self.inertia.to_matrix())

        M = np.zeros((6, 6))
        M[0:3, 0:3] = np.eye(3) * m
        M[3::, 3::] = I
        return M


class KCCDHull(Representation, SmurfBase):
    _class_variables = ["link", "points", "radius"]

    def __init__(self, points=None, radius=None, frame=None, **kwargs):
        """

        Args:
            points: relative to the link
            radius:
            **kwargs:
        """
        SmurfBase.__init__(returns=["points", "radius", "frame"], **kwargs)
        self._npoints = len(points)
        self.points = points
        self.radius = radius
        self.frame = frame

    @classmethod
    def from_collision(self, coll, npoints=None, iv_mesh=None, kccd_path=None):
        self.frame = coll.link
        if isinstance(coll.geometry, Sphere):
            self._npoints = 1
            self.radius = coll.geometry.radius
            self.points = [coll.origin.position]
        elif isinstance(coll.geometry, Cylinder):
            self._npoints = 2
            self.radius = coll.geometry.radius
            axis = coll.origin.to_matrix()[0:3, 0:3].dot(np.array([coll.geometry.length, 0, 0]))
            self.points = [coll.origin.position - axis, coll.origin.position+axis]
            self.radius = coll.geometry.radius
        elif isinstance(coll.geometry, Box):
            if npoints == 1:
                self._npoints = 1
                self.points = [coll.origin.position]
                self.radius = 2**0.5 * np.linalg.norm(coll.geometry.size)/2
            elif npoints != 8:
                log.warning(f"Can create kccd hull for a box either as sphere with one point or with eight. "
                            f"You asked for {npoints}, falling back to 8.")
            self._npoints = 8
            self.radius = 0.
            self.points = [coll.origin.to_matrix()[0:3, 0:3].dot(c) for c in coll.geometry.get_corners()]
        elif isinstance(coll.geometry, Mesh):
            assert npoints is not None
            assert iv_mesh is not None and os.path.isfile(iv_mesh)
            assert kccd_path is not None and os.path.isdir(kccd_path)
            self._npoints = npoints
            self.points = []
            log.info(f"Covering {iv_mesh} of {self.frame} with {self._npoints}")
            out, _ = execute_shell_command(f"kccdcoveriv {iv_mesh} {self._npoints} {self.frame}",
                                           cwd=kccd_path, silent=True)
            block_lines = out.split("\n")
            for line in block_lines:
                if line.startswith("BODYRADIUS"):
                    self.radius = float(line.split[-1])
                elif line.startswith("BODYPOINT"):
                    line = line.replace("[", "")
                    line = line.replace(",", "")
                    self.points.append(np.array([float(x) for x in line.split()[-3:]]))


class Link(Representation, SmurfBase):
    _class_variables = ["name", "visuals", "collisions", "inertial", "kccd_hulls"]

    def __init__(self, name=None, visuals=None, inertial=None, collisions=None, origin=None,
                 noDataPackage=False, reducedDataPackage=False, is_human=None, kccd_hulls=None, **kwargs):
        assert origin is None  # Unused but might be neccesary for sdf
        SmurfBase.__init__(self, **kwargs)
        self.name = name
        self.is_human = is_human
        self.returns += ['name', "is_human"]
        self.visuals = []
        if visuals is not None:
            self.visuals = visuals
        self.inertial = _singular(inertial)
        self.collisions = []
        if collisions is not None:
            self.collisions = collisions
        self.kccd_hulls = []
        if kccd_hulls is not None:
            self.kccd_hulls = kccd_hulls
        for geo in self.visuals + self.collisions:
            if geo.origin.relative_to is None:
                geo.origin.relative_to = self.name
        if noDataPackage is not None:
            self.noDataPackage = noDataPackage
            self.returns += ['noDataPackage']
        if reducedDataPackage is not None:
            self.reducedDataPackage = reducedDataPackage
            self.returns += ['reducedDataPackage']
        for geo in self.collisions:
            i = 0
            if geo.name is None:
                geo.name = self.name + "_collision"
                if i > 0:
                    geo.name += str(i)

        for geo in self.visuals:
            i = 0
            if geo.name is None:
                geo.name = self.name + "_visual"
                if i > 0:
                    geo.name += str(i)
        self.excludes += ["inertial"]

    def remove_aggregate(self, elem):
        if isinstance(elem, Visual):
            self.visuals.remove(elem)
        elif isinstance(elem, Collision):
            self.collisions.remove(elem)

    def add_aggregate(self, elem_type, elem):
        if isinstance(elem, Visual) or elem_type.lower() == "visual":
            self.visuals.append(elem)
        elif isinstance(elem, Collision) or elem_type.lower() == "collision":
            self.collisions.append(elem)


class JointDynamics(Representation):
    def __init__(self, damping=None, friction=None, spring_stiffness=None, spring_reference=None):
        super().__init__()
        self.damping = damping
        self.friction = friction
        self.spring_stiffness = spring_stiffness
        self.spring_reference = spring_reference


class JointLimit(Representation):
    _class_variables = ["effort", "velocity", "lower", "upper"]

    def __init__(self, effort=None, velocity=None, lower=None, upper=None, **kwargs):
        super().__init__()
        self.effort = effort
        self.velocity = velocity
        self.lower = lower
        self.upper = upper


class JointMimic(Representation, SmurfBase):
    _class_variables = ["joint", "multiplier", "offset"]

    def __init__(self, joint=None, multiplier=None, offset=None, **kwargs):
        super().__init__()
        self.joint = _singular(joint)
        assert self.joint is not None
        self.multiplier = multiplier
        assert self.multiplier is not None
        self.offset = offset
        assert self.offset is not None

    def equivalent(self, other):
        return other.joint == self.joint

    def __eq__(self, other):
        return other.joint == self.joint and other.offset == self.offset and other.multiplier == self.multiplier

    def stringable(self):
        return False


class Joint(Representation, SmurfBase):
    TYPES = ['unknown', 'revolute', 'continuous', 'prismatic', 'floating', 'planar', 'fixed']

    type_dict = {
        "parent": "links",
        "child": "links",
        "motor": "motors"
    }
    _class_variables = ["name", "parent", "child", "joint_type", "axis", "limit", "dynamics", "motor", "origin",
                        "joint_dependencies"]

    def __init__(self, name=None, parent=None, child=None, joint_type=None,
                 axis=None, origin=None, limit=None,
                 dynamics=None, safety_controller=None, calibration=None,
                 mimic=None, motor=None,
                 noDataPackage=False, reducedDataPackage=False,
                 damping_const_constraint_axis1=None, springDamping=None, springStiffness=None,
                 spring_const_constraint_axis1=None, cut_joint=False, constraint_axes=None, **kwargs):
        SmurfBase.__init__(self, **kwargs)
        self.name = name
        self.returns = ['name']
        self.parent = parent if type(parent) == str else parent.name
        assert self.parent is not None
        self.child = child if type(child) == str else child.name
        assert self.child is not None
        self.joint_type = joint_type if joint_type is not None else (kwargs["type"] if "type" in kwargs else None)
        assert self.joint_type is not None, f"Joint type of {self.name} undefined!"
        self.axis = axis if joint_type != "fixed" else None
        if origin is None:
            origin = Pose(xyz=[0, 0, 0], rpy=[0, 0, 0], relative_to=self.parent)
        self._origin = _singular(origin)
        self.limit = _singular(limit)
        self._joint_dependencies = _plural(mimic)
        self.cut_joint = cut_joint
        self.constraint_axes = constraint_axes if constraint_axes is not None else []
        self.motor = (motor if type(motor) == str else motor.name) if motor is not None else None
        if noDataPackage is not None:
            self.noDataPackage = noDataPackage
            self.returns += ["noDataPackage"]
        if reducedDataPackage is not None:
            self.reducedDataPackage = reducedDataPackage
            self.returns += ["reducedDataPackage"]
        # dynamics
        self.dynamics = _singular(dynamics)
        if damping_const_constraint_axis1 is not None:
            self.damping_const_constraint_axis1 = damping_const_constraint_axis1
            self.returns += ["damping_const_constraint_axis1"]
        if springDamping is not None:
            self.springDamping = springDamping
            self.returns += ["springDamping"]
        if springStiffness is not None:  # todo provide this to JointDynamics
            self.springStiffness = springStiffness
            self.returns += ["springStiffness"]
        if spring_const_constraint_axis1 is not None:  # todo provide this to JointDynamics (spring_reference)
            self.spring_const_constraint_axis1 = spring_const_constraint_axis1
            self.returns += ["spring_const_constraint_axis1"]
        self.excludes += ["limit", "mimic"]

    def check_valid(self):
        return (self.joint_type in self.TYPES, "Invalid joint type: {}".format(self.joint_type) and  # noqa
                (self._related_robot_instance is None or
                 (self._related_robot_instance.get_link(self.parent) is not None and
                  self._related_robot_instance.get_link(self.child) is not None)))

    @property
    def origin(self):
        if self._origin is not None and self._origin.relative_to is None:
            self._origin.relative_to = self.parent
        return self._origin

    @origin.setter
    def origin(self, origin: Pose):
        self._origin = _singular(origin)

    @property
    def mimic(self):
        if self.joint_dependencies is not None and len(self.joint_dependencies)==1:
            return self.joint_dependencies[0]
        else:
            return None

    @mimic.setter
    def mimic(self, value):
        assert value is None or isinstance(value, JointMimic)
        if value is None or (self.joint_dependencies is not None and len(self._joint_dependencies) == 1):
            self._joint_dependencies = []
        elif self._joint_dependencies is not None and len(self._joint_dependencies) == 1:
            self._joint_dependencies[0] = value
        else:
            raise ValueError("Can not set mimic for a joint that depends on mulitple joints. Consider using the joint_dependency setter.")

    @property
    def springStiffness(self):
        return self.dynamics.spring_stiffness if self.dynamics is not None else None

    @springStiffness.setter
    def springStiffness(self, value):
        if self.dynamics is None:
            self.dynamics = JointDynamics(spring_stiffness=value)
        else:
            self.dynamics.spring_stiffness = value

    @property
    def joint_dependencies(self):
        return self._joint_dependencies

    @joint_dependencies.setter
    def joint_dependencies(self, new_val):
        self._joint_dependencies = []
        if len(new_val) <= 1:
            self._joint_dependencies = new_val
            return
        else:
            self._joint_dependencies = []
        for idx, v1 in enumerate(new_val[:-1]):
            skip = False
            for v2 in new_val[idx:]:
                if v1.equivalent(v2) and v1 != v2:
                    log.error(v1.to_yaml())
                    log.error(v2.to_yaml())
                    raise AssertionError("Received conflicting joint dependencies!")
                elif v1 == v2:
                    skip = True
            if not skip:
                self._joint_dependencies.append(v1)
        if self._related_robot_instance is not None:
            for jd in self._joint_dependencies:
                jd.link_with_robot(robot=self._related_robot_instance)


class Interface(Representation, SmurfBase):
    _class_variables = ["name", "origin", "parent"]
    type_dict = {
        "parent": "links"
    }

    def __init__(self, name=None, origin=None, parent=None, type=None, direction=None, **kwargs):
        SmurfBase.__init__(self, **kwargs)
        self.excludes += ["origin"]
        self.returns += ["parent"]
        self.name = name
        self.type = type
        self.direction = direction
        assert self.name is not None
        if origin is None:
            origin = Pose()
        self.origin = _singular(origin)
        self.parent = parent
        assert self.parent is not None


# class PR2Transmission(Representation):
#     def __init__(self, name=None, joint=None, actuator=None, type=None,
#                  mechanicalReduction=1):
#         self.name = name
#         self.type = type
#         self.joint = joint
#         self.actuator = actuator
#         self.mechanicalReduction = mechanicalReduction


class Actuator(Representation):
    _class_variables = ["name", "mechanicalReduction"]

    def __init__(self, name, mechanicalReduction=1, **kwargs):
        super().__init__()
        self.name = name
        self.mechanicalReduction = mechanicalReduction


class TransmissionJoint(Representation):
    _class_variables = ["name", "hardwareInterface"]

    _type_dict = {"name": "joints"}

    def __init__(self, name, hardwareInterfaces=None, **kwargs):
        super().__init__()
        self.name = name
        self.hardwareInterfaces = [] if hardwareInterfaces is None else hardwareInterfaces

    def check_valid(self):
        assert len(self.hardwareInterfaces) > 0, "no hardwareInterface defined"


class Transmission(Representation):
    """ New format: http://wiki.ros.org/urdf/XML/Transmission """
    _class_variables = ["name", "joints", "actuators"]

    def __init__(self, name, joints: TransmissionJoint = None, actuators=None, **kwargs):
        super().__init__()
        self.name = name
        self.joints = [] if joints is None else joints
        self.actuators = [] if actuators is None else actuators

    def check_valid(self):
        assert len(self.joints) > 0, "no joint defined"
        assert len(self.actuators) > 0, "no actuator defined"


class Motor(Representation, SmurfBase):
    _class_variables = ["name", "joint"]

    def __init__(self, name=None, joint=None, **kwargs):
        SmurfBase.__init__(self, name=name, joint=joint, **kwargs)
        # This is hardcoded information
        assert self.joint is not None
        self._maxEffort = None
        self._maxSpeed = None
        self._maxValue = None
        self._minValue = None
        self.returns += ['joint', 'maxEffort', 'maxSpeed', 'maxValue', 'minValue']

    @property
    def maxEffort(self):
        if self._joint:
            return self._joint.limit.effort if self._joint.limit else 0
        else:
            return 0

    @maxEffort.setter
    def maxEffort(self, effort):
        if self._related_robot_instance is None:
            self._maxEffort = effort
        else:
            if type(effort) in [float, int] and effort > 0:
                if self._joint is not None and self._joint.limit:
                    self._joint.limit.effort = effort
                else:
                    self._joint.limit = JointLimit(
                        effort=effort,
                        velocity=self.maxSpeed,
                        lower=self.minValue,
                        upper=self.maxValue
                    )

    @property
    def maxValue(self):
        if self._joint:
            return self._joint.limit.upper if self._joint.limit else 0
        else:
            return 0

    @maxValue.setter
    def maxValue(self, maxval):
        if self._related_robot_instance is None:
            self._maxValue = maxval
        else:
            if type(maxval) in [float, int] and maxval >= self.minValue:
                if self._joint and self._joint.limit:
                    self._joint.limit.upper = maxval
                else:
                    self._joint.limit = JointLimit(
                        effort=self.maxEffort,
                        velocity=self.maxSpeed,
                        lower=self.minValue,
                        upper=maxval
                    )

    @property
    def minValue(self):
        if self._joint:
            return self._joint.limit.lower if self._joint.limit else 0
        else:
            return 0

    @minValue.setter
    def minValue(self, minval):
        if self._related_robot_instance is None:
            self._minValue = minval
        else:
            if type(minval) in [float, int] and minval <= self.maxValue:
                if self._joint and self._joint.limit:
                    self._joint.limit.lower = minval
                else:
                    self._joint.limit = JointLimit(
                        effort=self.maxEffort,
                        velocity=self.maxSpeed,
                        lower=minval,
                        upper=self.maxValue
                    )

    @property
    def maxSpeed(self):
        if self._joint:
            return self._joint.limit.velocity if self._joint.limit else 0
        else:
            return 0

    @maxSpeed.setter
    def maxSpeed(self, speedval):
        if self._related_robot_instance is None:
            self._maxSpeed = speedval
        else:
            if type(speedval) in [float, int] and speedval > 0:
                if self._joint and self._joint.limit:
                    self._joint.limit.velocity = speedval
                else:
                    self._joint.limit = JointLimit(
                        effort=self.maxEffort,
                        velocity=speedval,
                        lower=self.minValue,
                        upper=self.maxValue
                    )

    @property
    def mimic_motor(self):
        if self._joint.mimic is not None:
            return self._joint.mimic.joint

    @mimic_motor.setter
    def mimic_motor(self, val):
        pass

    @property
    def mimic_multiplier(self):
        if self._joint.mimic is not None:
            return self._joint.mimic.multiplier

    @mimic_multiplier.setter
    def mimic_multiplier(self, val):
        pass

    @property
    def mimic_offset(self):
        if self._joint.mimic is not None:
            return self._joint.mimic.offset

    @mimic_offset.setter
    def mimic_offset(self, val):
        pass
