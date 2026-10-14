# SPDX-License-Identifier: LGPL-2.1-or-later
"""NX Sheet Metal on FreeCAD's SheetMetal add-on (github.com/shaise/FreeCAD_SheetMetal, bundled as
vendor/FreeCAD_SheetMetal).

The add-on makes the features (Tab = Make Base Wall, Flange = Make Wall, Bend = Fold a Wall, Hem,
Cutout, Rip, Relief, Convert to Sheet Metal, Forming) and the flat pattern (Unfold). Two things NX
does that the add-on leaves to each dialog are added here:

- Sheet Metal Preferences: material thickness, bend radius and neutral factor (K) for new features,
  with the bend allowance and bend deduction they give (sheetmetal.py) and a check of K. They are the
  add-on's own defaults, so its dialogs start from them.
- Flat Pattern: the add-on's Unfold, started with the preferred neutral factor instead of its fixed
  0.4 (its Unfold does not take a saved K-factor).
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config, sheetmetal
from .qt import QtWidgets

PARAMS = "User parameter:BaseApp/Preferences/Mod/SheetMetal"


def preferences():
    """(thickness, radius, K) the add-on's dialogs start from; 1 mm, 1 mm and 0.41 where none is saved."""
    p = App.ParamGet(PARAMS)
    k = p.GetFloat("defaultKFactor", sheetmetal.K_DEFAULT)
    if p.GetString("defaultKFactorStandard", "ansi") == "din":
        k = sheetmetal.ansi(k)
    return p.GetFloat("defaultThickness", 1.0), p.GetFloat("defaultRadius", 1.0), k


def set_preferences(T, R, K):
    p = App.ParamGet(PARAMS)
    p.SetFloat("defaultThickness", float(T))
    p.SetFloat("defaultRadius", float(R))
    p.SetFloat("defaultKFactor", float(K))
    p.SetString("defaultKFactorStandard", "ansi")


class PreferencesPanel:
    def __init__(self):
        T, R, K = preferences()
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Sheet Metal Preferences")
        lay = QtWidgets.QFormLayout(self.form)
        self.spins = {}
        for name, label, value, step, decimals, suffix in (
                ("thickness", "Material Thickness", T, 0.1, 4, " mm"),
                ("radius", "Bend Radius", R, 0.1, 4, " mm"),
                ("neutral", "Neutral Factor", K, 0.01, 3, "")):
            s = QtWidgets.QDoubleSpinBox()
            s.setObjectName(name)
            s.setDecimals(decimals)
            s.setRange(0.0, 1000.0 if suffix else 1.0)
            s.setSingleStep(step)
            s.setSuffix(suffix)
            s.setValue(value)
            s.valueChanged.connect(self.update)
            lay.addRow(label, s)
            self.spins[name] = s
        self.info = QtWidgets.QLabel()
        self.info.setObjectName("bendInfo")
        self.info.setWordWrap(True)
        lay.addRow(self.info)
        note = QtWidgets.QLabel("The neutral factor K places the neutral layer at K x thickness from the inside of a "
                                "bend, usually 0.25 to 0.5 (DIN 6935 quotes twice the value). New tabs, flanges and flat "
                                "patterns use these values.")
        note.setWordWrap(True)
        lay.addRow(note)
        self.update()

    def values(self):
        return tuple(self.spins[n].value() for n in ("thickness", "radius", "neutral"))

    def update(self, *_):
        T, R, K = self.values()
        self.info.setText(sheetmetal.report(T, R, K).replace("\n", "<br>"))

    def accept(self):
        T, R, K = self.values()
        errors = [t for s, t in sheetmetal.check(T, R, K) if s == "error"]
        if errors:
            QtWidgets.QMessageBox.information(self.form, "Sheet Metal Preferences", "\n".join(errors))
            return False
        set_preferences(T, R, K)
        last.update(thickness=T, radius=R, neutral=K)
        Gui.Control.closeDialog()
        App.Console.PrintMessage("Sheet Metal Preferences: " + sheetmetal.report(T, R, K).replace("\n", "; ") + "\n")
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


last = {}


class Preferences:
    def GetResources(self):
        return {"MenuText": "Sheet Metal Preferences",
                "ToolTip": "Material thickness, bend radius and neutral factor for new sheet metal features and "
                           "flat patterns, with the bend allowance they give",
                "Pixmap": config.resource("icons", "sheet_metal_prefs.svg")}

    def IsActive(self):
        return not Gui.Control.activeDialog()

    def Activated(self):
        Gui.Control.showDialog(PreferencesPanel())


def flat_pattern(selobj, faces, K=None, panel=True):
    """The add-on's Unfold of selobj from a flat face, with neutral factor K (the preference by default)."""
    import SheetMetalTools
    import SheetMetalUnfoldCmd as U
    K = preferences()[2] if K is None else K
    parent = SheetMetalTools.smGetParentBody(selobj)
    name = "Unfold" if parent is None else f"{parent.Name}_Unfold"
    obj, body = SheetMetalTools.smCreateNewObject(selobj, name, False)
    if obj is None:
        return None
    obj.Label = "Flat Pattern" if parent is None else f"{parent.Label}_Flat Pattern"
    U.SMUnfold(obj, selobj, faces)
    obj.KFactorStandard = "ansi"
    obj.KFactor = float(K)
    U.SMUnfoldViewProvider(obj.ViewObject)
    SheetMetalTools.smAddNewObject(selobj, obj, body, U.SMUnfoldTaskPanel if panel else None)
    last.update(flat_pattern=obj.Name, neutral=K)
    return obj


class FlatPattern:
    def GetResources(self):
        return {"MenuText": "Flat Pattern",
                "ToolTip": "Unfold the sheet metal part from the selected flat face, with the neutral factor of "
                           "Sheet Metal Preferences",
                "Pixmap": config.resource("icons", "flat_pattern.svg")}

    def IsActive(self):
        sel = Gui.Selection.getSelectionEx()
        if len(sel) != 1 or len(sel[0].SubObjects) != 1 or Gui.Control.activeDialog():
            return False
        try:
            return sel[0].SubObjects[0].Surface.__class__.__name__ == "Plane"
        except Exception:
            return False

    def Activated(self):
        sel = Gui.Selection.getSelectionEx()[0]
        flat_pattern(sel.Object, list(sel.SubElementNames))


COMMANDS = {
    "NXStyle_SheetMetalPreferences": Preferences(),
    "NXStyle_FlatPattern": FlatPattern(),
}
