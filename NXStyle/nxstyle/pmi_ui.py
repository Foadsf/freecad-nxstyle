# SPDX-License-Identifier: LGPL-2.1-or-later
"""PMI: NX's Product and Manufacturing Information, 3D annotations that belong to the model.

FreeCAD has no PMI. These are document objects (App::FeaturePython) in a PMI folder of the Part
Navigator, as in NX:

- PMI Dimension: a distance between two faces, or the diameter or radius of a cylinder, measured
  from the model (it follows design changes), with deviations, Basic, and a count (4X);
- PMI Feature Control Frame: characteristic, Ø zone, tolerance, material condition, datums;
- PMI Datum Feature Symbol: a letter on a face.

Each is attached to faces by a link that FreeCAD's topological naming keeps on the same face.
They are drawn in the graphics window at constant screen size with a leader to the face; feature
control frames and datum symbols use the same drawing as NXStyle's Drafting dialogs (gdt.py).
The semantic content (pmi.py) feeds the inspection plan, the functional gauge sizes, the ASME
checks, the tolerance stack-up (Add from PMI), Drafting's Inherit PMI and the technical data
package.
"""

import FreeCAD as App
import FreeCADGui as Gui

from . import config, gdt, iso, pmi, refs, theme
from .qt import QtCore, QtGui, QtWidgets

TYPES = ["Dimension", "Feature Control Frame", "Datum Feature"]
DIM_TYPES = ["Distance", "Diameter", "Radius"]
MODIFIERS = ["None", "MMC", "LMC"]
FRAME_STYLES = ["Single Frame", "Composite Frame", "Stacked Frames"]
PX_PER_MM = 4.0           # label images: 7 mm frame height = 28 px


def _prop(obj, kind, name, group, doc, value=None, mode=None):
    if name not in obj.PropertiesList:
        obj.addProperty(kind, name, group, doc)
        if value is not None:
            setattr(obj, name, value)
    if mode is not None:
        obj.setEditorMode(name, mode)


# ------------------------------------------------------------------ the document object
class PMIFeature:
    def __init__(self, obj, kind):
        obj.Proxy = self
        self.setup(obj, kind)

    def setup(self, obj, kind=None):
        g = "PMI"
        _prop(obj, "App::PropertyEnumeration", "PMIType", g, "What this PMI is")
        if kind is not None:
            obj.PMIType = TYPES
            obj.PMIType = kind
        obj.setEditorMode("PMIType", 1)
        _prop(obj, "App::PropertyLinkSubList", "References", g, "The faces (or edges) it is attached to")
        _prop(obj, "App::PropertyInteger", "Number", g, "Characteristic number (balloon) in the inspection plan", 0)
        _prop(obj, "App::PropertyVector", "LabelOffset", g, "Where the label sits, from the attachment point (mm)")
        _prop(obj, "App::PropertyVector", "Anchor", g, "Attachment point on the model", mode=1)
        _prop(obj, "App::PropertyVector", "Anchor2", g, "Second attachment point (distance)", mode=2)
        _prop(obj, "App::PropertyString", "FeatureType", g, "plane, hole, pin, width or other", mode=1)
        _prop(obj, "App::PropertyString", "Callout", g, "The annotation as text", mode=1)
        _prop(obj, "App::PropertyBool", "Valid", g, "Measured from its faces at the last recompute; when false the "
              "Callout says why, and the inspection plan, drawings, analyses and exports do not use its old values",
              True, mode=1)
        _prop(obj, "App::PropertyLinkList", "Views", g, "The model views it is displayed in (empty: all views); "
              "PMI > Display in Views changes them")
        k = obj.PMIType
        if k != "Datum Feature":
            _prop(obj, "App::PropertyFloat", "Uncertainty", "Inspection", "Expanded measurement uncertainty U (k = 2) "
                  "of the method that checks it (mm); 0 = not stated. Gives the TUR and the ISO 14253-1 acceptance "
                  "limits in the inspection plan", 0.0)
        if k == "Dimension":
            d = "Dimension"
            _prop(obj, "App::PropertyEnumeration", "DimensionType", d, "Distance, Diameter or Radius")
            if kind is not None:
                obj.DimensionType = DIM_TYPES
            _prop(obj, "App::PropertyFloat", "Nominal", d, "Measured from the model (mm)", mode=1)
            _prop(obj, "App::PropertyFloat", "UpperDeviation", d, "Plus tolerance (mm)", 0.0)
            _prop(obj, "App::PropertyFloat", "LowerDeviation", d, "Minus tolerance, as a positive number (mm)", 0.0)
            _prop(obj, "App::PropertyString", "Fit", d, "ISO 286 tolerance class, e.g. H7 (hole) or g6 (shaft); "
                  "it gives the deviations", "")
            _prop(obj, "App::PropertyBool", "Envelope", d, "ISO 14405 envelope (E): perfect form at MMC", False)
            _prop(obj, "App::PropertyBool", "Basic", d, "Theoretically exact (boxed), no tolerance", False)
            _prop(obj, "App::PropertyInteger", "Quantity", d, "Number of like features (4X)", 1)
        elif k == "Feature Control Frame":
            f = "Feature Control Frame"
            _prop(obj, "App::PropertyEnumeration", "Characteristic", f, "Geometric characteristic")
            if kind is not None:
                obj.Characteristic = [c.title() for c in gdt.CHARACTERISTICS]
            _prop(obj, "App::PropertyFloat", "Tolerance", f, "Tolerance zone (mm)", 0.1)
            _prop(obj, "App::PropertyBool", "ZoneDiameter", f, "Ø: a cylindrical zone", False)
            _prop(obj, "App::PropertyEnumeration", "MaterialCondition", f, "Modifier on the tolerance")
            if kind is not None:
                obj.MaterialCondition = MODIFIERS
            _prop(obj, "App::PropertyStringList", "DatumReferences", f,
                  "Primary, secondary, tertiary datum, e.g. A, D(M), B")
            low = "Lower Row"
            for name, kind_, doc_ in (
                    ("FrameStyle", "App::PropertyEnumeration", "Single Frame; Composite Frame (ASME Y14.5: the lower "
                     "row refines spacing and orientation only); Stacked Frames (two single-segment frames)"),
                    ("LowerTolerance", "App::PropertyFloat", "The lower row's tolerance (mm), tighter than the upper"),
                    ("LowerMaterialCondition", "App::PropertyEnumeration", "Modifier on the lower row's tolerance"),
                    ("LowerDatumReferences", "App::PropertyStringList", "The lower row's datums (a composite frame "
                     "repeats the upper row's, in order: they orient, never locate)")):
                _prop(obj, kind_, name, low, doc_)
            if not obj.getEnumerationsOfProperty("FrameStyle"):     # new, or a part from before two-row frames
                obj.FrameStyle = FRAME_STYLES
                obj.FrameStyle = "Single Frame"
            if not obj.getEnumerationsOfProperty("LowerMaterialCondition"):
                obj.LowerMaterialCondition = MODIFIERS
                obj.LowerMaterialCondition = "None"
        elif k == "Datum Feature":
            _prop(obj, "App::PropertyString", "Letter", "Datum Feature", "Datum letter", "A")

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def execute(self, obj):
        """Measure from the faces and write the callout; any failure makes the PMI invalid (Valid false, the
        reason in Callout) instead of leaving the last good value looking current (measured: a diameter whose
        face became a plane kept its old nominal and callout)."""
        before = obj.Callout
        error = evaluate(obj)
        if "Valid" in obj.PropertiesList and obj.Valid != (error is None):
            obj.Valid = error is None
        if error is not None:
            obj.Callout = f"error: {error}"
        if obj.Callout != before:
            schedule_refresh(obj.Document)         # drawings that inherited it show the new callout


def evaluate(obj):
    """Measure obj from its references and set its callout; returns the reason it is not valid, or None."""
    picks = [(o, s) for o, subs in obj.References for s in (subs or [""])]
    if not picks:
        return "it is attached to nothing (its faces were removed)"
    try:
        shapes = [refs.resolve(o, s) for o, s in picks]
    except Exception as e:
        return f"its face cannot be found ({e})"
    obj.Anchor = refs.anchor(shapes[0])
    obj.FeatureType = classify(shapes)
    if obj.PMIType == "Dimension":
        problem = measure_dimension(obj, shapes)
        if problem:
            return problem
    try:
        obj.Callout = pmi.text(semantic(obj))
    except ValueError as e:                      # e.g. a fit class ISO 286 does not cover
        return str(e)
    return None


def valid(obj):
    return bool(getattr(obj, "Valid", True))


def require_valid(obj):
    """Raise ValueError when a PMI an analysis reads is not valid: its values are not current."""
    if obj is not None and not valid(obj):
        raise ValueError(f"{obj.Label} is not valid ({obj.Callout}): fix its references first")


def classify(shapes):
    if len(shapes) == 1:
        return refs.feature_type(shapes[0])
    kinds = {refs.feature_type(s) for s in shapes}
    if len(kinds) == 1 and kinds <= {"hole", "pin"}:      # a pattern (4X): its holes, or its pins
        return kinds.pop()
    a, b = shapes[0], shapes[1]
    if refs.surface_kind(a) == "plane" and refs.surface_kind(b) == "plane":
        na, nb = refs.plane_normal(a), refs.plane_normal(b)
        if na.dot(nb) < -1 + 1e-9:                    # opposed: a slot or a tab
            towards = na.dot(refs.anchor(b) - refs.anchor(a)) > 0
            return "width" if not towards else "slot"
    return "other"


def measure_dimension(obj, shapes):
    """Set Nominal (and Anchor2) from the shapes; returns why it cannot be measured, or None."""
    kind = obj.DimensionType
    if kind in ("Diameter", "Radius"):
        k = refs.surface_kind(shapes[0])
        if k not in ("cylinder", "circle"):
            return f"a {kind.lower()} needs a cylindrical face or a circular edge, not a {k}"
        r = shapes[0].Surface.Radius if k == "cylinder" else shapes[0].Curve.Radius
        obj.Nominal = 2 * r if kind == "Diameter" else r
        obj.Anchor2 = obj.Anchor
        return None
    if len(shapes) < 2:
        return "a distance needs two faces"
    a, b = shapes[0], shapes[1]
    axis = refs.default_axis(a, b)
    d = refs.signed_distance(a, b, axis)
    obj.Nominal = abs(d)
    obj.Anchor2 = obj.Anchor + axis * d
    return None


def feature_key(obj):
    picks = [(o, s) for o, subs in obj.References for s in (subs or [""])]
    return " | ".join(refs.describe(o, s) for o, s in picks)


def semantic(obj):
    """The PMI as a pmi.py annotation dict."""
    ft = obj.FeatureType or "other"
    a = {"id": obj.Name, "label": obj.Label, "feature": feature_key(obj),
         "feature_type": "width" if ft == "slot" else ft, "number": obj.Number}
    if ft == "slot":
        a["internal"] = True
    elif ft == "width":
        a["internal"] = False
    k = obj.PMIType
    if k == "Dimension":
        a.update(kind="dimension", dim_type=obj.DimensionType.lower(), nominal=float(obj.Nominal),
                 plus=0.0 if obj.Basic else float(obj.UpperDeviation),
                 minus=0.0 if obj.Basic else float(obj.LowerDeviation), basic=bool(obj.Basic),
                 count=max(1, int(obj.Quantity)), fit=(getattr(obj, "Fit", "") or "").strip(),
                 envelope=bool(getattr(obj, "Envelope", False)))
    elif k == "Feature Control Frame":
        mod = {"None": ""}.get(obj.MaterialCondition, obj.MaterialCondition)
        a.update(kind="fcf", characteristic=obj.Characteristic.lower(), tolerance=float(obj.Tolerance),
                 diameter=bool(obj.ZoneDiameter), modifier=mod, datums=[parse_datum(d) for d in obj.DatumReferences
                                                                       if d.strip()])
        style = getattr(obj, "FrameStyle", "Single Frame")
        if style != "Single Frame" and float(getattr(obj, "LowerTolerance", 0.0)) > 0:
            lm = {"None": ""}.get(obj.LowerMaterialCondition, obj.LowerMaterialCondition)
            a["frame"] = "composite" if style == "Composite Frame" else "single"
            a["lower"] = {"tolerance": float(obj.LowerTolerance), "modifier": lm,
                          "datums": [parse_datum(d) for d in obj.LowerDatumReferences if d.strip()]}
    else:
        a.update(kind="datum", letter=(obj.Letter or "").strip().upper())
    views = [v.Label for v in getattr(obj, "Views", []) or []]
    if views:
        a["views"] = views
    u = float(getattr(obj, "Uncertainty", 0.0) or 0.0)
    if u > 0:
        a["uncertainty"] = u
    if not valid(obj):
        a["valid"] = False
        a["invalid"] = (obj.Callout or "").replace("error: ", "", 1)
    return a


def parse_datum(text):
    t = text.strip().upper().replace(" ", "")
    for tag, mod in (("(M)", "MMC"), ("(L)", "LMC"), ("MMC", "MMC"), ("LMC", "LMC"), ("MMB", "MMC"), ("LMB", "LMC")):
        if t.endswith(tag):
            return [t[: -len(tag)], mod]
    return [t, ""]


def folder(doc):
    """The Part Navigator's PMI folder; it also holds the part's tolerancing standard and general
    tolerance note (what the title block of a drawing says)."""
    g = doc.getObject("PMI")
    if g is None or not g.isDerivedFrom("App::DocumentObjectGroup"):
        g = doc.addObject("App::DocumentObjectGroup", "PMI")
        g.Label = "PMI"
    if "Standard" not in g.PropertiesList:
        g.addProperty("App::PropertyEnumeration", "Standard", "Tolerancing",
                      "ISO GPS (ISO 8015 independency, ISO 2768) or ASME Y14.5 (Rule #1)")
        g.Standard = ["ISO GPS", "ASME Y14.5"]
        g.Standard = "ISO GPS"
    if "GeneralTolerance" not in g.PropertiesList:
        g.addProperty("App::PropertyString", "GeneralTolerance", "Tolerancing",
                      "General tolerances for dimensions without their own, e.g. ISO 2768-mK (add -E for the "
                      "envelope on every feature of size)")
    views_group(doc)
    return g


# ------------------------------------------------------------------ model views
VIEWS_GROUP = "ModelViews"


class ModelViewFeature:
    """An NX model view: a viewing direction and screen up. The part's work view is the Model Views
    folder's WorkView; new PMI goes into it."""

    def __init__(self, obj):
        obj.Proxy = self
        self.setup(obj)

    def setup(self, obj):
        g = "Model View"
        _prop(obj, "App::PropertyVector", "Direction", g, "Viewing direction, from the eye into the model")
        _prop(obj, "App::PropertyVector", "Up", g, "What is up on the screen")

    def onDocumentRestored(self, obj):
        self.setup(obj)

    def execute(self, obj):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None


class ModelViewView:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.vobj = vobj

    def getIcon(self):
        return config.resource("icons", "model_view.svg")

    def doubleClicked(self, vobj):
        activate(vobj.Object)
        return True

    def dumps(self):
        return None

    def loads(self, state):
        return None


def views_group(doc, make=True):
    """The Part Navigator's Model Views folder, with NX's eight standard views when it is made."""
    g = doc.getObject(VIEWS_GROUP)
    if g is not None and g.isDerivedFrom("App::DocumentObjectGroup"):
        return g
    if not make:
        return None
    from . import pmi_views
    g = doc.addObject("App::DocumentObjectGroup", VIEWS_GROUP)
    g.Label = "Model Views"
    g.addProperty("App::PropertyLink", "WorkView", "Model Views",
                  "The work view: new PMI goes into it, PMI not displayed in it are hidden (none: all show)")
    for name in pmi_views.ORDER:
        make_view(doc, name, *pmi_views.STANDARD[name], group=g)
    return g


def make_view(doc, label, direction, up, group=None):
    v = doc.addObject("App::FeaturePython", "ModelView")
    ModelViewFeature(v)
    v.Label = label
    v.Direction = App.Vector(*direction)
    v.Up = App.Vector(*up)
    if App.GuiUp:
        ModelViewView(v.ViewObject)
    (group or views_group(doc)).addObject(v)
    return v


def model_views(doc):
    g = views_group(doc, make=False)
    return [o for o in g.Group if isinstance(getattr(o, "Proxy", None), ModelViewFeature)] if g else []


def work_view(doc):
    g = views_group(doc, make=False)
    return getattr(g, "WorkView", None) if g is not None else None


def view_of(obj):
    """(direction, up) of the plane a PMI's label lies in: its first model view's, else Front's."""
    from . import pmi_views
    views = getattr(obj, "Views", None) or []
    if views:
        v = views[0]
        return tuple(v.Direction), tuple(v.Up)
    return pmi_views.STANDARD["Front"]


def apply_visibility(doc):
    """Show the PMI displayed in the work view (all of them when there is none), as NX does."""
    from . import pmi_views
    w = work_view(doc)
    shown = []
    for p in all_pmi(doc):
        show = pmi_views.shown([v.Name for v in getattr(p, "Views", []) or []], w.Name if w else None)
        if App.GuiUp and p.ViewObject is not None and p.ViewObject.Visibility != show:
            p.ViewObject.Visibility = show
        if show:
            shown.append(p.Name)
    return shown


def activate(view):
    """Make view the work view: the camera turns to it, and only its PMI show."""
    from . import pmi_views
    doc = view.Document
    g = views_group(doc)
    g.WorkView = view
    for v in model_views(doc):
        v.Label2 = "Work" if v is view else ""
    shown = apply_visibility(doc)
    if App.GuiUp:
        gd = Gui.getDocument(doc.Name)
        av = gd.ActiveView if gd is not None else None
        if av is not None and hasattr(av, "setCameraOrientation"):
            if hasattr(av, "stopAnimating"):
                av.stopAnimating()        # a view turn still running (Home, F8) would turn the camera back
            av.setCameraOrientation(pmi_views.quaternion(tuple(view.Direction), tuple(view.Up)))
            av.fitAll()
    last_view.update(work=view.Label, shown=shown)
    return shown


def show_all(doc):
    g = views_group(doc, make=False)
    if g is not None:
        g.WorkView = None
        for v in model_views(doc):
            v.Label2 = ""
    return apply_visibility(doc)


def replace_label(obj):
    """Put a PMI's label into the first free row of its view's column."""
    obj.LabelOffset = App.Vector()
    obj.LabelOffset = default_offset(obj)


last_view = {}


def settings(doc):
    """(standard 'ISO' or 'ASME', general tolerance note or None) of a part."""
    g = doc.getObject("PMI")
    if g is None or "Standard" not in g.PropertiesList:
        return "ISO", None
    return ("ASME" if str(g.Standard).startswith("ASME") else "ISO"), (g.GeneralTolerance.strip() or None)


def all_pmi(doc):
    return [o for o in doc.Objects if isinstance(getattr(o, "Proxy", None), PMIFeature)]


def create(kind, picks, doc=None, **values):
    doc = doc or App.ActiveDocument
    name = {"Dimension": "PMI_Dimension", "Feature Control Frame": "PMI_FCF", "Datum Feature": "PMI_Datum"}[kind]
    obj = doc.addObject("App::FeaturePython", name)
    PMIFeature(obj, kind)
    obj.References = list(picks)
    for k, v in values.items():
        setattr(obj, k, v)
    folder(doc).addObject(obj)
    w = work_view(doc)
    if w is not None and "Views" not in values:
        obj.Views = [w]                   # NX: a new PMI goes into the work view
    if App.GuiUp:
        PMIView(obj.ViewObject)
    doc.recompute()
    if obj.LabelOffset.Length < 1e-9:
        obj.LabelOffset = default_offset(obj)
    obj.Label = default_label(obj)
    return obj


def default_label(obj):
    k = obj.PMIType
    if k == "Datum Feature":
        return f"Datum {obj.Letter}"
    if k == "Feature Control Frame":
        return obj.Characteristic
    return f"{obj.DimensionType} {obj.Nominal:.3f}"


def model_size(obj):
    bb = model_box(obj)
    return max(bb.DiagonalLength, 10.0) if bb else 50.0


def model_box(obj):
    """The box all of the document's solids fill, so every PMI label shares one column and one row
    spacing, whichever part it is on (a pin on the bench, a hole in the module); the referenced
    objects' box when the document has no solid."""
    bb = None
    for o in obj.Document.Objects:
        if o.isDerivedFrom("PartDesign::Feature") and not o.isDerivedFrom("PartDesign::Body"):
            continue                            # a body's features lie inside the body's box
        try:
            s = o.Shape
            if s.isNull() or not s.Solids:
                continue
            b = s.BoundBox
        except Exception:
            continue
        bb = b if bb is None else bb.united(b)
    if bb is not None:
        return bb
    for o, _ in obj.References:
        try:
            b = o.Shape.BoundBox
        except Exception:
            continue
        bb = b if bb is None else bb.united(b)
    return bb


def _corners(bb):
    return [(x, y, z) for x in (bb.XMin, bb.XMax) for y in (bb.YMin, bb.YMax) for z in (bb.ZMin, bb.ZMax)]


def label_position(obj, row):
    """Where the row-th PMI label of its model view sits: one column left of the part as the view shows
    it, rows top down, in the view's plane (NX puts PMI in the plane of the view it belongs to), so labels
    never cover each other or the part; leaders run to the faces. PMI in no view use the Front plane."""
    from . import pmi_views
    size = model_size(obj)
    bb = model_box(obj)
    if bb is None:
        return App.Vector(-size, 0, -0.14 * size * row)
    return App.Vector(*pmi_views.label_point(_corners(bb), size, *view_of(obj), row))


def default_offset(obj):
    """The label's place, as an offset from the attachment point (see label_position): the first row
    of its view's column no other label is in (counting the others would reuse a deleted PMI's row while
    the row after it is still taken)."""
    from . import pmi_views
    size = model_size(obj)
    bb = model_box(obj)
    plane = view_of(obj)
    used = set()
    for p in all_pmi(obj.Document):
        if p is obj or "LabelOffset" not in p.PropertiesList or p.LabelOffset.Length < 1e-9 or bb is None:
            continue
        if view_of(p) != plane:
            continue                      # another view's column
        at = App.Vector(p.Anchor) + App.Vector(p.LabelOffset)
        centre = pmi_views.label_row(_corners(bb), size, *plane, (at.x, at.y, at.z), exact=True)
        used |= pmi_views.rows_taken(centre, label_rows(p))
    return label_position(obj, pmi_views.free_rows(used, label_rows(obj))) - App.Vector(obj.Anchor)


def label_rows(obj):
    """How many rows of the label column a label takes: a datum symbol (its letter, stem and triangle) and
    a two-row frame take two, so they do not run into the next label (labels keep their size on screen)."""
    import math
    try:
        _, _, h = label_svg(obj)
    except Exception:
        return 1
    return max(1, math.ceil(h / gdt.H - 0.05))       # a frame (7 mm) 1, a datum symbol (13) or two rows (14) 2


# ------------------------------------------------------------------ the labels
def label_svg(obj):
    """(svg, width mm, height mm) of the label drawn in the graphics window."""
    a = semantic(obj)
    if a["kind"] == "fcf":
        low = pmi.lower(a)
        if low:
            rows = [(f"{a['tolerance']:g}", a["diameter"], a["modifier"], [tuple(d) for d in a["datums"]]),
                    (f"{low['tolerance']:g}", a["diameter"], low.get("modifier", ""), [tuple(d) for d in low["datums"]])]
            return gdt.stacked_frame(a["characteristic"], rows, pmi.composite(a))
        svg, w = gdt.feature_control_frame(a["characteristic"], f"{a['tolerance']:g}", a["diameter"], a["modifier"],
                                           [tuple(d) for d in a["datums"]])
        return svg, w, gdt.H
    if a["kind"] == "datum":
        svg, (w, h) = gdt.datum_feature_symbol(a["letter"] or "?", "bottom")
        return svg, w, h
    text = pmi.dimension_text(a)
    if a.get("basic"):
        text = text.replace("[", "").replace("]", "")
    w = gdt.text_width(text) + 3.0
    h = gdt.H
    frame = (f'<rect x="0.2" y="0.2" width="{w - 0.4:.3f}" height="{h - 0.4:.3f}" fill="white" stroke="black" '
             f'stroke-width="0.35"/>' if a.get("basic") else
             f'<rect x="0" y="0" width="{w:.3f}" height="{h:.3f}" fill="white" fill-opacity="0.85" stroke="none"/>')
    from xml.sax.saxutils import escape
    body = frame + (f'<text x="{w / 2:.3f}" y="{h / 2 + gdt.TEXT / 2 - 0.3:.3f}" font-family="{gdt.FONT}" '
                    f'font-size="{gdt.TEXT}" text-anchor="middle">{escape(text)}</text>')
    return gdt._svg(w, h, body), w, h


def _qtsvg():
    for mod in ("PySide6", "PySide2", "PySide"):
        try:
            return __import__(mod, fromlist=["QtSvg"]).QtSvg
        except ImportError:
            continue
    return None


def label_font():
    f = QtGui.QFont("DejaVu Sans")
    f.setPixelSize(int(gdt.TEXT * PX_PER_MM))
    return f


def render_label(obj, number=0):
    """The label as a QImage (RGBA), with the characteristic number in a balloon when given. Frames and
    datum symbols come from gdt.py's SVG; a dimension's text is measured with the font it is drawn in."""
    a = semantic(obj)
    QtSvg = _qtsvg()
    text = None
    if not pmi.is_valid(a):                        # say what is wrong, never the last good value
        text = obj.Callout or "error"
        fm = QtGui.QFontMetricsF(label_font())
        W, H = int(fm.horizontalAdvance(text) + 14), int(gdt.H * PX_PER_MM) + 2
    elif a["kind"] == "dimension":
        text = pmi.dimension_text(a).replace("[", "").replace("]", "")
        fm = QtGui.QFontMetricsF(label_font())
        W, H = int(fm.horizontalAdvance(text) + 14), int(gdt.H * PX_PER_MM) + 2
    else:
        svg, w, h = label_svg(obj)
        W, H = int(w * PX_PER_MM) + 2, int(h * PX_PER_MM) + 2
    extra = int(min(H, int(gdt.H * PX_PER_MM) + 2) * 1.05) if number else 0     # room for a one-row balloon
    img = QtGui.QImage(W + extra, H, QtGui.QImage.Format_RGBA8888)
    img.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    if text is not None:
        bad = not pmi.is_valid(a)
        box = QtCore.QRectF(extra + 1, 1, W - 3, H - 3)
        p.setBrush(QtGui.QColor(255, 255, 255, 230))
        p.setPen(QtGui.QPen(QtGui.QColor("#c62828"), 1.4) if bad else
                 QtGui.QPen(QtGui.QColor("#000000"), 1.4) if a.get("basic") else QtCore.Qt.NoPen)
        p.drawRect(box)
        p.setPen(QtGui.QColor("#c62828" if bad else "#000000"))
        p.setFont(label_font())
        p.drawText(box, QtCore.Qt.AlignCenter, text)
    elif QtSvg is not None:
        r = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
        r.render(p, QtCore.QRectF(extra, 0, W - 2, H - 2))
    if number:
        p.setPen(QtGui.QPen(QtGui.QColor(theme.color("accent")), 2))
        p.setBrush(QtGui.QColor(theme.color("panel")))
        d = min(H, int(gdt.H * PX_PER_MM) + 2) - 4        # one row's size, on a two-row frame too
        p.drawEllipse(1, 1, d, d)
        f = p.font()
        f.setPixelSize(int(d * 0.55))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QtGui.QColor(theme.color("accent")))
        p.drawText(QtCore.QRectF(1, 1, d, d), QtCore.Qt.AlignCenter, str(number))
    p.end()
    return img


class PMIView:
    """Leader from the face to the label; the label is an image at constant screen size."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        from pivy import coin
        self.vobj = vobj
        self.root = coin.SoSeparator()
        self.geo = coin.SoSeparator()
        self.root.addChild(self.geo)
        vobj.addDisplayMode(self.root, "PMI")
        self.update(vobj.Object)

    def getDisplayModes(self, vobj):
        return ["PMI"]

    def getDefaultDisplayMode(self):
        return "PMI"

    def setDisplayMode(self, mode):
        return mode

    def getIcon(self):
        obj = getattr(getattr(self, "vobj", None), "Object", None)
        k = getattr(obj, "PMIType", "")
        name = {"Feature Control Frame": "feature_control_frame", "Datum Feature": "datum_feature_symbol"}.get(
            k, "pmi_dimension")
        return config.resource("icons", f"{name}.svg")

    def updateData(self, obj, prop):
        if prop in ("Callout", "Anchor", "Anchor2", "LabelOffset", "Number"):
            self.update(obj)

    def onChanged(self, vobj, prop):
        pass

    def dumps(self):
        return None

    def loads(self, state):
        return None

    def update(self, obj):
        from pivy import coin
        try:
            self.geo.removeAllChildren()
        except Exception:
            return
        if "Anchor" not in obj.PropertiesList:
            return
        a, off = App.Vector(obj.Anchor), App.Vector(obj.LabelOffset)
        if off.Length < 1e-9:
            return
        at = a + off
        col = coin.SoBaseColor()
        col.rgb = (0.05, 0.05, 0.05)
        style = coin.SoDrawStyle()
        style.lineWidth = 1.5
        self.geo += [col, style]
        pts = [a, at]
        if obj.PMIType == "Dimension" and obj.DimensionType == "Distance":
            b = App.Vector(obj.Anchor2)
            d = b - a
            if d.Length > 1e-9:
                # the dimension line stays beside the measured faces, moved a little towards the label column;
                # the leader runs from its middle to the label
                u = App.Vector(d).normalize()
                toward = at - (a + b) * 0.5
                perp = toward - u * toward.dot(u)
                reach = min(model_size(obj) * 0.12, perp.Length)
                perp = App.Vector(perp).normalize() * reach if perp.Length > 1e-9 else App.Vector()
                pa, pb = a + perp, b + perp
                pts = [a, pa, b, pb, pa, pb, (pa + pb) * 0.5, at]
        coords = coin.SoCoordinate3()
        coords.point.setValues(0, len(pts), [(p.x, p.y, p.z) for p in pts])
        ls = coin.SoLineSet()
        ls.numVertices.setValues(0, len(pts) // 2, [2] * (len(pts) // 2))
        self.geo += [coords, ls]
        dot = coin.SoSeparator()
        tr = coin.SoTranslation()
        tr.translation = (a.x, a.y, a.z)
        mk = coin.SoMarkerSet()
        mk.markerIndex = coin.SoMarkerSet.CIRCLE_FILLED_5_5
        mc = coin.SoCoordinate3()
        mc.point.setValue(0, 0, 0)
        dot += [tr, mc, mk]
        self.geo.addChild(dot)
        lab = coin.SoSeparator()
        lt = coin.SoTranslation()
        lt.translation = (at.x, at.y, at.z)
        lab.addChild(lt)
        try:
            img = render_label(obj, obj.Number)
            node = coin.SoImage()
            node.vertAlignment = coin.SoImage.HALF
            node.horAlignment = coin.SoImage.RIGHT       # the label ends where its leader starts
            flipped = img.mirrored(False, True)
            data = bytes(flipped.constBits())[: flipped.width() * flipped.height() * 4]
            node.image.setValue(coin.SbVec2s(flipped.width(), flipped.height()), 4, data)
            lab.addChild(node)
        except Exception as e:                    # no image support: the callout as text
            App.Console.PrintLog(f"NXStyle PMI: label image failed ({e}); text instead\n")
            font = coin.SoFont()
            font.size = 13
            txt = coin.SoText2()
            txt.string = obj.Callout
            lab += [font, txt]
        self.geo.addChild(lab)


# ------------------------------------------------------------------ dialogs
class _Panel:
    title = ""
    kind = ""

    def __init__(self):
        self.picks = refs.selection_refs()
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(self.title)
        self.layout = QtWidgets.QFormLayout(self.form)
        self.where = QtWidgets.QLabel()
        self.where.setWordWrap(True)
        self.where.setObjectName("pmiAttachment")
        self.layout.addRow(self.where)
        self.describe()

    def describe(self):
        if self.picks:
            self.where.setText("Attached to " + ", ".join(refs.describe(o, s) for o, s in self.picks))
        else:
            self.where.setText("Select the face(s) first, then start the command.")

    def reject(self):
        Gui.Control.closeDialog()
        return True

    def uncertainty_row(self):
        """The inspection method's expanded uncertainty U: the plan then gives the TUR and the ISO 14253-1
        acceptance limits (0 = not stated)."""
        self.uncertainty = QtWidgets.QDoubleSpinBox()
        self.uncertainty.setObjectName("uncertainty")
        self.uncertainty.setRange(0.0, 10.0)
        self.uncertainty.setDecimals(4)
        self.uncertainty.setSingleStep(0.001)
        self.uncertainty.setSuffix(" mm")
        self.uncertainty.setToolTip(self.uncertainty_row.__doc__)
        self.layout.addRow("Measurement uncertainty U", self.uncertainty)

    def accept(self):
        if not self.picks:
            QtWidgets.QMessageBox.information(self.form, self.title, "Select the face(s) the PMI belongs to first.")
            return False
        doc = App.ActiveDocument
        doc.openTransaction(self.title)
        values = self.values()
        if getattr(self, "uncertainty", None) is not None:
            values["Uncertainty"] = self.uncertainty.value()
        obj = create(self.kind, self.picks, doc, **values)
        doc.recompute()
        doc.commitTransaction()
        Gui.Control.closeDialog()
        Gui.Selection.clearSelection()
        if obj.Callout.startswith("error"):
            App.Console.PrintError(f"{self.title}: {obj.Callout}\n")
        return True


class DimensionPanel(_Panel):
    title = "PMI Rapid Dimension"
    kind = "Dimension"

    def __init__(self):
        super().__init__()
        self.type = QtWidgets.QComboBox()
        self.type.setObjectName("dimensionType")
        self.type.addItems(DIM_TYPES)
        shapes = []
        try:
            shapes = [refs.resolve(o, s) for o, s in self.picks]
        except Exception:
            pass
        if len(shapes) == 1 and refs.surface_kind(shapes[0]) in ("cylinder", "circle"):
            self.type.setCurrentIndex(1)
        self.nominal = QtWidgets.QLabel(self.measure(shapes))
        self.nominal.setObjectName("nominal")
        self.fit = QtWidgets.QLineEdit()
        self.fit.setObjectName("fit")
        self.fit.setPlaceholderText("e.g. H7 or g6 (ISO 286)")
        self.limits = QtWidgets.QLabel()
        self.limits.setObjectName("fitLimits")
        self.upper = self._spin("upperDeviation")
        self.lower = self._spin("lowerDeviation")
        self.envelope = QtWidgets.QCheckBox("Envelope Ⓔ (ISO 14405)")
        self.envelope.setObjectName("envelope")
        self.basic = QtWidgets.QCheckBox("Theoretically exact (basic)")
        self.basic.setObjectName("basic")
        self.count = QtWidgets.QSpinBox()
        self.count.setObjectName("quantity")
        self.count.setRange(1, 999)
        self.count.setPrefix("× ")
        std, general = settings(App.ActiveDocument)
        self.layout.addRow("Method", self.type)
        self.layout.addRow("Nominal", self.nominal)
        self.layout.addRow("Tolerance class", self.fit)
        self.layout.addRow("", self.limits)
        self.layout.addRow("Upper (+)", self.upper)
        self.layout.addRow("Lower (−)", self.lower)
        self.layout.addRow("", self.envelope)
        self.layout.addRow("", self.basic)
        self.layout.addRow("Quantity", self.count)
        note = QtWidgets.QLabel(f"Standard: {'ISO GPS' if std == 'ISO' else 'ASME Y14.5'}; without a tolerance the "
                                f"dimension takes {general or 'no general tolerance (set one: PMI › Tolerancing)'}")
        note.setWordWrap(True)
        self.layout.addRow(note)
        self.uncertainty_row()
        self.shapes = shapes
        self.type.currentIndexChanged.connect(lambda *_: self.nominal.setText(self.measure(shapes)))
        self.fit.textChanged.connect(self.show_fit)

    def show_fit(self, *_):
        t = self.fit.text().strip()
        if not t:
            self.limits.setText("")
            return
        try:
            n = float(self.nominal.text().split()[0])
            up, lo = iso.deviations(t, n)
            self.limits.setText(f"{t}: {pmi.deviation_text(up)} / {pmi.deviation_text(lo)} mm  "
                                f"({n + lo:.3f} to {n + up:.3f})")
        except (ValueError, IndexError) as e:
            self.limits.setText(str(e))

    def measure(self, shapes):
        try:
            if self.type.currentText() == "Distance" and len(shapes) == 2:
                return f"{abs(refs.signed_distance(shapes[0], shapes[1], refs.default_axis(*shapes))):.4f} mm"
            if len(shapes) == 1 and refs.surface_kind(shapes[0]) in ("cylinder", "circle"):
                r = shapes[0].Surface.Radius if shapes[0].ShapeType == "Face" else shapes[0].Curve.Radius
                return f"{(2 * r if self.type.currentText() == 'Diameter' else r):.4f} mm"
        except Exception as e:
            return f"cannot measure: {e}"
        return "select one cylinder (diameter) or two faces (distance)"

    @staticmethod
    def _spin(name):
        s = QtWidgets.QDoubleSpinBox()
        s.setObjectName(name)
        s.setRange(0.0, 1000.0)
        s.setDecimals(4)
        s.setSingleStep(0.01)
        s.setSuffix(" mm")
        return s

    def values(self):
        return {"DimensionType": self.type.currentText(), "UpperDeviation": self.upper.value(),
                "LowerDeviation": self.lower.value(), "Fit": self.fit.text().strip(),
                "Envelope": self.envelope.isChecked(), "Basic": self.basic.isChecked(), "Quantity": self.count.value()}


class FramePanel(_Panel):
    """The same fields (and object names) as Drafting's Feature Control Frame dialog."""
    title = "PMI Feature Control Frame"
    kind = "Feature Control Frame"

    def __init__(self):
        super().__init__()
        self.characteristic = QtWidgets.QComboBox()
        self.characteristic.setObjectName("characteristic")
        self.characteristic.addItems([c.title() for c in gdt.CHARACTERISTICS])
        self.diameter = QtWidgets.QCheckBox("Ø zone")
        self.diameter.setObjectName("zoneDiameter")
        self.tolerance = QtWidgets.QLineEdit("0.1")
        self.tolerance.setObjectName("tolerance")
        self.modifier = self._modifier("materialCondition")
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.diameter)
        row.addWidget(self.tolerance)
        row.addWidget(self.modifier)
        self.layout.addRow("Characteristic", self.characteristic)
        self.layout.addRow("Tolerance", row)
        self.datums = []
        for i, name in enumerate(("Primary", "Secondary", "Tertiary"), start=1):
            letter = QtWidgets.QLineEdit()
            letter.setObjectName(f"datum{i}")
            letter.setMaxLength(2)
            mod = self._modifier(f"datum{i}Modifier")
            r = QtWidgets.QHBoxLayout()
            r.addWidget(letter)
            r.addWidget(mod)
            self.layout.addRow(f"{name} datum", r)
            self.datums.append((letter, mod))
        # NX's Frame Style: a composite frame's lower row (FRTZF) refines the pattern's spacing
        self.style = QtWidgets.QComboBox()
        self.style.setObjectName("frameStyle")
        self.style.addItems(FRAME_STYLES)
        self.layout.addRow("Frame Style", self.style)
        self.lower_tol = QtWidgets.QLineEdit("")
        self.lower_tol.setObjectName("lowerTolerance")
        self.lower_mod = self._modifier("lowerMaterialCondition")
        r = QtWidgets.QHBoxLayout()
        r.addWidget(self.lower_tol)
        r.addWidget(self.lower_mod)
        self.layout.addRow("Lower row tolerance", r)
        self.lower_datums = QtWidgets.QLineEdit("")
        self.lower_datums.setObjectName("lowerDatums")
        self.lower_datums.setPlaceholderText("e.g. A (repeats the upper row's, in order)")
        self.layout.addRow("Lower row datums", self.lower_datums)

        def style_changed(*_):
            on = self.style.currentText() != "Single Frame"
            for w in (self.lower_tol, self.lower_mod, self.lower_datums):
                w.setEnabled(on)
        self.style.currentIndexChanged.connect(style_changed)
        style_changed()
        self.uncertainty_row()

    @staticmethod
    def _modifier(name):
        c = QtWidgets.QComboBox()
        c.setObjectName(name)
        c.addItems(MODIFIERS)
        return c

    def values(self):
        try:
            tol = float(self.tolerance.text().replace(",", "."))
        except ValueError:
            tol = 0.0
        ds = []
        for letter, m in self.datums:
            t = letter.text().strip().upper()
            if t:
                ds.append(t + {"MMC": "(M)", "LMC": "(L)"}.get(m.currentText(), ""))
        out = {"Characteristic": self.characteristic.currentText(), "Tolerance": tol,
               "ZoneDiameter": self.diameter.isChecked(), "MaterialCondition": self.modifier.currentText(),
               "DatumReferences": ds, "FrameStyle": self.style.currentText()}
        if self.style.currentText() != "Single Frame":
            try:
                low = float(self.lower_tol.text().replace(",", "."))
            except ValueError:
                low = 0.0
            out.update(LowerTolerance=low, LowerMaterialCondition=self.lower_mod.currentText(),
                       LowerDatumReferences=[d.strip().upper() for d in self.lower_datums.text().replace("|", ",")
                                             .split(",") if d.strip()])
        return out


class DatumPanel(_Panel):
    title = "PMI Datum Feature Symbol"
    kind = "Datum Feature"

    def __init__(self):
        super().__init__()
        used = {getattr(o, "Letter", "") for o in all_pmi(App.ActiveDocument)} if App.ActiveDocument else set()
        nxt = next((c for c in "ABCDEFGHJKLMNPRSTUVWXYZ" if c not in used), "A")
        self.letter = QtWidgets.QLineEdit(nxt)
        self.letter.setObjectName("datumLetter")
        self.letter.setMaxLength(2)
        self.layout.addRow("Letter", self.letter)

    def values(self):
        return {"Letter": self.letter.text().strip().upper() or "A"}


# ------------------------------------------------------------------ reports
def annotations(doc):
    """pmi.py dicts of every PMI in the document, numbered in creation order (numbers written back)."""
    objs = all_pmi(doc)
    anns = [semantic(o) for o in objs]
    pmi.number(anns, general=settings(doc)[1])
    for o, a in zip(objs, anns):
        if o.Number != a["number"]:
            o.Number = a["number"]
    return anns


def datum_feature(o):
    """The drf.py feature a Datum Feature Symbol's face gives: a plane (outward normal), a cylinder's axis,
    or None for other geometry."""
    picks = [(p, s) for p, subs in o.References for s in (subs or [""])]
    if not picks:
        return None
    try:
        shape = refs.resolve(*picks[0])
    except Exception:
        return None
    kind = refs.surface_kind(shape)
    if kind == "plane":
        return "plane", tuple(refs.anchor(shape)), tuple(refs.plane_normal(shape))
    if kind in ("cylinder", "circle"):
        c, d = refs.cylinder_axis(shape)
        return "axis", tuple(c), tuple(d)
    return None


def frames(doc):
    """[(frame text, datum letters, drf report)] of every distinct datum system the frames refer to."""
    from . import drf
    feats = {}
    for o in all_pmi(doc):
        if o.PMIType == "Datum Feature" and o.Letter.strip():
            f = datum_feature(o)
            if f is not None:
                feats.setdefault(o.Letter.strip().upper(), f)
    out, seen = [], set()
    for o in all_pmi(doc):
        if o.PMIType != "Feature Control Frame":
            continue
        letters = tuple(parse_datum(d)[0] for d in o.DatumReferences if d.strip())
        if not letters or letters in seen:
            continue
        seen.add(letters)
        missing = [x for x in letters if x not in feats]
        if missing:
            out.append((o.Label, letters, f"{' | '.join(letters)}: no datum feature symbol (or no plane or cylinder) "
                                          f"for {', '.join(missing)}"))
            continue
        out.append((o.Label, letters, drf.report(list(letters), [feats[x] for x in letters])))
    return out


def plan_text(doc):
    anns = annotations(doc)
    doc.recompute()
    std, general = settings(doc)
    text = pmi.report(anns, title=f"PMI of {doc.Label}: inspection plan, functional gauge, checks", standard=std,
                      general=general)
    systems = frames(doc)
    if systems:
        text += ("\n\nDatum reference frames (degrees of freedom, Drake 5.9.7: a plane arrests 3, 2 or 1 in order of "
                 "precedence, an axis up to 4):\n" + "\n".join(f"  {r}" for _, _, r in systems))
    return text


def stack_values(o, part="tolerance"):
    """(nominal, plus, minus) a stack-up row takes from a PMI object (Fischer's conversions): a
    dimension's deviations, from its ISO 286 class or the part's ISO 2768 general tolerance if it
    has none of its own. Raises ValueError for an invalid PMI: its values are not current."""
    require_valid(o)
    a = semantic(o)
    general = settings(o.Document)[1]
    if a["kind"] == "dimension":
        try:
            p, m, _ = pmi.deviations(a, general)
        except ValueError:
            p = m = 0.0
        return a["nominal"], p, m
    if a["kind"] == "fcf":
        if part == "bonus":
            size = next((s for s in (semantic(p) for p in all_pmi(o.Document)) if s["kind"] == "dimension"
                         and not s.get("basic") and s["feature"] == a["feature"]), None)
            if size is None or not a.get("modifier"):
                return 0.0, 0.0, 0.0
            lo, hi = pmi.size_limits(size, general)
            return 0.0, (hi - lo) / 2, (hi - lo) / 2
        return 0.0, a["tolerance"] / 2, a["tolerance"] / 2
    return None


def stack_rows(o, axis=None):
    """Stack-up rows (and picks for measured ones) for a selected PMI object."""
    if not isinstance(getattr(o, "Proxy", None), PMIFeature):
        return []
    a = semantic(o)
    picks = [(p, s) for p, subs in o.References for s in (subs or [""])]
    if a["kind"] == "dimension" and a["dim_type"] == "distance" and len(picks) == 2:
        return [({"name": f"{o.Label}", "part": picks[0][0].Label, "measured": True, "pmi": o.Name,
                  "kind": "dimension", "source": f"PMI {pmi.text(a)}"}, picks)]
    if a["kind"] == "dimension":
        return [({"name": o.Label, "part": picks[0][0].Label if picks else "", "pmi": o.Name, "direction": 1,
                  "kind": "dimension", "source": f"PMI {pmi.text(a)}"}, [])]
    if a["kind"] == "fcf":
        kind = {"position": "position"}.get(a["characteristic"],
                                            "profile" if "profile" in a["characteristic"] else
                                            "orientation" if a["characteristic"] in pmi.ORIENTATION else
                                            "runout" if a["characteristic"] in pmi.RUNOUT else "other")
        rows = [({"name": f"{a['characteristic'].title()} {o.Label}", "part": picks[0][0].Label if picks else "",
                  "pmi": o.Name, "nominal": 0.0, "direction": 1, "kind": kind,
                  "source": f"PMI {pmi.text(a)}: zone / 2"}, [])]
        if a.get("modifier"):
            rows.append(({"name": f"Bonus {o.Label}", "part": picks[0][0].Label if picks else "", "pmi": o.Name,
                          "pmi_part": "bonus", "nominal": 0.0, "direction": 1, "kind": "bonus",
                          "source": "PMI size tolerance / 2"}, []))
        return rows
    return []


# ------------------------------------------------------------------ Drafting: Inherit PMI
def project(view, p):
    """A model point on the sheet (mm, relative to the page), through the view's projection: in the
    view's own (unscaled, centred) coordinates like its edges, then scaled onto the sheet."""
    # (TechDraw's projectPoint gives the projection without the view's centring: measured, FreeCAD 1.1.4,
    # the top of a part 0..38 high projects to y 38 in a front view whose edges run from -19 to 19)
    s = float(view.Scale)
    q = view_xy(view, p)
    return float(view.X) + q.x * s, float(view.Y) + q.y * s


def view_frame(view):
    """The view's paper axes in the model: x along XDirection, y = Direction x XDirection."""
    d = App.Vector(view.Direction).normalize()
    x = App.Vector(view.XDirection).normalize()
    return x, d.cross(x), d


_centres = {}


def view_centre(view):
    """Where TechDraw centres a view: the middle of the source's exact bounding box in the view's own
    axes. (A plain BoundBox is padded around curved faces: the axis of a Ø25 body came out 0.019 mm off.)"""
    import Part
    key = (view.Name, tuple(view.Direction), tuple(view.XDirection), tuple(id(s) for s in view.Source),
           tuple(float(s.Shape.Volume) if hasattr(s, "Shape") else 0.0 for s in view.Source))
    if key in _centres:
        return _centres[key]
    x, y, d = view_frame(view)
    m = App.Matrix(x.x, x.y, x.z, 0, y.x, y.y, y.z, 0, d.x, d.y, d.z, 0, 0, 0, 0, 1)
    shape = Part.makeCompound([s.Shape for s in view.Source if hasattr(s, "Shape")]).copy()
    shape.transformShape(m)
    try:
        bb = shape.optimalBoundingBox(False, False)
    except Exception:
        bb = shape.BoundBox
    _centres[key] = (bb.Center.x, bb.Center.y)
    return _centres[key]


def view_xy(view, p):
    """A model point in the view's own coordinates: centred and unscaled, like its edges."""
    x, y, _ = view_frame(view)
    cx, cy = view_centre(view)
    return App.Vector(p.dot(x) - cx, p.dot(y) - cy, 0)


def _line_dist(p, a, b):
    """Distance of 2D point p from the infinite line through a and b."""
    d = b - a
    if d.Length < 1e-12:
        return (p - a).Length
    d.normalize()
    w = p - a
    return (w - d * w.dot(d)).Length


def edge_for_face(view, shape):
    """(index, edge) of the view edge that shows a face edge-on: a plane square to the paper as a line on
    its trace, a cylinder seen from the side as a silhouette line a radius from its axis. None when the
    view does not show the face that way."""
    d = App.Vector(view.Direction).normalize()
    k = refs.surface_kind(shape)
    lines = [(i, e) for i, e in _view_edges(view) if not hasattr(e.Curve, "Radius") and len(e.Vertexes) >= 2]
    if k == "plane":
        n = refs.plane_normal(shape)
        if abs(n.dot(d)) > 0.05:
            return None
        p0 = refs.anchor(shape)
        t = n.cross(d).normalize()
        a, b = view_xy(view, p0), view_xy(view, p0 + t * 10.0)
        cands = [(i, e) for i, e in lines
                 if _line_dist(e.Vertexes[0].Point, a, b) < 1e-3 and _line_dist(e.Vertexes[-1].Point, a, b) < 1e-3]
        P = view_xy(view, p0)
        return min(cands, key=lambda ie: ((ie[1].Vertexes[0].Point + ie[1].Vertexes[-1].Point) * 0.5 - P).Length,
                   default=None)
    if k in ("cylinder", "circle"):
        c, ax = refs.cylinder_axis(shape)
        if abs(ax.dot(d)) > 0.05:
            why["last"] = f"cylinder axis at {abs(ax.dot(d)):.3f} to the view direction"
            return None
        r = shape.Surface.Radius if shape.ShapeType == "Face" else shape.Curve.Radius
        a, b = view_xy(view, c), view_xy(view, c + ax * 10.0)
        u = (b - a).normalize()
        cands, seen = [], []
        for i, e in lines:
            v = e.Vertexes[-1].Point - e.Vertexes[0].Point
            if v.Length < 1e-9 or abs(abs(App.Vector(v).normalize().dot(u)) - 1) > 1e-6:
                continue
            gap = _line_dist(e.Vertexes[0].Point, a, b)
            seen.append(round(gap, 4))
            if abs(gap - r) < 1e-3:
                cands.append((i, e))
        why["last"] = (f"r {r:g}, axis in the view {a} -> {b}, {len(lines)} lines, parallel ones at "
                       f"{sorted(seen)} from the axis")
        return min(cands, key=lambda ie: ie[1].Vertexes[0].Point.x, default=None)     # the left silhouette
    why["last"] = f"a {k}"
    return None


why = {}


INHERIT_MODES = ["From Model View", "Aligned to Drawing (Entire Part)"]


def inherit_mode(view):
    """NX's Inherit PMI setting of a drawing view (Settings > Common > PMI), as a property of the view."""
    if "NX_InheritPMI" not in view.PropertiesList:
        view.addProperty("App::PropertyEnumeration", "NX_InheritPMI", "NX",
                         "Which PMI Inherit PMI brings: those of the model view this view looks along (and those "
                         "shown in all views), or every PMI whose plane faces this view")
        view.NX_InheritPMI = INHERIT_MODES
        view.NX_InheritPMI = INHERIT_MODES[0]
    return view.NX_InheritPMI


def pmi_for_view(view, mode=None):
    """(PMI a drawing view inherits, how it chose them). From Model View: the PMI of the model view that
    looks the way this drawing view does (TechDraw's Direction points at the viewer, a model view's into
    the part), else as Aligned to Drawing; Aligned to Drawing (Entire Part): every PMI whose plane faces
    the view, whichever model view it is in (Wünsch, Pilz and Vajna, NX für Einsteiger 6.10)."""
    from . import pmi_views
    doc = view.Document
    mode = mode or inherit_mode(view)
    look = App.Vector(view.Direction)
    if look.Length < 1e-12:
        return all_pmi(doc), "all PMI"
    look = App.Vector(-look.x, -look.y, -look.z).normalize()
    if mode == INHERIT_MODES[0]:
        match = next((v for v in model_views(doc)
                      if (App.Vector(v.Direction).normalize() - look).Length < 1e-6), None)
        if match is not None:
            return ([p for p in all_pmi(doc) if pmi_views.shown([v.Name for v in p.Views or []], match.Name)],
                    f"from model view {match.Label}")
    picked = []
    for p in all_pmi(doc):
        d = App.Vector(*view_of(p)[0]).normalize()
        if abs(d.dot(look)) > 1 - 1e-6:
            picked.append(p)
    return picked, "aligned to the drawing (entire part)"


def inherit(view, objs=None, refresh=True):
    """Put the model's PMI on a drawing view: diameters and distances as TechDraw dimensions on the edges
    that show their faces, with the PMI's ISO class or tolerance, stacked outside the view; datum symbols on
    the edge that shows their face; a frame under its feature's size dimension, or against that edge.
    What the sheet shows already is brought up to date first (refresh_inherited).
    Returns (created objects, skipped PMI with the reason)."""
    from . import gdt_ui
    page = gdt_ui.owning_page(view)
    doc = view.Document
    made, skipped = [], []
    anns = {a["id"]: a for a in annotations(doc)}
    refreshed = refresh_inherited(doc, page) if refresh else set()
    on_sheet = {getattr(v, "NX_Pmi", "") for v in page.Views}
    objs = objs if objs is not None else all_pmi(doc)
    # dimensions first, so a frame can go under its feature's size dimension
    for o in sorted(objs, key=lambda o: o.PMIType != "Dimension"):
        if o.Name in on_sheet:                  # one PMI is shown once on a sheet, in the first view that shows it
            skipped.append((o.Label, "already on this sheet" + (", updated" if o.Name in refreshed else "")))
            continue
        a = anns.get(o.Name) or semantic(o)
        if not pmi.is_valid(a):
            skipped.append((o.Label, f"not valid, its values are not current: {a.get('invalid', '')}"))
            continue
        if a["kind"] == "dimension":
            dim = inherit_dimension(view, page, o, a)
            if dim is None:
                skipped.append((o.Label, "no matching edge in this view"))
            else:
                made.append(dim)
                on_sheet.add(o.Name)
            continue
        picks = [(p, s) for p, subs in o.References for s in (subs or [""])]
        try:
            shape = refs.resolve(*picks[0])
        except Exception as e:
            skipped.append((o.Label, str(e)))
            continue
        if a["kind"] == "fcf":
            size_dim = size_dimension_on(page, o)
            params = {"characteristic": a["characteristic"], "tolerance": f"{a['tolerance']:g}",
                      "diameter": a["diameter"], "modifier": a["modifier"], "datums": [tuple(d) for d in a["datums"]]}
            low = pmi.lower(a)
            if low:                             # a two-row frame keeps its lower row on the drawing
                params["lower"] = (f"{low['tolerance']:g}", low.get("modifier", ""),
                                   [tuple(d) for d in low.get("datums", [])])
                params["composite"] = pmi.composite(a)
            if size_dim is not None:
                sym = gdt_ui.place_frame(params, page, "dimension", size_dim)
            else:
                hit = edge_for_face(view, shape)
                if hit is None:
                    skipped.append((o.Label, "its face is not seen edge-on in this view"))
                    continue
                sym = gdt_ui.place_frame(params, page, "edge", (view, hit[1]))
        else:
            hit = edge_for_face(view, shape)
            if hit is None:
                skipped.append((o.Label, f"its face is not seen edge-on in this view ({why.get('last', '')})"))
                continue
            sym = gdt_ui.place_datum(a["letter"], page, "edge", (view, hit[1]))
        gdt_ui.tag(sym, pmi=o.Name)
        mark_inherited(sym, o, view)
        made.append(sym)
        on_sheet.add(o.Name)
    for dim in made:
        if dim.isDerivedFrom("TechDraw::DrawViewDimension"):
            mark_inherited(dim, doc.getObject(dim.NX_Pmi), view)
    note = tolerancing_note(page)
    if note is not None:
        made.append(note)
    doc.recompute()
    last_inherit[view.Name] = skipped
    return made, skipped


last_inherit = {}
last_inherit_how = {}


# ---------------------------------------------- inherited annotations follow their PMI
def _tag(obj, name, value, doc):
    if name not in obj.PropertiesList:
        obj.addProperty("App::PropertyString", name, "NX", doc)
    setattr(obj, name, value)


def mark_inherited(ann, o, view):
    """Remember what an inherited annotation was made from: the PMI's callout then, and its view."""
    if ann is None or o is None:
        return
    _tag(ann, "NX_PmiCallout", o.Callout, "The PMI's callout when this annotation was made from it")
    _tag(ann, "NX_View", view.Name, "The drawing view it was inherited into")


def inherited(doc, page=None):
    """[(annotation, page, PMI name)] of the annotations Inherit PMI made (not the tolerancing note)."""
    out = []
    for p in ([page] if page is not None else [o for o in doc.Objects if o.isDerivedFrom("TechDraw::DrawPage")]):
        for v in p.Views:
            name = getattr(v, "NX_Pmi", "")
            if name and name != "tolerancing-note":
                out.append((v, p, name))
    return out


def stale_inherited(doc, page=None):
    """[(annotation, reason)] of inherited annotations that no longer show their PMI as it is: the PMI was
    deleted, is not valid, or its callout changed (a fit, a tolerance, a datum letter, a lower row)."""
    out = []
    for ann, _, name in inherited(doc, page):
        o = doc.getObject(name)
        if o is None:
            out.append((ann, f"its PMI {name} was deleted"))
        elif not valid(o):
            out.append((ann, f"its PMI {o.Label} is not valid ({o.Callout})"))
        elif "NX_PmiCallout" in ann.PropertiesList and ann.NX_PmiCallout != o.Callout:
            out.append((ann, f"{o.Label} changed: '{ann.NX_PmiCallout}' is now '{o.Callout}'"))
    return out


def refresh_inherited(doc, page=None):
    """Bring the inherited annotations up to date: one whose PMI changed is made again from it, where the
    drafter had placed it; one whose PMI was deleted goes. One whose PMI is not valid stays as it is and
    stays reported by stale_inherited (a release package refuses it). Returns the names of the PMI updated."""
    done = set()
    for ann, pg, name in inherited(doc, page):
        o = doc.getObject(name)
        if o is None:
            doc.removeObject(ann.Name)
            continue
        if not valid(o) or "NX_PmiCallout" not in ann.PropertiesList or ann.NX_PmiCallout == o.Callout:
            continue
        if ann.isDerivedFrom("TechDraw::DrawViewDimension") and ann.References2D:
            view = ann.References2D[0][0]
        else:
            view = doc.getObject(getattr(ann, "NX_View", "")) or next(
                (v for v in pg.Views if v.isDerivedFrom("TechDraw::DrawViewPart")), None)
        if view is None:
            continue
        x, y = float(ann.X), float(ann.Y)
        ann.NX_Pmi = ""             # the page lists a removed view until it recomputes (measured: the new one
        doc.removeObject(ann.Name)  # was then skipped as "already on this sheet")
        made, skipped = inherit(view, [o], refresh=False) if (pg.Name, name) not in done else ([], [])
        for m in made:
            if getattr(m, "NX_Pmi", "") == name:
                m.X, m.Y = x, y                    # where the drafter had it
        last_refresh[name] = {"view": view.Name, "made": [m.Name for m in made], "skipped": skipped}
        done.add((pg.Name, name))
    if done:
        doc.recompute()
    return {name for _, name in done}


_pending_refresh = set()
last_refresh = {}                    # PMI name -> what its last refresh made or skipped; "error": a failure


def schedule_refresh(doc):
    """Refresh the document's inherited annotations once the current recompute is over (changing other
    objects from inside a recompute is not safe)."""
    if not App.GuiUp or doc.Name in _pending_refresh:
        return
    _pending_refresh.add(doc.Name)

    def run():
        _pending_refresh.discard(doc.Name)
        if doc.Name in App.listDocuments() and inherited(doc):
            try:
                refresh_inherited(doc)
            except Exception as e:
                import traceback
                last_refresh["error"] = traceback.format_exc()
                App.Console.PrintWarning(f"NXStyle: inherited PMI not updated: {e}\n")
    QtCore.QTimer.singleShot(0, run)


def size_dimension_on(page, o):
    """The inherited TechDraw dimension of the same feature's size, if the sheet has one."""
    key = feature_key(o)
    for v in page.Views:
        name = getattr(v, "NX_Pmi", "")
        if not name or not v.isDerivedFrom("TechDraw::DrawViewDimension"):
            continue
        p = o.Document.getObject(name)
        if p is not None and getattr(p, "PMIType", "") == "Dimension" and not p.Basic and feature_key(p) == key \
                and p.DimensionType in ("Diameter", "Radius"):
            return v
    return None


def tolerancing_note(page):
    """The drawing's tolerancing note near the title block (ISO: 'Tolerancing ISO 8015', 'General
    tolerances ISO 2768-mK'); one per sheet, updated in place. None when the sheet's title block has
    a general tolerances field that is filled in: it says so there (Populate Title Block)."""
    doc = page.Document
    std, general = settings(doc)
    lines = (["Tolerancing ISO 8015"] if std == "ISO" else ["Dimensioning and tolerancing per ASME Y14.5"])
    if general:
        lines.append(f"General tolerances {general}")
    note = next((v for v in page.Views if getattr(v, "NX_Pmi", "") == "tolerancing-note"), None)
    try:
        in_title_block = bool(dict(page.Template.EditableTexts).get("general_tolerances", "").strip())
    except Exception:
        in_title_block = False
    if in_title_block:
        if note is not None:
            doc.removeObject(note.Name)
        return None
    if note is None:
        note = doc.addObject("TechDraw::DrawViewAnnotation", "TolerancingNote")
        page.addView(note)
        note.addProperty("App::PropertyString", "NX_Pmi", "NX", "What this annotation is")
        note.NX_Pmi = "tolerancing-note"
        try:
            w, h = float(page.Template.Width), float(page.Template.Height)
        except Exception:
            w, h = 297.0, 210.0
        note.X, note.Y = w - 95.0, 62.0 if h < 300 else 80.0
        note.TextSize = 3.5
    note.Text = lines
    return note


def _view_edges(view):
    out = []
    for i in range(len(view.getVisibleEdges())):
        try:
            out.append((i, view.getEdgeByIndex(i)))
        except Exception:
            continue
    return out


def inherit_dimension(view, page, o, a):
    """A TechDraw dimension for a PMI diameter or distance, on the view edges that show its faces."""
    doc = view.Document
    s = edge_scale(view)
    edges = _view_edges(view)
    refs_2d = []
    dtype = None
    if a["dim_type"] in ("diameter", "radius"):
        r = a["nominal"] / (2 if a["dim_type"] == "diameter" else 1)
        for i, e in edges:
            if hasattr(e.Curve, "Radius") and abs(e.Curve.Radius - r * s) < 1e-4 * max(1, r):
                refs_2d = [(view, f"Edge{i}")]
                dtype = "Diameter" if a["dim_type"] == "diameter" else "Radius"
                break
        if not refs_2d:
            # a cylinder seen from the side: two parallel lines a diameter apart
            lines = [(i, e) for i, e in edges if not hasattr(e.Curve, "Radius")]
            for k, (i, e) in enumerate(lines):
                for j, f in lines[k + 1:]:
                    if _parallel_gap(e, f) is not None and abs(_parallel_gap(e, f) - 2 * r * s) < 1e-3:
                        v = e.Vertexes[-1].Point - e.Vertexes[0].Point
                        refs_2d = [(view, f"Edge{i}"), (view, f"Edge{j}")]
                        dtype = "DistanceX" if abs(v.y) > abs(v.x) else "DistanceY"
                        break
                if refs_2d:
                    break
    else:
        lines = [(i, e) for i, e in edges if not hasattr(e.Curve, "Radius")]
        target = a["nominal"] * s
        pa = project(view, App.Vector(o.Anchor))
        pb = project(view, App.Vector(o.Anchor2))
        best = None
        for k, (i, e) in enumerate(lines):
            for j, f in lines[k + 1:]:
                g = _parallel_gap(e, f)
                if g is None or abs(g - target) > 1e-3:
                    continue
                # prefer the pair nearest the PMI's own attachment points
                ce, cf = _centre(view, e), _centre(view, f)
                score = min(_d(ce, pa) + _d(cf, pb), _d(ce, pb) + _d(cf, pa))
                if best is None or score < best[0]:
                    best = (score, i, j, e)
        if best is not None:
            _, i, j, e = best
            v = e.Vertexes[-1].Point - e.Vertexes[0].Point
            dtype = "DistanceX" if abs(v.y) > abs(v.x) else "DistanceY"
            refs_2d = [(view, f"Edge{i}"), (view, f"Edge{j}")]
    if not refs_2d:
        return None
    dim = doc.addObject("TechDraw::DrawViewDimension", "Dimension")
    dim.Type = dtype
    dim.References2D = refs_2d
    dim.MeasureType = "Projected"
    page.addView(dim)
    # the dimension's own tolerance or ISO 286 class; one covered by the general tolerance shows none
    # (the title block note covers it)
    try:
        plus, minus, _ = pmi.deviations(a)
    except ValueError:
        plus, minus = 0.0, 0.0
    if a.get("basic"):
        dim.TheoreticalExact = True
    elif plus or minus:
        dim.EqualTolerance = abs(plus - minus) < 1e-12
        dim.OverTolerance = plus
        dim.UnderTolerance = -minus
        dim.FormatSpecOverTolerance = "%+.3w"
        dim.FormatSpecUnderTolerance = "%+.3w"
    count = f"{a['count']}X " if a.get("count", 1) > 1 else ""
    fit = f" {a['fit']}" if a.get("fit") else ""
    env = f" {pmi.ENVELOPE}" if a.get("envelope") else ""
    if count or fit or env:
        dim.FormatSpec = count + ("⌀" if dtype == "Diameter" or a["dim_type"] == "diameter" else "") + "%.3w" + fit + env
    try:
        dim.addProperty("App::PropertyString", "NX_Pmi", "NX", "The PMI this dimension was inherited from")
        dim.NX_Pmi = o.Name
    except Exception:
        pass
    place_dimension(view, page, dim, dtype, [view.getEdgeByIndex(int(n[4:])) for _, n in refs_2d])
    return dim


def place_dimension(view, page, dim, dtype, edges):
    """Move an inherited dimension outside its view, as a drafter drags it: vertical ones to the right,
    horizontal ones below, diameters out at an angle, each further out than the ones before."""
    s = float(view.Scale)
    bb = None
    for _, e in _view_edges(view):
        bb = e.BoundBox if bb is None else bb.united(e.BoundBox)
    if bb is None:
        return
    mine = [v for v in page.Views if v is not dim and v.isDerivedFrom("TechDraw::DrawViewDimension")
            and getattr(v, "NX_Pmi", "") and v.References2D and v.References2D[0][0] is view]
    same = sum(1 for v in mine if v.Type == dtype)
    pts = [p.Point for e in edges for p in e.Vertexes]
    if dtype == "DistanceY":
        dim.X = (bb.XMax * s) + 10.0 + 9.0 * same
        dim.Y = sum(p.y for p in pts) / len(pts) * s
    elif dtype == "DistanceX":
        dim.Y = (bb.YMin * s) - 10.0 - 9.0 * same
        dim.X = sum(p.x for p in pts) / len(pts) * s
    else:
        import math
        ang = math.radians(40.0 + 28.0 * same)
        R = max(bb.XMax, bb.YMax) * s + 8.0 + 4.0 * same
        dim.X, dim.Y = R * math.cos(ang), R * math.sin(ang)


def edge_scale(view):
    """Factor from model mm to the view's edge coordinates. TechDraw's getEdgeByIndex returns the
    projected edges unscaled (measured, FreeCAD 1.1.4: circles of a 2:1 view report the model's radii);
    the view's Scale applies only on the way to the sheet."""
    return 1.0


def _centre(view, e):
    m = (e.Vertexes[0].Point + e.Vertexes[-1].Point) * 0.5
    s = float(view.Scale)
    return float(view.X) + m.x * s, float(view.Y) + m.y * s


def _d(p, q):
    return ((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5


def _parallel_gap(e, f):
    """Distance between two parallel straight edges (None if not parallel)."""
    try:
        if len(e.Vertexes) < 2 or len(f.Vertexes) < 2:
            return None
        u = e.Vertexes[-1].Point - e.Vertexes[0].Point
        v = f.Vertexes[-1].Point - f.Vertexes[0].Point
        if u.Length < 1e-9 or v.Length < 1e-9:
            return None
        u.normalize()
        v.normalize()
        if abs(abs(u.dot(v)) - 1) > 1e-6:
            return None
        w = f.Vertexes[0].Point - e.Vertexes[0].Point
        return (w - u * w.dot(u)).Length
    except Exception:
        return None


# ------------------------------------------------------------------ commands
def _part_document():
    doc = App.ActiveDocument
    return doc is not None and not Gui.Control.activeDialog()


class PMICommand:
    def __init__(self, panel, menu, tip, icon):
        self.panel, self.menu, self.tip, self.icon = panel, menu, tip, icon

    def GetResources(self):
        return {"MenuText": self.menu, "ToolTip": self.tip, "Pixmap": config.resource("icons", self.icon)}

    def IsActive(self):
        return _part_document()

    def Activated(self):
        Gui.Control.showDialog(self.panel())


class TolerancingPanel:
    """The part's tolerancing standard and general tolerance note (a drawing's title block entries)."""

    def __init__(self):
        self.doc = App.ActiveDocument
        std, general = settings(self.doc)
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Tolerancing")
        lay = QtWidgets.QFormLayout(self.form)
        self.standard = QtWidgets.QComboBox()
        self.standard.setObjectName("standard")
        self.standard.addItems(["ISO GPS", "ASME Y14.5"])
        self.standard.setCurrentIndex(0 if std == "ISO" else 1)
        self.general = QtWidgets.QComboBox()
        self.general.setObjectName("generalTolerance")
        self.general.setEditable(True)
        self.general.addItems(["", "ISO 2768-fH", "ISO 2768-mK", "ISO 2768-cL", "ISO 2768-mK-E"])
        self.general.setCurrentText(general or "")
        lay.addRow("Standard", self.standard)
        lay.addRow("General tolerances", self.general)
        help_ = QtWidgets.QLabel("ISO GPS: a size controls local sizes only (ISO 8015 independency); a fit needs the "
                                 "envelope Ⓔ. ISO 2768-mK: medium linear and angular tolerances, class K geometrical "
                                 "tolerances; -E puts every feature of size in its envelope.")
        help_.setWordWrap(True)
        lay.addRow(help_)

    def accept(self):
        g = self.general.currentText().strip()
        if g and iso.parse_general(g) is None:
            QtWidgets.QMessageBox.information(self.form, "Tolerancing", f"'{g}' is not an ISO 2768 note "
                                              "(e.g. ISO 2768-mK).")
            return False
        self.doc.openTransaction("Tolerancing")
        f = folder(self.doc)
        f.Standard = self.standard.currentText()
        f.GeneralTolerance = g
        for o in all_pmi(self.doc):
            o.touch()
        self.doc.recompute()
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


class Tolerancing:
    def GetResources(self):
        return {"MenuText": "Tolerancing",
                "ToolTip": "The part's tolerancing standard (ISO GPS or ASME Y14.5) and general tolerances "
                           "(ISO 2768), as a drawing's title block states them",
                "Pixmap": config.resource("icons", "tolerancing.svg")}

    def IsActive(self):
        return _part_document()

    def Activated(self):
        Gui.Control.showDialog(TolerancingPanel())


class InspectionPlan:
    def GetResources(self):
        return {"MenuText": "Inspection Plan",
                "ToolTip": "Number the PMI characteristics (balloons) and list them with their limits and how to "
                           "measure them, the functional gauge sizes (virtual condition, datums at MMB) and the "
                           "ASME Y14.5 checks",
                "Pixmap": config.resource("icons", "inspection_plan.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and bool(all_pmi(App.ActiveDocument))

    def Activated(self):
        from .commands import show_information
        doc = App.ActiveDocument
        doc.openTransaction("Inspection Plan")
        text = plan_text(doc)
        doc.commitTransaction()
        show_information(text)


def export_step(doc, path):
    """STEP AP242 of the part's solids with its semantic PMI; returns the report text."""
    from . import ap242, package_ui
    objs = package_ui.solids(doc)
    if not objs:
        raise ValueError("the part has no solid to export")
    done = package_ui.export_step_pmi(doc, objs, path)
    if done is None:
        why = "this FreeCAD has no pythonocc (OCCT's AP242 PMI writer)" if not ap242.available() else \
            "the part has no PMI" if not all_pmi(doc) else "assemblies are written without PMI"
        schema = package_ui.export_step(objs, path)
        text = f"{path}\nSTEP {schema} without PMI: {why}."
    else:
        schema, summary, problems = done
        text = f"{path}\nSTEP AP242 with semantic PMI: {summary}"
        if problems:
            text += "\n\nNot written:\n" + "\n".join("  " + p for p in problems)
    try:
        back = ap242.read_back(path) if done else None
    except Exception:
        back = None
    if back:
        text += (f"\n\nRead back by OpenCASCADE: {back['datums']} datum references, {back['dimensions']} "
                 f"dimensions, {back['geometric_tolerances']} geometric tolerances")
    last.update(path=path, text=text, read_back=back)
    return text


last = {}


def import_step(path, doc=None):
    """A STEP AP242 file's parts and its semantic PMI as NXStyle PMI on their faces (the MBD direction
    back: another CAD system's PMI, or NXStyle's own, becomes PMI here). Returns (objects, PMI, problems)."""
    import Part
    from . import ap242
    doc = doc or App.ActiveDocument or App.newDocument()
    data = ap242.read(path)
    parts = []
    for name, shape in data["shapes"]:
        o = doc.addObject("Part::Feature", "Imported")
        o.Shape = Part.__fromPythonOCC__(shape)
        o.Label = name
        parts.append(o)
    doc.recompute()
    made, problems = [], list(data["problems"])
    for rec in data["records"]:
        kind, values = ap242.pmi_values(rec)
        if kind is None:
            problems.append(values)
            continue
        faces = rec.get("faces", []) + rec.get("faces2", [])
        if not faces:
            problems.append(f"{kind} {values}: not attached to a face")
            continue
        picks = [(parts[n], sub) for n, sub in faces]
        if kind == "Dimension" and values["DimensionType"] == "Distance" and len(picks) < 2:
            problems.append(f"distance {rec.get('nominal')}: needs two faces, the file gives {len(picks)}")
            continue
        try:
            made.append(create(kind, picks, doc, **values))
        except Exception as e:
            problems.append(f"{kind} {values}: {e}")
    doc.recompute()
    last.update(imported=[p.Label for p in made], import_problems=problems)
    return parts, made, problems


class StepPanel:
    """File > Export > STEP with PMI: the model and its PMI as data (ISO 10303-242)."""

    def __init__(self):
        import os
        self.doc = App.ActiveDocument
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("STEP AP242 with PMI")
        lay = QtWidgets.QFormLayout(self.form)
        base = os.path.splitext(self.doc.FileName)[0] if self.doc.FileName else \
            os.path.join(os.path.expanduser("~"), self.doc.Label)
        self.path = QtWidgets.QLineEdit(base + ".step")
        self.path.setObjectName("stepFile")
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.path)
        row.addWidget(browse)
        lay.addRow("File", row)
        n = len(all_pmi(self.doc))
        info = QtWidgets.QLabel(f"{n} PMI object(s): datums, dimensions with their tolerances and ISO 286 classes, "
                                "and feature control frames are written as semantic PMI that CAM, CMM and other CAD "
                                "systems read.")
        info.setWordWrap(True)
        lay.addRow(info)

    def browse(self):
        p, _ = QtWidgets.QFileDialog.getSaveFileName(self.form, "STEP with PMI", self.path.text(),
                                                     "STEP (*.step *.stp)")
        if p:
            self.path.setText(p)

    def accept(self):
        from .commands import show_information
        try:
            text = export_step(self.doc, self.path.text().strip())
        except Exception as e:
            QtWidgets.QMessageBox.warning(self.form, "STEP with PMI", str(e))
            return False
        Gui.Control.closeDialog()
        show_information(text)
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


class ImportStep:
    def GetResources(self):
        return {"MenuText": "Import STEP with PMI",
                "ToolTip": "Open a STEP AP242 file's parts and its semantic PMI (datums, dimensions with their "
                           "tolerances and ISO 286 classes, feature control frames) as PMI on their faces",
                "Pixmap": config.resource("icons", "import_step_pmi.svg")}

    def IsActive(self):
        return not Gui.Control.activeDialog()

    def Activated(self):
        Gui.Control.showDialog(ImportPanel())


class ImportPanel:
    """File > Import > STEP with PMI: another system's (or NXStyle's) AP242 part with its PMI as data."""

    def __init__(self):
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Import STEP with PMI")
        lay = QtWidgets.QFormLayout(self.form)
        self.path = QtWidgets.QLineEdit()
        self.path.setObjectName("stepFile")
        browse = QtWidgets.QPushButton("Browse…")
        browse.clicked.connect(self.browse)
        row = QtWidgets.QHBoxLayout()
        row.addWidget(self.path)
        row.addWidget(browse)
        lay.addRow("File", row)
        info = QtWidgets.QLabel("The parts come in as solids; datums, dimensions with their tolerances and ISO 286 "
                                "classes, and feature control frames become PMI on their faces. Into the open part, "
                                "or a new one.")
        info.setWordWrap(True)
        lay.addRow(info)

    def browse(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(self.form, "Import STEP with PMI", self.path.text(),
                                                     "STEP (*.step *.stp)")
        if p:
            self.path.setText(p)

    def accept(self):
        import os
        from .commands import show_information
        path = self.path.text().strip()
        if not os.path.isfile(path):
            QtWidgets.QMessageBox.information(self.form, "Import STEP with PMI", f"No file {path!r}.")
            return False
        try:
            text = import_report(path)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self.form, "Import STEP with PMI", str(e))
            return False
        Gui.Control.closeDialog()
        Gui.SendMsgToActiveView("ViewFit")
        show_information(text)
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


def import_report(path, doc=None):
    """Import path (import_step) and describe what came in, for the Information window."""
    doc = doc or App.ActiveDocument or App.newDocument()
    doc.openTransaction("Import STEP with PMI")
    parts, made, problems = import_step(path, doc)
    doc.commitTransaction()
    text = (f"{path}\n{len(parts)} part(s): {', '.join(p.Label for p in parts)}\n{len(made)} PMI:\n"
            + "\n".join(f"  {p.PMIType}: {p.Callout}" for p in made))
    if problems:
        text += "\n\nNot imported:\n" + "\n".join("  " + p for p in problems)
    last.update(import_text=text)
    return text


class ExportStep:
    def GetResources(self):
        return {"MenuText": "STEP with PMI",
                "ToolTip": "Export the part as STEP AP242 with its semantic PMI (datums, dimensions, fits, "
                           "feature control frames), the way NX exports PMI to STEP",
                "Pixmap": config.resource("icons", "step_pmi.svg")}

    def IsActive(self):
        return _part_document() and bool(all_pmi(App.ActiveDocument))

    def Activated(self):
        Gui.Control.showDialog(StepPanel())


def selected_pmi():
    return [o for o in Gui.Selection.getSelection() if isinstance(getattr(o, "Proxy", None), PMIFeature)]


def display_in_views(objs, views):
    """NX's Display > in Views: show objs in exactly these model views (an empty list: in all views).
    A PMI that now belongs to one view only gets its label in that view's plane, if its plane changed."""
    doc = objs[0].Document
    for o in objs:
        before = view_of(o)
        o.Views = list(views)
        if view_of(o) != before:
            replace_label(o)
    doc.recompute()
    return apply_visibility(doc)


class DisplayInViewsPanel:
    """Which model views the selected PMI are displayed in (NX: RMB > Display > in Views)."""

    def __init__(self, objs):
        self.objs = objs
        self.doc = objs[0].Document
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle("Display in Views")
        lay = QtWidgets.QVBoxLayout(self.form)
        lay.addWidget(QtWidgets.QLabel(f"{len(objs)} PMI: " + ", ".join(o.Label for o in objs[:4])
                                       + (" …" if len(objs) > 4 else "")))
        current = {v.Name for o in objs for v in (o.Views or [])}
        everywhere = all(not o.Views for o in objs)
        self.all = QtWidgets.QCheckBox("All views")
        self.all.setObjectName("allViews")
        self.all.setChecked(everywhere)
        lay.addWidget(self.all)
        self.boxes = {}
        for v in model_views(self.doc):
            b = QtWidgets.QCheckBox(v.Label)
            b.setObjectName(f"view_{v.Label}")
            b.setChecked(v.Name in current)
            b.setEnabled(not everywhere)
            lay.addWidget(b)
            self.boxes[v.Name] = (b, v)
        self.all.toggled.connect(lambda on: [b.setEnabled(not on) for b, _ in self.boxes.values()])
        note = QtWidgets.QLabel("A PMI shows when its view is the work view (double-click a view in the Part "
                                "Navigator). Tick several views to copy it, one to move it.")
        note.setWordWrap(True)
        lay.addWidget(note)
        lay.addStretch()

    def accept(self):
        views = [] if self.all.isChecked() else [v for b, v in self.boxes.values() if b.isChecked()]
        if not self.all.isChecked() and not views:
            QtWidgets.QMessageBox.information(self.form, "Display in Views", "Tick at least one view, or All views.")
            return False
        self.doc.openTransaction("Display in Views")
        display_in_views(self.objs, views)
        self.doc.commitTransaction()
        Gui.Control.closeDialog()
        return True

    def reject(self):
        Gui.Control.closeDialog()
        return True


class DisplayInViews:
    def GetResources(self):
        return {"MenuText": "Display in Views",
                "ToolTip": "Show the selected PMI in other model views, move it to one, or show it in all views "
                           "(NX: Display > in Views)",
                "Pixmap": config.resource("icons", "display_in_views.svg")}

    def IsActive(self):
        return bool(selected_pmi()) and not Gui.Control.activeDialog()

    def Activated(self):
        objs = selected_pmi()
        folder(objs[0].Document)
        Gui.Control.showDialog(DisplayInViewsPanel(objs))


class NewModelView:
    def GetResources(self):
        return {"MenuText": "New Model View",
                "ToolTip": "Save the current view direction as a model view and make it the work view; rename it "
                           "in the Part Navigator",
                "Pixmap": config.resource("icons", "new_model_view.svg")}

    def IsActive(self):
        return _part_document() and Gui.ActiveDocument is not None and \
            hasattr(Gui.ActiveDocument.ActiveView, "getCameraOrientation")

    def Activated(self):
        doc = App.ActiveDocument
        rot = Gui.ActiveDocument.ActiveView.getCameraOrientation()
        d, u = rot.multVec(App.Vector(0, 0, -1)), rot.multVec(App.Vector(0, 1, 0))
        doc.openTransaction("New Model View")
        folder(doc)
        n = 1 + sum(1 for v in model_views(doc) if v.Label.startswith("Model View "))
        v = make_view(doc, f"Model View {n}", tuple(d), tuple(u))
        activate(v)
        doc.commitTransaction()


class ShowAllPMI:
    def GetResources(self):
        return {"MenuText": "Show All PMI",
                "ToolTip": "No work view: every PMI shows, whichever views it belongs to",
                "Pixmap": config.resource("icons", "show_all_pmi.svg")}

    def IsActive(self):
        return App.ActiveDocument is not None and work_view(App.ActiveDocument) is not None

    def Activated(self):
        show_all(App.ActiveDocument)


class InheritPMI:
    def GetResources(self):
        return {"MenuText": "Inherit PMI",
                "ToolTip": "Put the model's PMI on the selected drawing view: dimensions with their tolerances, "
                           "feature control frames and datum feature symbols",
                "Pixmap": config.resource("icons", "inherit_pmi.svg")}

    @staticmethod
    def _view():
        for o in Gui.Selection.getSelection():
            if o.isDerivedFrom("TechDraw::DrawViewPart"):
                return o
        return None

    def IsActive(self):
        return self._view() is not None

    def Activated(self):
        view = self._view()
        doc = view.Document
        doc.openTransaction("Inherit PMI")
        objs, how = pmi_for_view(view)
        made, skipped = inherit(view, objs)
        doc.commitTransaction()
        last_inherit_how[view.Name] = how
        msg = f"Inherit PMI ({how}): {len(made)} annotation(s) on {view.Label}"
        for label, why in skipped:
            msg += f"\n  {label}: not placed ({why})"
        App.Console.PrintMessage(msg + "\n")


COMMANDS = {
    "NXStyle_PMIRapidDimension": PMICommand(DimensionPanel, "Rapid Dimension",
                                            "PMI: a dimension on the model. Select a cylinder (diameter) or two "
                                            "faces (distance) first; it is measured from the model and keeps up "
                                            "with design changes", "pmi_dimension.svg"),
    "NXStyle_PMIFeatureControlFrame": PMICommand(FramePanel, "Feature Control Frame",
                                                 "PMI: a feature control frame on the selected face",
                                                 "feature_control_frame.svg"),
    "NXStyle_PMIDatumFeatureSymbol": PMICommand(DatumPanel, "Datum Feature Symbol",
                                                "PMI: a datum feature symbol on the selected face",
                                                "datum_feature_symbol.svg"),
    "NXStyle_PMIInspectionPlan": InspectionPlan(),
    "NXStyle_PMITolerancing": Tolerancing(),
    "NXStyle_InheritPMI": InheritPMI(),
    "NXStyle_PMIExportSTEP": ExportStep(),
    "NXStyle_PMIImportSTEP": ImportStep(),
    "NXStyle_PMIDisplayInViews": DisplayInViews(),
    "NXStyle_PMINewModelView": NewModelView(),
    "NXStyle_PMIShowAll": ShowAllPMI(),
}
