# SPDX-License-Identifier: LGPL-2.1-or-later
"""Real Qt keyboard selection interactions, with only FreeCAD services replaced."""
import importlib
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6 import QtCore, QtGui, QtWidgets, QtTest
except ImportError:
    if os.environ.get("NXSTYLE_REQUIRE_QT") == "1":
        raise
    QtCore = None

PACKAGE = Path(__file__).resolve().parents[1] / "NXStyle" / "nxstyle"


class Shape:
    def __init__(self, null=False, valid=True, count=4):
        self.null, self.valid, self.version = null, valid, 1
        point = types.SimpleNamespace(x=1.5, y=2, z=3)
        self.Faces = [types.SimpleNamespace(Area=12 + i, CenterOfMass=point) for i in range(count)]
        self.Edges = [types.SimpleNamespace(Length=5 + i) for i in range(count)]
        self.Vertexes = [types.SimpleNamespace(Point=point) for _ in range(count)]
        self.Solids = [self]

    def isNull(self):
        return self.null

    def isValid(self):
        return self.valid

    def hashCode(self):
        return self.version


class Object:
    def __init__(self, name="Box", label="Block", shape=None, visible=True, selectable=True, parent=None):
        self.Name, self.Label = name, label
        self.Shape = shape if shape is not None else Shape()
        self.TypeId = "Part::Feature"
        self.ViewObject = types.SimpleNamespace(Visibility=visible, Selectable=selectable)
        self.parent = parent
        self.Placement = "identity"

    def isDerivedFrom(self, name):
        return name == self.TypeId

    def getParentGeoFeatureGroup(self):
        return self.parent

    def getSubObject(self, name, _resolve):
        return self


class Document:
    Name = "KeyboardTest"

    def __init__(self, objects):
        self.Objects = objects

    def getObject(self, name):
        return next((obj for obj in self.Objects if obj.Name == name), None)


class Selection:
    def __init__(self):
        self.keys, self.added, self.removed = set(), [], []
        self.reject = lambda key: False

    def addSelection(self, *key):
        self.added.append(key)
        if not self.reject(key):
            self.keys.add(key)

    def removeSelection(self, *key):
        self.removed.append(key)
        if key[2]:
            self.keys.discard(key)
        else:
            self.keys = {item for item in self.keys if item[:2] != key[:2]}

    def getSelectionEx(self, *_):
        return [types.SimpleNamespace(DocumentName=doc, ObjectName=obj, SubElementNames=[sub] if sub else [])
                for doc, obj, sub in self.keys]


@unittest.skipIf(QtCore is None, "PySide6 required for real keyboard interaction checks")
class KeyboardSelectionQt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        cls.old_font = cls.app.font()
        cls.font_id = -1
        if not QtGui.QFontDatabase.families() and os.environ.get("WINDIR"):
            cls.font_id = QtGui.QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / "segoeui.ttf"))
            families = QtGui.QFontDatabase.applicationFontFamilies(cls.font_id)
            if families:
                cls.app.setFont(QtGui.QFont(families[0], 10))
        cls.package_name = "_nxstyle_keyboard_selection_qt"
        package = types.ModuleType(cls.package_name)
        package.__path__ = [str(PACKAGE)]
        wrapper = types.ModuleType("PySide")
        wrapper.QtCore, wrapper.QtGui, wrapper.QtWidgets = QtCore, QtGui, QtWidgets
        cls.freecad, cls.gui = types.ModuleType("FreeCAD"), types.ModuleType("FreeCADGui")
        cls.host = patch.dict(sys.modules, {cls.package_name: package, "PySide": wrapper,
                                          "FreeCAD": cls.freecad, "FreeCADGui": cls.gui})
        cls.host.start()
        cls.module = importlib.import_module(cls.package_name + ".keyboard_selection")
        cls.sf = importlib.import_module(cls.package_name + ".selection_filter")

    @classmethod
    def tearDownClass(cls):
        cls.app.setFont(cls.old_font)
        if cls.font_id >= 0:
            QtGui.QFontDatabase.removeApplicationFont(cls.font_id)
        cls.host.stop()
        for name in list(sys.modules):
            if name.startswith(cls.package_name + "."):
                del sys.modules[name]

    def setUp(self):
        self.box = Object()
        self.other = Object("Cylinder", "Round post")
        self.doc = Document([self.box, self.other])
        self.freecad.ActiveDocument = self.doc
        self.freecad.getDocument = lambda name: self.doc if name == self.doc.Name else None
        self.selection = Selection()
        self.selection.keys.add((self.doc.Name, "Cylinder", ""))
        self.gui.Selection = self.selection
        self.gui.Control = types.SimpleNamespace(activeDialog=lambda: None)
        self.sf._manager = None
        self.dialog = self.module.GeometrySelectionDialog()
        self.dialog.show()
        self.dialog.activateWindow()
        self.dialog.search.setFocus()
        self.app.processEvents()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()
        QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)

    def kind(self, kind):
        self.dialog.kind.setCurrentText(kind)
        self.app.processEvents()

    def key(self, widget, key, modifiers=QtCore.Qt.NoModifier):
        QtTest.QTest.keyClick(widget, key, modifiers)
        self.app.processEvents()

    def test_keyboard_search_tab_type_and_enter_select_exact_face(self):
        QtTest.QTest.keyClicks(self.dialog.search, "box")  # internal name, not label
        self.assertEqual(self.dialog.objects.currentItem().text(), "Block [Box]")
        self.key(self.dialog.search, QtCore.Qt.Key_Tab)
        self.assertIs(self.app.focusWidget(), self.dialog.objects)
        self.key(self.dialog.objects, QtCore.Qt.Key_Tab)
        self.assertIs(self.app.focusWidget(), self.dialog.kind)
        self.key(self.dialog.kind, QtCore.Qt.Key_Down)
        self.assertEqual(self.dialog.kind.currentText(), "Face")
        self.key(self.dialog.kind, QtCore.Qt.Key_Tab)
        self.assertIs(self.app.focusWidget(), self.dialog.elements)
        self.key(self.dialog.elements, QtCore.Qt.Key_Down)
        self.assertIn("Face2 - area 13", self.dialog.elements.currentItem().text())
        self.key(self.dialog.elements, QtCore.Qt.Key_Return)
        self.assertEqual(self.selection.keys, {(self.doc.Name, "Box", "Face2")})
        self.assertEqual(self.selection.added, [(self.doc.Name, "Box", "Face2")])
        self.assertIn("Selected 1", self.dialog.status.text())

    def test_mnemonics_focus_buddies(self):
        for letter, target in (("o", self.dialog.objects), ("t", self.dialog.kind),
                               ("g", self.dialog.elements), ("f", self.dialog.search)):
            self.key(self.dialog, getattr(QtCore.Qt, "Key_" + letter.upper()), QtCore.Qt.AltModifier)
            self.assertIs(self.app.focusWidget(), target)

    def test_local_mnemonic_wins_over_conflicting_host_action(self):
        from PySide6 import QtGui
        action = QtGui.QAction("Host Tools", self.dialog)
        action.setShortcut(QtGui.QKeySequence("Alt+T"))
        self.dialog.addAction(action)
        calls = []
        action.triggered.connect(lambda: calls.append(True))
        self.dialog.search.setFocus()
        self.key(self.dialog.search, QtCore.Qt.Key_T, QtCore.Qt.AltModifier)
        self.assertIs(self.app.focusWidget(), self.dialog.kind)
        self.assertEqual(calls, [])

    def test_space_toggle_ctrl_and_shift_allow_multiple_edges(self):
        self.kind("Edge")
        widget = self.dialog.elements
        widget.setFocus()
        self.key(widget, QtCore.Qt.Key_Space)  # deselect first row
        self.assertEqual(len(widget.selectedItems()), 0)
        self.key(widget, QtCore.Qt.Key_Space)  # select it again
        self.key(widget, QtCore.Qt.Key_Down, QtCore.Qt.ControlModifier)
        self.key(widget, QtCore.Qt.Key_Space, QtCore.Qt.ControlModifier)
        self.key(widget, QtCore.Qt.Key_Down, QtCore.Qt.ShiftModifier)
        self.key(widget, QtCore.Qt.Key_Return)
        self.assertEqual(self.selection.keys, {(self.doc.Name, "Box", "Edge1"),
                                              (self.doc.Name, "Box", "Edge2"),
                                              (self.doc.Name, "Box", "Edge3")})

    def test_all_types_have_topological_names_and_useful_units(self):
        for kind, expected in (("Object", "4 faces; 4 edges; 4 vertices"),
                               ("Face", "area 12 mm²; centre (1.5, 2, 3) mm"),
                               ("Edge", "length 5 mm"), ("Vertex", "XYZ (1.5, 2, 3) mm")):
            self.kind(kind)
            text = self.dialog.elements.item(0).text()
            self.assertIn(expected, text)
            self.assertTrue(text.startswith("Box" if kind == "Object" else kind + "1"))

    def test_escape_and_search_do_not_change_previous_selection(self):
        before = set(self.selection.keys)
        QtTest.QTest.keyClicks(self.dialog.search, "round")
        self.assertEqual(self.dialog.objects.currentItem().data(self.module.ROLE), self.other)
        self.key(self.dialog.search, QtCore.Qt.Key_Escape)
        self.assertFalse(self.dialog.isVisible())
        self.assertEqual(self.selection.keys, before)
        self.assertEqual(self.selection.added, [])

    def test_type_filter_rejects_before_native_mutation(self):
        self.sf.manager().global_kind = "edge"
        self.kind("Face")
        self.assertFalse(self.dialog.apply_selection())
        self.assertIn("Type Filter is Edge", self.dialog.status.text())
        self.assertEqual(self.selection.added, [])
        self.assertEqual(self.selection.keys, {(self.doc.Name, "Cylinder", "")})

    def test_scope_rejects_outside_work_part(self):
        self.sf.manager().scope = "work_part_only"
        with patch.object(self.sf, "work_part", return_value=("OtherPart",)):
            self.assertFalse(self.dialog.apply_selection())
        self.assertIn("outside the work part", self.dialog.status.text())
        self.assertEqual(self.selection.added, [])

    def test_native_gate_rejection_rolls_back_new_items_without_clearing_old(self):
        self.kind("Edge")
        self.dialog.elements.item(1).setSelected(True)
        self.selection.reject = lambda key: key[2] == "Edge2"
        self.assertFalse(self.dialog.apply_selection())
        self.assertIn("native selection gate", self.dialog.status.text())
        self.assertEqual(self.selection.keys, {(self.doc.Name, "Cylinder", "")})
        self.assertEqual(self.selection.removed, [(self.doc.Name, "Box", "Edge1")])

    def test_replacing_same_whole_object_with_faces_readds_after_object_removal(self):
        self.selection.keys = {(self.doc.Name, "Box", "")}
        self.kind("Face")
        self.dialog.elements.item(1).setSelected(True)
        self.assertTrue(self.dialog.apply_selection())
        self.assertEqual(self.selection.keys, {(self.doc.Name, "Box", "Face1"), (self.doc.Name, "Box", "Face2")})
        self.assertEqual(self.selection.removed, [(self.doc.Name, "Box", "")])

    def test_keyboard_add_mode_builds_native_selection_across_objects(self):
        self.key(self.dialog, QtCore.Qt.Key_A, QtCore.Qt.AltModifier)
        QtTest.QTest.qWait(150)  # mnemonic button activation uses Qt's animateClick timer
        self.assertTrue(self.dialog.add_to_selection.isChecked())
        self.key(self.dialog.elements, QtCore.Qt.Key_Return)
        self.assertEqual(self.selection.keys, {(self.doc.Name, "Cylinder", ""), (self.doc.Name, "Box", "")})
        self.assertEqual(self.selection.removed, [])

    def test_rejected_readdition_restores_previous_selection_and_reports_failure(self):
        self.selection.keys = {(self.doc.Name, "Box", "")}
        self.kind("Face")
        self.selection.reject = lambda key: key[2] == "Face1" and len(self.selection.added) > 1
        self.assertFalse(self.dialog.apply_selection())
        self.assertEqual(self.selection.keys, {(self.doc.Name, "Box", "")})
        self.assertIn("Cannot select", self.dialog.status.text())

    def test_collector_preserves_prior_picks_and_applies_actual_task_gate(self):
        manager = self.sf.manager()
        manager.tasks = [(1, self.sf.Layer("Faces only", kinds=("face",)))]
        self.kind("Edge")
        self.assertFalse(self.dialog.apply_selection())
        self.assertIn("takes a face", self.dialog.status.text())
        self.kind("Face")
        self.assertTrue(self.dialog.apply_selection())
        self.assertEqual(self.selection.keys, {(self.doc.Name, "Cylinder", ""), (self.doc.Name, "Box", "Face1")})

    def test_collector_policy_is_rechecked_between_multiple_picks(self):
        manager = self.sf.manager()
        manager.tasks = [(1, self.sf.Layer("One pick", verdict=lambda pick:
            (not self.selection.added, "collector takes at most one")))]
        self.kind("Edge")
        self.dialog.elements.item(1).setSelected(True)
        self.assertFalse(self.dialog.apply_selection())
        self.assertIn("at most one", self.dialog.status.text())
        self.assertEqual(self.selection.added, [(self.doc.Name, "Box", "Edge1")])
        self.assertEqual(self.selection.keys, {(self.doc.Name, "Cylinder", "")})

    def test_nested_object_address_preserves_scope_and_hidden_ancestor_is_excluded(self):
        part = Object("Part", "Assembly")
        part.TypeId = "App::Part"
        self.box.parent = part
        self.doc.Objects.append(part)
        self.dialog.refresh()
        self.kind("Face")
        self.sf.manager().scope = "work_part_and_components"
        with patch.object(self.sf, "work_part", return_value=("Part",)):
            self.assertTrue(self.dialog.apply_selection())
        self.assertEqual(self.selection.keys, {(self.doc.Name, "Part", "Box.Face1")})
        part.ViewObject.Visibility = False
        self.dialog.refresh()
        self.assertEqual(self.dialog.objects.count(), 1)
        self.assertIn("Round post", self.dialog.objects.item(0).text())

    def test_stale_geometry_rejected_until_explicit_refresh(self):
        self.kind("Face")
        self.box.Shape.version += 1
        self.assertFalse(self.dialog.apply_selection())
        self.assertIn("Geometry or containment changed", self.dialog.status.text())
        self.assertEqual(self.selection.added, [])
        self.dialog.refresh()
        self.assertTrue(self.dialog.apply_selection())

    def test_removed_replaced_hidden_null_and_document_closed_cannot_select(self):
        cases = (lambda: setattr(self.box.ViewObject, "Visibility", False),
                 lambda: setattr(self.box.ViewObject, "Selectable", False),
                 lambda: setattr(self.box.Shape, "null", True),
                 lambda: setattr(self.box.Shape, "valid", False),
                 lambda: setattr(self.freecad, "ActiveDocument", None),
                 lambda: setattr(self.doc, "Objects", [Object(), self.other]))
        for mutate in cases:
            with self.subTest(mutate=mutate):
                self.box.ViewObject.Visibility = self.box.ViewObject.Selectable = True
                self.box.Shape.null, self.box.Shape.valid = False, True
                self.freecad.ActiveDocument = self.doc
                self.doc.Objects = [self.box, self.other]
                self.dialog.refresh()
                mutate()
                self.assertFalse(self.dialog.apply_selection())
                self.assertEqual(self.selection.added, [])
                self.assertEqual(self.selection.keys, {(self.doc.Name, "Cylinder", "")})

    def test_refresh_excludes_unsupported_models_and_search_has_empty_control(self):
        self.doc.Objects.extend([Object("Hidden", visible=False), Object("Locked", selectable=False),
                                 Object("Null", shape=Shape(null=True)), Object("Invalid", shape=Shape(valid=False))])
        unsupported = Object("Mesh")
        del unsupported.Shape
        self.doc.Objects.append(unsupported)
        self.dialog.refresh()
        self.assertEqual(self.dialog.objects.count(), 2)
        self.assertIn("5 excluded", self.dialog.status.text())
        self.assertIn("Meshes, datums", self.dialog.status.text())
        self.dialog.search.setText("does-not-exist")
        self.assertEqual(self.dialog.elements.count(), 0)
        self.assertFalse(self.dialog.select_button.isEnabled())
        self.assertFalse(self.dialog.apply_selection())
        self.dialog.search.setText("block")
        self.assertGreater(self.dialog.elements.count(), 0)

    def test_paging_bounds_geometry_rows_and_keeps_native_indices(self):
        self.box.Shape = Shape(count=405)
        self.dialog.refresh()
        self.kind("Vertex")
        self.assertEqual(self.dialog.elements.count(), 200)
        self.assertFalse(self.dialog.previous.isEnabled())
        self.key(self.dialog.next, QtCore.Qt.Key_Space)
        self.assertEqual(self.dialog.elements.item(0).data(self.module.ROLE), "Vertex201")
        self.key(self.dialog.next, QtCore.Qt.Key_Space)
        self.assertEqual(self.dialog.elements.count(), 5)
        self.assertEqual(self.dialog.elements.item(0).data(self.module.ROLE), "Vertex401")
        self.assertFalse(self.dialog.next.isEnabled())
        self.assertTrue(self.dialog.apply_selection())
        self.assertEqual(self.selection.keys, {(self.doc.Name, "Box", "Vertex401")})


if __name__ == "__main__":
    unittest.main()
