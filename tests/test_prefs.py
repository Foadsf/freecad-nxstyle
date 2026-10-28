# SPDX-License-Identifier: LGPL-2.1-or-later
"""prefs.apply against a stand-in parameter tree (no FreeCAD needed): what it writes at every start."""

import copy
import importlib
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

VIEW = "User parameter:BaseApp/Preferences/View"


class Group:
    """A FreeCAD ParameterGrp: one value per name, the default when it has none."""

    def __init__(self):
        self.values = {}

    def _get(self, name, default=None):
        return self.values.get(name, default)

    def _set(self, name, value):
        self.values[name] = value

    GetBool = GetInt = GetUnsigned = GetString = _get
    SetBool = SetInt = SetUnsigned = SetString = _set


def freecad(tree):
    app = types.ModuleType("FreeCAD")
    app.ParamGet = lambda path: tree.setdefault(path, Group())
    app.Version = lambda: ["1", "1", "4"]
    app.Units = types.SimpleNamespace(listSchemas=lambda i=None: ["Standard (mm, kg, s, °)"] if i is None
                                      else "Standard (mm, kg, s, °)", setSchema=lambda i: None)
    app.Console = types.SimpleNamespace(PrintWarning=lambda s: None)
    return {"FreeCAD": app, "FreeCADGui": types.ModuleType("FreeCADGui")}


class ApplyTests(unittest.TestCase):
    def apply(self, tree):
        with mock.patch.dict(sys.modules, freecad(tree)):
            sys.modules.pop("nxstyle.prefs", None)
            sys.modules.pop("nxstyle.config", None)
            prefs = importlib.import_module("nxstyle.prefs")
            from nxstyle import config
            prefs.apply(copy.deepcopy(config.DEFAULTS))
        sys.modules.pop("nxstyle.prefs", None)
        sys.modules.pop("nxstyle.config", None)

    def test_view_cube_switched_on_in_freecad_stays_on(self):
        # issue #7: the cube came back hidden after every restart
        tree = {VIEW: Group()}
        tree[VIEW].SetBool("ShowNaviCube", True)
        self.apply(tree)
        self.assertIs(tree[VIEW].GetBool("ShowNaviCube", None), True)

    def test_still_applies_nx_view_settings(self):
        tree = {}
        self.apply(tree)
        view = tree[VIEW]
        self.assertIs(view.GetBool("CornerCoordSystem", None), False)     # NXStyle draws the triad lower-left
        self.assertIsNone(view.GetBool("ShowNaviCube", None))             # left to the profile's user.cfg


if __name__ == "__main__":
    unittest.main()
