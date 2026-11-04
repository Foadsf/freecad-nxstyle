# SPDX-License-Identifier: LGPL-2.1-or-later
"""Self-test of the navigation settings (issue #44), called from smoke.py:

- s_nav_settings: the navigation style nxstyle.json names is the one the graphics window runs
  (NXSTYLE_SMOKE_EXPECT_NAV, else skipped), and a style picked for a view during the session (FreeCAD's status-bar
  menu) is kept instead of being put back.
- s_orbit_style: a real MB2 drag rotates the camera the way FreeCAD's orbit style (Preferences › Display ›
  Navigation › Orbit style) says: Turntable and Free Turntable turn about the world Z axis and keep the horizon level,
  Trackball rolls the view when dragged at the window's edge; with no orbit style set the drag keeps NX's own free
  rotation (the control: the same drag tilts the horizon and does not roll)."""

import os
import traceback

import FreeCAD as App
import FreeCADGui as Gui

from .qt import QtCore, QtWidgets, Qt

ORBIT_PARAM = "OrbitStyle"


def owns_mouse(f, cfg):
    """Does NX-Style's filter take MB2 on this view? (owns_mouse is new with issue #44; before it, the setting alone
    decided.)"""
    from . import prefs
    return f.owns_mouse() if hasattr(f, "owns_mouse") else prefs.uses_own_navigation(cfg)


def _view_and_filter(smoke, name):
    """A fresh document with a box, its 3D view and NX-Style's mouse filter on that view."""
    from .tutorial import qtest
    doc = App.newDocument(name)
    import Part  # noqa: F401
    doc.addObject("Part::Box", "Box")
    doc.recompute()
    qtest().qWait(300)
    view = Gui.ActiveDocument.ActiveView
    view.fitAll()
    f = smoke.nav()
    return doc, view, f


def frame(view):
    """The camera's orientation as an App.Rotation, and its right, up and view vectors in world coordinates."""
    cam = view.getCameraNode()
    q = cam.orientation.getValue().getValue()
    r = App.Rotation(q[0], q[1], q[2], q[3])
    return {"rot": r, "right": r.multVec(App.Vector(1, 0, 0)), "up": r.multVec(App.Vector(0, 1, 0)),
            "dir": r.multVec(App.Vector(0, 0, -1))}


def turn(before, after):
    """The rotation that took the camera from before to after, in world coordinates: (unit axis, degrees in
    [0, 180]), the axis flipped where the angle came back above 180 degrees."""
    import math
    rel = after["rot"].multiply(before["rot"].inverted())
    axis, angle = App.Vector(rel.Axis), rel.Angle % (2 * math.pi)
    if angle > math.pi:
        axis, angle = -axis, 2 * math.pi - angle
    return axis, math.degrees(angle)


def measure(before, after):
    axis, deg = turn(before, after)
    z = App.Vector(0, 0, 1)
    return {"degrees": round(deg, 3),
            "horizon tilt at start": round(abs(before["right"].dot(z)), 5),
            "horizon tilt": round(abs(after["right"].dot(z)), 5),          # 0: the camera's right stays level
            "roll": round(abs(axis.dot(before["dir"])) * deg, 3),           # turn about the view direction
            "about Z": round(axis.dot(z) * deg, 3)}                         # signed turn about world Z


def set_orbit(p, style):
    if style is None:
        p.RemInt(ORBIT_PARAM)
    else:
        p.SetInt(ORBIT_PARAM, style)


def run_nav_settings(smoke):
    """The navigation style nxstyle.json names reaches the graphics window; a style picked for a view in the
    session stays (NX-Style used to put its own back at every scan, 0.8 s later)."""
    from . import config, prefs
    from .tutorial import qtest
    doc = None
    try:
        doc, view, f = _view_and_filter(smoke, "SmokeNavSettings")
        cfg = smoke.shell.cfg
        path = config.user_file()
        nav = view.getNavigationType()
        smoke.info["settings file read"] = {"path": path, "exists": os.path.isfile(path),
                                            "navigation": cfg.get("navigation"), "view": nav,
                                            "NavigationStyle parameter":
                                                App.ParamGet(prefs.VIEW).GetString("NavigationStyle")}
        want = os.environ.get("NXSTYLE_SMOKE_EXPECT_NAV", "")
        if want:
            smoke.check(f"the view runs the navigation style nxstyle.json names ({want})", nav == want,
                        {"view": nav, "nxstyle.json": path, "navigation": cfg.get("navigation")})
            own = prefs.uses_own_navigation(cfg)
            smoke.check("NX-Style's own MB2 handling is on only with \"navigation\": \"nx\"",
                        own == (cfg.get("navigation") == "nx"), {"own": own, "navigation": cfg.get("navigation")})
        else:
            smoke.skip("the view runs the navigation style nxstyle.json names", "NXSTYLE_SMOKE_EXPECT_NAV not set")
        # a style picked in the session (FreeCAD's status-bar menu does view.setNavigationType)
        other = "Gui::TouchpadNavigationStyle" if nav != "Gui::TouchpadNavigationStyle" \
            else "Gui::GestureNavigationStyle"
        view.setNavigationType(other)
        qtest().qWait(2000)                                   # NavigationManager.scan runs every 0.8 s
        kept = view.getNavigationType()
        smoke.shell.navigation.scan()
        smoke.check("a navigation style picked for a view during the session is kept",
                    kept == other and view.getNavigationType() == other,
                    {"picked": other, "after 2 s": kept, "after a scan": view.getNavigationType()})
        if f is not None:
            smoke.check("NX-Style's MB2 handling steps aside while the view runs another style",
                        not owns_mouse(f, cfg), {"view": view.getNavigationType()})
        view.setNavigationType(nav)
        smoke.check("NX-Style's MB2 handling is back with its style",
                    f is None or owns_mouse(f, cfg) == prefs.uses_own_navigation(cfg),
                    {"view": view.getNavigationType()})
    except Exception:
        smoke.check("navigation settings scenario ran", False, traceback.format_exc().splitlines()[-1])
    finally:
        if doc is not None:
            App.closeDocument(doc.Name)


def run_orbit_style(smoke):
    """A real MB2 drag (mouse events into the graphics window) under each orbit style, from FreeCAD's isometric
    view; the orbit style parameter is put back as it was."""
    from . import prefs
    from .tutorial import qtest
    p = App.ParamGet(prefs.VIEW)
    had = p.GetInt(ORBIT_PARAM, -1)
    doc = None
    try:
        doc, view, f = _view_and_filter(smoke, "SmokeOrbit")
        if f is None:
            smoke.check("orbit style scenario: NX-Style's mouse filter on the view", False, "no filter")
            return
        w = f.widget
        smoke.info["orbit test viewport"] = (w.width(), w.height())
        who = "NX-Style's MB2" if prefs.uses_own_navigation(smoke.shell.cfg) else view.getNavigationType()
        p_anim = App.ParamGet(prefs.VIEW)
        animated = p_anim.GetBool("UseNavigationAnimations", True)
        p_anim.SetBool("UseNavigationAnimations", False)
        view.viewIsometric()
        qtest().qWait(200)
        iso = view.getCameraNode().orientation.getValue().getValue()     # FreeCAD's isometric view
        p_anim.SetBool("UseNavigationAnimations", animated)

        def drag(style, dx, dy, start=None):
            set_orbit(p, style)
            QtWidgets.QApplication.processEvents()
            view.getCameraNode().orientation.setValue(*iso)
            QtWidgets.QApplication.processEvents()
            before = frame(view)
            smoke.drag(f, [Qt.MiddleButton], dx, dy, start)
            qtest().qWait(50)
            return measure(before, frame(view))

        edge = QtCore.QPoint(w.width() - 8, w.height() // 2 - 40)
        res = {}
        for label, style in (("none", None), ("Turntable", 0), ("Trackball", 1), ("Free Turntable", 2),
                             ("Trackball Classic", 3), ("Rounded Arcball", 4)):
            res[label] = {"diagonal": drag(style, 60, 25), "horizontal": drag(style, 60, 0),
                          "edge": drag(style, 0, 80, edge)}
        smoke.info[f"orbit styles under {who}"] = res
        none, ft, tt, tb = res["none"], res["Free Turntable"], res["Turntable"], res["Trackball"]
        smoke.check(f"{who}: every orbit style rotates the camera",
                    all(r["diagonal"]["degrees"] > 5 for r in res.values()),
                    {k: r["diagonal"]["degrees"] for k, r in res.items()})
        if prefs.uses_own_navigation(smoke.shell.cfg):
            # the control: NX's own free rotation tilts the horizon and does not roll at the edge
            smoke.check("no orbit style set: NX's own rotation (a diagonal drag tilts the horizon; control)",
                        none["diagonal"]["horizon tilt"] > 0.05 and none["edge"]["roll"] < 0.5, none)
        smoke.check(f"{who}, Free Turntable: a diagonal MB2 drag turns about world Z and keeps the horizon level",
                    ft["diagonal"]["horizon tilt"] < 1e-3 and abs(ft["diagonal"]["about Z"]) > 5, ft["diagonal"])
        smoke.check(f"{who}, Turntable: the horizon stays level too", tt["diagonal"]["horizon tilt"] < 1e-3,
                    tt["diagonal"])
        smoke.check(f"{who}, Trackball: a drag at the window's edge rolls the view",
                    tb["edge"]["roll"] > 2, {"Trackball": tb["edge"], "no orbit style": none["edge"]})
        signs = {k: r["horizontal"]["about Z"] for k, r in res.items()}
        smoke.check(f"{who}: a drag to the right turns the model the same way in every orbit style",
                    all(v > 0 for v in signs.values()) or all(v < 0 for v in signs.values()), signs)
    except Exception:
        smoke.check("orbit style scenario ran", False, traceback.format_exc().splitlines()[-1])
    finally:
        set_orbit(p, None if had < 0 else had)
        if doc is not None:
            App.closeDocument(doc.Name)
