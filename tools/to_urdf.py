#! /usr/bin/env python

import sys
import xml.etree.ElementTree as ET
from xml.dom import minidom
import re
import numpy
import math

import transformations

def prettify(elem):
    """Return a pretty-printed XML string for the Element.
    """
    rough_string = ET.tostring(elem, 'utf-8')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")


shapexml = "shape.xml"
structurexml = "structure.xml"

robot_name = "hoap3"


shape = ET.parse(shapexml)
struct = ET.parse(structurexml)
root = struct.getroot()

robot = ET.Element("robot", {"name": robot_name})


def getaxis(joint):

    axis = joint.find("Axis")
    if axis is None:
        return None

    axis = axis.text.strip()
    if axis == "EZ":
        return (0, 0, 1)
    if axis == "NEG_EZ":
        return (0, 0, -1)

    if axis == "EX":
        return (1, 0, 0)

    if axis == "NEG_EX":
        return (-1, 0, 0)

    if axis == "EY":
        return (0, 1, 0)

    if axis == "NEG_EY":
        return (0, -1, 0)


def gettype(type):
    if type == "None":
        return "fixed"
    if type == "Revolute":
        return "revolute"

def getpose(pose, parent = None):

    xyz = [float(i) for i in pose.find("Origin").text.split()]

    r = numpy.reshape([float(i) for i in pose.find("Orient").text.split()], (3,3))

    if parent is not None:
        # Rparent->joint = (Rworld->parent)^-1 . Rworld->joint
        r = numpy.dot(numpy.linalg.inv(parent), r)

    #rpy = transformations.euler_from_matrix(rot_mat, 'rzxy')
    # transformation based on: http://planning.cs.uiuc.edu/node103.html
    #yaw = math.atan2(r[1,0], r[0,0])
    #pitch = math.atan2(-r[2,0], math.sqrt(math.pow(r[2,1],2) + math.pow(r[2,2],2)))
    #roll = math.atan2(r[2,1], r[2,2])

    # Based on INtroduction to Robotics, J. Craig, p.43
    # pitch -> beta
    pitch = math.atan2(-r[2,0], math.sqrt(math.pow(r[0,0],2) + math.pow(r[1,0],2)))
    
    if abs(pitch - 1.57079) < 0.001: # pitch = 90deg
        yaw = 0.0
        roll = math.atan2(r[0,1], r[1,1])
    elif abs(pitch + 1.57079) < 0.001: # pitch = -90deg
        yaw = 0.0
        roll = -math.atan2(r[0,1], r[1,1])

    else:
        # yaw -> alpha
        yaw = math.atan2(r[1,0]/math.cos(pitch), r[0,0]/math.cos(pitch))
        # roll -> gamma
        roll = math.atan2(r[2,1]/math.cos(pitch), r[2,2]/math.cos(pitch))
    return xyz, (roll, pitch, yaw), r

def getlimits(joint, offset = 0.0):

    range = joint.find("Range")
    if range is None:
        return None

    lower, upper = [math.radians(float(i)) for i in range.text.strip().split()]

    limit = ET.Element("limit", {"upper": str(upper + offset), "lower": str(lower + offset), "velocity": "100", "effort": "100"})

    return limit

def getlink(name, model):
    for l in model.getroot().iter("Link"):
        if l.text.strip() == name:
            return l


def getinertial(linkname):
    global struct

    link = getlink(linkname, struct)
    if link is None:
        return None

    mass = link.find("Mass")
    if mass is None:
        return None

    xyz = link.find("CenterOfMass")
    if xyz is None:
        xyz = None
 
    xyz = [float(i) for i in xyz.text.strip().split()]


    inertial = ET.Element("intertial")
    mass = ET.SubElement(inertial, "mass", {"value": mass.text.strip()})
    if xyz:
        origin = ET.SubElement(inertial, "origin", {"xyz": "{0} {1} {2}".format(*xyz)})

    return inertial


def getvisual(linkname):
    global shape

    link = getlink(linkname, shape)
    if link is None:
        return None

    gfxshape = link.find("GfxShape")
    if gfxshape is None:
        return None

    gfxshape = gfxshape.find("Shape")
    dae = "package://hoap3_description/meshes/" + gfxshape.text.strip()[:-4] + ".dae"

    xyz, rpy, r = getpose(gfxshape)

    visual = ET.Element("visual")
    
    visu_origin = ET.SubElement(visual, "origin", {"xyz": "{0} {1} {2}".format(*xyz), "rpy": "{0} {1} {2}".format(*rpy)})

    visu_geom = ET.SubElement(visual, "geometry")
    visu_dae = ET.SubElement(visu_geom, "mesh", {"filename": dae})

    return visual


def makelinks(node, urdf_robot):
    for child in node.iter("Link"):
        name = child.text.strip()
        link = ET.SubElement(urdf_robot, "link", {"name": name})

        visual = getvisual(name)
        if visual is not None:
            link.append(visual)

        inertial = getinertial(name)
        if inertial is not None:
            link.append(inertial)
 


def makejoints(node, parent, urdf_robot, print_zeros = False):

    name = node.text.strip()
    offset = [0.0,0.0,0.0]
    abs_orientation = numpy.identity(3)

    joint = node.find('Joint')
    if (joint is not None) and parent:

        xyz, rpy, abs_orientation = getpose(joint.find("BaseFrame"), None) # -> do not apply inverse of parent rotation
        type = gettype(joint.get('type'))
        joint_name = "%s_%s_joint" % (parent["name"], name)
        urdf_joint =  ET.SubElement(urdf_robot, "joint", {"name": joint_name, "type": type})
        urdf_parent = ET.SubElement(urdf_joint, "parent", {"link": parent["name"]})
        urdf_child = ET.SubElement(urdf_joint, "child", {"link": name})

        axis = getaxis(joint)

        if print_zeros:
            zero = joint.find("Zero")
            if zero is not None:
                delta = math.radians(float(zero.text))
                sys.stdout.write("%s: %s," % (joint_name, delta))

        if axis:
            urdf_axis = ET.SubElement(urdf_joint, "axis", {"xyz": "{0} {1} {2}".format(*axis)})

        urdf_limit = getlimits(joint, sum(parent["offset"])) # we can sum the get the delta because only one coordinate is different from zero
        if urdf_limit is not None:
            urdf_joint.append(urdf_limit)

        urdf_origin = ET.SubElement(urdf_joint, "origin", {"xyz": "{0} {1} {2}".format(*xyz), "rpy": "{0} {1} {2}".format(*rpy)})

    children = node.find('Children')
    if children is not None:
        for child in children:
            makejoints(child, {"name":name, "offset": offset, "abs_orientation": abs_orientation}, urdf_robot, print_zeros)

def usage():
    print("""Converts a LASA RobotToolKit robot description to URDF.

The script expects to find 'structure.xml' and 'shape.xml' in the current directory.
Currently, the robots name must be set directly in this script source.

With the option --zeros, it prints out a YAML file with rest values of joints.""")

if __name__ == "__main__":
    if sys.argv[1] in ["-h", "--help"]:
        usage()
        sys.exit(1)
    if sys.argv[1] == "--zeros":
        sys.stdout.write("zeros: {")
        makejoints(root, None, robot, print_zeros = True)
        print("}")

    else:

        makelinks(root, robot)
        makejoints(root, None, robot)

        print(prettify(robot))
