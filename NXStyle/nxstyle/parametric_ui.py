# SPDX-License-Identifier: LGPL-2.1-or-later
"""PMI › Exchange: STEP with Parameters, Import STEP with Parameters, Check STEP (ISO 10303).

The work is in parametric_fc.py (FreeCAD) and parametric.py / iso10303.py (no FreeCAD); this module is
the three commands and their task panels.
"""

import os

import FreeCAD as App
import FreeCADGui as Gui

from . import config
from .qt import QtWidgets


def _target():
    """The selected Body, Part object or sketch, else the active Body."""
    for o in Gui.Selection.getSelection():
        if o.TypeId in ("PartDesign::Body", "Sketcher::SketchObject") or (hasattr(o, "Shape") and o.Shape.Solids):
            return o
        body = getattr(o, "_Body", None) or (o.getParentGeoFeatureGroup() if hasattr(o, "getParentGeoFeatureGroup")
                                              else None)
        if body is not None and body.TypeId == "PartDesign::Body":
            return body
    view = Gui.ActiveDocument.ActiveView if Gui.ActiveDocument else None
    body = view.getActiveObject("pdbody") if view and hasattr(view, "getActiveObject") else None
    if body is not None:
        return body
    doc = App.ActiveDocument
    bodies = doc.findObjects("PartDesign::Body") if doc else []
    return bodies[0] if len(bodies) == 1 else None


class _FilePanel:
    title, save, filt = "", False, "STEP (*.step *.stp)"

    def __init__(self, default="", text=""):
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(self.title)
        lay = QtWidgets.QFormLayout(self.form)
        self.path = QtWidgets.QLineEdit(default)
        self.path.setObjectName("stepFile")
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.path)
        row.addWidget(browse)
        lay.addRow("File", row)
        info = QtWidgets.QLabel(text)
        info.setWordWrap(True)
        lay.addRow(info)

    def browse(self):
        dlg = QtWidgets.QFileDialog.getSaveFileName if self.save else QtWidgets.QFileDialog.getOpenFileName
        p, _ = dlg(self.form, self.title, self.path.text(), self.filt)
        if p:
            self.path.setText(p)

    def run(self, path):
        raise NotImplementedError

    def accept(self):
        from .commands import show_information
        path = self.path.text().strip()
        if not self.save and not os.path.isfile(path):
            QtWidgets.QMessageBox.information(self.form, self.title, f"No file {path!r}.")
            return False
        try:
            text = self.run(path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self.form, self.title, str(e))
            return False
        Gui.Control.closeDialog()
        show_information(text)
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


class ExportPanel(_FilePanel):
    title, save = "STEP with Parameters", True

    def __init__(self, obj):
        self.obj = obj
        doc = obj.Document
        base = os.path.splitext(doc.FileName)[0] if doc.FileName else os.path.join(os.path.expanduser("~"), obj.Label)
        super().__init__(base + ".step",
                         f"{obj.Label}: the solid as STEP AP242 (ISO 10303-42 B-rep, what every CAD system reads), "
                         "and in the same file its construction history (ISO 10303-55), Part 111 features, sketches "
                         "with their constraints and the spreadsheet parameters with the expressions that use them "
                         "(ISO 10303-108). The report lists what could not be written.")
        self.commands = QtWidgets.QCheckBox("Also write each sketch as ISO 10303-112 commands")
        self.commands.setObjectName("sketchCommands")
        self.commands.setToolTip("For a receiver that reads Part 112. No AP242 edition includes Part 112, so a "
                                 "strict AP242 reader will not know these entities")
        self.form.layout().addRow(self.commands)

    def run(self, path):
        from . import parametric_fc
        return parametric_fc.export(self.obj, path, sketch_commands=self.commands.isChecked())


class ImportPanel(_FilePanel):
    title = "Import STEP with Parameters"

    def __init__(self):
        super().__init__("", "Rebuilds the construction history, sketches, constraints and parameters an ISO 10303-55/108"
                             " STEP file carries, as a PartDesign Body (or Part CSG objects) with a Parameters "
                             "spreadsheet, and compares the result with the file's explicit B-rep. A file without "
                             "them comes in as its B-rep.")

    def run(self, path):
        from . import parametric_fc
        doc = App.ActiveDocument or App.newDocument()
        doc.openTransaction(self.title)
        _, text = parametric_fc.import_file(path, doc)
        doc.commitTransaction()
        Gui.SendMsgToActiveView("ViewFit")
        return text


class CheckPanel(_FilePanel):
    title = "Check STEP"

    def __init__(self):
        super().__init__("", "Reads the file as ISO 10303-21 and checks every instance against the EXPRESS schemas of "
                             "ISO 10303-42, -43, -55, -108, -111 and -112, and the WHERE rules that give parametric "
                             "data its meaning; an application protocol's own entities (product structure, PMI, "
                             "presentation) against the AP's long form when it is in the schema cache. Lists the "
                             "product structure (BOM).")
        self.fetch = QtWidgets.QCheckBox("Download the AP's schema if it is missing (AP203, AP214, AP242)")
        self.fetch.setObjectName("fetchSchema")
        self.fetch.setToolTip("AP242 from standards.iso.org, AP203 and AP214 from the STEPcode project; kept in "
                              "the schema cache, not downloaded again")
        self.form.layout().addRow(self.fetch)

    def run(self, path):
        from . import express, iso10303, p21
        f = p21.read(path)
        fetched = []
        if self.fetch.isChecked():
            for i in iso10303.identify(f):
                key = (i["ap"] or "") + ("E2" if i["edition"] == "edition 2" else "")
                if key in iso10303.FETCH and i["schema"] not in iso10303.cached_schemas():
                    fetched += iso10303.fetch_schema(key)
        issues = iso10303.check(f)
        s = express.summary(issues)
        aps = [f"{i['ap']} {i['title']} ({i['edition']})" for i in iso10303.identify(f) if i["ap"]]
        lines = [path, f"{len(f)} instances; " + ("; ".join(aps) or f"schema {', '.join(f.schemas)}"),
                 f"{s['error']} error(s), {s['warning']} warning(s), {s['info']} note(s)", ""]
        lines += [f"schema {n} downloaded: {k} entities" for n, k, _ in fetched]
        for std, ents in sorted(iso10303.inventory(f).items()):
            lines.append(f"{std}: {sum(ents.values())}")
        b = iso10303.bom(f)
        if b["roots"]:
            lines += ["", "Product structure:", iso10303.bom_text(b)]
        lines.append("")
        lines += [repr(i) for i in issues[:300]]
        return "\n".join(lines)


class _Command:
    def __init__(self, text, tip, icon, panel):
        self.text, self.tip, self.icon, self.panel = text, tip, icon, panel

    def GetResources(self):
        return {"MenuText": self.text, "ToolTip": self.tip, "Pixmap": config.resource("icons", self.icon)}

    def IsActive(self):
        return not Gui.Control.activeDialog()

    def Activated(self):
        if self.panel is ExportPanel:
            obj = _target()
            if obj is None:
                QtWidgets.QMessageBox.information(Gui.getMainWindow(), self.text,
                                                  "Select a Body, a Part solid or a sketch first.")
                return
            Gui.Control.showDialog(ExportPanel(obj))
        else:
            Gui.Control.showDialog(self.panel())


COMMANDS = {
    "NXStyle_ExportParametricSTEP": _Command(
        "STEP with Parameters", "Export the part as STEP AP242 with its construction history, sketch constraints "
        "and parameters (ISO 10303-55, -108, -111) next to its B-rep", "step_parametric.svg", ExportPanel),
    "NXStyle_ImportParametricSTEP": _Command(
        "Import STEP with Parameters", "Rebuild the construction history, sketches and parameters of an ISO "
        "10303-55/108 STEP file as an editable FreeCAD part", "import_step_parametric.svg", ImportPanel),
    "NXStyle_CheckSTEP": _Command(
        "Check STEP", "Check a STEP file against ISO 10303-21 and the EXPRESS schemas of Parts 42, 43, 55, 108, "
        "111 and 112", "check_step.svg", CheckPanel),
}
