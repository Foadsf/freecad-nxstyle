# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD-Nxt as the Part Navigator (nxstyle/nxt.py, nxt_navigator.py): the Dependencies panel's links, NX's
names for Nxt's words, NXStyle's menu file, and the parts of the pinned Nxt that NXStyle relies on (no FreeCAD
needed)."""

import importlib.util
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "NXStyle"))
from nxstyle import nxt_core  # noqa: E402

RES = ROOT / "NXStyle" / "nxstyle" / "resources" / "nxt"
NXT = ROOT / "vendor" / "FreeCAD-Nxt" / "freecad" / "nxt"


def _kind_of(props):
    return "attachment" if props == ["AttachmentSupport"] else "geometry" if props else "link"


def _node(refs=(), consumers=()):
    return SimpleNamespace(refs=list(refs), consumers=list(consumers))


class Dependencies(unittest.TestCase):
    # Sketch -> Pad (Profile), Pad -> Sketch001 (attached to a face), Sketch001 -> Pocket
    SNAP = SimpleNamespace(nodes={
        "Sketch": _node(consumers=[("Pad", "Pad", ["Profile"])]),
        "Pad": _node(refs=[("Sketch", "Sketch", 0, "")], consumers=[("Sketch001", "Sketch001", ["AttachmentSupport"]),
                                                                    ("Pocket", "Pocket", ["BaseFeature"])]),
        "Sketch001": _node(refs=[("Pad", "Pad", 0, "Face6")], consumers=[("Pocket", "Pocket", ["Profile"])]),
        "Pocket": _node(refs=[("Pad", "Pad", 0, ""), ("Sketch001", "Sketch001", 0, "")]),
    })

    def test_parents_take_the_kind_of_the_link_the_subject_reads(self):
        parents, children = nxt_core.dependencies(self.SNAP, "Sketch001", _kind_of)
        self.assertEqual(parents, [("Pad", "Pad", "attachment")])
        self.assertEqual(children, [("Pocket", "Pocket", "geometry")])

    def test_a_nested_sketch_is_still_a_parent(self):
        # Nxt's arrows leave out a sketch shown under its Pad; NX's Dependencies lists it
        parents, children = nxt_core.dependencies(self.SNAP, "Pad", _kind_of)
        self.assertEqual(parents, [("Sketch", "Sketch", "geometry")])
        self.assertEqual([c[0] for c in children], ["Sketch001", "Pocket"])
        self.assertEqual(children[0][2], "attachment")

    def test_unknown_object_has_none(self):
        self.assertEqual(nxt_core.dependencies(self.SNAP, "Nope", _kind_of), ([], []))

    def test_kinds_have_nx_words(self):
        self.assertEqual(set(nxt_core.KINDS), {"geometry", "attachment", "expression", "link"})


class NxNames(unittest.TestCase):
    """nx_names.ts gives Nxt's words NX's names; nx_names.qm is built from it (tools/build_nxt_names.py)."""

    def messages(self):
        out = []
        for ctx in ET.parse(RES / "nx_names.ts").getroot().iter("context"):
            for msg in ctx.iter("message"):
                out.append((ctx.findtext("name"), msg.findtext("source"), msg.findtext("translation")))
        return out

    def test_the_names(self):
        got = {(c, s): t for c, s, t in self.messages()}
        self.assertEqual(got[("Nxt", "Model (Nxt)")], "Part Navigator")
        self.assertEqual(got[("NxtMenu", "Roll back to here")], "Make Current Feature")
        self.assertEqual(got[("NxtMenu", "Roll forward to here")], "Make Current Feature")
        self.assertEqual(got[("Nxt", "Tip of %s moved to %s")].count("%s"), 2)

    def test_qm_is_built_from_the_ts(self):
        qm = (RES / "nx_names.qm").read_bytes()
        self.assertTrue(qm.startswith(bytes.fromhex("3CB86418CAEF9C95CD211CBF60A1BDDD")))     # Qt's .qm magic
        for _ctx, _src, translation in self.messages():
            self.assertIn(translation.encode("utf-16-be"), qm, f"rebuild nx_names.qm: {translation!r} missing")

    def test_the_sources_are_nxts_own_words(self):
        if not NXT.is_dir():
            self.skipTest("vendor/FreeCAD-Nxt not checked out (git submodule update --init)")
        text = "\n".join(p.read_text(encoding="utf-8") for p in NXT.rglob("*.py"))
        for _ctx, src, _t in self.messages():
            self.assertIn(f'"{src}"', text, f"Nxt no longer says {src!r}: update nx_names.ts")


@unittest.skipUnless(NXT.is_dir(), "vendor/FreeCAD-Nxt not checked out (git submodule update --init)")
class PinnedNxt(unittest.TestCase):
    """What NXStyle uses of the pinned Nxt beyond its preferences: checked against its source, so a submodule
    update that moves them fails here rather than in FreeCAD."""

    def src(self, *parts):
        return (NXT.joinpath(*parts)).read_text(encoding="utf-8")

    def test_menu_file_loads_with_nxts_own_reader(self):
        spec = importlib.util.spec_from_file_location("nxt_definitions", NXT / "menus" / "definitions.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod                # dataclasses look their module up while the class is built
        try:
            spec.loader.exec_module(mod)
            merged = mod.load(NXT / "resources" / "menus" / "default.toml")
            ours = mod.load(RES / "nx_menu.toml")
        finally:
            sys.modules.pop(spec.name, None)
        self.assertEqual(ours.errors, [])
        merged.extend(ours)
        self.assertEqual(merged.errors, [])
        self.assertIn("nxt:recompute_object", self.src("resources", "menus", "default.toml"))   # our `before`

    def test_what_nxstyle_calls(self):
        panel, bridge = self.src("tree", "panel.py"), self.src("tree", "bridge.py")
        self.assertIn('OBJECT_NAME = "NxtModelPanel"', panel)
        for name in ("def instance(", "def bridge("):
            self.assertIn(name, panel)
        for name in ("def _arrow_subject(", "self._snapshot =", "def select(", "def revealObject(",
                     "def openPropertyInspector(", "problemCountChanged", "linkArrowsChanged", "pickOriginsChanged"):
            self.assertIn(name, bridge)
        self.assertIn("self._space = SpaceInView(self)", self.src("app", "services.py"))
        self.assertIn('NAME = "NxtTesting"', self.src("app", "test_toolbar.py"))
        self.assertIn("def _toolbar(", self.src("app", "test_toolbar.py"))
        self.assertIn("def register(", self.src("menus", "__init__.py"))
        self.assertIn("def apply(keys", self.src("ui", "prefs.py"))
        for name in ("def describe(", "def apply(", "def visible_count("):
            self.assertIn(name, self.src("inspector", "properties.py"))
        self.assertIn("def kind_of(", self.src("tree", "links.py"))
        # Home/End: Nxt claims them in the tree's ShortcutOverride, which NXStyle keeps from it
        self.assertIn("Keys.onShortcutOverride", self.src("resources", "qml", "NxtTree.qml"))


if __name__ == "__main__":
    unittest.main()
