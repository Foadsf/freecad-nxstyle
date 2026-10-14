# SPDX-License-Identifier: LGPL-2.1-or-later
"""Volume claims: space reservations in an assembly or system layout.

In a high-tech system layout every module or discipline owns a claimed volume (a space
reservation, "ruimteclaim"): its parts must stay inside it, nobody else's parts may enter it,
and claims must not overlap, because then one space is promised twice. Keep-out claims (a beam
path, a service access, a moving part's sweep) reserve space that no part may enter at all.

A VolumeClaim is a solid (a box of its own size, or the shape of a source object, e.g. a sketch
extruded by the architect), with an owner, its member parts and a margin: members must keep the
margin to the claim's boundary, and parts of other owners must keep it to the claim.
Check Volume Claims tests every claim and shows the offending volumes in red.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config
from .qt import QtWidgets

TOL = 1e-3            # mm^3: smaller overlaps are numerical noise
COLOURS = [(0.11, 0.53, 0.60), (0.85, 0.55, 0.10), (0.45, 0.30, 0.70), (0.20, 0.60, 0.25), (0.70, 0.25, 0.45),
           (0.30, 0.45, 0.80)]


def _prop(obj, kind, name, group, doc, value=None):
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, group, doc)
        if value is not None:
            setattr(obj, name, value)


class ClaimFeature:
    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        g = "Volume Claim"
        _prop(obj, "App::PropertyString", "Owner", g, "Module, discipline or team that owns this space")
        _prop(obj, "App::PropertyEnumeration", "ClaimType", g,
              "Keep-in: space for the owner's parts; Keep-out: no part may enter (beam path, access, sweep)")
        if not obj.ClaimType:
            obj.ClaimType = ["Keep-in", "Keep-out"]
            obj.ClaimType = "Keep-in"
        _prop(obj, "App::PropertyLinkList", "Members", g, "The parts that must stay inside this claim")
        _prop(obj, "App::PropertyLength", "Margin", g, "Clearance members keep to the boundary and others keep to "
              "the claim", 0.0)
        _prop(obj, "App::PropertyLink", "Source", g, "Take the claim's shape from this object (else a box)")
        _prop(obj, "App::PropertyLength", "Length", g, "Box size along X", 100.0)
        _prop(obj, "App::PropertyLength", "Width", g, "Box size along Y", 100.0)
        _prop(obj, "App::PropertyLength", "Height", g, "Box size along Z", 100.0)
        _prop(obj, "App::PropertyString", "Status", "Check", "Result of the last Check Volume Claims")
        obj.setEditorMode("Status", 1)
        _prop(obj, "App::PropertyStringList", "Findings", "Check", "What the last check found")
        obj.setEditorMode("Findings", 1)

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        import Part
        if obj.Source is not None and getattr(obj.Source, "Shape", None) is not None and obj.Source.Shape.Solids:
            obj.Shape = Part.getShape(obj.Source, "", transform=True)     # where the source is
            return
        pl = obj.Placement                         # a box at its own placement (assigning a shape resets it)
        obj.Shape = Part.makeBox(float(obj.Length), float(obj.Width), float(obj.Height))
        obj.Placement = pl


class ClaimView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.vobj = vobj
        colour(vobj.Object)

    def getIcon(self):
        return config.resource("icons", "volume_claim.svg")

    def updateData(self, obj, prop):
        if prop in ("Status", "Owner", "ClaimType"):
            colour(obj)

    def onChanged(self, vobj, prop):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


def colour(obj):
    vo = getattr(obj, "ViewObject", None)
    if vo is None:
        return
    try:
        if getattr(obj, "Status", "").startswith("VIOLATED"):
            c = (0.85, 0.12, 0.12)
        elif obj.ClaimType == "Keep-out":
            c = (0.55, 0.55, 0.58)
        else:
            c = COLOURS[sum(map(ord, obj.Owner or obj.Name)) % len(COLOURS)]
        vo.ShapeColor = c
        vo.LineColor = c
        vo.Transparency = 78
        vo.DisplayMode = "Shaded" if "Shaded" in vo.listDisplayModes() else vo.DisplayMode
        vo.Selectable = True
    except Exception:
        pass


def create(doc=None, owner="", members=(), size=(100, 100, 100), placement=None, kind="Keep-in", margin=0.0,
           source=None, name="VolumeClaim"):
    doc = doc or App.ActiveDocument
    obj = doc.addObject("Part::FeaturePython", name)
    ClaimFeature(obj)
    obj.Owner = owner
    obj.ClaimType = kind
    obj.Members = list(members)
    obj.Margin = margin
    obj.Length, obj.Width, obj.Height = size
    if placement is not None:
        obj.Placement = placement
    if source is not None:
        obj.Source = source
    obj.Label = f"Claim {owner}" if owner else "Volume Claim"
    if App.GuiUp:
        ClaimView(obj.ViewObject)
    group(doc).addObject(obj)
    doc.recompute()
    return obj


def group(doc):
    g = doc.getObject("VolumeClaims")
    if g is None:
        g = doc.addObject("App::DocumentObjectGroup", "VolumeClaims")
        g.Label = "Volume Claims"
    return g


def claims(doc):
    return [o for o in doc.Objects if isinstance(getattr(o, "Proxy", None), ClaimFeature)]


def parts(doc):
    """The solids of the layout that claims apply to: top-level parts, bodies and links (not the claims,
    not features consumed by others, not the check's own result)."""
    out = []
    for o in doc.Objects:
        if isinstance(getattr(o, "Proxy", None), ClaimFeature) or o.Name.startswith("ClaimViolations"):
            continue
        if o.isDerivedFrom("PartDesign::Feature") and not o.isDerivedFrom("PartDesign::Body"):
            continue
        if o.TypeId not in ("App::Link",) and not o.isDerivedFrom("Part::Feature"):
            continue
        if any(p.isDerivedFrom("Part::Feature") and not isinstance(getattr(p, "Proxy", None), ClaimFeature)
               for p in o.InList):
            continue
        try:
            import Part
            s = Part.getShape(o, "", transform=True)
        except Exception:
            continue
        if s.isNull() or not s.Solids:
            continue
        out.append((o, s))
    return out


def _inner(claim_shape, margin):
    """The claim shrunk by the margin (members must stay inside this)."""
    if margin <= 0:
        return claim_shape
    try:
        s = claim_shape.makeOffsetShape(-margin, 1e-4, join=2)
        if s.isValid() and s.Volume > 0:
            return s
    except Exception:
        pass
    return claim_shape


def _grown(claim_shape, margin):
    if margin <= 0:
        return claim_shape
    try:
        s = claim_shape.makeOffsetShape(margin, 1e-4, join=2)
        if s.isValid() and s.Volume > claim_shape.Volume:
            return s
    except Exception:
        pass
    return claim_shape


def check(doc):
    """Check every claim. Returns (findings, offending solids); findings are dicts: kind ('outside',
    'intrusion', 'overlap', 'unclaimed'), claim, other, volume, text."""
    import Part
    doc.recompute()
    cs = claims(doc)
    layout = parts(doc)
    findings, bad = [], []
    owner_of = {}
    for c in cs:
        for m in c.Members:
            owner_of.setdefault(m.Name, []).append(c)
    for c in cs:
        cshape = c.Shape
        margin = float(c.Margin)
        own = []
        if c.ClaimType == "Keep-in":
            inner = _inner(cshape, margin)
            for m in c.Members:
                ms = Part.getShape(m, "", transform=True)
                out = ms.cut(inner)
                if out.Volume > TOL:
                    findings.append({"kind": "outside", "claim": c.Label, "other": m.Label, "volume": out.Volume,
                                     "text": f"{m.Label} sticks out of {c.Label}" + (f" (margin {margin:g} mm)" if
                                                                                    margin else "") +
                                     f": {out.Volume:.1f} mm³ outside"})
                    bad.append(out)
                own.append(m.Name)
        grown = _grown(cshape, margin)
        for o, s in layout:
            if o.Name in own:
                continue
            common = s.common(grown)
            if common.Volume > TOL:
                who = ", ".join(x.Label for x in owner_of.get(o.Name, [])) or "no claim"
                findings.append({"kind": "intrusion", "claim": c.Label, "other": o.Label, "volume": common.Volume,
                                 "text": f"{o.Label} ({who}) enters {c.Label}" + (f" or its {margin:g} mm margin"
                                                                                  if margin else "") +
                                 f": {common.Volume:.1f} mm³"})
                bad.append(common)
    for i, a in enumerate(cs):
        for b in cs[i + 1:]:
            if a.ClaimType == "Keep-out" and b.ClaimType == "Keep-out":
                continue
            common = a.Shape.common(b.Shape)
            if common.Volume > TOL:
                findings.append({"kind": "overlap", "claim": a.Label, "other": b.Label, "volume": common.Volume,
                                 "text": f"{a.Label} and {b.Label} claim the same {common.Volume:.1f} mm³"})
                bad.append(common)
    claimed = {n for n in owner_of}
    for o, _ in layout:
        if o.Name not in claimed:
            findings.append({"kind": "unclaimed", "claim": "", "other": o.Label, "volume": 0.0,
                             "text": f"{o.Label} belongs to no claim"})
    for c in cs:
        mine = [f["text"] for f in findings if f["claim"] == c.Label or (f["kind"] == "overlap" and f["other"] == c.Label)]
        c.Status = "VIOLATED" if mine else "OK"
        c.Findings = mine
        colour(c)
    show_violations(doc, bad)
    return findings, bad


def show_violations(doc, solids):
    import Part
    old = doc.getObject("ClaimViolations")
    if not solids:
        if old is not None:
            doc.removeObject(old.Name)
        return None
    obj = old or doc.addObject("Part::Feature", "ClaimViolations")
    obj.Label = "Claim violations"
    obj.Shape = Part.makeCompound(solids)
    vo = getattr(obj, "ViewObject", None)
    if vo is not None:
        vo.ShapeColor = (0.9, 0.05, 0.05)
        vo.LineColor = (0.6, 0.0, 0.0)
        vo.Transparency = 0
    return obj


def report(doc, findings):
    cs = claims(doc)
    lines = [f"Volume claims of {doc.Label}", ""]
    lines.append(f"{'Claim':<26} {'Owner':<16} {'Type':<9} {'Volume mm³':>14} {'Margin':>7}  Members  Status")
    for c in cs:
        lines.append(f"{c.Label[:26]:<26} {c.Owner[:16]:<16} {c.ClaimType:<9} {c.Shape.Volume:>14,.0f} "
                     f"{float(c.Margin):>7g}  {len(c.Members):>7}  {c.Status}")
    lines.append("")
    order = {"overlap": 0, "outside": 1, "intrusion": 2, "unclaimed": 3}
    if not findings:
        lines.append("No findings: every part is inside its claim, no claim is entered by another owner's part, "
                     "and no space is claimed twice.")
    for f in sorted(findings, key=lambda f: (order[f["kind"]], -f["volume"])):
        tag = {"overlap": "OVERLAP", "outside": "OUTSIDE", "intrusion": "INTRUSION", "unclaimed": "unclaimed"}[f["kind"]]
        lines.append(f"  {tag:<10} {f['text']}")
    return "\n".join(lines)


# ------------------------------------------------------------------ commands
class ClaimPanel:
    """New volume claim: owner, type, size or source, margin; members = the selected parts."""

    def __init__(self):
        self.doc = App.ActiveDocument
        sel = Gui.Selection.getSelection()
        self.members = [o for o in sel if not isinstance(getattr(o, "Proxy", None), ClaimFeature)]
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Volume Claim")
        lay = QtWidgets.QFormLayout(self.form)
        self.owner = QtWidgets.QLineEdit()
        self.owner.setObjectName("owner")
        self.kind = QtWidgets.QComboBox()
        self.kind.setObjectName("claimType")
        self.kind.addItems(["Keep-in", "Keep-out"])
        self.size = []
        for n in ("Length", "Width", "Height"):
            s = QtWidgets.QDoubleSpinBox()
            s.setObjectName(n.lower())
            s.setRange(0.01, 1e6)
            s.setDecimals(2)
            s.setSuffix(" mm")
            s.setValue(100.0)
            self.size.append(s)
        self.pos = []
        for n in ("X", "Y", "Z"):
            s = QtWidgets.QDoubleSpinBox()
            s.setObjectName(f"position{n}")
            s.setRange(-1e6, 1e6)
            s.setDecimals(2)
            s.setSuffix(" mm")
            self.pos.append(s)
        self.margin = QtWidgets.QDoubleSpinBox()
        self.margin.setObjectName("margin")
        self.margin.setRange(0, 1000)
        self.margin.setDecimals(2)
        self.margin.setSuffix(" mm")
        lay.addRow("Owner", self.owner)
        lay.addRow("Type", self.kind)
        for n, s in zip(("Length (X)", "Width (Y)", "Height (Z)"), self.size):
            lay.addRow(n, s)
        for n, s in zip(("Corner X", "Corner Y", "Corner Z"), self.pos):
            lay.addRow(n, s)
        lay.addRow("Margin", self.margin)
        mem = QtWidgets.QLabel("Members: " + (", ".join(o.Label for o in self.members) or
                                              "none (select the parts first, or add them to Members later)"))
        mem.setWordWrap(True)
        mem.setObjectName("members")
        lay.addRow(mem)
        if self.members:
            import Part
            bb = None
            for o in self.members:
                try:
                    b = Part.getShape(o, "", transform=True).BoundBox
                    bb = b if bb is None else bb.united(b)
                except Exception:
                    continue
            if bb is not None:                    # start from the members' box, a little larger
                pad = max(bb.DiagonalLength * 0.05, 1.0)
                for s, v in zip(self.size, (bb.XLength, bb.YLength, bb.ZLength)):
                    s.setValue(v + 2 * pad)
                for s, v in zip(self.pos, (bb.XMin, bb.YMin, bb.ZMin)):
                    s.setValue(v - pad)

    def accept(self):
        self.doc.openTransaction("Volume Claim")
        create(self.doc, self.owner.text().strip(), self.members if self.kind.currentText() == "Keep-in" else [],
               tuple(s.value() for s in self.size), App.Placement(App.Vector(*(s.value() for s in self.pos)),
                                                                  App.Rotation()),
               self.kind.currentText(), self.margin.value())
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        Gui.Selection.clearSelection()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


class NewClaim:
    def GetResources(self):
        return {"MenuText": "Volume Claim",
                "ToolTip": "Reserve a space in the layout: an owner, keep-in (space for the owner's parts, select "
                           "them first) or keep-out (no part may enter), a margin",
                "Pixmap": config.resource("icons", "volume_claim.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        Gui.Control.showDialog(ClaimPanel())


last = {}


class CheckClaims:
    def GetResources(self):
        return {"MenuText": "Check Volume Claims",
                "ToolTip": "Is every part inside its claim, does any part enter another owner's claim or keep-out, "
                           "is any space claimed twice? Offending volumes are shown in red",
                "Pixmap": config.resource("icons", "check_claims.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and bool(claims(App.ActiveDocument))

    def Activated(self):
        from .commands import show_information
        doc = App.ActiveDocument
        doc.openTransaction("Check Volume Claims")
        findings, _ = check(doc)
        doc.recompute()
        doc.commitTransaction()
        last["findings"] = findings
        show_information(report(doc, findings))


COMMANDS = {"NXStyle_VolumeClaim": NewClaim(), "NXStyle_CheckVolumeClaims": CheckClaims()}
