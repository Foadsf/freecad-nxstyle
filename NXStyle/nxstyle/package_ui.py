# SPDX-License-Identifier: LGPL-2.1-or-later
"""PLM > Publish Release Package: what a released part is handed over in (NX has the same job under
File > Export > Publish Technical Data Package).

With Strata, a package is made from a release: the document exactly as it was released (taken from
Strata's history, not the working copy), with the release record (part number, revision, state,
approver, the version it came from) in the manifest. Without a release it is marked "Not released"
and made from the open document. Contents:

  model/       <PN>_<rev>.step (STEP AP242, with the semantic PMI when the part has PMI; ap242.py) and
               the native .FCStd
  drawings/    every drawing sheet as PDF
  pmi/         pmi.json (semantic PMI), inspection_plan.csv, functional_gauge.csv, checks.txt
  analysis/    each tolerance stack-up (.txt report and .csv) and mass_properties.csv
  manifest.json and README.txt with the SHA-256 of every file; a reproducible zip beside the folder
"""

import json
import os
import shutil
import tempfile

import FreeCAD as App
import FreeCADGui as Gui

from . import config, package, pmi
from .qt import QtWidgets

STEP_PARAMS = ("User parameter:BaseApp/Preferences/Mod/Import", "User parameter:BaseApp/Preferences/Mod/Part/STEP")


# ------------------------------------------------------------------ Strata
def strata_project(doc):
    if not doc or not doc.FileName:
        return None
    try:
        from strata.project import Project
        return Project.locate(doc.FileName)
    except Exception:
        return None


def releases_of(doc):
    """Strata release records of this document, newest revision last."""
    proj = strata_project(doc)
    if proj is None:
        return None, []
    rel = proj.rel(doc.FileName).replace(os.sep, "/")
    try:
        return proj, [r for r in proj.releases() if r.document.replace(os.sep, "/") == rel]
    except Exception:
        return proj, []


def release_meta(rel):
    import datetime
    return {"part_number": rel.part_number, "revision": rel.revision, "description": rel.description,
            "state": rel.state, "released_by": rel.author, "approved_by": rel.approver or "",
            "version": rel.version, "commit": rel.sha, "source_document": rel.document,
            "released": datetime.datetime.fromtimestamp(rel.time).date().isoformat() if rel.time else ""}


# ------------------------------------------------------------------ exporters
def solids(doc):
    """What a STEP of the part holds: assemblies, else bodies and other solids not used by others."""
    tops = [o for o in doc.Objects if o.isDerivedFrom("Assembly::AssemblyObject")]
    if tops:
        return tops
    out = []
    for o in doc.Objects:
        shape = getattr(o, "Shape", None)
        if shape is None or shape.isNull() or not shape.Solids:
            continue
        if o.isDerivedFrom("PartDesign::Feature") and not o.isDerivedFrom("PartDesign::Body"):
            continue
        if any(p.isDerivedFrom("Part::Feature") for p in o.InList):     # consumed by another solid
            continue
        out.append(o)
    return out


def step_schema(path):
    """The schema name a STEP file declares, e.g. AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF
    (without the ASN.1 identifier that follows it in braces, which FreeCAD's writer wraps over lines)."""
    try:
        with open(path, "r", encoding="latin-1") as f:
            head = f.read(4000)
        i = head.find("FILE_SCHEMA")
        if i < 0:
            return ""
        name = head[i:head.find(";", i)].split("'")[1]
        return " ".join(name.split("{")[0].split())
    except Exception:
        return ""


def colors(objs):
    """{object name: (r, g, b)} of the bodies' display colours, for the STEP file."""
    out = {}
    if not App.GuiUp:
        return out
    for o in objs:
        try:
            out[o.Name] = tuple(o.ViewObject.ShapeAppearance[0].DiffuseColor[:3])
        except Exception:
            try:
                out[o.Name] = tuple(o.ViewObject.ShapeColor[:3])
            except Exception:
                pass
    return out


def export_step_pmi(doc, objs, path):
    """STEP AP242 of objs with the part's semantic PMI (ap242.py). Returns (schema, summary text,
    problems), or None when there is no PMI, the model is an assembly or this FreeCAD lacks pythonocc."""
    from . import ap242, pmi_ui
    p = pmi_ui.all_pmi(doc)
    if not p or not ap242.available() or any(o.isDerivedFrom("Assembly::AssemblyObject") for o in objs):
        return None
    std, general = pmi_ui.settings(doc)
    s, problems = ap242.write(objs, p, path, std, general, colors=colors(objs))
    return s["schema"], ap242.summary_text(s), problems


def export_step(objs, path):
    """STEP of objs, AP242 requested; returns the schema the file actually has."""
    saved = []
    for p in STEP_PARAMS:
        g = App.ParamGet(p)
        saved.append((g, g.GetString("Scheme", "")))
        g.SetString("Scheme", "AP242DIS")
    try:
        try:
            import ImportGui
            ImportGui.export(objs, path)
        except Exception:
            import Import
            Import.export(objs, path)
    finally:
        for g, v in saved:
            if v:
                g.SetString("Scheme", v)
            else:
                g.RemString("Scheme")
    return step_schema(path)


def export_pdfs(doc, folder):
    out = []
    pages = [o for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawPage")]
    if not pages:
        return out
    import TechDrawGui
    for p in pages:
        path = os.path.join(folder, package.safe_name(p.Label) + ".pdf")
        os.makedirs(folder, exist_ok=True)
        TechDrawGui.exportPageAsPdf(p, path)
        if os.path.isfile(path):
            out.append(path)
    return out


def export_pmi(doc, folder):
    from . import pmi_ui
    objs = pmi_ui.all_pmi(doc)
    if not objs:
        return {}
    anns = pmi_ui.annotations(doc)
    std, general = pmi_ui.settings(doc)
    name = "ISO GPS (ISO 8015)" if std == "ISO" else "ASME Y14.5"
    views = [{"name": v.Label, "direction": [round(c, 6) for c in v.Direction], "up": [round(c, 6) for c in v.Up]}
             for v in pmi_ui.model_views(doc)]
    package.write_text(os.path.join(folder, "pmi.json"), json.dumps(
        {"standard": name, "general_tolerances": general or "", "units": "mm", "model_views": views,
         "annotations": anns}, indent=1, ensure_ascii=False))
    plan = pmi.inspection_plan(anns, general=general)
    package.write_csv(os.path.join(folder, "inspection_plan.csv"), package.dict_rows(
        plan, ["number", "requirement", "kind", "nominal", "lower", "upper", "tolerance_from", "upper_at_departure",
               "datums", "feature", "method", "note"]))
    g = pmi.gauges(anns, general)
    if g:
        package.write_csv(os.path.join(folder, "functional_gauge.csv"), package.dict_rows(g, ["element", "size", "for",
                                                                                       "feature", "how"]))
    issues = pmi.check(anns, std, general)
    package.write_text(os.path.join(folder, "checks.txt"), f"{name} checks: " + (
        "no findings" if not issues else "\n".join(f"{s}: {i}: {m}" for s, i, m in issues)))
    return {"standard": name, "general_tolerances": general or "", "characteristics": len(plan),
            "gauge_elements": len(g), "check_findings": len(issues)}


def export_analysis(doc, folder):
    from . import commands, stackup_ui
    n = 0
    for s in stackup_ui.stackups(doc):
        name = package.safe_name(s.Label)
        package.write_text(os.path.join(folder, f"{name}.txt"), s.Report or s.Verdict)
        package.write_csv(os.path.join(folder, f"{name}.csv"), stackup_ui.csv_rows(s))
        n += 1
    _, rows = commands.measure_bodies(solids(doc))
    if rows:
        package.write_csv(os.path.join(folder, "mass_properties.csv"), package.dict_rows(
            [dict(r, com=" ".join(f"{c:.4f}" for c in r["com"])) for r in rows],
            ["object", "volume_mm3", "area_mm2", "material", "density_kg_m3", "mass_kg", "com"]))
    return n


def publish(doc, out_root, meta, parts=None, released_file=None, make_zip=True):
    """Write the package for doc (or for released_file, a released copy that is opened, exported and
    closed) into out_root/<PN>_<rev>/. Returns (folder, manifest, zip path or None)."""
    parts = parts or {"step", "native", "pdf", "pmi", "analysis"}
    name = f"{package.safe_name(meta.get('part_number', doc.Label))}_{package.safe_name(meta.get('revision', '-'))}"
    folder = os.path.join(out_root, name)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
    os.makedirs(folder)
    src = doc
    opened = None
    if released_file:
        before = set(App.listDocuments())
        src = App.openDocument(released_file)
        opened = src if src.Name not in before else None
        src.recompute()
    try:
        info = {}
        if "step" in parts:
            objs = solids(src)
            if objs:
                path = os.path.join(folder, "model", name + ".step")
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with_pmi = export_step_pmi(src, objs, path)
                if with_pmi:
                    info["step_schema"], info["step_pmi"], problems = with_pmi
                    if problems:
                        info["step_pmi_not_written"] = problems
                else:
                    info["step_schema"] = export_step(objs, path)
        if "native" in parts:
            path = os.path.join(folder, "model", name + ".FCStd")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if released_file:
                shutil.copyfile(released_file, path)
            elif doc.FileName:
                doc.save()
                shutil.copyfile(doc.FileName, path)
        if "pdf" in parts:
            info["drawings"] = len(export_pdfs(src, os.path.join(folder, "drawings")))
        if "pmi" in parts:
            info.update(export_pmi(src, os.path.join(folder, "pmi")))
        if "analysis" in parts:
            info["stackups"] = export_analysis(src, os.path.join(folder, "analysis"))
    finally:
        if opened is not None:
            App.closeDocument(opened.Name)
            if App.GuiUp and App.ActiveDocument is not doc and doc.Name in App.listDocuments():
                Gui.getDocument(doc.Name)          # back to the part that was open
                App.setActiveDocument(doc.Name)
    full = dict(meta)
    full.update({k: v for k, v in info.items() if v not in (None, "")})
    full.setdefault("units", "mm")
    full.setdefault("standard", "ISO GPS (ISO 8015)")
    full["digital_product_definition"] = "ISO 16792" if full["standard"].startswith("ISO") else "ASME Y14.41"
    full["created"] = package.today()
    full["created_with"] = "FreeCAD " + ".".join(App.Version()[:3]) + " with FreeCAD NX-Style"
    m = package.write_manifest(folder, full)
    z = package.zip_folder(folder, folder + ".zip") if make_zip else None
    return folder, m, z


# ------------------------------------------------------------------ dialog
class PublishPanel:
    def __init__(self):
        self.doc = App.ActiveDocument
        self.project, self.releases = releases_of(self.doc)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Publish Release Package")
        lay = QtWidgets.QFormLayout(self.form)
        self.release = QtWidgets.QComboBox()
        self.release.setObjectName("release")
        self.release.addItem("Not released: the open document")
        for r in self.releases:
            self.release.addItem(f"{r.part_number} rev {r.revision} ({r.state})")
        released = [i for i, r in enumerate(self.releases) if r.state == "Released"]
        if released:
            self.release.setCurrentIndex(released[-1] + 1)
        self.pn = QtWidgets.QLineEdit(self.doc.Label)
        self.pn.setObjectName("partNumber")
        self.rev = QtWidgets.QLineEdit("-")
        self.rev.setObjectName("revision")
        self.desc = QtWidgets.QLineEdit("")
        self.desc.setObjectName("description")
        base = os.path.dirname(self.doc.FileName) if self.doc.FileName else os.path.expanduser("~")
        self.out = QtWidgets.QLineEdit(os.path.join(base, "Release packages"))
        self.out.setObjectName("outputFolder")
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.out)
        row.addWidget(browse)
        lay.addRow("Release", self.release)
        lay.addRow("Part number", self.pn)
        lay.addRow("Revision", self.rev)
        lay.addRow("Description", self.desc)
        lay.addRow("Folder", row)
        self.parts = {}
        for key, text in (("step", "Model as STEP"), ("native", "Native FreeCAD file"), ("pdf", "Drawings as PDF"),
                          ("pmi", "PMI, inspection plan, gauge sizes"), ("analysis", "Stack-ups, mass properties"),
                          ("zip", "Zip archive")):
            b = QtWidgets.QCheckBox(text)
            b.setObjectName(f"part_{key}")
            b.setChecked(True)
            lay.addRow("", b)
            self.parts[key] = b
        if self.project is None:
            lay.addRow(QtWidgets.QLabel("This part is not in a Strata project: the package is marked Not released."))
        self.release.currentIndexChanged.connect(self.pick)
        self.pick()

    def browse(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self.form, "Folder for the package", self.out.text())
        if d:
            self.out.setText(d)

    def pick(self, *_):
        i = self.release.currentIndex() - 1
        r = self.releases[i] if 0 <= i < len(self.releases) else None
        for w in (self.pn, self.rev, self.desc):
            w.setReadOnly(r is not None)
        if r is not None:
            self.pn.setText(r.part_number)
            self.rev.setText(r.revision)
            self.desc.setText(r.description)

    def selected(self):
        i = self.release.currentIndex() - 1
        return self.releases[i] if 0 <= i < len(self.releases) else None

    def accept(self):
        from .commands import show_information
        r = self.selected()
        parts = {k for k, b in self.parts.items() if b.isChecked() and k != "zip"}
        tmp = None
        try:
            if r is not None:
                meta = release_meta(r)
                tmp = tempfile.mkdtemp(prefix="nxstyle-package-")
                released = self.project.export_document(r.sha, r.document, tmp)
            else:
                meta = {"part_number": self.pn.text().strip() or self.doc.Label, "revision": self.rev.text().strip()
                        or "-", "description": self.desc.text().strip(), "state": "Not released",
                        "source_document": os.path.basename(self.doc.FileName or self.doc.Label)}
                released = None
            folder, m, z = publish(self.doc, self.out.text(), meta, parts, released, self.parts["zip"].isChecked())
        except Exception as e:
            import traceback
            App.Console.PrintError(traceback.format_exc())
            QtWidgets.QMessageBox.warning(self.form, "Publish Release Package", f"Not published: {e}")
            return False
        finally:
            if tmp:
                shutil.rmtree(tmp, ignore_errors=True)
        Gui.Control.closeDialog()
        global last
        last = {"folder": folder, "manifest": m, "zip": z}
        show_information(package.readme_text(m) + (f"\nArchive: {z}\n" if z else "") + f"Folder: {folder}")
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


last = {}


class PublishPackage:
    def GetResources(self):
        return {"MenuText": "Publish Release Package",
                "ToolTip": "The released part as a package for manufacturing and suppliers: STEP, native model, "
                           "drawings as PDF, PMI and inspection plan, stack-ups and mass properties, with a manifest "
                           "of SHA-256 checksums (NX: File > Export > Publish Technical Data Package)",
                "Pixmap": config.resource("icons", "release_package.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        Gui.Control.showDialog(PublishPanel())
