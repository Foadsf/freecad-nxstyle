# SPDX-License-Identifier: LGPL-2.1-or-later
"""Manufacturing tutorial: the released part handed to the manufacturing system.

  BC  tutorial V's guide bush, released as BUSH-100 rev B, sent to Carbon (ERP, MES, quality) with
      PLM › Publish to Manufacturing: the connection, the review, the publish (item, revision, CAD model,
      documents, the inspection plan's characteristics), a second publish that writes nothing, and the
      shop's stock and a non-conformance read back with Manufacturing Status (runs T and V first)

The replay's Carbon is the stand-in server of the unit tests (tests/carbon_fake.py): real HTTP on this
computer, every request checked against Carbon's published API schemas. A user connects to Carbon Cloud or
their own server instead; the dialogs are the same.
"""

import os
import sys

import FreeCAD as App
import FreeCADGui as Gui

from .qt import Qt, QtWidgets

SAME, DIFFERS, MISSING, FAIL = "same", "differs", "missing", "FAILED"


def _out():
    return os.environ.get("NXSTYLE_TUTORIAL_OUT", "")


class ManufacturingTutorials:
    """Mixin for tutorial.Replay (uses the p_ and v_ helpers of PrecisionTutorials)."""

    def BC_STEPS(self):
        return [self.an_new, self.an_connect, self.an_review, self.an_publish, self.an_check, self.an_again,
                self.an_shop, self.an_status, self.an_done]

    def an_new(self):
        self.tutorial = "BC: Release to manufacturing: the guide bush into Carbon"
        from . import config
        tests = os.path.normpath(os.path.join(config.RESOURCES, "..", "..", "..", "tests"))
        self._an_srv = None
        if os.path.isfile(os.path.join(tests, "carbon_fake.py")):
            sys.path.insert(0, tests)
            import carbon_fake
            self._an_fake = carbon_fake
            self._an_srv = carbon_fake.Server().__enter__()
        doc = getattr(self, "_v_doc", None)
        if doc is not None:
            App.setActiveDocument(doc.Name)
            Gui.ActiveDocument = Gui.getDocument(doc.Name)
            try:
                Gui.activateView("Gui::View3DInventor", True)
            except Exception:
                pass
        rels = [(r.part_number, r.revision, r.state) for r in self.v_project().releases()] if doc else []
        ok = self._an_srv is not None and ("BUSH-100", "B", "Released") in rels
        self.step("The guide bush, released in tutorial V as BUSH-100 rev B (rev A obsolete); a Carbon to send it to",
                  "the replay's Carbon: the stand-in server of the unit tests, on this computer", DIFFERS if ok else FAIL,
                  f"releases {rels}; server {self._an_srv.url if self._an_srv else 'missing (tests/carbon_fake.py)'}. "
                  "A user connects to Carbon Cloud (app.carbon.ms) or their own Carbon instead")
        self.wait = 300

    def an_connect(self):
        from . import carbon, carbon_ui, config
        from .tutorial import qtest
        b, where = self.click_ribbon("Manufacturing Connection", tab="PLM")
        QtWidgets.QApplication.processEvents()
        dlg = carbon_ui.dialog
        result = ""
        if dlg is not None and dlg.isVisible() and self._an_srv is not None:
            for name, text in (("carbonUrl", self._an_srv.url), ("carbonKey", self._an_fake.KEY)):
                w = dlg.findChild(QtWidgets.QLineEdit, name)
                w.setFocus()
                w.selectAll()
                qtest().keyClicks(w, text)
            qtest().mouseClick(dlg.findChild(QtWidgets.QPushButton, "carbonTest"), Qt.LeftButton)
            QtWidgets.QApplication.processEvents()
            result = dlg.result.text()
            dlg.grab().save(os.path.join(_out(), "tutorial-BC-01-connection.png"))
            save = next((x for x in dlg.findChildren(QtWidgets.QPushButton) if x.text().replace("&", "") == "Save"),
                        None)
            if save is not None:
                qtest().mouseClick(save, Qt.LeftButton)
            QtWidgets.QApplication.processEvents()
        key, where_key = carbon.api_key(carbon_ui.key_file())
        saved = config.get().get("carbon", {}).get("url")
        mode = oct(os.stat(where_key).st_mode & 0o777) if where_key and os.path.isfile(where_key) else "?"
        ok = ("Test Precision BV" in result and self._an_srv is not None and saved == self._an_srv.url
              and key == self._an_fake.KEY and (os.name != "posix" or mode == "0o600"))
        self.step("Manufacturing Connection: server and API key, Test Connection, Save",
                  f"ribbon '{where} > Manufacturing Connection', server and key typed, 'Test Connection', 'Save'",
                  SAME if ok else FAIL,
                  f"{result!r}; the server goes into nxstyle.json, the key into {os.path.basename(where_key or '?')} "
                  f"(mode {mode}), never into nxstyle.json")
        self.wait = 300

    def an_review(self):
        from .tutorial import qtest
        b, where = self.click_ribbon("Publish to Manufacturing", tab="PLM")
        QtWidgets.QApplication.processEvents()
        combo = self.p_widget(QtWidgets.QComboBox, "release")
        choice = combo.currentText() if combo is not None else ""
        review = self.p_widget(QtWidgets.QPushButton, "carbonReview")
        if review is not None:
            qtest().mouseClick(review, Qt.LeftButton)
            QtWidgets.QApplication.processEvents()
        box = self.p_widget(QtWidgets.QPlainTextEdit, "carbonReviewText")
        text = box.toPlainText() if box is not None else ""
        self._an_review = text
        writes = self._an_srv.writes() if self._an_srv else ["no server"]
        ok = (choice.startswith("BUSH-100 rev B") and "Would write" in text and "part BUSH-100 rev B" in text
              and "inspection plan" in text and writes == [])
        self.step("Publish to Manufacturing: the newest Released revision, Review",
                  f"ribbon '{where} > Publish to Manufacturing', release '{choice}', 'Review'", SAME if ok else FAIL,
                  f"nothing written yet ({len(writes)} writes); the review lists "
                  + "; ".join(x.strip() for x in text.splitlines() if x.startswith("  "))[:600])
        dock = self.tasks_dock()
        if dock is not None:
            dock.grab().save(os.path.join(_out(), "tutorial-BC-02-review.png"))
        self.wait = 300

    def an_publish(self):
        from . import carbon_ui
        how = self.p_ok()
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        r = carbon_ui.last or {}
        ok = "published to Carbon" in text and not Gui.Control.activeDialog() and len(r.get("actions", [])) > 0
        self.step("OK: Carbon gets the release", f"{how} = OK", SAME if ok else FAIL,
                  f"{len(r.get('actions', []))} writes: "
                  + "; ".join(a["what"] for a in r.get("actions", []))[:700])
        self.p_shot_info("tutorial-BC-03-published.png")
        self.p_close_info()
        self.wait = 300

    def an_check(self):
        import csv
        co = self._an_srv.company
        items = [i for i in co.items.values() if i["readableId"] == "BUSH-100"]
        item = items[0] if len(items) == 1 else {}
        docs = sorted(p.rsplit("/", 1)[1] for p in co.storage if p.startswith(f"co1/parts/{item.get('id')}/"))
        model = co.models.get(item.get("modelUploadId"), {}).get("name")
        feats = {f["label"]: f for f in co.features.values()}
        plan = []
        try:
            with open(os.path.join(self._v_pkg_b, "pmi", "inspection_plan.csv"), encoding="utf-8") as f:
                plan = list(csv.DictReader(f))
        except (OSError, AttributeError):
            pass
        bore = next((f for f in feats.values() if f["description"].startswith("Ø16.000 F7")), {})
        ok = (item.get("revision") == "B" and item.get("active") and model == "BUSH-100_B.step"
              and "model_BUSH-100_B.FCStd" in docs and any(d.startswith("drawings_") for d in docs)
              and len(feats) == len(plan) > 0
              and (bore.get("nominalValue"), bore.get("tolerancePlus"), bore.get("toleranceMinus")) ==
              ("16", "0.034", "-0.016") and self._an_srv.schema_problems == [])
        self.step("In Carbon: the part at rev B, its CAD model, documents and inspection plan",
                  "what the replay's Carbon holds", SAME if ok else FAIL,
                  f"item {item.get('readableId')} rev {item.get('revision')} ({'active' if item.get('active') else '?'}); "
                  f"CAD model {model}; documents {docs}; {len(feats)} characteristics for {len(plan)} plan rows; the bore "
                  f"Ø16 F7 as nominal {bore.get('nominalValue')} +{bore.get('tolerancePlus')} "
                  f"-({bore.get('toleranceMinus')}) mm, i.e. 16.016 to 16.034; requests outside Carbon's published "
                  f"schemas: {len(self._an_srv.schema_problems)}")
        self.wait = 200

    def an_again(self):
        from . import carbon_ui
        before = len(self._an_srv.writes())
        b, where = self.click_ribbon("Publish to Manufacturing", tab="PLM")
        QtWidgets.QApplication.processEvents()
        how = self.p_ok()
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        r = carbon_ui.last or {}
        ok = "Nothing to write" in text and r.get("actions") == [] and len(self._an_srv.writes()) == before
        self.step("Publish the same release again", f"ribbon '{where} > Publish to Manufacturing', {how} = OK",
                  SAME if ok else FAIL, f"{len(self._an_srv.writes()) - before} writes "
                  f"{[a['what'] for a in r.get('actions', [])]}: Carbon already has the part, "
                  f"its model, its {len([n for n in r.get('notes', []) if n.startswith('document')])} documents and its "
                  "characteristics, so nothing is sent twice")
        self.p_close_info()
        self.wait = 200

    def an_shop(self):
        co = self._an_srv.company
        item = next(i for i in co.items.values() if i["readableId"] == "BUSH-100")
        co.quantities[(item["id"], "loc1")] = {"onHand": 23, "onHold": 0, "rejected": 2, "onProduction": 25}
        co.issues.append({"id": "nc1", "nonConformanceId": "NCR-0001", "name": "Bore below 16.016 (F7)",
                          "status": "In Progress", "containmentStatus": "Contained", "items": [item["id"]]})
        self.step("The shop builds it: 25 on a job, 23 good, 2 rejected for an undersize bore (a non-conformance)",
                  "written into the replay's Carbon by script, as the shop floor and quality would in Carbon",
                  DIFFERS, "in a real Carbon this comes from jobs, receipts and inspections on the MES and QMS side")
        self.wait = 100

    def an_status(self):
        b, where = self.click_ribbon("Manufacturing Status", tab="PLM")
        QtWidgets.QApplication.processEvents()
        text = self.p_info_text()
        ok = ("BUSH-100 rev B: Guide bush" in text and "23 EA on hand" in text and "2 rejected" in text
              and "NCR-0001 Bore below 16.016 (F7)" in text)
        self.step("Manufacturing Status: revision, stock and the open non-conformance", f"ribbon '{where} > "
                  "Manufacturing Status'", SAME if ok else FAIL, " | ".join(x.strip() for x in text.splitlines())[:600])
        self.p_shot_info("tutorial-BC-04-status.png")
        self.p_close_info()
        self.wait = 100

    def an_done(self):
        problems = self._an_srv.schema_problems if self._an_srv else ["no server"]
        self.step("Every request the replay sent matches Carbon's published API", "checked by the replay's Carbon",
                  SAME if not problems else FAIL, f"{len(self._an_srv.company.sent) if self._an_srv else 0} requests; "
                  f"refused by the schemas: {problems or 'none'}")
        if self._an_srv is not None:
            self._an_srv.__exit__(None, None, None)
