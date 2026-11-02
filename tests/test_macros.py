# SPDX-License-Identifier: LGPL-2.1-or-later
"""The user's own macro commands on the Tools ribbon: discovery and the ribbon spec (no FreeCAD needed)."""

import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, os.path.join(str(ROOT), "NXStyle"))

from nxstyle import macros  # noqa: E402

RIBBONS = ROOT / "NXStyle" / "nxstyle" / "resources" / "ribbons"


def common():
    return json.loads((RIBBONS / "common.json").read_text(encoding="utf-8"))


def tools_tab():
    return next(t for t in common()["tabs"] if t["name"] == "Tools")


def macros_group():
    return next(g for g in tools_tab()["groups"] if g["name"] == "Macros")


class DiscoveryTests(unittest.TestCase):
    """Which FreeCAD commands are the user's own macro commands (FreeCAD names them Std_Macro_<n>)."""

    def test_only_the_users_macro_commands_are_found(self):
        known = {"Std_Macro_0", "Std_Macro_1", "Std_DlgMacroExecute", "Std_DlgMacroRecord", "Part_Box"}
        self.assertEqual(macros.user_commands(known), ["Std_Macro_0", "Std_Macro_1"])

    def test_the_debugger_commands_are_not_user_macros(self):
        """FreeCAD's own macro commands (1.1.4's list, smoke info 'macro commands in this FreeCAD', and the
        recorder's Std_MacroStopRecord of other versions) have no underscore after 'Macro'."""
        known = {"Std_MacroStartDebug", "Std_MacroStepInto", "Std_MacroStepOver", "Std_MacroStopDebug",
                 "Std_MacroAttachDebugger", "Std_MacroStopRecord", "Std_RecentMacros"}
        self.assertEqual(macros.user_commands(known), [])

    def test_numbered_commands_keep_the_order_they_were_made_in(self):
        known = {"Std_Macro_10", "Std_Macro_2", "Std_Macro_0"}
        self.assertEqual(macros.user_commands(known), ["Std_Macro_0", "Std_Macro_2", "Std_Macro_10"])

    def test_no_macro_command_means_no_item(self):
        self.assertEqual(macros.items_for({"Std_DlgMacroExecute"}), [])

    def test_each_command_is_a_button_with_its_menu_text(self):
        items = macros.items_for({"Std_Macro_0", "Std_Macro_1"},
                                 {"Std_Macro_0": "Make &Gear", "Std_Macro_1": "Export STEP"}.get)
        self.assertEqual(items, [{"cmd": "Std_Macro_0", "label": "Make Gear", "size": "small"},
                                 {"cmd": "Std_Macro_1", "label": "Export STEP", "size": "small"}])

    def test_a_command_without_menu_text_falls_back_to_its_name(self):
        self.assertEqual(macros.label("Std_Macro_3", ""), "3")
        self.assertEqual(macros.label("Std_Macro_3", None), "3")
        self.assertEqual(macros.items_for({"Std_Macro_3"})[0]["label"], "3")


class RibbonSpecTests(unittest.TestCase):
    """The Macros group of the Tools tab."""

    def test_the_tools_tab_has_a_macros_group(self):
        self.assertIn("Macros", [g["name"] for g in tools_tab()["groups"]])

    def test_the_group_offers_macros_record_and_stop(self):
        cmds = [i["cmd"] for i in macros_group()["items"] if "cmd" in i]
        self.assertEqual(cmds[:3], ["Std_DlgMacroExecute", "Std_DlgMacroRecord", "Std_MacroStopRecord"])

    def test_stop_waits_for_a_freecad_that_has_it(self):
        """FreeCAD 1.1.4 lists no Std_MacroStopRecord (smoke run, info 'macro commands in this FreeCAD')."""
        stop = next(i for i in macros_group()["items"] if i.get("cmd") == "Std_MacroStopRecord")
        self.assertTrue(stop.get("optional"))

    def test_the_group_marks_where_the_users_macros_go(self):
        self.assertEqual(sum(1 for i in macros_group()["items"] if i.get("macros")), 1)

    def test_every_button_has_a_label(self):
        for it in macros_group()["items"]:
            if "cmd" in it:
                with self.subTest(cmd=it["cmd"]):
                    self.assertTrue(it.get("label"))

    def test_every_application_ribbon_gets_the_tools_tab(self):
        apps = json.loads((RIBBONS / "apps.json").read_text(encoding="utf-8"))
        files = {a["ribbon"] for g in apps["groups"] for a in g["apps"] if a.get("ribbon")}
        self.assertTrue(files)
        for name in sorted(files):
            spec = json.loads((RIBBONS / name).read_text(encoding="utf-8"))
            with self.subTest(ribbon=name):
                self.assertIn("common:Tools", [t.get("include") for t in spec["tabs"]])


if __name__ == "__main__":
    unittest.main()
