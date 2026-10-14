# SPDX-License-Identifier: LGPL-2.1-or-later
"""Model references for analysis and PMI: picked faces, edges and vertices, located in space.

A reference is (object, subname) as FreeCAD links store it. A face picked on a PartDesign Body
is kept as the Body's own face (not the face of whichever feature was picked), so it follows the
finished solid when features are added later; FreeCAD 1.1's topological naming keeps it on the
same face when the model changes.
"""

import FreeCAD as App

TOL = 1e-6


def resolve(obj, sub):
    """The referenced shape in global coordinates."""
    shape = obj.getSubObject(sub) if sub else obj.Shape
    if shape is None:
        raise ValueError(f"{obj.Label}: {sub} no longer exists")
    shape = shape.copy()
    try:
        parent = obj.getGlobalPlacement().multiply(obj.Placement.inverse())
        if not parent.isIdentity():
            shape.transformShape(parent.toMatrix())
    except Exception:
        pass
    return shape


def element_name(sub):
    return sub.split(".")[-1] if sub else ""


def same_face(a, b):
    try:
        return (a.Surface.__class__ is b.Surface.__class__ and abs(a.Area - b.Area) < 1e-6 * max(1.0, a.Area)
                and a.CenterOfMass.distanceToPoint(b.CenterOfMass) < 1e-6)
    except Exception:
        return False


def stable(sel_obj, subname):
    """(object, subname) to store for a pick: a face of a Body (or of a feature inside one) becomes
    the Body's face; anything else stays as picked."""
    body = None
    if sel_obj.isDerivedFrom("PartDesign::Body"):
        body = sel_obj
    elif hasattr(sel_obj, "getParentGeoFeatureGroup"):
        g = sel_obj.getParentGeoFeatureGroup()
        if g is not None and g.isDerivedFrom("PartDesign::Body"):
            body = g
    if body is None:
        return sel_obj, subname
    leaf = element_name(subname)
    picked = sel_obj.getSubObject(subname) if subname else None
    try:
        mine = body.Shape.getElement(leaf)
    except Exception:
        mine = None
    if picked is None or mine is None or leaf[:4] != "Face" or same_face(mine, picked):
        return body, leaf
    for i, f in enumerate(body.Shape.Faces):          # the feature's face is a different one of the Body's
        if same_face(f, picked):
            return body, f"Face{i + 1}"
    return body, leaf


def selection_refs():
    """Stable references of the current selection, in pick order."""
    import FreeCADGui as Gui
    out = []
    for s in Gui.Selection.getSelectionEx("", 0):
        for sub in s.SubElementNames or [""]:
            obj, name = s.Object, sub
            # a path through containers (Body.Pad.Face3, Assembly.Link.Face1): resolve to the leaf owner
            if "." in sub:
                leaf_owner = s.Object.getSubObject(sub, 1)
                if leaf_owner is not None and leaf_owner.isDerivedFrom("PartDesign::Feature"):
                    obj, name = leaf_owner, element_name(sub)
            out.append(stable(obj, name))
    return out


def describe(obj, sub):
    return f"{obj.Label}:{element_name(sub)}" if sub else obj.Label


# ------------------------------------------------------------------ geometry
def surface_kind(shape):
    t = shape.ShapeType
    if t == "Face":
        name = shape.Surface.__class__.__name__
        return {"Plane": "plane", "Cylinder": "cylinder"}.get(name, name.lower())
    if t == "Edge":
        name = shape.Curve.__class__.__name__
        return {"Line": "line", "Circle": "circle"}.get(name, name.lower())
    if t == "Vertex":
        return "vertex"
    return t.lower()


def plane_normal(face):
    """Outward unit normal of a planar face (the side away from the material)."""
    u0, u1, v0, v1 = face.ParameterRange
    n = face.normalAt((u0 + u1) / 2, (v0 + v1) / 2)
    return n.normalize()


def cylinder_axis(shape):
    """(point on the axis, unit direction) of a cylindrical face or a circular edge."""
    if shape.ShapeType == "Face":
        s = shape.Surface
        return App.Vector(s.Center), App.Vector(s.Axis).normalize()
    c = shape.Curve
    return App.Vector(c.Center), App.Vector(c.Axis).normalize()


def feature_type(shape):
    """'plane', 'hole' (internal cylinder), 'pin' (external cylinder) or 'other'."""
    k = surface_kind(shape)
    if k == "plane":
        return "plane"
    if k == "cylinder":
        u0, u1, v0, v1 = shape.ParameterRange
        u, v = (u0 + u1) / 2, (v0 + v1) / 2
        p, n = shape.valueAt(u, v), shape.normalAt(u, v)
        c, d = cylinder_axis(shape)
        radial = (p - c) - d * ((p - c).dot(d))
        return "hole" if radial.dot(n) < 0 else "pin"
    return "other"


def anchor(shape):
    """A point on the referenced geometry to attach an annotation or a dimension line to."""
    k = surface_kind(shape)
    if k == "vertex":
        return App.Vector(shape.Point)
    if shape.ShapeType == "Face":
        u0, u1, v0, v1 = shape.ParameterRange
        p = shape.valueAt((u0 + u1) / 2, (v0 + v1) / 2)
        if k == "plane":
            q = shape.CenterOfMass
            if shape.isInside(q, 1e-6, True):
                return q
            # a ring (a shoulder) has its centre of mass in the hole: take the face's own point nearest to it,
            # a triangle centre of the face's mesh, so the point is on the face and away from its edges
            try:
                pts, tris = shape.tessellate(max(shape.BoundBox.DiagonalLength / 50.0, 0.05))
                cents = [(pts[i] + pts[j] + pts[k_]) * (1.0 / 3.0) for i, j, k_ in tris]
                if cents:
                    return min(cents, key=lambda c: (c - q).Length)
            except Exception:
                pass
            return p if shape.isInside(p, 1e-6, True) else shape.Vertexes[0].Point
        return p
    return shape.valueAt((shape.FirstParameter + shape.LastParameter) / 2)


def locate(shape, axis):
    """Position of the referenced feature along the unit vector axis. A plane must be square to
    the axis, a cylinder or circle's axis across it; otherwise its position along the axis is not
    one number and ValueError says why."""
    k = surface_kind(shape)
    if k == "plane":
        n = plane_normal(shape)
        if abs(abs(n.dot(axis)) - 1.0) > 1e-6:
            raise ValueError("the face is not square to the stack direction")
        return shape.CenterOfMass.dot(axis)
    if k in ("cylinder", "circle"):
        c, d = cylinder_axis(shape)
        if abs(d.dot(axis)) > 1e-6:
            raise ValueError("the cylinder's axis is not across the stack direction")
        return c.dot(axis)
    if k == "vertex":
        return shape.Point.dot(axis)
    if k == "line":
        d = shape.Curve.Direction
        if abs(App.Vector(d).normalize().dot(axis)) > 1e-6:
            raise ValueError("the edge is not across the stack direction")
        return shape.Vertexes[0].Point.dot(axis)
    raise ValueError(f"a {k} has no single position along a direction")


def default_axis(a, b):
    """Stack direction for a first dimension from a to b: the outward normal of a planar a (it points
    across the gap a bounds), else the direction from a to b."""
    if surface_kind(a) == "plane":
        return plane_normal(a)
    if surface_kind(b) == "plane":
        n = plane_normal(b)
        return n * -1
    d = anchor(b) - anchor(a)
    if d.Length < TOL:
        raise ValueError("the two picks are at the same place")
    return d.normalize()


def signed_distance(a, b, axis):
    return locate(b, axis) - locate(a, axis)
