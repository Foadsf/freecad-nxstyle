# SPDX-License-Identifier: LGPL-2.1-or-later
"""A stand-in Carbon server for tests/test_carbon.py: real HTTP on 127.0.0.1, the request bodies checked
against Carbon's published OpenAPI input schemas (tests/data/carbon-openapi.json), and an in-memory company
that behaves as Carbon documents it: a new part gets a Draft make method, an Active method refuses edits, a
new revision copies the method of the revision below, uploads go to signed storage URLs.

It is a model of Carbon written from its documentation and source, not Carbon: what it proves is that the
client sends requests Carbon's schemas accept and handles the answers Carbon documents.
"""

import copy
import itertools
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SPEC = json.loads((Path(__file__).parent / "data" / "carbon-openapi.json").read_text(encoding="utf-8"))
KEY = "crbn_test_0123456789abcdef"


# ------------------------------------------------------------------ JSON Schema (the subset the spec uses)
def validate(schema, value, path="$", required=True):
    """Problems of value against schema: type, properties, required, enum, items, anyOf/oneOf.
    required=False skips 'required' (responses: the fake fills only what a test reads)."""
    out = []
    if not isinstance(schema, dict) or not schema:
        return out
    for key in ("anyOf", "oneOf"):
        if key in schema:
            if not any(not validate(s, value, path, required) for s in schema[key]):
                out.append(f"{path}: matches none of {key}")
            return out
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{path}: {value!r} not in {schema['enum']}")
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        ok = {"object": lambda v: isinstance(v, dict), "array": lambda v: isinstance(v, list),
              "string": lambda v: isinstance(v, str), "boolean": lambda v: isinstance(v, bool),
              "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
              "integer": lambda v: isinstance(v, int) and not isinstance(v, bool), "null": lambda v: v is None}
        if not any(ok.get(x, lambda v: True)(value) for x in types):
            return out + [f"{path}: {type(value).__name__} is not {t}"]
    if isinstance(value, dict):
        if required:
            out += [f"{path}.{k}: required" for k in schema.get("required", []) if k not in value]
        for k, v in value.items():
            if k in schema.get("properties", {}):
                out += validate(schema["properties"][k], v, f"{path}.{k}", required)
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            out += validate(schema["items"], v, f"{path}[{i}]", required)
    return out


def input_schema(op):
    e = SPEC["paths"]["/" + op.replace(".", "/")]["post"]
    return e.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema", {})


def output_schema(op):
    e = SPEC["paths"]["/" + op.replace(".", "/")]["post"]
    return e["responses"]["200"]["content"]["application/json"]["schema"]


# ------------------------------------------------------------------ the company
class Refusal(Exception):
    def __init__(self, status, message, category):
        super().__init__(message)
        self.status, self.message, self.category = status, message, category


class Company:
    def __init__(self):
        self._n = itertools.count(1)
        self.items, self.methods, self.lines = {}, {}, {}
        self.models, self.files, self.storage = {}, {}, {}
        self.docs, self.features, self.issues = {}, {}, []
        self.locations = [{"id": "loc1", "name": "Main Shop", "timezone": "Europe/Amsterdam"}]
        self.quantities = {}
        self.sent = []                        # (operation, body) of every API call
        self.uploads = []                     # (path, bytes) of every storage PUT

    def nid(self, prefix):
        return f"{prefix}{next(self._n):04d}"

    # ---- items
    def new_item(self, fields):
        iid = self.nid("itm")
        self.items[iid] = dict(fields, id=iid, companyId="co1", type="Part", createdAt=f"2026-10-27T00:00:{len(self.items):02d}",
                               revisionStatus="Design", sourcingType="Specified", modelUploadId=None, mpn=None,
                               thumbnailPath=None, description=fields.get("description"))
        mid = self.nid("mm")
        self.methods[mid] = {"id": mid, "itemId": iid, "status": "Draft", "version": 1, "companyId": "co1"}
        return iid

    def op_items_createPart(self, a):
        if any(i["readableId"] == a["id"] and i["revision"] == a["revision"] for i in self.items.values()):
            raise Refusal(409, f"{a['id']} rev {a['revision']} exists", "conflict")
        iid = self.new_item({k: a.get(k) for k in ("name", "description", "replenishmentSystem", "defaultMethodType",
                                                   "itemTrackingType", "unitOfMeasureCode", "revision")}
                            | {"readableId": a["id"], "active": True})
        return {"id": iid}

    def op_items_createRevision(self, a):
        src = self.items[a["item"]["id"]]
        iid = self.new_item({k: src[k] for k in ("name", "description", "replenishmentSystem", "defaultMethodType",
                                                 "itemTrackingType", "unitOfMeasureCode", "readableId")}
                            | {"revision": a["revision"], "active": a.get("active", True)})
        new_mm = next(m for m in self.methods.values() if m["itemId"] == iid)
        old = max((m for m in self.methods.values() if m["itemId"] == src["id"]), key=lambda m: m["version"])
        for ln in [x for x in self.lines.values() if x["makeMethodId"] == old["id"]]:
            lid = self.nid("ml")
            self.lines[lid] = dict(ln, id=lid, makeMethodId=new_mm["id"])
        return {"id": iid}

    def op_items_getParts(self, a):
        rows = list(self.items.values())
        for f in a.get("filters") or []:
            assert f["operator"] == "eq", f
            rows = [r for r in rows if str(r.get(f["column"])) == f["value"]]
        rows = [dict(r, readableIdWithRevision=f"{r['readableId']}.{r['revision']}") for r in rows]
        off, lim = a.get("offset", 0), a.get("limit", 100)
        return {"results": rows[off:off + lim], "count": len(rows)}

    def item(self, iid):
        if iid not in self.items:
            raise Refusal(404, "Item not found", "notFound")
        return self.items[iid]

    def op_items_getItem(self, a):
        return copy.deepcopy(self.item(a["id"]))

    def op_items_getPart(self, a):
        it = self.item(a["itemId"])
        m = self.models.get(it.get("modelUploadId"), {})
        out = dict(it, modelName=m.get("name"), modelSize=m.get("size"), modelId=it.get("modelUploadId"))
        return {k: v for k, v in out.items() if v is not None}       # the view's columns, as its schema types them

    # ---- methods
    def op_items_getMakeMethods(self, a):
        return {"results": [dict(m) for m in self.methods.values() if m["itemId"] == a["itemId"]], "count": None}

    def op_items_createMethodVersion(self, a):
        src = self.methods[a["copyFromId"]]
        if a.get("activeVersionId") != src["id"]:
            raise Refusal(422, "activeVersionId must be copyFromId", "rule")
        mid = self.nid("mm")
        self.methods[mid] = dict(src, id=mid, status="Draft", version=a["version"])
        for ln in [x for x in self.lines.values() if x["makeMethodId"] == src["id"]]:
            lid = self.nid("ml")
            self.lines[lid] = dict(ln, id=lid, makeMethodId=mid)
        return {"id": src["itemId"], "itemId": src["itemId"], "type": "Part"}

    def op_items_getMethodMaterialsByMakeMethod(self, a):
        rows = []
        for ln in self.lines.values():
            if ln["makeMethodId"] == a["makeMethodId"]:
                it = self.items[ln["itemId"]]
                rows.append(dict(ln, item={"name": it["name"], "itemTrackingType": it["itemTrackingType"],
                                           "replenishmentSystem": it["replenishmentSystem"],
                                           "defaultMethodType": it["defaultMethodType"],
                                           "sourcingType": it["sourcingType"]}, methodMaterialStep=[]))
        return {"results": sorted(rows, key=lambda r: r["order"]), "count": None}

    def writable(self, mid):
        m = self.methods.get(mid)
        if m is None:
            raise Refusal(404, "Make method not found", "notFound")
        if m["status"] != "Draft":
            raise Refusal(422, "The make method is Active: create a new version to change it", "rule")

    def op_items_createMethodMaterial(self, a):
        self.writable(a["makeMethodId"])
        if not a["id"].strip() or a["id"] in self.lines:
            raise Refusal(409, "Material ID exists", "conflict")
        self.item(a["itemId"])
        self.lines[a["id"]] = {k: a.get(k) for k in ("id", "makeMethodId", "order", "itemType", "itemId", "methodType",
                                                     "sourcingType", "quantity", "unitOfMeasureCode")} | {
            "kit": a.get("kit") == "true", "companyId": "co1"}
        return {"id": a["id"]}

    def op_items_updateMethodMaterial(self, a):
        self.writable(a["makeMethodId"])
        ln = self.lines.get(a["id"])
        if ln is None or ln["makeMethodId"] != a["makeMethodId"]:
            raise Refusal(404, "Method material not found", "notFound")
        ln.update({k: v for k, v in a.items() if k != "kit"}, kit=a.get("kit") == "true")
        return {"id": a["id"]}

    # ---- files
    def signed(self, bucket, path):
        return f"{self.base}/storage/v1/object/upload/sign/{bucket}/{path}?token=t{next(self._n)}"

    def op_items_createModelUploadUrl(self, a):
        mid = self.nid("mdl")
        path = f"co1/models/{mid}/{a['name']}"
        return {"modelId": mid, "path": path, "signedUrl": self.signed("temp-staging", path), "token": "t"}

    def op_items_insertModelUpload(self, a):
        if a["path"] not in self.storage:
            raise Refusal(422, "No file at that path", "rule")
        self.models[a["modelId"]] = {"name": a["name"], "size": a["size"]}
        if a.get("itemId"):
            self.item(a["itemId"])["modelUploadId"] = a["modelId"]
        return {"modelUploadId": a["modelId"]}

    def op_items_createItemDocumentUploadUrl(self, a):
        self.item(a["itemId"])
        path = f"co1/parts/{a['itemId']}/{a['name']}"
        return {"signedUrl": self.signed("private", path), "token": "t", "path": path}

    def op_items_getItemFiles(self, a):
        prefix = f"co1/parts/{a['itemId']}/"
        rows = [{"name": p[len(prefix):], "id": p, "updated_at": None, "created_at": None, "last_accessed_at": None,
                 "metadata": {"size": len(b), "eTag": "", "mimetype": "", "cacheControl": "", "lastModified": "",
                              "contentLength": len(b), "httpStatusCode": 200}}
                for p, b in self.storage.items() if p.startswith(prefix)]
        return {"results": rows, "count": None}

    # ---- inventory
    def op_items_getItemQuantities(self, a):
        q = self.quantities.get((a["itemId"], a["locationId"]), {})
        return {"id": a["itemId"], "quantityOnHand": q.get("onHand", 0), "quantityOnHold": q.get("onHold", 0),
                "quantityRejected": q.get("rejected", 0), "quantityOnProductionOrder": q.get("onProduction", 0),
                "quantityOnPurchaseOrder": 0, "quantityOnSalesOrder": 0}

    def op_resources_getLocationsList(self, a):
        return {"results": self.locations, "count": None}

    def op_settings_getCompanies(self, a):
        return {"results": [{"id": "co1", "companyId": "co1", "name": "Test Precision BV"}], "count": None}

    # ---- quality
    def op_quality_getInspectionDocumentsForItem(self, a):
        return {"results": [{"id": d["id"], "fileName": None, "drawingNumber": d["drawingNumber"], "version": 0}
                            for d in self.docs.values() if d["partId"] == a["itemId"]], "count": None}

    def op_quality_upsertInspectionDocument(self, a):
        self.item(a["partId"])
        did = self.nid("ins")
        self.docs[did] = {"id": did, "partId": a["partId"], "name": a.get("name"), "drawingNumber": a.get("drawingNumber")}
        return {"id": did}

    def op_quality_getInspectionFeatures(self, a):
        return {"results": [dict(f) for f in self.features.values() if f["inspectionDocumentId"] ==
                            a["inspectionDocumentId"]], "count": None}

    def op_quality_saveInspectionDocument(self, a):
        did = a["inspectionDocumentId"]
        if did not in self.docs:
            raise Refusal(404, "Inspection plan not found", "notFound")
        fs = a.get("features") or {}
        for f in fs.get("create", []):
            fid = self.nid("feat")
            self.features[fid] = dict(f, id=fid, inspectionDocumentId=did)
        for f in fs.get("update", []):
            self.features[f["id"]].update(f)
        for fid in fs.get("delete", []):
            del self.features[fid]
        return {"success": True, "featureIdMap": {}, "balloonAnchorIdMap": {}, "features": [], "anchors": [],
                "balloons": []}

    def op_quality_getIssues(self, a):
        rows = list(self.issues)
        for f in a.get("filters") or []:
            if f["operator"] == "neq":
                rows = [r for r in rows if r.get(f["column"]) != f["value"]]
        off, lim = a.get("offset", 0), a.get("limit", 100)
        return {"results": rows[off:off + lim], "count": len(rows)}


# ------------------------------------------------------------------ HTTP
class Server:
    """with Server() as s: s.url, s.company"""

    def __init__(self, key=KEY):
        self.key, self.company = key, Company()
        self.schema_problems = []             # requests the published schemas reject (a test asserts none)
        self.fail_next = []                   # [(status, headers, body)] answered before handling

    def __enter__(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def reply(self, status, body, headers=None, ctype="application/json"):
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_PUT(self):
                n = int(self.headers.get("Content-Length") or 0)
                data = self.rfile.read(n)
                if "/storage/v1/object/upload/sign/" not in self.path or "token=" not in self.path:
                    return self.reply(400, {"message": "not a signed URL"})
                if self.headers.get("Authorization"):
                    outer.schema_problems.append("the API key was sent to the storage URL")
                path = self.path.split("/upload/sign/", 1)[1].split("?")[0].split("/", 1)[1]
                outer.company.storage[path] = data
                outer.company.uploads.append((path, data))
                self.reply(200, {"Key": path})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n)
                if outer.fail_next:
                    status, headers, body = outer.fail_next.pop(0)
                    return self.reply(status, body, headers, "text/plain" if isinstance(body, bytes) else
                                      "application/json")
                auth = self.headers.get("Authorization", "")
                if auth != f"Bearer {outer.key}":
                    return self.reply(401, b"Unauthorized: send your API key as `Authorization: Bearer crbn_...`.",
                                      ctype="text/plain")
                if not self.path.startswith("/api/v1/"):
                    return self.reply(404, {"error": "Operation not found"})
                op = ".".join(self.path[len("/api/v1/"):].split("/"))
                if "/" + op.replace(".", "/") not in SPEC["paths"]:
                    return self.reply(404, {"error": "Operation not found"})
                body = json.loads(raw or b"{}")
                problems = validate(input_schema(op), body)
                if problems:
                    outer.schema_problems.append((op, problems))
                    return self.reply(400, {"defined": True, "code": "BAD_REQUEST", "status": 400,
                                            "message": "; ".join(problems), "data": {"category": "validation"}})
                outer.company.sent.append((op, body))
                try:
                    result = getattr(outer.company, "op_" + op.replace(".", "_"))(body)
                except Refusal as e:
                    return self.reply(e.status, {"defined": True, "code": "REFUSED", "status": e.status,
                                                 "message": e.message, "data": {"category": e.category}})
                bad = validate(output_schema(op), result, required=False)
                if bad:
                    outer.schema_problems.append((op + " (fake's answer)", bad))
                self.reply(200, result)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.company.base = self.url
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()

    def writes(self):
        """The calls that changed something, by operation name."""
        return [op for op, _ in self.company.sent if not op.split(".")[1].startswith("get")]
