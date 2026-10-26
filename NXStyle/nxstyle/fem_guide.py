# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Simulation (FEM) application's guided workflow.

The ribbon's Home tab shows the analysis as numbered steps (``ribbons/simulation.json``): each group
carries a ``step``. From the active analysis's members this module says which steps are done and
which comes next; the shell ticks finished groups and highlights the next one.

``classify`` and ``states`` need no FreeCAD, so the unit tests check them. ``active_members`` reads
the document.
"""

STEPS = ("analysis", "material", "loads", "mesh", "solve", "results")

MATERIAL_TYPES = {"Fem::MaterialCommon", "Fem::MaterialFluid", "Fem::MaterialMechanicalNonlinear",
                  "Fem::MaterialReinforced", "Fem::MaterialElectromagnetic"}


def classify(type_id, proxy_type=""):
    """The workflow step an analysis member belongs to, or None. FreeCAD's Python FEM objects share a
    generic TypeId (Fem::FemSolverObjectPython ...) and say what they are in Proxy.Type."""
    kind = proxy_type or ""
    t = type_id or ""
    if t == "Fem::FemAnalysis" or kind == "Fem::FemAnalysis":
        return "analysis"
    if kind in MATERIAL_TYPES or kind.startswith("Fem::Material"):
        return "material"
    if t.startswith("Fem::Constraint") or kind.startswith("Fem::Constraint"):
        return "loads"
    if t.startswith("Fem::FemMesh") or kind.startswith("Fem::FemMesh"):
        return "mesh"
    if t.startswith("Fem::FemSolver") or kind.startswith("Fem::Solver"):
        return "solver"
    if (t.startswith("Fem::FemResult") or kind.startswith("Fem::Result") or t.startswith("Fem::FemPost")
            or kind.startswith("Fem::FemPost")):
        return "results"
    return None


def states(members):
    """members: (TypeId, Proxy.Type) of the active analysis and its members, or None without one.

    Returns {step: "done" | "next" | ""}: steps in order, the first unfinished one is next. Solve
    is done when the analysis has results (a solver alone has not solved anything); Results is
    "next" once there are results to look at and stays so (looking at them is not tracked)."""
    found = {classify(t, p) for t, p in (members or [])}
    if members is not None:
        found.add("analysis")
    done = {
        "analysis": "analysis" in found,
        "material": "material" in found,
        "loads": "loads" in found,
        "mesh": "mesh" in found,
        "solve": "solver" in found and "results" in found,
        "results": False,
    }
    out = {}
    next_given = False
    for step in STEPS:
        if done[step]:
            out[step] = "done"
        elif not next_given:
            out[step] = "next"
            next_given = True
        else:
            out[step] = ""
    if "results" in found:
        out["results"] = "next"
    return out


def active_analysis(doc=None):
    """The analysis FEM works on: FemGui's active one, else the document's only one."""
    import FreeCAD as App
    doc = doc or App.ActiveDocument
    if doc is None:
        return None
    try:
        import FemGui
        a = FemGui.getActiveAnalysis()
        if a is not None and a.Document == doc:
            return a
    except Exception:
        pass
    analyses = [o for o in doc.Objects if o.TypeId == "Fem::FemAnalysis"]
    return analyses[0] if len(analyses) == 1 else None


def active_members(doc=None):
    analysis = active_analysis(doc)
    if analysis is None:
        return None
    out = []
    for o in analysis.Group:
        proxy = getattr(o, "Proxy", None)
        out.append((o.TypeId, getattr(proxy, "Type", "") if proxy is not None else ""))
    return out
