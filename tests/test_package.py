# SPDX-License-Identifier: LGPL-2.1-or-later
"""Release package manifest, verification and archive (no FreeCAD needed)."""

import hashlib
import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "NXStyle"))
from nxstyle import package  # noqa: E402


class Package(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "PLT-100_B")
        os.makedirs(os.path.join(self.dir, "model"))
        os.makedirs(os.path.join(self.dir, "pmi"))
        with open(os.path.join(self.dir, "model", "PLT-100_B.step"), "wb") as f:
            f.write(b"ISO-10303-21;\nEND-ISO-10303-21;\n")
        package.write_csv(os.path.join(self.dir, "pmi", "inspection_plan.csv"), [["number", "requirement"], [1, "Ø6"]])
        self.meta = {"part_number": "PLT-100", "revision": "B", "state": "Released", "description": "Plate"}

    def tearDown(self):
        self.tmp.cleanup()

    def test_manifest_lists_every_file_with_its_hash(self):
        m = package.write_manifest(self.dir, self.meta)
        paths = [e["path"] for e in m["files"]]
        self.assertEqual(paths, ["model/PLT-100_B.step", "pmi/inspection_plan.csv"])
        step = m["files"][0]
        want = hashlib.sha256(b"ISO-10303-21;\nEND-ISO-10303-21;\n").hexdigest()
        self.assertEqual(step["sha256"], want)
        self.assertEqual(step["role"], "model (STEP), model")
        on_disk = json.load(open(os.path.join(self.dir, package.MANIFEST), encoding="utf-8"))
        self.assertEqual(on_disk["package"]["revision"], "B")
        with open(os.path.join(self.dir, package.README), encoding="utf-8") as f:
            self.assertIn("PLT-100 rev B", f.read())

    def test_verify_finds_changed_missing_and_extra_files(self):
        package.write_manifest(self.dir, self.meta)
        self.assertEqual(package.verify(self.dir), [])
        with open(os.path.join(self.dir, "pmi", "inspection_plan.csv"), "a") as f:
            f.write("2,tampered\n")
        os.remove(os.path.join(self.dir, "model", "PLT-100_B.step"))
        with open(os.path.join(self.dir, "extra.txt"), "w") as f:
            f.write("x")
        problems = package.verify(self.dir)
        self.assertIn("changed: pmi/inspection_plan.csv", problems)
        self.assertIn("missing: model/PLT-100_B.step", problems)
        self.assertIn("not in the manifest: extra.txt", problems)

    def test_zip_is_reproducible(self):
        package.write_manifest(self.dir, self.meta)
        a = package.zip_folder(self.dir, os.path.join(self.tmp.name, "a.zip"))
        b = package.zip_folder(self.dir, os.path.join(self.tmp.name, "b.zip"))
        with open(a, "rb") as fa, open(b, "rb") as fb:
            self.assertEqual(fa.read(), fb.read())
        with zipfile.ZipFile(a) as z:
            names = z.namelist()
        self.assertIn("PLT-100_B/manifest.json", names)
        self.assertIn("PLT-100_B/model/PLT-100_B.step", names)

    def test_cli(self):
        package.write_manifest(self.dir, self.meta)
        self.assertEqual(package.main(["verify", self.dir]), 0)
        os.remove(os.path.join(self.dir, "pmi", "inspection_plan.csv"))
        self.assertEqual(package.main(["verify", self.dir]), 1)

    def test_safe_name(self):
        self.assertEqual(package.safe_name("PLT 100/B"), "PLT_100_B")


if __name__ == "__main__":
    unittest.main()
