# SPDX-License-Identifier: LGPL-2.1-or-later
"""Carbon (manufacturing) client: settings and credentials, the HTTP contract, publishing a release
package (part, revision, model, documents, BOM, inspection plan) and reading its status back. Runs against
tests/carbon_fake.py, which checks every request against Carbon's published OpenAPI schemas (no FreeCAD,
no Carbon server needed)."""

import contextlib
import io
import json
import os
import stat
import sys
import tempfile
import unittest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "NXStyle"))
sys.path.insert(0, HERE)
from nxstyle import carbon, package, pmi  # noqa: E402
import carbon_fake  # noqa: E402

STEP = ("ISO-10303-21;HEADER;FILE_DESCRIPTION((''),'2;1');FILE_NAME('','2026-01-01T00:00',(''),(''),'','','');"
        "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));ENDSEC;DATA;{}ENDSEC;END-ISO-10303-21;\n")


def step_assembly():
    """ASM: 2 x SUB, SUB: 3 x BOLT (iso10303.bom reads it)."""
    rows = ["#1=PRODUCT('ASM','Assembly','',());", "#2=PRODUCT('BOLT','Bolt','',());",
            "#3=PRODUCT('SUB','Sub','',());", "#11=PRODUCT_DEFINITION_FORMATION('','',#1);",
            "#12=PRODUCT_DEFINITION_FORMATION('','',#2);", "#13=PRODUCT_DEFINITION_FORMATION('','',#3);",
            "#21=PRODUCT_DEFINITION('design','',#11,#9);", "#22=PRODUCT_DEFINITION('design','',#12,#9);",
            "#23=PRODUCT_DEFINITION('design','',#13,#9);", "#9=PRODUCT_DEFINITION_CONTEXT('','','');",
            "#31=NEXT_ASSEMBLY_USAGE_OCCURRENCE('1','','',#21,#23,$);",
            "#32=NEXT_ASSEMBLY_USAGE_OCCURRENCE('2','','',#21,#23,$);"]
    rows += [f"#{40 + i}=NEXT_ASSEMBLY_USAGE_OCCURRENCE('{4 + i}','','',#23,#22,$);" for i in range(3)]
    return STEP.format("".join(rows))


def make_package(root, pn="PLT-100", rev="B", state="Released", step=None, plan=True):
    folder = os.path.join(root, f"{pn}_{rev}")
    os.makedirs(os.path.join(folder, "model"), exist_ok=True)
    with open(os.path.join(folder, "model", f"{pn}_{rev}.step"), "w", encoding="latin-1") as f:
        f.write(step or STEP.format("#1=PRODUCT('PLT-100','Plate','',());"))
    with open(os.path.join(folder, "model", f"{pn}_{rev}.FCStd"), "wb") as f:
        f.write(b"PK native")
    if plan:
        os.makedirs(os.path.join(folder, "pmi"), exist_ok=True)
        anns = [{"id": "Bore", "kind": "dimension", "dim_type": "diameter", "nominal": 10.0, "fit": "H7",
                 "feature": "Face9", "feature_type": "hole", "number": 1},
                {"id": "PosBore", "kind": "fcf", "characteristic": "position", "tolerance": 0.05, "diameter": True,
                 "datums": [["A", ""]], "feature": "Face9", "feature_type": "hole", "number": 2},
                {"id": "DatumA", "kind": "datum", "letter": "A", "feature": "Face6", "feature_type": "plane"}]
        rows = pmi.inspection_plan(anns)
        package.write_csv(os.path.join(folder, "pmi", "inspection_plan.csv"), package.dict_rows(
            rows, ["number", "requirement", "kind", "segment", "nominal", "lower", "upper", "tolerance_from",
                   "upper_at_departure", "uncertainty", "tur", "accept_lower", "accept_upper", "datums", "feature",
                   "method", "note"]))
    package.write_manifest(folder, {"part_number": pn, "revision": rev, "state": state, "description": "Guide plate"})
    return folder


class Settings(unittest.TestCase):
    def test_url(self):
        self.assertEqual(carbon.normalise_url("app.carbon.ms"), "https://app.carbon.ms")
        self.assertEqual(carbon.normalise_url("https://erp.example.com/api/v1/"), "https://erp.example.com")
        self.assertEqual(carbon.normalise_url("http://localhost:3000"), "http://localhost:3000")
        with self.assertRaises(carbon.CarbonError):        # a bearer key never goes over plain http elsewhere
            carbon.normalise_url("http://erp.example.com")
        with self.assertRaises(carbon.CarbonError):
            carbon.normalise_url("")

    def test_key(self):
        self.assertTrue(carbon.check_key(" crbn_abcdefgh12 ").startswith("crbn_"))
        for bad in ("", "abc", "crbn_", "sk_live_0123456789", "crbn_abc def ghij"):
            with self.subTest(key=bad), self.assertRaises(carbon.CarbonError):
                carbon.check_key(bad)
        self.assertEqual(carbon.masked("crbn_abcdefgh1234"), "crbn_…1234")
        self.assertNotIn("abcdefgh", carbon.masked("crbn_abcdefgh1234"))

    def test_key_sources(self):
        with tempfile.TemporaryDirectory() as d:
            path = carbon.save_api_key(os.path.join(d, "config", "carbon.key"), carbon_fake.KEY)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)
            self.assertEqual(carbon.api_key(path, env={}), (carbon_fake.KEY, path))
            self.assertEqual(carbon.api_key(path, env={"CARBON_API_KEY": "crbn_fromenv123"}),
                             ("crbn_fromenv123", "CARBON_API_KEY"))
            self.assertEqual(carbon.api_key(os.path.join(d, "none"), env={}), ("", ""))
            with self.assertRaises(carbon.CarbonError):
                carbon.save_api_key(path, "not a key")


class Contract(unittest.TestCase):
    """The operations exist in Carbon's published API, and the client speaks its HTTP contract."""

    def test_every_operation_is_in_the_published_spec(self):
        spec = carbon_fake.SPEC
        self.assertEqual(spec["x-nxstyle"]["operations"], len(carbon.OPERATIONS))
        for op in carbon.OPERATIONS:
            with self.subTest(op=op):
                self.assertIn("/" + op.replace(".", "/"), spec["paths"])

    def test_request_shape_and_errors(self):
        seen = []

        def transport(method, url, headers, body, timeout):
            seen.append((method, url, headers, json.loads(body)))
            if len(seen) == 1:
                return 429, {"Retry-After": "1"}, b""
            if len(seen) == 2:
                return 200, {}, b'{"id": "itm1"}'
            if len(seen) == 3:
                return 422, {}, json.dumps({"code": "X", "status": 422, "message": "Revision is locked",
                                            "data": {"category": "rule"}}).encode()
            return 401, {}, b"Unauthorized"

        slept = []
        c = carbon.Client("https://erp.example.com", carbon_fake.KEY, transport=transport, sleep=slept.append)
        self.assertEqual(c.call("items.createPart", {"id": "P"}), {"id": "itm1"})
        self.assertEqual(slept, [1.0])
        method, url, headers, body = seen[1]
        self.assertEqual((method, url, body), ("POST", "https://erp.example.com/api/v1/items/createPart", {"id": "P"}))
        self.assertEqual(headers["Authorization"], f"Bearer {carbon_fake.KEY}")
        with self.assertRaises(carbon.CarbonError) as e:
            c.call("items.updateRevision", {"id": "x", "revision": "B"})
        self.assertEqual((e.exception.status, e.exception.category, e.exception.message), (422, "rule",
                                                                                         "Revision is locked"))
        with self.assertRaises(carbon.CarbonError) as e:
            c.call("settings.getCompanies")
        self.assertIn("API key is not valid", str(e.exception))
        self.assertNotIn(carbon_fake.KEY, str(e.exception))

    def test_unreachable_server(self):
        c = carbon.Client("http://127.0.0.1:9", carbon_fake.KEY, timeout=2, retries=0)
        with self.assertRaises(carbon.CarbonError) as e:
            carbon.check(c)
        self.assertIn("cannot reach", str(e.exception))

    def test_the_schema_gate_catches_a_bad_request(self):
        """Negative control: a request Carbon's schema rejects is refused by the stand-in and recorded."""
        with carbon_fake.Server() as s:
            with self.assertRaises(carbon.CarbonError) as e:
                carbon.Client(s.url, carbon_fake.KEY).call("items.createPart", {"id": "P", "name": "Plate"})
            self.assertEqual((e.exception.status, e.exception.category), (400, "validation"))
            self.assertIn("$.revision: required", e.exception.message)
            self.assertEqual(len(s.schema_problems), 1)
            self.assertEqual(s.company.items, {})

    def test_wrong_key_against_the_server(self):
        with carbon_fake.Server() as s:
            c = carbon.Client(s.url, "crbn_wrongwrongwrong")
            with self.assertRaises(carbon.CarbonError) as e:
                carbon.check(c)
            self.assertEqual(e.exception.status, 401)
            self.assertEqual(carbon.check(carbon.Client(s.url, carbon_fake.KEY)), ["Test Precision BV"])


class Mapping(unittest.TestCase):
    def test_inspection_plan_becomes_characteristics(self):
        with tempfile.TemporaryDirectory() as d:
            feats = carbon.characteristics(carbon.plan_rows(make_package(d)))
        bore = next(f for f in feats if f["label"] == "1")
        self.assertEqual((bore["nominalValue"], bore["tolerancePlus"], bore["toleranceMinus"], bore["unit"]),
                         ("10", "0.015", "0", "mm"))            # Ø10 H7: 0/+15 µm (ISO 286-2)
        pos = next(f for f in feats if f["label"] == "2")
        self.assertEqual((pos["nominalValue"], pos["tolerancePlus"], pos["toleranceMinus"]), ("0", "0.05", "0"))
        self.assertIn("datums A", pos["description"])
        self.assertTrue(all(f["type"] == "Measurement" for f in feats))

    def test_bom_lines_merge(self):
        kids = carbon.merge_children([{"id": "B", "quantity": 1}, {"id": "C", "quantity": 2},
                                      {"id": "B", "quantity": 3}])
        self.assertEqual([(k["id"], k["quantity"]) for k in kids], [("B", 4), ("C", 2)])

    def test_part_defaults(self):
        a = carbon.part_args({"part_number": "P-1", "revision": "A", "description": "Guide plate"})
        self.assertEqual((a["id"], a["revision"], a["name"], a["replenishmentSystem"], a["unitOfMeasureCode"]),
                         ("P-1", "A", "Guide plate", "Make", "EA"))


class Publish(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.srv = carbon_fake.Server().__enter__()
        self.c = carbon.Client(self.srv.url, carbon_fake.KEY)
        self.co = self.srv.company

    def tearDown(self):
        self.srv.__exit__(None, None, None)
        self.tmp.cleanup()
        self.assertEqual(self.srv.schema_problems, [])     # every request matched Carbon's published schemas

    def test_part_with_model_documents_and_inspection_plan(self):
        folder = make_package(self.tmp.name)
        r = carbon.publish(self.c, folder)
        item = self.co.items[r["item"]["id"]]
        self.assertEqual((item["readableId"], item["revision"], item["name"], item["active"]),
                         ("PLT-100", "B", "Guide plate", True))
        self.assertEqual(self.co.models[item["modelUploadId"]]["name"], "PLT-100_B.step")
        names = {p.rsplit("/", 1)[1] for p in self.co.storage if p.startswith(f"co1/parts/{item['id']}/")}
        self.assertEqual(names, {"model_PLT-100_B.FCStd", "pmi_inspection_plan.csv", "PLT-100_B_manifest.json"})
        feats = sorted(f["label"] for f in self.co.features.values())
        self.assertEqual(feats, ["1", "2"])
        doc = next(iter(self.co.docs.values()))
        self.assertEqual((doc["partId"], doc["drawingNumber"]), (item["id"], "PLT-100"))
        # what was uploaded is what the manifest vouches for
        m = json.load(open(os.path.join(folder, "manifest.json"), encoding="utf-8"))
        step = next(e for e in m["files"] if e["path"].endswith(".step"))
        up = next(b for p, b in self.co.uploads if p.endswith(".step"))
        self.assertEqual(len(up), step["bytes"])

    def test_publishing_again_writes_nothing(self):
        folder = make_package(self.tmp.name)
        carbon.publish(self.c, folder)
        before = len(self.srv.writes())
        r = carbon.publish(self.c, folder)
        self.assertEqual(r["actions"], [])
        self.assertEqual(len(self.srv.writes()), before)
        self.assertIn("Nothing to write", carbon.publish_text(r))

    def test_review_writes_nothing_and_lists_the_same_writes(self):
        folder = make_package(self.tmp.name, step=step_assembly())
        review = carbon.publish(self.c, folder, dry_run=True)
        self.assertEqual(self.srv.writes(), [])
        self.assertEqual(self.co.items, {})
        done = carbon.publish(self.c, folder)
        self.assertEqual([a["what"].split(" (new")[0] for a in review["actions"]],
                         [a["what"].split(" (new")[0] for a in done["actions"]])
        self.assertIn("nothing written yet", carbon.publish_text(review))

    def test_only_released_parts(self):
        folder = make_package(self.tmp.name, state="In work")
        with self.assertRaises(carbon.CarbonError) as e:
            carbon.publish(self.c, folder)
        self.assertIn("only a released part", str(e.exception))
        self.assertEqual(self.co.sent, [])
        carbon.publish(self.c, folder, allow_unreleased=True)
        self.assertEqual(len(self.co.items), 1)

    def test_tampered_package_is_refused(self):
        folder = make_package(self.tmp.name)
        with open(os.path.join(folder, "model", "PLT-100_B.step"), "a") as f:
            f.write("/* changed */")
        with self.assertRaises(carbon.CarbonError) as e:
            carbon.publish(self.c, folder)
        self.assertIn("does not verify", str(e.exception))
        self.assertEqual(self.co.sent, [])

    def lines(self, item_id):
        mm = max((m for m in self.co.methods.values() if m["itemId"] == item_id), key=lambda m: m["version"])
        return mm, {self.co.items[ln["itemId"]]["readableId"]: ln["quantity"] for ln in self.co.lines.values()
                    if ln["makeMethodId"] == mm["id"]}

    def test_assembly_bom_from_the_step(self):
        folder = make_package(self.tmp.name, pn="ASM", rev="A", step=step_assembly(), plan=False)
        carbon.publish(self.c, folder)
        by_pn = {i["readableId"]: i for i in self.co.items.values()}
        self.assertEqual(set(by_pn), {"ASM", "SUB", "BOLT"})
        self.assertEqual(self.lines(by_pn["ASM"]["id"])[1], {"SUB": 2})
        self.assertEqual(self.lines(by_pn["SUB"]["id"])[1], {"BOLT": 3})
        self.assertEqual(by_pn["SUB"]["replenishmentSystem"], "Make")    # it has components

    def test_bom_change_on_an_active_method_goes_to_a_new_draft(self):
        folder = make_package(self.tmp.name, pn="ASM", rev="A", step=step_assembly(), plan=False)
        tree = {"id": "ASM", "children": [{"id": "BOLT", "revision": "0", "quantity": 4},
                                          {"id": "NUT", "revision": "0", "quantity": 4}]}
        carbon.publish(self.c, folder, bom=tree)
        asm = next(i for i in self.co.items.values() if i["readableId"] == "ASM")
        mm, lines = self.lines(asm["id"])
        self.assertEqual(lines, {"BOLT": 4, "NUT": 4})
        mm["status"] = "Active"                     # manufacturing released the method
        washer = self.co.items[self.co.new_item({"readableId": "WASHER", "revision": "0", "name": "Washer",
                                                 "replenishmentSystem": "Buy", "defaultMethodType": "Pull from Inventory",
                                                 "itemTrackingType": "Inventory", "unitOfMeasureCode": "EA",
                                                 "active": True})]
        self.co.lines["hand1"] = {"id": "hand1", "makeMethodId": mm["id"], "order": 9, "itemType": "Part",
                                  "itemId": washer["id"], "methodType": "Pull from Inventory",
                                  "sourcingType": "Specified", "quantity": 8, "unitOfMeasureCode": "EA",
                                  "kit": False}
        tree["children"][0]["quantity"] = 6
        r = carbon.publish(self.c, folder, bom=tree)
        self.assertEqual(self.lines(asm["id"])[1], {"BOLT": 6, "NUT": 4, "WASHER": 8})
        active = self.co.methods[mm["id"]]
        self.assertEqual(active["status"], "Active")
        self.assertEqual({self.co.items[ln["itemId"]]["readableId"]: ln["quantity"] for ln in self.co.lines.values()
                          if ln["makeMethodId"] == active["id"]}, {"BOLT": 4, "NUT": 4, "WASHER": 8})
        self.assertTrue(any("Draft version 2" in a["what"] for a in r["actions"]))
        self.assertTrue(any("WASHER" in n or "Washer" in n for n in r["notes"]))     # hand-added line kept

    def test_new_revision_is_inactive_until_manufacturing_releases_it(self):
        carbon.publish(self.c, make_package(self.tmp.name, rev="A"))
        a = next(iter(self.co.items.values()))
        mm = next(m for m in self.co.methods.values() if m["itemId"] == a["id"])
        self.co.lines["l1"] = {"id": "l1", "makeMethodId": mm["id"], "order": 1, "itemType": "Part", "itemId": a["id"],
                               "methodType": "Make to Order", "sourcingType": "Specified", "quantity": 1,
                               "unitOfMeasureCode": "EA", "kit": False}
        r = carbon.publish(self.c, make_package(self.tmp.name, rev="B"))
        revs = {i["revision"]: i for i in self.co.items.values() if i["readableId"] == "PLT-100"}
        self.assertEqual(set(revs), {"A", "B"})
        self.assertTrue(revs["A"]["active"])
        self.assertFalse(revs["B"]["active"])
        self.assertIn("items.createRevision", self.srv.writes())
        self.assertNotIn("items.createPart", self.srv.writes()[len(self.srv.writes()) - len(r["actions"]):])
        self.assertTrue(any("inactive until manufacturing releases it" in x["what"] for x in r["actions"]))


    def test_a_component_without_a_revision_uses_the_one_carbon_has(self):
        bolt = self.co.new_item({"readableId": "BOLT", "revision": "C", "name": "Bolt", "replenishmentSystem": "Buy",
                                 "defaultMethodType": "Pull from Inventory", "itemTrackingType": "Inventory",
                                 "unitOfMeasureCode": "EA", "active": True})
        folder = make_package(self.tmp.name, pn="ASM", rev="A", step=step_assembly(), plan=False)
        r = carbon.publish(self.c, folder, bom={"id": "ASM", "children": [{"id": "BOLT", "quantity": 2},
                                                                          {"id": "NEW", "quantity": 1}]})
        self.assertNotIn("items.createRevision", self.srv.writes())
        asm = next(i for i in self.co.items.values() if i["readableId"] == "ASM")
        self.assertEqual(self.lines(asm["id"])[1], {"BOLT": 2, "NEW": 1})
        self.assertIn(bolt, [ln["itemId"] for ln in self.co.lines.values()])
        new = next(i for i in self.co.items.values() if i["readableId"] == "NEW")
        self.assertEqual(new["revision"], "0")
        self.assertTrue(any("2 x BOLT rev C" in a["what"] for a in r["actions"]))


class Status(unittest.TestCase):
    def test_status_and_cli(self):
        with carbon_fake.Server() as s, tempfile.TemporaryDirectory() as d:
            c = carbon.Client(s.url, carbon_fake.KEY)
            self.assertFalse(carbon.status(c, "PLT-100")["found"])
            carbon.publish(c, make_package(d))
            item = next(iter(s.company.items.values()))
            s.company.quantities[(item["id"], "loc1")] = {"onHand": 12, "onHold": 1, "rejected": 2}
            s.company.issues = [{"id": "nc1", "nonConformanceId": "NCR-7", "name": "Bore oversize", "status": "In Progress",
                                 "items": [item["id"]]},
                                {"id": "nc2", "nonConformanceId": "NCR-8", "name": "Closed one", "status": "Closed",
                                 "items": [item["id"]]},
                                {"id": "nc3", "nonConformanceId": "NCR-9", "name": "Other part", "status": "Registered",
                                 "items": ["itm9999"]}]
            st = carbon.status(c, "PLT-100")
            self.assertEqual(st["stock"]["quantityOnHand"], 12)
            self.assertEqual(st["stock"]["location"], "Main Shop")
            self.assertEqual([i["id"] for i in st["open_issues"]], ["NCR-7"])
            self.assertEqual(st["inspection_plans"][0]["characteristics"], 2)
            text = carbon.status_text(st)
            self.assertIn("12 EA on hand", text)
            self.assertIn("NCR-7 Bore oversize", text)
            env = {"CARBON_API_KEY": carbon_fake.KEY}
            out = io.StringIO()
            with unittest.mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
                code = carbon.main(["--url", s.url, "status", "PLT-100", "--revision", "B"])
            self.assertEqual(code, 0)
            self.assertIn("rev B", out.getvalue())
            self.assertNotIn(carbon_fake.KEY, out.getvalue())
            out = io.StringIO()
            with unittest.mock.patch.dict(os.environ, env), contextlib.redirect_stdout(out):
                self.assertEqual(carbon.main(["--url", s.url, "check"]), 0)
            self.assertIn("crbn_…cdef works", out.getvalue())
            self.assertEqual(s.schema_problems, [])


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
