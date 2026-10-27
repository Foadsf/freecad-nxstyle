# SPDX-License-Identifier: LGPL-2.1-or-later
"""Carbon as NX-Style's manufacturing system (no FreeCAD needed).

Carbon (https://github.com/crbnos/carbon) is an open-source ERP, MES and QMS: items and revisions, bills of
materials and methods, inventory, jobs, inspection plans and non-conformances. It plays the part that Siemens'
manufacturing systems play next to NX and Teamcenter: Strata releases the part (part number, revision, approval),
Carbon makes it. Carbon is a server (AGPL-3.0); NX-Style talks to it over its HTTP API and copies none of it.

The flows:

- publish: a release package (package.py) becomes a Carbon part at its revision: the STEP as the item's CAD
  model, the native file, drawings, PMI tables and the manifest as the item's documents, the assembly's bill of
  materials on its make method (components created when Carbon has none), and the inspection plan
  (pmi.inspection_plan) as a Carbon inspection plan whose characteristics carry nominal and tolerances;
- status: the item's revisions, stock at a location, inspection plans and open issues;
- check: the connection, with the companies the API key belongs to.

Every publish can be reviewed first (``dry_run=True``): the same reads, and the writes listed instead of made.
Nothing is ever deleted in Carbon: BOM lines and characteristics added there by hand stay, and the review
lists them. A make method that is Active is not edited: a new Draft
version takes the change, as Carbon's own CAD push does, so nothing on the shop floor moves until manufacturing
activates it. A new revision of an existing item is created inactive for the same reason.

Carbon API: ``POST <server>/api/v1/<module>/<operation>`` with the arguments as the JSON body and the API key
as a bearer token (https://docs.carbon.ms/api). Lists answer ``{"results", "count"}``, single results the
record itself, refusals ``{"code", "status", "message", "data": {"category"}}``. OPERATIONS lists every
operation this module calls; tests/test_carbon.py checks each request against Carbon's published OpenAPI
schema (a copy of the parts used is in tests/data).
"""

import argparse
import csv
import json
import os
import random
import string
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

API = "/api/v1"
CLOUD = "https://app.carbon.ms"
KEY_PREFIX = "crbn_"
KEY_ENV, URL_ENV = "CARBON_API_KEY", "CARBON_URL"
USER_AGENT = "FreeCAD-NX-Style"

OPERATIONS = (
    "settings.getCompanies", "resources.getLocationsList",
    "items.getParts", "items.getItem", "items.getPart", "items.createPart", "items.createRevision",
    "items.getMakeMethods", "items.createMethodVersion", "items.getMethodMaterialsByMakeMethod",
    "items.createMethodMaterial", "items.updateMethodMaterial",
    "items.createModelUploadUrl", "items.insertModelUpload", "items.createItemDocumentUploadUrl",
    "items.getItemFiles", "items.getItemQuantities",
    "quality.getInspectionDocumentsForItem", "quality.upsertInspectionDocument", "quality.getInspectionFeatures",
    "quality.saveInspectionDocument", "quality.getIssues",
)

# what a new part gets when nothing else says (Carbon's own CAD push uses the same defaults)
NEW_PART = {"replenishmentSystem": "Make", "defaultMethodType": "Make to Order", "itemTrackingType": "Inventory",
            "unitOfMeasureCode": "EA"}
REPLENISHMENT = ("Buy", "Buy and Make", "Make")
METHOD_TYPES = ("Make to Order", "Pull from Inventory", "Purchase to Order")
TRACKING = ("Batch", "Inventory", "Non-Inventory", "Serial")
CONTENT_TYPES = {".step": "application/step", ".stp": "application/step", ".pdf": "application/pdf",
                 ".csv": "text/csv", ".json": "application/json", ".txt": "text/plain",
                 ".fcstd": "application/zip", ".zip": "application/zip"}
CLOSED_ISSUE = ("Closed",)
PLAN_SUFFIX = "inspection plan (NX-Style PMI)"


class CarbonError(Exception):
    """A refusal or a failure, with what Carbon said: status (HTTP), code, category, message."""

    def __init__(self, message, status=None, code="", category="", operation=""):
        super().__init__(message)
        self.message, self.status, self.code, self.category, self.operation = message, status, code, category, operation

    def __str__(self):
        where = f"{self.operation}: " if self.operation else ""
        return f"{where}{self.message}" + (f" (HTTP {self.status})" if self.status else "")


# ------------------------------------------------------------------ settings and credentials
def normalise_url(url):
    """The server's origin: 'app.carbon.ms' -> 'https://app.carbon.ms'; a trailing /api/v1 or / is dropped.
    The API key is a bearer secret, so plain http is refused except to this machine."""
    url = (url or "").strip().rstrip("/")
    if not url:
        raise CarbonError("no Carbon server set (PLM › Manufacturing Connection, or CARBON_URL)")
    if "://" not in url:
        url = "https://" + url
    if url.endswith(API):
        url = url[: -len(API)]
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https") or not p.netloc:
        raise CarbonError(f"not a server address: {url!r}")
    if p.scheme == "http" and p.hostname not in ("localhost", "127.0.0.1", "::1"):
        raise CarbonError(f"refusing to send the API key over plain http to {p.hostname}; use https")
    return f"{p.scheme}://{p.netloc}{p.path.rstrip('/')}"


def check_key(key):
    key = (key or "").strip()
    if not key:
        raise CarbonError("no Carbon API key (Settings › API Keys in Carbon; CARBON_API_KEY or the key file)")
    if not key.startswith(KEY_PREFIX) or len(key) < len(KEY_PREFIX) + 8 or any(c.isspace() for c in key):
        raise CarbonError("that is not a Carbon API key (they start with crbn_)")
    return key


def api_key(key_file=None, env=None):
    """(key, where it came from): CARBON_API_KEY first, then the key file. The key is never logged."""
    env = os.environ if env is None else env
    if env.get(KEY_ENV, "").strip():
        return env[KEY_ENV].strip(), KEY_ENV
    if key_file and os.path.isfile(key_file):
        with open(key_file, encoding="utf-8") as f:
            return f.read().strip(), key_file
    return "", ""


def save_api_key(path, key):
    """Write the key file readable by its owner only (0600 where the system has modes)."""
    key = check_key(key)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(key + "\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def masked(key):
    return f"{KEY_PREFIX}…{key[-4:]}" if key and len(key) > len(KEY_PREFIX) + 4 else "(none)"


# ------------------------------------------------------------------ HTTP
def urllib_transport(method, url, headers, body, timeout):
    """(status, headers, bytes) of one request; HTTP errors are answers too, network failures raise."""
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read() or b""
    except (urllib.error.URLError, OSError) as e:
        raise CarbonError(f"cannot reach {urllib.parse.urlsplit(url).netloc}: {getattr(e, 'reason', e)}")


class Client:
    """One Carbon company, as its API key sees it."""

    def __init__(self, url, key, transport=None, timeout=60, retries=3, sleep=time.sleep):
        self.url = normalise_url(url)
        self._key = check_key(key)
        self.transport = transport or urllib_transport
        self.timeout, self.retries, self.sleep = timeout, retries, sleep
        self.calls = []                       # (operation, args) of every call, for the review and the tests

    def call(self, operation, args=None):
        module, op = operation.split(".")
        body = json.dumps(args or {}).encode("utf-8")
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
                   "Accept": "application/json", "User-Agent": USER_AGENT}
        self.calls.append((operation, args or {}))
        for attempt in range(self.retries + 1):
            status, rh, data = self.transport("POST", f"{self.url}{API}/{module}/{op}", headers, body, self.timeout)
            if status == 429 and attempt < self.retries:
                self.sleep(min(float(_header(rh, "Retry-After") or 2), 60))
                continue
            if status == 503 and attempt < self.retries:
                self.sleep(2 * (attempt + 1))
                continue
            break
        return _answer(operation, status, data)

    def results(self, operation, args=None, page=100, limit=5000):
        """Every row of a list operation, page by page."""
        out, args = [], dict(args or {})
        while len(out) < limit:
            r = self.call(operation, dict(args, limit=page, offset=len(out)))
            rows = r.get("results") or []
            out += rows
            count = r.get("count")
            if len(rows) < page or (count is not None and len(out) >= count):
                break
        return out

    def upload(self, signed_url, data, content_type="application/octet-stream"):
        """PUT file bytes to a signed storage URL that Carbon handed out (no API key: the URL carries a token)."""
        url = signed_url if "://" in signed_url else self.url + "/" + signed_url.lstrip("/")
        status, _, body = self.transport("PUT", url, {"Content-Type": content_type, "x-upsert": "true",
                                                      "User-Agent": USER_AGENT}, data, max(self.timeout, 300))
        if not 200 <= status < 300:
            raise CarbonError(f"upload refused: {body[:200].decode('utf-8', 'replace')}", status, operation="upload")


def _header(headers, name):
    for k, v in (headers or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def _answer(operation, status, data):
    text = data.decode("utf-8", "replace") if data else ""
    try:
        payload = json.loads(text) if text else None
    except ValueError:
        payload = None
    if 200 <= status < 300:
        return payload
    if isinstance(payload, dict) and payload.get("message"):
        cat = (payload.get("data") or {}).get("category", "") if isinstance(payload.get("data"), dict) else ""
        raise CarbonError(payload["message"], status, payload.get("code", ""), cat, operation)
    hint = {401: "the API key is not valid", 402: "the company's Carbon plan does not include the API",
            403: "the API key lacks the permission", 404: "this Carbon has no such operation (older server?)",
            429: "rate limited by Carbon; try again in a minute"}.get(status, "")
    raise CarbonError(hint or (text[:200] or f"HTTP {status}"), status, operation=operation)


# ------------------------------------------------------------------ reading a release package
def read_package(folder):
    """The release package's manifest and the files it lists, verified (package.verify) first: Carbon is
    given exactly what the manifest vouches for."""
    from . import package
    problems = package.verify(folder)
    if problems:
        raise CarbonError("the release package does not verify: " + "; ".join(problems[:5]))
    with open(os.path.join(folder, package.MANIFEST), encoding="utf-8") as f:
        return json.load(f)


def plan_rows(folder):
    """pmi/inspection_plan.csv of a package as dicts with numbers (pmi.inspection_plan's columns)."""
    path = os.path.join(folder, "pmi", "inspection_plan.csv")
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for k in ("nominal", "lower", "upper", "number"):
            try:
                r[k] = float(r[k]) if k != "number" else int(float(r[k]))
            except (KeyError, TypeError, ValueError):
                r[k] = None
    return rows


def step_bom(folder, manifest):
    """The product structure of the package's STEP (iso10303.bom), or None for a single part. FreeCAD's STEP
    writer wraps a lone solid in a product of its own (the document holding its Body): one component, once,
    with none below it, is that wrapper, not an assembly."""
    from . import iso10303, p21
    step = next((e["path"] for e in manifest["files"] if e["role"].startswith("model (STEP)")), None)
    if step is None:
        return None
    b = iso10303.bom(p21.read(os.path.join(folder, *step.split("/"))))
    roots = [r for r in b["roots"] if r["children"]]
    if len(roots) != 1:
        return None
    kids = roots[0]["children"]
    if len(kids) == 1 and kids[0]["quantity"] == 1 and not kids[0]["children"]:
        return None
    return roots[0]


# ------------------------------------------------------------------ mapping NX-Style onto Carbon
def _num(v, digits=6):
    s = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def characteristics(rows, digits=4):
    """Inspection plan rows -> Carbon inspection features: label (the characteristic's number, with its frame
    segment), description (the requirement), nominal, plus and minus tolerance, unit, type Measurement."""
    out = []
    for r in rows:
        if r.get("number") is None or r.get("nominal") is None or r.get("upper") is None:
            continue
        nom, low = r["nominal"], r.get("lower") if r.get("lower") is not None else r["nominal"]
        seg = (r.get("segment") or "").strip()
        desc = r.get("requirement", "")
        if r.get("feature"):
            desc += f"; feature {r['feature']}"
        if r.get("datums"):
            desc += f"; datums {r['datums']}"
        if r.get("method"):
            desc += f"; {r['method']}"
        out.append({"label": f"{r['number']}{' ' + seg if seg else ''}", "description": desc[:1000],
                    "nominalValue": _num(nom, digits), "tolerancePlus": _num(r["upper"] - nom, digits),
                    "toleranceMinus": _num(nom - low, digits),
                    "unit": "deg" if "angle" in (r.get("kind") or "") else "mm", "type": "Measurement"})
    return out


def part_args(identity, defaults=None):
    """createPart arguments for a release identity {part_number, revision, description/name}."""
    d = dict(NEW_PART, **(defaults or {}))
    name = (identity.get("name") or identity.get("description") or identity["part_number"]).strip()
    args = {"id": identity["part_number"], "revision": identity.get("revision") or "0", "name": name[:255],
            "replenishmentSystem": d["replenishmentSystem"], "defaultMethodType": d["defaultMethodType"],
            "itemTrackingType": d["itemTrackingType"], "unitOfMeasureCode": d["unitOfMeasureCode"]}
    if identity.get("description") and identity.get("description") != name:
        args["description"] = identity["description"]
    return args


def merge_children(children):
    """BOM children with the same part number and revision as one line, quantities added, order kept."""
    out = {}
    for c in children:
        key = (c["id"], c.get("revision") or "")
        if key in out:
            out[key]["quantity"] += c.get("quantity", 1)
        else:
            out[key] = dict(c, quantity=c.get("quantity", 1))
    return list(out.values())


def new_id(n=20):
    """A record id for a new BOM line (Carbon lets the caller choose it)."""
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


# ------------------------------------------------------------------ publish
class Publisher:
    """Carbon's records for one release. With dry_run, reads happen and writes are listed, not made."""

    def __init__(self, client, defaults=None, dry_run=False):
        self.c, self.defaults, self.dry_run = client, dict(NEW_PART, **(defaults or {})), dry_run
        self.actions = []                     # [{"what", "op"}]: written, or to be written
        self.notes = []                       # what was kept or left alone, and why
        self._items = {}
        self._files = {}

    # writes go through here
    def write(self, op, args, what):
        self.actions.append({"what": what, "op": op})
        if self.dry_run:
            return {"id": f"(new: {what})", "_dry": True}
        return self.c.call(op, args) or {}

    @staticmethod
    def planned(record_id):
        return isinstance(record_id, str) and record_id.startswith("(new")

    # ---- items
    def find(self, part_number):
        """Every revision of a part number in Carbon (rows of the parts list)."""
        rows = self.c.call("items.getParts", {"filters": [{"column": "readableId", "operator": "eq",
                                                           "value": part_number}], "limit": 100})
        return [r for r in (rows or {}).get("results") or [] if r.get("readableId") == part_number]

    def ensure_item(self, identity, defaults=None, activate=False):
        """The Carbon item of identity (part number and revision): found, made as a new revision of the
        part number, or created as a part. Without a revision (a component nobody released) the revision
        Carbon has is used: the active one, else the newest; a new part gets revision 0. Returns the item
        record (or a stand-in in a dry run)."""
        pn, rev = identity["part_number"], identity.get("revision") or ""
        key = (pn, rev)
        if key in self._items:
            return self._items[key]
        rows = self.find(pn)
        if not rev:
            rev = (max(rows, key=lambda r: (bool(r.get("active")), r.get("createdAt") or "")).get("revision")
                   if rows else "0") or "0"
            identity = dict(identity, revision=rev)
        same = [r for r in rows if (r.get("revision") or "") == rev]
        if same:
            item = self.c.call("items.getItem", {"id": same[0]["id"]})
            self.notes.append(f"{pn} rev {rev}: in Carbon already ({'active' if item.get('active') else 'inactive'}, "
                              f"{item.get('revisionStatus', '')})")
        elif rows:
            base = self.c.call("items.getItem", {"id": max(rows, key=lambda r: r.get("createdAt") or "")["id"]})
            fields = ("companyId", "id", "name", "type", "modelUploadId", "description", "unitOfMeasureCode",
                      "readableId", "defaultMethodType", "itemTrackingType", "mpn", "replenishmentSystem",
                      "sourcingType", "thumbnailPath")
            r = self.write("items.createRevision", {"item": {k: base.get(k) for k in fields}, "revision": rev,
                                                    "active": bool(activate)},
                           f"revision {rev} of {pn}, from rev {base.get('revision')}"
                           + ("" if activate else ", inactive until manufacturing releases it"))
            item = dict(base, id=r["id"], revision=rev, active=bool(activate))
            if not r.get("_dry"):
                item = self.c.call("items.getItem", {"id": r["id"]})
        else:
            args = part_args(identity, defaults or self.defaults)
            r = self.write("items.createPart", args, f"part {pn} rev {rev} ({args['replenishmentSystem']})")
            item = dict(args, id=r["id"], readableId=pn, active=True, type="Part", sourcingType="Specified")
            if not r.get("_dry"):
                item = self.c.call("items.getItem", {"id": r["id"]})
        self._items[key] = item
        return item

    # ---- files
    def files_of(self, item):
        """{name: size} of the item's documents in Carbon."""
        if self.planned(item["id"]):
            return {}
        if item["id"] not in self._files:
            rows = (self.c.call("items.getItemFiles", {"itemId": item["id"]}) or {}).get("results") or []
            self._files[item["id"]] = {f.get("name"): (f.get("metadata") or {}).get("size") for f in rows}
        return self._files[item["id"]]

    def attach_model(self, item, path, marker=None):
        """The STEP as the item's CAD model. Not sent again when the item has a model of that name and size,
        or of that name when the release marker (the release's manifest, sent last) shows this release is
        in Carbon: a package made again from the same release differs only in time stamps."""
        name, size = os.path.basename(path), os.path.getsize(path)
        if not self.planned(item["id"]) and item.get("modelUploadId"):
            part = self.c.call("items.getPart", {"itemId": item["id"]}) or {}
            if part.get("modelName") == name and (part.get("modelSize") == size or marker in self.files_of(item)):
                self.notes.append(f"CAD model {name}: already the item's model")
                return
        if self.dry_run:
            self.write("items.insertModelUpload", {}, f"CAD model {name} ({size} bytes)")
            return
        up = self.c.call("items.createModelUploadUrl", {"name": name})
        with open(path, "rb") as f:
            self.c.upload(up["signedUrl"], f.read(), CONTENT_TYPES.get(os.path.splitext(name)[1].lower(),
                                                                       "application/octet-stream"))
        self.write("items.insertModelUpload", {"modelId": up["modelId"], "path": up["path"], "name": name,
                                               "size": size, "itemId": item["id"]}, f"CAD model {name} ({size} bytes)")

    def attach_documents(self, item, files, marker=None):
        """files: [(name in Carbon, local path)], the release marker last. A document with the same name and
        size is not sent again, nor one with the same name once the marker shows this release is in Carbon."""
        have = self.files_of(item)
        released = marker is not None and marker in have
        for name, path in files:
            size = os.path.getsize(path)
            if have.get(name) == size or (released and name in have):
                self.notes.append(f"document {name}: in Carbon already")
                continue
            self.actions.append({"what": f"document {name} ({size} bytes)", "op": "items.createItemDocumentUploadUrl"})
            if self.dry_run:
                continue
            up = self.c.call("items.createItemDocumentUploadUrl", {"itemId": item["id"], "name": name})
            with open(path, "rb") as f:
                self.c.upload(up["signedUrl"], f.read(), CONTENT_TYPES.get(os.path.splitext(name)[1].lower(),
                                                                           "application/octet-stream"))

    # ---- bill of materials
    def method_for_lines(self, item, label):
        """The make method that takes BOM changes: the newest Draft, or a new Draft copied from the Active one
        (a released method is never edited). Returns (method record, its lines)."""
        if self.planned(item["id"]):
            return {"id": f"(new: method of {label})", "status": "Draft", "version": 1}, []
        methods = (self.c.call("items.getMakeMethods", {"itemId": item["id"]}) or {}).get("results") or []
        if not methods:
            raise CarbonError(f"{label} has no make method in Carbon (is it a Buy item?)")
        top = max(methods, key=lambda m: m.get("version") or 0)
        lines = (self.c.call("items.getMethodMaterialsByMakeMethod", {"makeMethodId": top["id"]})
                 or {}).get("results") or []
        return top, lines

    def new_draft(self, item, active, label):
        v = active.get("version") or 1
        r = self.write("items.createMethodVersion", {"copyFromId": active["id"], "version": v + 1,
                                                     "activeVersionId": active["id"]},
                       f"Draft version {v + 1} of {label}'s make method (version {v} is Active and stays live)")
        if r.get("_dry"):
            return {"id": f"(new: Draft of {label})", "status": "Draft", "version": v + 1}
        methods = (self.c.call("items.getMakeMethods", {"itemId": item["id"]}) or {}).get("results") or []
        drafts = [m for m in methods if m.get("status") == "Draft"]
        if not drafts:
            raise CarbonError(f"Carbon made no Draft method for {label}")
        return max(drafts, key=lambda m: m.get("version") or 0)

    def push_bom(self, node, item, label=None, depth=0):
        """node: {id (part number), revision, name, quantity, children}; item: its Carbon item. Each assembly's
        direct components become the lines of its make method; sub-assemblies get their own, recursively."""
        label = label or f"{node['id']} rev {node.get('revision') or '0'}"
        children = merge_children(node.get("children") or [])
        if not children or depth > 20:
            return
        wanted = []
        for c in children:
            ident = {"part_number": c["id"], "revision": c.get("revision") or "", "name": c.get("name") or c["id"]}
            defaults = dict(self.defaults)
            if c.get("children"):
                defaults.update(replenishmentSystem="Make", defaultMethodType="Make to Order")
            wanted.append((c, self.ensure_item(ident, defaults)))
        method, lines = self.method_for_lines(item, label)
        by_item = {ln.get("itemId"): ln for ln in lines}
        changes = []
        for order, (c, ci) in enumerate(wanted, 1):
            ln = by_item.pop(ci["id"], None)
            if ln is None:
                changes.append(("create", order, c, ci, None))
            elif abs((ln.get("quantity") or 0) - c["quantity"]) > 1e-9:
                changes.append(("update", order, c, ci, ln))
        for ln in by_item.values():
            self.notes.append(f"{label}: BOM line {ln.get('item', {}).get('name') or ln.get('itemId')} "
                              f"x {ln.get('quantity')} is not in the CAD BOM; kept")
        if changes and method.get("status") == "Active":
            method = self.new_draft(item, method, label)
            if not self.planned(method["id"]):        # the Draft holds a copy of the lines: match them again
                lines = (self.c.call("items.getMethodMaterialsByMakeMethod", {"makeMethodId": method["id"]})
                         or {}).get("results") or []
                copy = {ln.get("itemId"): ln for ln in lines}
                changes = [(k, o, c, ci, copy.get(ci["id"]) if k == "update" else None) for k, o, c, ci, _ in changes]
        for kind, order, c, ci, ln in changes:
            what = f"{label}: {c['quantity']:g} x {c['id']} rev {ci.get('revision') or c.get('revision') or '0'}"
            if kind == "create":
                self.write("items.createMethodMaterial", {
                    "id": new_id(), "makeMethodId": method["id"], "order": order, "itemType": "Part",
                    "itemId": ci["id"], "methodType": ci.get("defaultMethodType") or "Make to Order",
                    "sourcingType": ci.get("sourcingType") or "Specified", "quantity": c["quantity"],
                    "unitOfMeasureCode": ci.get("unitOfMeasureCode") or "EA"}, "BOM line " + what)
            else:
                keep = ("id", "makeMethodId", "order", "itemType", "methodType", "sourcingType", "itemId",
                        "methodOperationId", "unitOfMeasureCode")
                args = {k: ln.get(k) for k in keep if ln.get(k) is not None}
                args.update(quantity=c["quantity"], kit="true" if ln.get("kit") else "false")
                if args.get("itemType") not in ("Part", "Material", "Consumable"):
                    args["itemType"] = "Part"
                self.write("items.updateMethodMaterial", args, f"BOM line {what} (was {ln.get('quantity'):g})")
        if not changes:
            self.notes.append(f"{label}: make method version {method.get('version')} already has this BOM")
        for c, ci in wanted:
            if c.get("children"):
                self.push_bom(c, ci, depth=depth + 1)

    # ---- quality
    def push_inspection_plan(self, item, identity, features):
        """The inspection plan as a Carbon inspection plan of this item, one characteristic per row."""
        if not features:
            return
        pn, rev = identity["part_number"], identity.get("revision") or "0"
        name = f"{pn} rev {rev} {PLAN_SUFFIX}"
        doc_id, have = None, {}
        if not self.planned(item["id"]):
            docs = (self.c.call("quality.getInspectionDocumentsForItem", {"itemId": item["id"]}) or {}).get(
                "results") or []
            mine = [d for d in docs if d.get("drawingNumber") == pn]
            if mine:
                doc_id = mine[0]["id"]
                for f in (self.c.call("quality.getInspectionFeatures", {"inspectionDocumentId": doc_id})
                          or {}).get("results") or []:
                    have[f.get("label")] = f
        if doc_id is None:
            r = self.write("quality.upsertInspectionDocument", {"partId": item["id"], "name": name,
                                                                 "drawingNumber": pn},
                           f"inspection plan '{name}'")
            doc_id = r["id"]
        fields = ("description", "nominalValue", "tolerancePlus", "toleranceMinus", "unit", "type")
        create, update = [], []
        for f in features:
            old = have.pop(f["label"], None)
            if old is None:
                create.append(dict(f, pageNumber=1))
            elif any((old.get(k) or "") != (f.get(k) or "") for k in fields):
                update.append(dict(f, id=old["id"]))
        for f in have.values():
            self.notes.append(f"inspection plan: characteristic {f.get('label')} is not in the PMI plan; kept")
        if not (create or update):
            self.notes.append(f"inspection plan: its {len(features)} characteristics are in Carbon already")
            return
        self.write("quality.saveInspectionDocument", {"inspectionDocumentId": doc_id,
                                                      "features": {"create": create, "update": update}},
                   f"inspection plan: {len(create)} characteristics added, {len(update)} changed")


def publish(client, folder, bom=None, dry_run=False, defaults=None, allow_unreleased=False,
            parts=("model", "documents", "bom", "inspection"), name=None):
    """A release package into Carbon. bom: the assembly tree (see Publisher.push_bom; None reads the package
    STEP's product structure). name: the part's name for a new item (default: the release's description,
    which for a later revision says what changed). Returns {"item", "actions", "notes", "dry_run"}."""
    m = read_package(folder)
    meta = m["package"]
    if not allow_unreleased and meta.get("state") != "Released":
        raise CarbonError(f"{meta.get('part_number')} rev {meta.get('revision')} is {meta.get('state') or 'not released'}: "
                          "only a released part goes to manufacturing (allow_unreleased to send it anyway)")
    identity = {"part_number": meta["part_number"], "revision": meta.get("revision") or "0",
                "description": meta.get("description") or "", "name": name or ""}
    p = Publisher(client, defaults, dry_run)
    item = p.ensure_item(identity)
    files = [(e["path"], os.path.join(folder, *e["path"].split("/"))) for e in m["files"]]
    from . import package
    # the manifest, named after the release's commit when Strata gave one: its presence in Carbon says that
    # this release was published (it is sent last), so a package made again from it is not sent twice
    commit = (meta.get("commit") or "")[:12]
    marker = (f"{package.safe_name(identity['part_number'])}_{package.safe_name(identity['revision'])}_manifest"
              f"{'_' + commit if commit else ''}.json")
    if "model" in parts:
        step = next((path for rel, path in files if rel.lower().endswith((".step", ".stp"))), None)
        if step:
            p.attach_model(item, step, marker if commit else None)
    if "documents" in parts:
        docs = [(rel.replace("/", "_"), path) for rel, path in files if not rel.lower().endswith((".step", ".stp"))]
        docs.append((marker, os.path.join(folder, package.MANIFEST)))
        p.attach_documents(item, docs, marker if commit else None)
    if "bom" in parts:
        tree = bom if bom is not None else step_bom(folder, m)
        if tree:
            p.push_bom(dict(tree, id=identity["part_number"], revision=identity["revision"]), item)
    if "inspection" in parts:
        p.push_inspection_plan(item, identity, characteristics(plan_rows(folder)))
    return {"item": {k: item.get(k) for k in ("id", "readableId", "revision", "name", "active")},
            "actions": p.actions, "notes": p.notes, "dry_run": dry_run}


def publish_text(r):
    head = (f"{r['item'].get('readableId')} rev {r['item'].get('revision')}: "
            + ("review, nothing written yet" if r["dry_run"] else "published to Carbon"))
    lines = [head, ""]
    if r["actions"]:
        lines.append("Would write:" if r["dry_run"] else "Written:")
        lines += [f"  {a['what']}" for a in r["actions"]]
    else:
        lines.append("Nothing to write: Carbon has all of it.")
    if r["notes"]:
        lines += ["", "Left as it is:"] + [f"  {n}" for n in r["notes"]]
    return "\n".join(lines)


# ------------------------------------------------------------------ status
def status(client, part_number, revision=None, location=None):
    """What manufacturing has for a part: its revisions, stock at a location, inspection plans, open issues."""
    p = Publisher(client)
    rows = p.find(part_number)
    out = {"part_number": part_number, "found": bool(rows),
           "revisions": sorted(({"revision": r.get("revision"), "active": r.get("active"), "id": r.get("id")}
                                for r in rows), key=lambda r: r["revision"] or "")}
    if not rows:
        return out
    pick = [r for r in rows if r.get("revision") == revision] if revision else []
    row = pick[0] if pick else max(rows, key=lambda r: (bool(r.get("active")), r.get("createdAt") or ""))
    item = client.call("items.getItem", {"id": row["id"]}) or {}
    out["item"] = {k: item.get(k) for k in ("id", "readableId", "revision", "name", "active", "revisionStatus",
                                            "replenishmentSystem", "defaultMethodType", "itemTrackingType",
                                            "unitOfMeasureCode")}
    if location is None:
        locs = (client.call("resources.getLocationsList", {}) or {}).get("results") or []
        location = locs[0] if locs else None
    elif isinstance(location, str):
        locs = (client.call("resources.getLocationsList", {}) or {}).get("results") or []
        location = next((x for x in locs if location in (x.get("id"), x.get("name"))), {"id": location,
                                                                                         "name": location})
    if location:
        q = client.call("items.getItemQuantities", {"itemId": item["id"], "locationId": location["id"]}) or {}
        out["stock"] = {"location": location.get("name"), **{k: q.get(k) for k in (
            "quantityOnHand", "quantityOnHold", "quantityRejected", "quantityOnProductionOrder",
            "quantityOnPurchaseOrder", "quantityOnSalesOrder")}}
    docs = (client.call("quality.getInspectionDocumentsForItem", {"itemId": item["id"]}) or {}).get("results") or []
    out["inspection_plans"] = []
    for d in docs:
        feats = (client.call("quality.getInspectionFeatures", {"inspectionDocumentId": d["id"]})
                 or {}).get("results") or []
        out["inspection_plans"].append({"name": d.get("fileName") or d.get("drawingNumber") or d["id"],
                                        "version": d.get("version"), "characteristics": len(feats)})
    ids = {r["id"] for r in rows}
    issues = client.results("quality.getIssues", {"filters": [{"column": "status", "operator": "neq",
                                                               "value": "Closed"}]}, limit=1000)
    out["open_issues"] = [{"id": i.get("nonConformanceId") or i.get("id"), "name": i.get("name"),
                           "status": i.get("status"), "containment": i.get("containmentStatus")}
                          for i in issues if ids & set(i.get("items") or []) and i.get("status") not in CLOSED_ISSUE]
    return out


def status_text(s):
    if not s["found"]:
        return f"{s['part_number']}: not in Carbon yet (PLM › Publish to Manufacturing)"
    it = s["item"]
    lines = [f"{it['readableId']} rev {it['revision']}: {it['name']}",
             f"  {'active' if it['active'] else 'inactive'}, {it.get('revisionStatus') or ''}; "
             f"{it.get('replenishmentSystem')}, {it.get('defaultMethodType')}, tracked as {it.get('itemTrackingType')}",
             "  revisions in Carbon: " + ", ".join(f"{r['revision']}{'' if r['active'] else ' (inactive)'}"
                                                   for r in s["revisions"])]
    st = s.get("stock")
    if st:
        u = it.get("unitOfMeasureCode") or ""
        lines.append(f"  stock at {st['location']}: {st.get('quantityOnHand') or 0:g} {u} on hand, "
                     f"{st.get('quantityOnHold') or 0:g} on hold, {st.get('quantityRejected') or 0:g} rejected; "
                     f"{st.get('quantityOnProductionOrder') or 0:g} on production orders, "
                     f"{st.get('quantityOnPurchaseOrder') or 0:g} on purchase orders")
    plans = s.get("inspection_plans") or []
    lines.append("  inspection plans: " + (", ".join(f"{p['name']} ({p['characteristics']} characteristics)"
                                                     for p in plans) or "none"))
    issues = s.get("open_issues") or []
    lines.append(f"  open issues: {len(issues)}" + "".join(f"\n    {i['id']} {i['name']} ({i['status']})"
                                                           for i in issues))
    return "\n".join(lines)


def check(client):
    """The companies the key belongs to: proves the server, the key and the API plan."""
    rows = (client.call("settings.getCompanies", {}) or {}).get("results") or []
    return [r.get("name") or r.get("companyId") or r.get("id") for r in rows]


# ------------------------------------------------------------------ command line
def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m nxstyle.carbon", description="NX-Style and Carbon (manufacturing)")
    ap.add_argument("--url", default=os.environ.get(URL_ENV, ""), help=f"Carbon server (default ${URL_ENV})")
    ap.add_argument("--key-file", help=f"file holding the API key (default ${KEY_ENV})")
    ap.add_argument("--json", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check", help="test the connection and the API key")
    s = sub.add_parser("status", help="a part's revisions, stock, inspection plans and open issues")
    s.add_argument("part_number")
    s.add_argument("--revision")
    s.add_argument("--location")
    p = sub.add_parser("publish", help="a release package (python -m nxstyle.package) into Carbon")
    p.add_argument("package")
    p.add_argument("--dry-run", action="store_true", help="review: list what would be written")
    p.add_argument("--allow-unreleased", action="store_true")
    args = ap.parse_args(argv)
    try:
        key, _ = api_key(args.key_file)
        c = Client(args.url, key)
        if args.cmd == "check":
            r = check(c)
            text = f"{c.url}: API key {masked(key)} works; companies: {', '.join(map(str, r)) or '(none)'}"
        elif args.cmd == "status":
            r = status(c, args.part_number, args.revision, args.location)
            text = status_text(r)
        else:
            r = publish(c, args.package, dry_run=args.dry_run, allow_unreleased=args.allow_unreleased)
            text = publish_text(r)
    except CarbonError as e:
        print(f"Carbon: {e}", file=sys.stderr)
        return 1
    print(json.dumps(r, indent=1, ensure_ascii=False) if args.json else text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
