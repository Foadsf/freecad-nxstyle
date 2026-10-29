# SPDX-License-Identifier: LGPL-2.1-or-later
"""Tutorial mixins: no two define the same method, else the replay's MRO runs one tutorial's step in another's
place (AN ran Carbon's an_new/an_check once BC kept AN's prefix); parsed, no FreeCAD needed."""

import ast
import collections
import glob
import os
import unittest

HERE = os.path.join(os.path.dirname(__file__), "..", "NXStyle", "nxstyle")


def methods_by_name():
    seen = collections.defaultdict(list)
    for path in sorted(glob.glob(os.path.join(HERE, "tutorial*.py"))):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), path)
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and (node.name.endswith("Tutorials") or node.name == "Replay"):
                for m in node.body:
                    if isinstance(m, ast.FunctionDef):
                        seen[m.name].append(f"{os.path.basename(path)}:{node.name}")
    return seen


class Mixins(unittest.TestCase):
    def test_the_mixins_are_found(self):
        self.assertEqual({"AN_STEPS", "BC_STEPS", "an_new", "bc_new"} - set(methods_by_name()), set())

    def test_no_method_is_defined_twice(self):
        twice = {k: v for k, v in methods_by_name().items() if len(v) > 1}
        self.assertEqual(twice, {})


if __name__ == "__main__":
    unittest.main()
