# SPDX-License-Identifier: LGPL-2.1-or-later
"""STEP AP242 with semantic PMI (ISO 10303-242): the model and its PMI in one file that CAM, CMM
and other CAD systems read as data, not as pictures.

FreeCAD's STEP writer drops PMI. Its Windows and conda builds ship pythonocc-core, which reaches
OpenCASCADE's XCAF dimension and tolerance tools (XCAFDoc_DimTolTool) and its AP242 writer
(STEPCAFControl_Writer, GDT mode). This module maps NXStyle's PMI (pmi.py annotations) onto those:

  datum feature       -> DATUM + DATUM_FEATURE on the face
  datum references    -> DATUM_SYSTEM of DATUM_REFERENCE_COMPARTMENTs (precedence 1, 2, 3; MMB/LMB)
  diameter / radius   -> DIMENSIONAL_SIZE 'diameter' / 'radius'
  width (slot, tab)   -> DIMENSIONAL_SIZE 'thickness' on both faces (a feature of size)
  distance            -> DIMENSIONAL_LOCATION between the two faces
  deviations          -> PLUS_MINUS_TOLERANCE; an ISO 286 class adds LIMITS_AND_FITS (H, hole, 7)
  feature control     -> <characteristic>_TOLERANCE with zone form (cylindrical for Ø), material
  frame                  requirement (M)/(L) and its datum system

The mapping follows OCCT's XCAFDimTolObjects enumerations, the same ones FreeCAD's planned PMI
workbench names for its AP242 exchange (FreeCAD issue 29772, appendix A).

Not written, because OCCT 7.8 has no semantic slot for them: ISO 14405 (E) envelope, basic
(theoretically exact) dimensions, "4X" counts and the ISO 2768 general tolerance (it stays in
pmi.json and on the drawing). A dimension that takes its tolerance from ISO 2768 is written with its
nominal only.

OCCT 7.8 writes the grade of LIMITS_AND_FITS two too high (IT7 as '9'), so its own reader returns
IT9; write() puts the IT number the annotation has into the file. The pure functions here (plan,
fix_limits_and_fits, summary) need neither FreeCAD nor OCCT.
"""

import re

from . import iso, pmi

# NXStyle characteristic -> OCCT XCAFDimTolObjects_GeomToleranceType_*
GEOM_TYPES = {
    "position": "Position",
    "flatness": "Flatness",
    "straightness": "Straightness",
    "circularity": "CircularityOrRoundness",
    "cylindricity": "Cylindricity",
    "perpendicularity": "Perpendicularity",
    "parallelism": "Parallelism",
    "angularity": "Angularity",
    "profile of a surface": "ProfileOfSurface",
    "profile of a line": "ProfileOfLine",
    "concentricity": "Concentricity",     # ISO 1101 coaxiality when the toleranced feature is an axis
    "symmetry": "Symmetry",
    "circular runout": "CircularRunout",
    "total runout": "TotalRunout",
}
# STEP entity each characteristic becomes (for summary())
ENTITY = {
    "Position": "POSITION_TOLERANCE", "Flatness": "FLATNESS_TOLERANCE",
    "Straightness": "STRAIGHTNESS_TOLERANCE", "CircularityOrRoundness": "ROUNDNESS_TOLERANCE",
    "Cylindricity": "CYLINDRICITY_TOLERANCE", "Perpendicularity": "PERPENDICULARITY_TOLERANCE",
    "Parallelism": "PARALLELISM_TOLERANCE", "Angularity": "ANGULARITY_TOLERANCE",
    "ProfileOfSurface": "SURFACE_PROFILE_TOLERANCE", "ProfileOfLine": "LINE_PROFILE_TOLERANCE",
    "Concentricity": "CONCENTRICITY_TOLERANCE", "Coaxiality": "COAXIALITY_TOLERANCE",
    "Symmetry": "SYMMETRY_TOLERANCE", "CircularRunout": "CIRCULAR_RUNOUT_TOLERANCE",
    "TotalRunout": "TOTAL_RUNOUT_TOLERANCE",
}
MATERIAL = {"MMC": "M", "LMC": "L"}

# XCAF child labels of a geometric tolerance (XCAFDoc_GeomTolerance.cxx); pythonocc does not wrap
# XCAFDoc_GeomTolerance, so write() sets these attributes as XCAFDoc_GeomTolerance::SetObject does
GT_TYPE, GT_TYPE_OF_VALUE, GT_VALUE, GT_MATERIAL, GT_ZONE = 1, 2, 3, 4, 5


# ------------------------------------------------------------------ what is written (pure)
def geom_type(a, standard="ISO"):
    """OCCT type name of a feature control frame annotation."""
    t = GEOM_TYPES[a["characteristic"]]
    if t == "Concentricity" and standard == "ISO" and a.get("feature_type") in ("hole", "pin"):
        return "Coaxiality"
    return t


def dimension_type(a):
    """OCCT dimension type name, and whether the dimension is a size (one feature) or a location."""
    d = a.get("dim_type")
    if d == "diameter":
        return "Size_Diameter", True
    if d == "radius":
        return "Size_Radius", True
    if d == "angle":
        return "Location_Angular", False
    if a.get("feature_type") == "width":
        return "Size_Thickness", True
    return "Location_LinearDistance", False


def plan(annotations, standard="ISO", general=None):
    """What write() puts into the STEP file, one record per annotation, in file order:

      {"kind": "datum", "id", "letter"}
      {"kind": "dimension", "id", "type", "size", "nominal", "upper", "lower", "fit": (letter, grade,
       "hole"/"shaft") or None, "not_written": [...]}
      {"kind": "fcf", "id", "type", "value", "diameter", "material", "datums": [(letter, precedence,
       material)], "not_written": [...]}

    upper/lower are signed deviations (mm); None when the dimension has no individual tolerance.
    """
    out = []
    for a in annotations:
        k = a["kind"]
        if k == "datum":
            out.append({"kind": "datum", "id": a["id"], "letter": a["letter"]})
        elif k == "dimension":
            t, size = dimension_type(a)
            r = {"kind": "dimension", "id": a["id"], "type": t, "size": size, "nominal": a["nominal"],
                 "upper": None, "lower": None, "fit": None, "not_written": []}
            p, m, src = pmi.deviations(a, general)
            if src.startswith("ISO 286"):
                letter, grade, kind = iso.parse_class(a["fit"])
                r.update(upper=p, lower=-m, fit=(letter, grade, kind))
            elif src == "individual":
                r.update(upper=p, lower=-m)
            elif src.startswith("ISO 2768"):
                r["not_written"].append(f"{src} general tolerance")
            if a.get("basic"):
                r["not_written"].append("basic (theoretically exact)")
            if a.get("envelope"):
                r["not_written"].append("ISO 14405 envelope (E)")
            if a.get("count", 1) > 1:
                r["not_written"].append(f"{a['count']}X")
            out.append(r)
        elif k == "fcf":
            r = {"kind": "fcf", "id": a["id"], "type": geom_type(a, standard), "value": a["tolerance"],
                 "diameter": bool(a.get("diameter")), "material": MATERIAL.get(a.get("modifier", ""), ""),
                 "datums": [(d[0], i, MATERIAL.get(d[1] if len(d) > 1 else "", ""))
                            for i, d in enumerate(a.get("datums", []), 1)],
                 "not_written": []}
            low = pmi.lower(a)
            if low:
                # the lower row goes out as a second tolerance on the same faces; OCCT's XCAF has no relationship
                # that ties it to the upper one, so a composite frame reads back as two single-segment frames
                r["lower"] = {"value": low["tolerance"], "material": MATERIAL.get(low.get("modifier", ""), ""),
                              "datums": [(d[0], i, MATERIAL.get(d[1] if len(d) > 1 else "", ""))
                                         for i, d in enumerate(low.get("datums", []), 1)]}
                if pmi.composite(a):
                    r["not_written"].append("the composite link between the rows (written as two frames)")
            out.append(r)
    return out


# ------------------------------------------------------------------ the file (pure)
_LAF = re.compile(r"LIMITS_AND_FITS\('([^']*)','([^']*)','([^']*)','([^']*)'\)")


def fix_limits_and_fits(text, fits):
    """Put the ISO 286 class each dimension has into the LIMITS_AND_FITS entities of a STEP file:
    fits is the (letter, grade, 'hole'/'shaft') of each dimension with a class, in file order.
    Returns (text, number of entities changed); the text is unchanged when the counts disagree."""
    found = _LAF.findall(text)
    if len(found) != len(fits):
        return text, 0
    it = iter(fits)
    changed = [0]

    def repl(m):
        letter, grade, kind = next(it)
        new = f"LIMITS_AND_FITS('{letter}','{kind}','{grade}','{m.group(4)}')"
        if new != m.group(0):
            changed[0] += 1
        return new

    return _LAF.sub(repl, text), changed[0]


def _entities(text):
    """{id: 'ENTITY(...)'} of a STEP file's DATA section, complex entities joined to one line."""
    body = text[text.find("DATA;"):]
    out = {}
    for m in re.finditer(r"#(\d+)\s*=\s*(.*?);\s*(?=#\d+\s*=|ENDSEC)", body, re.S):
        out[int(m.group(1))] = " ".join(m.group(2).split())
    return out


_NUM = r"([-+]?(?:\d+\.?\d*|\.\d+)(?:E[-+]?\d+)?)"


def signed_tolerances(text):
    """[(nominal, lower, upper)] of every ± tolerance in a STEP file, signed as written (OCCT's reader
    returns only the size of the lower bound, so a lower bound above nominal would come back below it)."""
    ents = _entities(text)

    def number(i):
        e = ents.get(i, "")
        m = re.search(r"MEASURE\(" + _NUM + r"\)", e) or re.search(r"MEASURE_WITH_UNIT\(" + _NUM, e)
        return float(m.group(1)) if m else None

    nominal = {}
    for e in ents.values():
        m = re.match(r"DIMENSIONAL_CHARACTERISTIC_REPRESENTATION\(#(\d+),#(\d+)\)", e)
        if m:
            rep = ents.get(int(m.group(2)), "")
            items = re.findall(r"#(\d+)", rep)
            vals = [number(int(i)) for i in items]
            vals = [v for v in vals if v is not None]
            if vals:
                nominal[int(m.group(1))] = vals[0]
    out = []
    for e in ents.values():
        m = re.match(r"PLUS_MINUS_TOLERANCE\(#(\d+),#(\d+)\)", e)
        if not m:
            continue
        tv = re.match(r"TOLERANCE_VALUE\(#(\d+),#(\d+)\)", ents.get(int(m.group(1)), ""))
        if tv and int(m.group(2)) in nominal:
            lo, up = number(int(tv.group(1))), number(int(tv.group(2)))
            if lo is not None and up is not None:
                out.append((nominal[int(m.group(2))], lo, up))
    return out


def summary(text):
    """The semantic PMI a STEP file holds, read from its entities:
    {"schema", "datums": [letters], "datum_systems": n, "dimensions": {"diameter": n, ...},
     "locations": n, "plus_minus": n, "fits": ["H7", ...], "tolerances": {"POSITION_TOLERANCE": n},
     "material_requirements": n, "values": [tolerance values]}"""
    head = text[: text.find("DATA;")] if "DATA;" in text else text[:4000]
    sm = re.search(r"FILE_SCHEMA\s*\(\s*\(\s*'([^'{]*)", head)
    ents = _entities(text)
    s = {"schema": sm.group(1).strip(" .") if sm else "", "datums": [], "datum_systems": 0, "dimensions": {},
         "locations": 0, "plus_minus": 0, "fits": [], "tolerances": {}, "material_requirements": 0, "values": []}
    measures = {}
    for i, e in ents.items():
        m = re.match(r"LENGTH_MEASURE_WITH_UNIT\(LENGTH_MEASURE\(([-+0-9.E]+)\)", e)
        if m:
            measures[i] = float(m.group(1))
    types = set(ENTITY.values())
    toleranced = set()
    for i, e in ents.items():
        if e.startswith("DATUM("):
            s["datums"].append(e.split("'")[-2])
        elif e.startswith("DATUM_SYSTEM("):
            s["datum_systems"] += 1
        elif e.startswith("DIMENSIONAL_SIZE("):
            kind = e.split("'")[-2]
            s["dimensions"][kind] = s["dimensions"].get(kind, 0) + 1
        elif e.startswith(("DIMENSIONAL_LOCATION(", "DIRECTED_DIMENSIONAL_LOCATION(", "ANGULAR_LOCATION(")):
            s["locations"] += 1
        elif e.startswith("PLUS_MINUS_TOLERANCE("):          # a class adds a second one to the same dimension
            toleranced.add(e.rstrip(")").split(",")[-1].strip())
        m = _LAF.search(e)
        if m:
            s["fits"].append(f"{m.group(1)}{m.group(3)}")
        if "TOLERANCE" in e:
            found = [t for t in types if re.search(rf"\b{t}\(", e)]
            for t in found:
                s["tolerances"][t] = s["tolerances"].get(t, 0) + 1
            if found:
                if "MAXIMUM_MATERIAL_REQUIREMENT" in e or "LEAST_MATERIAL_REQUIREMENT" in e:
                    s["material_requirements"] += 1
                ref = re.search(r"GEOMETRIC_TOLERANCE\('[^']*','[^']*',#(\d+)", e) or \
                    re.match(r"\w+\('[^']*','[^']*',#(\d+)", e)
                if ref and int(ref.group(1)) in measures:
                    s["values"].append(measures[int(ref.group(1))])
    s["plus_minus"] = len(toleranced)
    s["datums"].sort()
    s["fits"].sort()
    s["values"].sort()
    return s


def summary_text(s):
    dims = ", ".join(f"{n} {k}" for k, n in sorted(s["dimensions"].items())) or "none"
    tols = ", ".join(f"{n} {k.replace('_TOLERANCE', '').lower().replace('_', ' ')}"
                     for k, n in sorted(s["tolerances"].items())) or "none"
    return (f"schema {s['schema']}; datums {', '.join(s['datums']) or 'none'} ({s['datum_systems']} datum systems); "
            f"sizes: {dims}; locations: {s['locations']}; with ± tolerances: {s['plus_minus']}; "
            f"fits: {', '.join(s['fits']) or 'none'}; geometric tolerances: {tols}")


# ------------------------------------------------------------------ writing (FreeCAD + OCCT)
def available():
    """True when this FreeCAD has pythonocc with the XCAF tolerance tools and the AP242 writer."""
    try:
        import OCC.Core.XCAFDimTolObjects  # noqa: F401
        from OCC.Core.STEPCAFControl import STEPCAFControl_Writer  # noqa: F401
        return True
    except Exception:
        return False


def _match(shape, sub, tol=1e-6):
    """1-based index of the face (or edge) of shape that is sub, by identity or by geometry."""
    items = shape.Faces if sub.ShapeType == "Face" else shape.Edges
    for i, f in enumerate(items, 1):
        if f.isSame(sub):
            return i
    size = max(shape.BoundBox.DiagonalLength, 1.0)
    measure = (lambda s: s.Area) if sub.ShapeType == "Face" else (lambda s: s.Length)
    m0, c0 = measure(sub), sub.CenterOfMass
    for i, f in enumerate(items, 1):
        if abs(measure(f) - m0) <= tol * max(m0, 1.0) and (f.CenterOfMass - c0).Length <= tol * size and \
                type(getattr(f, "Surface", getattr(f, "Curve", None))) is \
                type(getattr(sub, "Surface", getattr(sub, "Curve", None))):
            return i
    return None


def write(objs, pmi_objs, path, standard="ISO", general=None, names=None, colors=None):
    """STEP AP242 of the solids objs with the semantic PMI of pmi_objs (pmi_ui PMIFeature objects).

    Returns (summary of the written file, problems): a problem is an annotation that could not be
    attached (its face is on none of objs) or an attribute OCCT cannot carry."""
    import Part

    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.Interface import Interface_Static
    from OCC.Core.Quantity import Quantity_Color, Quantity_TOC_RGB
    from OCC.Core.STEPCAFControl import STEPCAFControl_Controller, STEPCAFControl_Writer
    from OCC.Core.TCollection import TCollection_HAsciiString
    from OCC.Core.TDataStd import TDataStd_Integer, TDataStd_Name, TDataStd_Real
    from OCC.Core.TDF import TDF_Label, TDF_LabelSequence
    from OCC.Core.TDocStd import TDocStd_Document
    from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCC.Core.TopExp import topexp
    from OCC.Core.TopTools import TopTools_IndexedMapOfShape
    from OCC.Core.XCAFDoc import XCAFDoc_ColorSurf, XCAFDoc_Datum, XCAFDoc_Dimension, XCAFDoc_DocumentTool
    import OCC.Core.XCAFDimTolObjects as X

    from . import claims, pmi_ui, refs

    STEPCAFControl_Controller.Init()
    Interface_Static.SetCVal("write.step.schema", "AP242DIS")
    Interface_Static.SetCVal("write.step.unit", "MM")

    doc = TDocStd_Document("pythonocc-xcaf")
    shapes = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    dimtol = XCAFDoc_DocumentTool.DimTolTool(doc.Main())
    colortool = XCAFDoc_DocumentTool.ColorTool(doc.Main())

    parts = []                       # (FreeCAD global shape, XCAF label, face map, edge map)
    for o in objs:
        g = claims.global_shape(o)          # where refs.resolve puts the PMI faces, inside assemblies too
        label = shapes.AddShape(Part.__toPythonOCC__(g), False, False)
        name = str((names or {}).get(o.Name, o.Label))
        TDataStd_Name.Set(label, name)
        if shapes.IsReference(label):        # a located shape: sub-shapes hang on the shape it refers to
            simple = TDF_Label()
            if shapes.GetReferredShape(label, simple) and not simple.IsNull():
                label = simple
                TDataStd_Name.Set(label, name)
        rgb = (colors or {}).get(o.Name)
        if rgb:
            colortool.SetColor(label, Quantity_Color(*rgb[:3], Quantity_TOC_RGB), XCAFDoc_ColorSurf)
        fmap, emap = TopTools_IndexedMapOfShape(), TopTools_IndexedMapOfShape()
        topexp.MapShapes(shapes.GetShape(label), TopAbs_FACE, fmap)
        topexp.MapShapes(shapes.GetShape(label), TopAbs_EDGE, emap)
        parts.append((g, label, fmap, emap))

    problems = []

    def labels_of(p):
        """XCAF sub-shape labels of the faces/edges a PMI object is attached to."""
        out = []
        for o, subs in p.References:
            for s in subs or [""]:
                try:
                    sub = refs.resolve(o, s)
                except Exception as e:
                    problems.append(f"{p.Label}: {refs.describe(o, s)}: {e}")
                    continue
                for g, root, fmap, emap in parts:
                    i = _match(g, sub)
                    if i is None:
                        continue
                    occ = (fmap if sub.ShapeType == "Face" else emap).FindKey(i)
                    lab = TDF_Label()
                    if not shapes.FindSubShape(root, occ, lab):
                        lab = shapes.AddSubShape(root, occ)
                    if lab.IsNull():
                        problems.append(f"{p.Label}: {refs.describe(o, s)} could not be labelled in STEP")
                    else:
                        out.append(lab)
                    break
                else:
                    problems.append(f"{p.Label}: {refs.describe(o, s)} is not on an exported solid")
        return out

    def seq(labels):
        q = TDF_LabelSequence()
        for lab in labels:
            q.Append(lab)
        return q

    objs_by_id = {p.Name: p for p in pmi_objs}
    anns = [pmi_ui.semantic(p) for p in pmi_objs]
    datum_faces = {}
    for a in anns:
        if a["kind"] == "datum":
            datum_faces.setdefault(a["letter"], labels_of(objs_by_id[a["id"]]))

    def datum(letter, position, material=""):
        faces = datum_faces.get(letter)
        if not faces:
            problems.append(f"datum {letter} is referenced but has no datum feature symbol")
            return None
        lab = dimtol.AddDatum()
        d = X.XCAFDimTolObjects_DatumObject()
        d.SetName(TCollection_HAsciiString(letter))
        d.SetPosition(position)
        if material:
            d.AddModifier(X.XCAFDimTolObjects_DatumSingleModif_MaximumMaterialRequirement if material == "M"
                          else X.XCAFDimTolObjects_DatumSingleModif_LeastMaterialRequirement)
        XCAFDoc_Datum.Set(lab).SetObject(d)
        dimtol.SetDatum(seq(faces), lab)
        return lab

    fits = []
    referenced = {d[0] for a in anns if a["kind"] == "fcf"
                  for d in list(a.get("datums", [])) + list((pmi.lower(a) or {}).get("datums", []))}
    for a, r in zip(anns, plan(anns, standard, general)):
        p = objs_by_id[a["id"]]
        for what in r.get("not_written", []):
            problems.append(f"{p.Label}: {what} has no AP242 semantic form in OCCT; not written")
        if r["kind"] == "datum":
            if r["letter"] not in referenced:          # datums in a frame are written with it
                datum(r["letter"], 1)
            continue
        on = labels_of(p)
        if not on:
            continue
        if r["kind"] == "dimension":
            lab = dimtol.AddDimension()
            d = X.XCAFDimTolObjects_DimensionObject()
            d.SetType(getattr(X, "XCAFDimTolObjects_DimensionType_" + r["type"]))
            d.SetValue(float(r["nominal"]))
            if r["upper"] is not None:
                d.SetUpperTolValue(float(r["upper"]))
                # OCCT takes the lower tolerance as the size below nominal and writes its negative as the
                # TOLERANCE_VALUE lower bound (measured: -0.1 given became +0.1 in the file)
                d.SetLowerTolValue(-float(r["lower"]))
            if r["fit"]:
                letter, grade, kind = r["fit"]
                variance = getattr(X, "XCAFDimTolObjects_DimensionFormVariance_" + letter.upper(), None)
                if variance is None:
                    problems.append(f"{p.Label}: OCCT has no form variance {letter}; class not written")
                else:
                    d.SetClassOfTolerance(kind == "hole", variance,
                                          getattr(X, f"XCAFDimTolObjects_DimensionGrade_IT{grade}"))
                    fits.append(r["fit"])
            XCAFDoc_Dimension.Set(lab).SetObject(d)
            if r["size"] and len(on) == 1:
                dimtol.SetDimension(on[0], lab)
            elif r["size"]:
                dimtol.SetDimension(seq(on), TDF_LabelSequence(), lab)
            elif len(on) >= 2:
                dimtol.SetDimension(seq(on[:1]), seq(on[1:2]), lab)
            else:
                problems.append(f"{p.Label}: a distance needs two faces")
        else:
            for row in [r] + ([dict(r, **r["lower"])] if r.get("lower") else []):
                lab = dimtol.AddGeomTolerance()
                TDataStd_Integer.Set(lab.FindChild(GT_TYPE), int(getattr(X, "XCAFDimTolObjects_GeomToleranceType_"
                                                                           + row["type"])))
                if row["diameter"]:
                    TDataStd_Integer.Set(lab.FindChild(GT_TYPE_OF_VALUE),
                                         int(X.XCAFDimTolObjects_GeomToleranceTypeValue_Diameter))
                TDataStd_Real.Set(lab.FindChild(GT_VALUE), float(row["value"]))
                mat = {"M": X.XCAFDimTolObjects_GeomToleranceMatReqModif_M,
                       "L": X.XCAFDimTolObjects_GeomToleranceMatReqModif_L}.get(
                    row["material"], X.XCAFDimTolObjects_GeomToleranceMatReqModif_None)
                TDataStd_Integer.Set(lab.FindChild(GT_MATERIAL), int(mat))
                TDataStd_Integer.Set(lab.FindChild(GT_ZONE), int(X.XCAFDimTolObjects_GeomToleranceZoneModif_None))
                dimtol.SetGeomTolerance(seq(on), lab)
                for letter, position, material in row["datums"]:
                    dl = datum(letter, position, material)
                    if dl is not None:
                        dimtol.SetDatumToGeomTol(dl, lab)

    w = STEPCAFControl_Writer()
    w.SetDimTolMode(True)
    w.SetNameMode(True)
    w.SetColorMode(True)
    if not w.Transfer(doc):
        raise RuntimeError("OpenCASCADE could not transfer the model to STEP")
    if w.Write(path) != IFSelect_RetDone:
        raise RuntimeError(f"OpenCASCADE could not write {path}")
    with open(path, encoding="latin-1") as f:
        text = f.read()
    if "NUL REF" in text:
        problems.append("the STEP file has null references: a PMI attachment did not reach the model")
    text, _ = fix_limits_and_fits(text, fits)
    with open(path, "w", encoding="latin-1", newline="") as f:
        f.write(text)
    return summary(text), problems


# ------------------------------------------------------------------ reading (the other direction)
GEOM_NAMES = {v: k for k, v in GEOM_TYPES.items()}
GEOM_NAMES["Coaxiality"] = "concentricity"          # ISO's coaxiality uses the concentricity symbol here
MATERIAL_NAMES = {"M": "MMC", "L": "LMC", "": "None"}


def pmi_values(record):
    """The PMI object's properties (pmi_ui.create keyword arguments) for a record read from a file:

      {"kind": "dimension", "type": "Size_Diameter", "upper", "lower", "fit": (letter, grade, kind) or None}
      {"kind": "fcf", "type": "Position", "value", "diameter", "material": "M"/"L"/"",
       "datums": [(letter, precedence, material)]}
      {"kind": "datum", "letter"}
    Returns (PMI type, properties), or (None, reason) for what NXStyle's PMI cannot hold."""
    k = record["kind"]
    if k == "datum":
        return "Datum Feature", {"Letter": record["letter"]}
    if k == "dimension":
        t = record["type"]
        dim = "Diameter" if t == "Size_Diameter" else "Radius" if t == "Size_Radius" else \
            "Distance" if t in ("Size_Thickness", "Location_LinearDistance") else None
        if dim is None:
            return None, f"dimension type {t} is not one NXStyle's PMI has"
        values = {"DimensionType": dim}
        if record.get("fit"):
            letter, grade, kind = record["fit"]
            values["Fit"] = f"{letter.upper() if kind == 'hole' else letter.lower()}{grade}"
        elif record.get("upper") is not None:
            values["UpperDeviation"] = float(record["upper"])
            values["LowerDeviation"] = -float(record["lower"])          # stored as a magnitude below nominal
        return "Dimension", values
    if k == "fcf":
        name = GEOM_NAMES.get(record["type"])
        if name is None:
            return None, f"tolerance type {record['type']} is not one NXStyle's PMI has"
        refs = [f"{letter}({mat})" if mat else letter for letter, _, mat in sorted(record.get("datums", []),
                                                                                   key=lambda d: d[1])]
        return "Feature Control Frame", {"Characteristic": name.title(), "Tolerance": float(record["value"]),
                                         "ZoneDiameter": bool(record.get("diameter")),
                                         "MaterialCondition": MATERIAL_NAMES.get(record.get("material", ""), "None"),
                                         "DatumReferences": refs}
    return None, f"unknown record {k}"


def read(path):
    """Model and semantic PMI of an AP242 file (OCCT's reader in GDT mode).

    Returns {"shapes": [(name, OCC shape)], "records": [record with "faces": [(shape index, "FaceN"), ...] and,
    for a distance, "faces2"], "problems": [...]}; records as pmi_values() takes them."""
    from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
    from OCC.Core.TDF import TDF_AttributeIterator, TDF_LabelSequence
    from OCC.Core.TDataStd import TDataStd_Integer, TDataStd_Real
    from OCC.Core.TDocStd import TDocStd_Document
    from OCC.Core.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCC.Core.TopExp import topexp
    from OCC.Core.TopTools import TopTools_IndexedMapOfShape
    from OCC.Core.XCAFDoc import XCAFDoc_Datum, XCAFDoc_Dimension, XCAFDoc_DocumentTool
    import OCC.Core.XCAFDimTolObjects as X

    def names(prefix):
        return {int(getattr(X, n)): n[len(prefix):] for n in dir(X) if n.startswith(prefix)}
    geom = names("XCAFDimTolObjects_GeomToleranceType_")
    dims = names("XCAFDimTolObjects_DimensionType_")
    variance = names("XCAFDimTolObjects_DimensionFormVariance_")
    grade = {k: v for k, v in names("XCAFDimTolObjects_DimensionGrade_").items()}
    mmb = int(X.XCAFDimTolObjects_DatumSingleModif_MaximumMaterialRequirement)
    lmb = int(X.XCAFDimTolObjects_DatumSingleModif_LeastMaterialRequirement)

    r = STEPCAFControl_Reader()
    r.SetGDTMode(True)
    r.SetNameMode(True)
    doc = TDocStd_Document("pythonocc-xcaf")
    if not r.ReadFile(path):
        raise RuntimeError(f"OpenCASCADE could not read {path}")
    r.Transfer(doc)
    st = XCAFDoc_DocumentTool.ShapeTool(doc.Main())
    dt = XCAFDoc_DocumentTool.DimTolTool(doc.Main())

    def attrs(label):
        """{type name: value} of the label's own attributes."""
        out = {}
        it = TDF_AttributeIterator(label)
        while it.More():
            a = it.Value()
            n = a.DynamicType().Name()
            try:
                if n == "TDataStd_Integer":
                    out[n] = TDataStd_Integer.DownCast(a).Get()
                elif n == "TDataStd_Real":
                    out[n] = TDataStd_Real.DownCast(a).Get()
                elif n == "TDataStd_Name":
                    out[n] = label.GetLabelName()        # pythonocc does not wrap TDataStd_Name.Get()
            except Exception:
                pass
            it.Next()
        return out

    from OCC.Core.TDF import TDF_Label

    def parts_of(lab, loc, out):
        """The simple (part) shapes under a free shape: PMI hang on their faces in the part's own frame,
        and an assembly or a reference places them (loc)."""
        if st.IsAssembly(lab):
            comps = TDF_LabelSequence()
            st.GetComponents(lab, comps)
            for k in range(1, comps.Length() + 1):
                c = comps.Value(k)
                ref = TDF_Label()
                if st.GetReferredShape(c, ref):
                    parts_of(ref, loc.Multiplied(st.GetLocation(c)), out)
            return
        if st.IsReference(lab):
            ref = TDF_Label()
            if st.GetReferredShape(lab, ref):
                parts_of(ref, loc.Multiplied(st.GetLocation(lab)), out)
            return
        out.append((lab, loc))

    from OCC.Core.TopLoc import TopLoc_Location
    free = TDF_LabelSequence()
    st.GetFreeShapes(free)
    leaves = []
    for i in range(1, free.Length() + 1):
        parts_of(free.Value(i), TopLoc_Location(), leaves)
    shapes, maps = [], []
    for i, (lab, loc) in enumerate(leaves, 1):
        s = st.GetShape(lab)                      # in the part's own frame: the PMI's faces are found here
        fmap, emap = TopTools_IndexedMapOfShape(), TopTools_IndexedMapOfShape()
        topexp.MapShapes(s, TopAbs_FACE, fmap)
        topexp.MapShapes(s, TopAbs_EDGE, emap)
        placed = s.Moved(loc) if not loc.IsIdentity() else s
        shapes.append((attrs(lab).get("TDataStd_Name") or f"Part{i}", placed))
        maps.append((fmap, emap))
    problems = []

    def where(seq):
        out = []
        for k in range(1, seq.Length() + 1):
            s = st.GetShape(seq.Value(k))
            for n, (fmap, emap) in enumerate(maps):
                m, kind = (fmap, "Face") if s.ShapeType() == TopAbs_FACE else (emap, "Edge")
                idx = m.FindIndex(s)
                if idx:
                    out.append((n, f"{kind}{idx}"))
                    break
            else:
                problems.append("a PMI is attached to a shape that is not a face or edge of a part")
        return out

    records = []
    with open(path, encoding="latin-1") as f:
        written = signed_tolerances(f.read())
    q = TDF_LabelSequence()
    dt.GetDatumLabels(q)
    seen = set()
    for i in range(1, q.Length() + 1):
        lab = q.Value(i)
        o = XCAFDoc_Datum.Set(lab).GetObject()
        letter = o.GetName().ToCString() if o.GetName() is not None else ""
        a, b = TDF_LabelSequence(), TDF_LabelSequence()
        dt.GetRefShapeLabel(lab, a, b)
        faces = where(a)
        if letter and faces and letter not in seen:
            seen.add(letter)
            records.append({"kind": "datum", "letter": letter, "faces": faces})
    q = TDF_LabelSequence()
    dt.GetDimensionLabels(q)
    for i in range(1, q.Length() + 1):
        lab = q.Value(i)
        o = XCAFDoc_Dimension.Set(lab).GetObject()
        a, b = TDF_LabelSequence(), TDF_LabelSequence()
        dt.GetRefShapeLabel(lab, a, b)
        rec = {"kind": "dimension", "type": dims.get(int(o.GetType()), str(o.GetType())), "nominal": o.GetValue(),
               "upper": None, "lower": None, "fit": None, "faces": where(a), "faces2": where(b)}
        if o.IsDimWithClassOfTolerance():
            vals = list(o.GetClassOfTolerance())        # pythonocc: (ok, isHole, form variance, grade)
            hole, fv, gr = vals[-3:]
            letter, it_grade = variance.get(int(fv), ""), grade.get(int(gr), "")
            if letter and it_grade.startswith("IT") and it_grade[2:].isdigit():
                rec["fit"] = (letter, int(it_grade[2:]), "hole" if hole else "shaft")
        if o.GetUpperTolValue() or o.GetLowerTolValue():
            up, size = o.GetUpperTolValue(), o.GetLowerTolValue()
            # the reader gives the lower bound's size only: its sign comes from the file itself
            signed = [lo for nom, lo, u in written if abs(nom - rec["nominal"]) < 1e-9 and abs(u - up) < 1e-9
                      and abs(abs(lo) - abs(size)) < 1e-9]
            rec["upper"] = up
            rec["lower"] = signed[0] if len(set(signed)) == 1 else -abs(size)
        records.append(rec)
    q = TDF_LabelSequence()
    dt.GetGeomToleranceLabels(q)
    for i in range(1, q.Length() + 1):
        lab = q.Value(i)
        child = {n: attrs(lab.FindChild(n, False)) for n in (GT_TYPE, GT_TYPE_OF_VALUE, GT_VALUE, GT_MATERIAL)}
        a, b = TDF_LabelSequence(), TDF_LabelSequence()
        dt.GetRefShapeLabel(lab, a, b)
        mat = {int(X.XCAFDimTolObjects_GeomToleranceMatReqModif_M): "M",
               int(X.XCAFDimTolObjects_GeomToleranceMatReqModif_L): "L"}.get(
            child[GT_MATERIAL].get("TDataStd_Integer", -1), "")
        refs = TDF_LabelSequence()
        dt.GetDatumWithObjectOfTolerLabels(lab, refs)
        datums = []
        for k in range(1, refs.Length() + 1):
            d = XCAFDoc_Datum.Set(refs.Value(k)).GetObject()
            mods = d.GetModifiers()
            mm = [int(mods.Value(j)) for j in range(1, mods.Length() + 1)] if mods is not None else []
            datums.append((d.GetName().ToCString(), d.GetPosition(), "M" if mmb in mm else "L" if lmb in mm else ""))
        records.append({"kind": "fcf", "type": geom.get(child[GT_TYPE].get("TDataStd_Integer", -1), "?"),
                        "value": child[GT_VALUE].get("TDataStd_Real", 0.0),
                        "diameter": child[GT_TYPE_OF_VALUE].get("TDataStd_Integer", 0) ==
                        int(X.XCAFDimTolObjects_GeomToleranceTypeValue_Diameter),
                        "material": mat, "datums": datums, "faces": where(a)})
    return {"shapes": shapes, "records": records, "problems": problems}


def read_back(path):
    """Counts OCCT's AP242 reader finds in a file: {"datums", "dimensions", "geometric_tolerances"}."""
    from OCC.Core.STEPCAFControl import STEPCAFControl_Reader
    from OCC.Core.TDF import TDF_LabelSequence
    from OCC.Core.TDocStd import TDocStd_Document
    from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool

    r = STEPCAFControl_Reader()
    r.SetGDTMode(True)
    doc = TDocStd_Document("pythonocc-xcaf")
    r.ReadFile(path)
    r.Transfer(doc)
    tool = XCAFDoc_DocumentTool.DimTolTool(doc.Main())
    out = {}
    for key, get in (("datums", tool.GetDatumLabels), ("dimensions", tool.GetDimensionLabels),
                     ("geometric_tolerances", tool.GetGeomToleranceLabels)):
        q = TDF_LabelSequence()
        get(q)
        out[key] = q.Length()
    return out
