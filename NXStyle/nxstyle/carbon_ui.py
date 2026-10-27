# SPDX-License-Identifier: LGPL-2.1-or-later
"""PLM › Manufacturing: the released part into Carbon, and what manufacturing has for it (carbon.py).

- Publish to Manufacturing: a Strata release becomes a release package (package_ui.publish: the part as it
  was released, verified), and the package goes to Carbon: item and revision, CAD model, documents, the
  assembly's bill of materials and the inspection plan. Review lists what would be written first.
- Manufacturing Status: the part's revisions, stock, inspection plans and open issues in Carbon.
- Manufacturing Connection: the Carbon server, the API key (kept in a file of its own, never in
  nxstyle.json) and the stock location.
"""

import json
import os
import shutil
import tempfile

import FreeCAD as App
import FreeCADGui as Gui

from . import carbon, config
from .qt import QtCore, QtWidgets

KEY_FILE = "carbon.key"


# ------------------------------------------------------------------ settings
def enabled():
    return config.get().get("manufacturing", "carbon") == "carbon" and os.environ.get("NXSTYLE_CARBON", "1") != "0"


def settings():
    return config.get().get("carbon", {})


def key_file():
    return settings().get("api_key_file") or os.path.join(config.profile_dir(), KEY_FILE)


def client():
    """A Client for the configured server, or CarbonError saying what is missing."""
    s = settings()
    key, _ = carbon.api_key(key_file())
    return carbon.Client(s.get("url") or os.environ.get(carbon.URL_ENV, ""), key)


def save_settings(url, location):
    """url and location into the profile's nxstyle.json (the file holds only what was changed)."""
    path = config.user_file()
    data = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    data.setdefault("carbon", {}).update(url=url, location=location)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    config.load()


def describe():
    """One line for the dialogs: where it connects and where the key comes from (never the key)."""
    s = settings()
    url = s.get("url") or os.environ.get(carbon.URL_ENV, "")
    key, where = carbon.api_key(key_file())
    if not url:
        return "Not set up: no Carbon server yet (PLM › Manufacturing Connection)."
    return f"Carbon at {url}; API key {carbon.masked(key)}" + (f" from {where}" if where else " missing")


# ------------------------------------------------------------------ identity and BOM from FreeCAD
def identity(doc):
    """{part_number, revision, description, state} of a document: its newest Released Strata release, else
    its newest release, else its NX attributes (DB_PART_NO, DB_PART_REV, DB_PART_NAME), else its label
    (revision "": none known)."""
    from . import package_ui
    _, rels = package_ui.releases_of(doc)
    released = [r for r in rels if r.state == "Released"]
    if rels:
        m = package_ui.release_meta((released or rels)[-1])
        return {k: m.get(k, "") for k in ("part_number", "revision", "description", "state")}
    try:
        meta = dict(doc.Meta)
    except Exception:
        meta = {}
    return {"part_number": meta.get("DB_PART_NO") or doc.Label, "revision": meta.get("DB_PART_REV") or "",
            "description": meta.get("DB_PART_NAME") or "", "state": "Not released"}


def _is_assembly(o):
    return o is not None and o.isDerivedFrom("Assembly::AssemblyObject")


def linked(o):
    """What a link (or a link to a link) stands for. getLinkedObject(True) answers the link itself for a link
    array (ElementCount > 0, FreeCAD 1.1.4), so the LinkedObject property is followed instead."""
    target = o
    for _ in range(20):
        nxt = getattr(target, "LinkedObject", None)
        if isinstance(nxt, tuple):
            nxt = nxt[0] if nxt else None
        if nxt is None or nxt is target:
            break
        target = nxt
    return target


def bom_tree(obj, depth=0):
    """An assembly as carbon.Publisher.push_bom takes it: each component (a link, a link array or a part in
    the assembly itself) with its part number from its own document's release; sub-assemblies nest."""
    children = []
    for o in getattr(obj, "Group", []) or []:
        if o.isDerivedFrom("Assembly::JointGroup") or o.TypeId in ("Assembly::ViewGroup", "Assembly::BomGroup"):
            continue
        target = linked(o)
        if target is None or (target is not o and target.isDerivedFrom("App::DocumentObjectGroup")
                              and not _is_assembly(target)):
            continue
        if not _is_assembly(target) and getattr(target, "Shape", None) is None:
            continue
        qty = int(getattr(o, "ElementCount", 0) or 0) or 1
        if target.Document is not obj.Document:
            ident = identity(target.Document)
            pn, rev, name = ident["part_number"], ident["revision"], ident["description"] or target.Label
        else:
            pn, rev, name = target.Label, "", target.Label
        node = {"id": pn, "revision": rev, "name": name, "quantity": qty, "children": []}
        if _is_assembly(target) and depth < 20:
            node["children"] = bom_tree(target, depth + 1)["children"]
        children.append(node)
    return {"children": children}


def assembly_of(doc):
    return next((o for o in doc.Objects if _is_assembly(o)), None)


# ------------------------------------------------------------------ Manufacturing Connection
class ConnectionDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setObjectName("CarbonConnection")
        self.setWindowTitle("Manufacturing Connection")
        s = settings()
        lay = QtWidgets.QFormLayout(self)
        intro = QtWidgets.QLabel("Carbon (carbon.ms) is the manufacturing system: items, BOMs, inventory, jobs and "
                                 "quality. Use Carbon Cloud or your own server; the API key comes from Carbon's "
                                 "Settings › API Keys.")
        intro.setWordWrap(True)
        lay.addRow(intro)
        self.url = QtWidgets.QLineEdit(s.get("url") or "")
        self.url.setObjectName("carbonUrl")
        self.url.setPlaceholderText(carbon.CLOUD)
        key, where = carbon.api_key(key_file())
        self.key = QtWidgets.QLineEdit()
        self.key.setObjectName("carbonKey")
        self.key.setEchoMode(QtWidgets.QLineEdit.Password)
        self.key.setPlaceholderText(f"kept: {carbon.masked(key)} ({where})" if key else "crbn_…")
        self.location = QtWidgets.QLineEdit(s.get("location") or "")
        self.location.setObjectName("carbonLocation")
        self.location.setPlaceholderText("the first location")
        lay.addRow("Server", self.url)
        lay.addRow("API key", self.key)
        lay.addRow("Stock location", self.location)
        self.result = QtWidgets.QLabel("")
        self.result.setObjectName("carbonResult")
        self.result.setWordWrap(True)
        lay.addRow(self.result)
        if os.environ.get(carbon.KEY_ENV):
            lay.addRow(QtWidgets.QLabel(f"{carbon.KEY_ENV} is set: it is used instead of a saved key."))
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        test = buttons.addButton("Test Connection", QtWidgets.QDialogButtonBox.ActionRole)
        test.setObjectName("carbonTest")
        test.clicked.connect(self.test)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        lay.addRow(buttons)

    def _client(self):
        typed = self.key.text().strip()
        key = typed or carbon.api_key(key_file())[0]
        return carbon.Client(self.url.text().strip() or carbon.CLOUD, key)

    def test(self):
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            c = self._client()
            names = carbon.check(c)
            self.result.setText(f"Connected to {c.url}: {', '.join(map(str, names)) or 'no company'}.")
            return True
        except carbon.CarbonError as e:
            self.result.setText(f"Not connected: {e}")
            return False
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def save(self):
        try:
            url = carbon.normalise_url(self.url.text().strip() or carbon.CLOUD)
            if self.key.text().strip():
                carbon.save_api_key(key_file(), self.key.text())
            save_settings(url, self.location.text().strip())
        except (carbon.CarbonError, OSError, ValueError) as e:
            self.result.setText(f"Not saved: {e}")
            return
        self.accept()


# ------------------------------------------------------------------ Publish to Manufacturing
class PublishPanel:
    PARTS = (("model", "CAD model (STEP, with PMI)"), ("documents", "Documents: native file, drawings, PMI, manifest"),
             ("bom", "Bill of materials (assemblies)"), ("inspection", "Inspection plan (PMI characteristics)"))

    def __init__(self):
        from . import package_ui
        self.doc = App.ActiveDocument
        self.project, self.releases = package_ui.releases_of(self.doc)
        self.allow_unreleased = bool(settings().get("allow_unreleased", False))
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Publish to Manufacturing")
        self.form.setObjectName("CarbonPublish")
        lay = QtWidgets.QFormLayout(self.form)
        self.where = QtWidgets.QLabel(describe())
        self.where.setObjectName("carbonWhere")
        self.where.setWordWrap(True)
        lay.addRow(self.where)
        self.release = QtWidgets.QComboBox()
        self.release.setObjectName("release")
        for r in self.releases:
            self.release.addItem(f"{r.part_number} rev {r.revision} ({r.state})")
        if self.allow_unreleased:
            self.release.addItem("Not released: the open document")
        released = [i for i, r in enumerate(self.releases) if r.state == "Released"]
        if released:
            self.release.setCurrentIndex(released[-1])
        lay.addRow("Release", self.release)
        if not self.releases:
            lay.addRow(QtWidgets.QLabel("This part has no Strata release: release it first (PLM › Releases)."
                                        if not self.allow_unreleased else
                                        "No Strata release: the open document is sent as it is."))
        self.parts = {}
        for key, text in self.PARTS:
            b = QtWidgets.QCheckBox(text)
            b.setObjectName(f"carbon_{key}")
            b.setChecked(True)
            lay.addRow("", b)
            self.parts[key] = b
        review = QtWidgets.QPushButton("Review")
        review.setObjectName("carbonReview")
        review.setToolTip("List what Carbon would get, without writing anything")
        review.clicked.connect(self.review)
        lay.addRow("", review)
        self.out = QtWidgets.QPlainTextEdit()
        self.out.setObjectName("carbonReviewText")
        self.out.setReadOnly(True)
        self.out.setMinimumHeight(160)
        lay.addRow(self.out)
        self._built = None                    # (selection, package folder, bom, temporary folder)

    def selected(self):
        i = self.release.currentIndex()
        return self.releases[i] if 0 <= i < len(self.releases) else None

    def _package(self):
        """The release package for the selection (built once per selection) and the assembly's BOM."""
        from . import package_ui
        r = self.selected()
        key = (self.release.currentIndex(), r.sha if r is not None else None)
        if self._built and self._built[0] == key:
            return self._built[1], self._built[2]
        if r is None and not self.allow_unreleased:
            raise carbon.CarbonError("nothing released to publish: release the part in Strata first")
        self.cleanup()
        tmp = tempfile.mkdtemp(prefix="nxstyle-carbon-")
        released = None
        if r is not None:
            meta = package_ui.release_meta(r)
            released = self.project.export_document(r.sha, r.document, tmp)
        else:
            meta = dict(identity(self.doc), state="Not released",
                        source_document=os.path.basename(self.doc.FileName or self.doc.Label))
        folder, _, _ = package_ui.publish(self.doc, os.path.join(tmp, "package"), meta,
                                          {"step", "native", "pdf", "pmi", "analysis"}, released, make_zip=False)
        asm = assembly_of(self.doc)
        bom = dict(bom_tree(asm), id=meta["part_number"]) if asm is not None else None
        self._built = (key, folder, bom, tmp)
        return folder, bom

    def run(self, dry_run):
        parts = tuple(k for k, b in self.parts.items() if b.isChecked())
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            c = client()
            folder, bom = self._package()
            r = carbon.publish(c, folder, bom=bom, dry_run=dry_run, defaults=settings().get("new_part"),
                               allow_unreleased=self.allow_unreleased, parts=parts)
            return r, carbon.publish_text(r)
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()

    def review(self):
        try:
            _, text = self.run(True)
        except Exception as e:
            text = f"Not reviewed: {e}"
            if not isinstance(e, carbon.CarbonError):
                import traceback
                App.Console.PrintError(traceback.format_exc())
        self.out.setPlainText(text)

    def accept(self):
        from .commands import show_information
        global last
        try:
            r, text = self.run(False)
        except Exception as e:
            if not isinstance(e, carbon.CarbonError):
                import traceback
                App.Console.PrintError(traceback.format_exc())
            self.out.setPlainText(f"Not published: {e}")
            last = {"error": str(e)}
            return False
        last = r
        self.cleanup()
        Gui.Control.closeDialog()
        show_information(text)
        return True

    def reject(self):
        self.cleanup()
        Gui.Control.closeDialog()
        return True

    def cleanup(self):
        if self._built:
            shutil.rmtree(self._built[3], ignore_errors=True)
            self._built = None


last = {}


# ------------------------------------------------------------------ commands
class PublishToManufacturing:
    def GetResources(self):
        return {"MenuText": "Publish to Manufacturing",
                "ToolTip": "The released part into Carbon (manufacturing ERP, MES and quality): item and revision, "
                           "CAD model, drawings and documents, the assembly's BOM and the inspection plan; Review "
                           "lists what would be written first",
                "Pixmap": config.resource("icons", "manufacturing_publish.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        Gui.Control.showDialog(PublishPanel())


class ManufacturingStatus:
    def GetResources(self):
        return {"MenuText": "Manufacturing Status",
                "ToolTip": "What Carbon has for this part: revisions, stock, inspection plans and open issues",
                "Pixmap": config.resource("icons", "manufacturing_status.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None

    def Activated(self):
        from .commands import show_information
        ident = identity(App.ActiveDocument)
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        try:
            s = carbon.status(client(), ident["part_number"], ident["revision"] or None,
                              settings().get("location") or None)
            text = carbon.status_text(s)
        except carbon.CarbonError as e:
            text = f"Manufacturing Status of {ident['part_number']}: {e}\n\n{describe()}"
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
        show_information(text)


class ManufacturingConnection:
    def GetResources(self):
        return {"MenuText": "Manufacturing Connection",
                "ToolTip": "The Carbon server and API key that Publish to Manufacturing and Manufacturing Status use",
                "Pixmap": config.resource("icons", "manufacturing_connection.svg")}

    def IsActive(self):
        return True

    def Activated(self):
        global dialog
        dialog = ConnectionDialog()           # kept: a dialog without a Python owner is collected
        dialog.show()


dialog = None


def commands():
    if not enabled():
        return {}
    return {"NXStyle_CarbonPublish": PublishToManufacturing(), "NXStyle_CarbonStatus": ManufacturingStatus(),
            "NXStyle_CarbonConnection": ManufacturingConnection()}
