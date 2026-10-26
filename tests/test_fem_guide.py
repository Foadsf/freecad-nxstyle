# SPDX-License-Identifier: LGPL-2.1-or-later
"""The Simulation application's guided workflow (fem_guide.py and ribbons/simulation.json); no FreeCAD needed."""

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))

from nxstyle import fem_guide  # noqa: E402

RIBBONS = Path(__file__).resolve().parents[1] / "NXStyle" / "nxstyle" / "resources" / "ribbons"

# (TypeId, Proxy.Type) as FreeCAD 1.1's ObjectsFem makes them
MATERIAL = ("App::MaterialObjectPython", "Fem::MaterialCommon")
FIXED = ("Fem::ConstraintFixed", "")
GRAVITY = ("Fem::ConstraintPython", "Fem::ConstraintSelfWeight")
MESH = ("Fem::FemMeshObjectPython", "Fem::FemMeshGmsh")
SOLVER = ("Fem::FemSolverObjectPython", "Fem::SolverCalculiX")
RESULT = ("Fem::FemResultObjectPython", "Fem::ResultMechanical")


class Classify(unittest.TestCase):
    def test_members(self):
        self.assertEqual(fem_guide.classify(*MATERIAL), "material")
        self.assertEqual(fem_guide.classify(*FIXED), "loads")
        self.assertEqual(fem_guide.classify(*GRAVITY), "loads")
        self.assertEqual(fem_guide.classify(*MESH), "mesh")
        self.assertEqual(fem_guide.classify(*SOLVER), "solver")
        self.assertEqual(fem_guide.classify(*RESULT), "results")
        self.assertEqual(fem_guide.classify("Fem::FemPostPipeline", ""), "results")
        self.assertIsNone(fem_guide.classify("Part::Box", ""))
        self.assertIsNone(fem_guide.classify("Fem::FeaturePython", "Fem::EquationElmerElasticity"))


class States(unittest.TestCase):
    def test_no_analysis_means_create_one(self):
        s = fem_guide.states(None)
        self.assertEqual(s["analysis"], "next")
        self.assertEqual([v for v in s.values() if v == "next"], ["next"])

    def test_empty_analysis_asks_for_material(self):
        s = fem_guide.states([])
        self.assertEqual((s["analysis"], s["material"], s["loads"]), ("done", "next", ""))

    def test_order_is_kept_even_when_a_later_step_exists(self):
        """A mesh without a material: the material is still the next step, the mesh is done."""
        s = fem_guide.states([MESH])
        self.assertEqual((s["material"], s["mesh"]), ("next", "done"))

    def test_solver_alone_has_not_solved(self):
        s = fem_guide.states([MATERIAL, FIXED, MESH, SOLVER])
        self.assertEqual((s["solve"], s["results"]), ("next", ""))

    def test_complete_analysis(self):
        s = fem_guide.states([MATERIAL, FIXED, MESH, SOLVER, RESULT])
        self.assertEqual(s, {"analysis": "done", "material": "done", "loads": "done", "mesh": "done",
                             "solve": "done", "results": "next"})


class Ribbon(unittest.TestCase):
    def setUp(self):
        self.spec = json.loads((RIBBONS / "simulation.json").read_text(encoding="utf-8"))

    def test_home_tab_is_the_workflow_in_order(self):
        home = next(t for t in self.spec["tabs"] if t.get("name") == "Home")
        self.assertEqual([g.get("step") for g in home["groups"]], list(fem_guide.STEPS))
        self.assertEqual([g["name"].split()[0] for g in home["groups"]], ["1", "2", "3", "4", "5", "6"])

    def test_offered_as_the_simulation_application(self):
        apps = [a for g in json.loads((RIBBONS / "apps.json").read_text(encoding="utf-8"))["groups"] for a in g["apps"]]
        app = next(a for a in apps if a["id"] == "simulation")
        self.assertEqual((app["ribbon"], app.get("guide"), app["workbench"]),
                         ("simulation.json", "fem", "FemWorkbench"))

    def test_essential_commands_are_on_the_home_tab(self):
        home = next(t for t in self.spec["tabs"] if t.get("name") == "Home")
        cmds = [i["cmd"] for g in home["groups"] for i in g["items"]]
        for e in self.spec["essential"]:
            with self.subTest(essential=e):
                self.assertIn(e, cmds)


if __name__ == "__main__":
    unittest.main()
