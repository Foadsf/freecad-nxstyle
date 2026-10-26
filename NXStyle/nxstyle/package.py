# SPDX-License-Identifier: LGPL-2.1-or-later
"""Release package: manifest, checksums, archive and verification (no FreeCAD needed).

A package is a folder with the released model (STEP and native), the drawings (PDF), the PMI
(semantic JSON, inspection plan, gauge sizes, checks), the analyses (tolerance stack-ups, mass
properties) and a manifest that identifies the release (part number, revision, state, approver,
the version it was released from) and lists every file with its size and SHA-256. The manifest
is what a supplier or an auditor checks the package against: ``verify(folder)`` recomputes the
hashes. The zip is reproducible: same files in, same bytes out.

Hashes prove the files are those listed, not that the package is complete or right. ``verify`` also
checks the manifest itself (its format, the release identity, at least one file) and the package's
profile: what it must contain ("release": the model as STEP and as the native file; "geometry": the STEP
only, with no claim of complete PMI; "partial": whatever was chosen). The manifest lists the losses met
while making it: a loss the format cannot carry (the envelope or a 4X count in STEP AP242 through
OpenCASCADE; pmi.json keeps them) is listed, a critical one (a PMI that is not valid, a stack-up without a
valid result: values that are not current) fails a release.
"""

import csv
import datetime
import hashlib
import io
import json
import os
import zipfile

MANIFEST = "manifest.json"
README = "README.txt"
FIXED_TIME = (2000, 1, 1, 0, 0, 0)          # zip entries carry no wall-clock time
ROLES = {".step": "model (STEP)", ".stp": "model (STEP)", ".fcstd": "model (FreeCAD, native)",
         ".pdf": "drawing (PDF)", ".csv": "table", ".json": "data", ".txt": "report"}
FORMAT = "freecad-nxstyle release package 1"
# profile -> roles that must be in the package, and whether critical losses are allowed
PROFILES = {"release": (("model (STEP)", "model (FreeCAD, native)"), False),
            "geometry": (("model (STEP)",), True),
            "partial": ((), True)}


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def files_in(folder):
    """Every file under folder except the manifest and readme, as sorted relative '/' paths."""
    out = []
    for root, _, names in os.walk(folder):
        for n in names:
            rel = os.path.relpath(os.path.join(root, n), folder).replace(os.sep, "/")
            if rel not in (MANIFEST, README):
                out.append(rel)
    return sorted(out)


def role(rel):
    ext = os.path.splitext(rel)[1].lower()
    top = rel.split("/")[0]
    r = ROLES.get(ext, "file")
    return f"{r}, {top}" if "/" in rel else r


def build_manifest(folder, meta, profile="release", losses=()):
    """meta: part_number, revision, description, state, ... (anything JSON); losses: [{"what", "critical"}].
    Returns the manifest dict."""
    entries = []
    for rel in files_in(folder):
        p = os.path.join(folder, *rel.split("/"))
        entries.append({"path": rel, "bytes": os.path.getsize(p), "sha256": sha256(p), "role": role(rel)})
    losses = [dict(x) for x in losses]
    return {"format": FORMAT, "profile": profile, "package": dict(meta), "files": entries, "losses": losses,
            "pmi_complete": not losses}


def write_manifest(folder, meta, profile="release", losses=()):
    m = build_manifest(folder, meta, profile, losses)
    with open(os.path.join(folder, MANIFEST), "w", encoding="utf-8", newline="\n") as f:
        json.dump(m, f, indent=1, ensure_ascii=False, sort_keys=False)
        f.write("\n")
    with open(os.path.join(folder, README), "w", encoding="utf-8", newline="\n") as f:
        f.write(readme_text(m))
    return m


def readme_text(m):
    p = m["package"]
    lines = [f"Release package: {p.get('part_number', '?')} rev {p.get('revision', '?')}",
             f"{p.get('description', '')}".strip(), ""]
    for key in ("state", "approved_by", "released_by", "version", "source_document", "created", "created_with",
                "units", "standard", "step_schema"):
        if p.get(key):
            lines.append(f"{key.replace('_', ' ').capitalize():<16} {p[key]}")
    lines.append(f"{'Profile':<16} {m.get('profile', '?')}")
    for x in m.get("losses", []):
        lines.append(f"{'Critical loss' if x.get('critical') else 'Not carried':<16} {x.get('what', '')}")
    lines += ["", f"{'File':<52} {'Bytes':>10}  SHA-256"]
    for e in m["files"]:
        lines.append(f"{e['path']:<52} {e['bytes']:>10}  {e['sha256']}")
    lines += ["", "Check the files against this list with: python -m nxstyle.package verify <this folder>", ""]
    return "\n".join(lines)


def check_manifest(m):
    """Problems with the manifest itself: what it must say before its hashes mean anything."""
    if not isinstance(m, dict):
        return ["the manifest is not an object"]
    problems = []
    if m.get("format") != FORMAT:
        problems.append(f"unknown manifest format {m.get('format')!r} (expected {FORMAT!r})")
    p = m.get("package")
    if not isinstance(p, dict) or not str(p.get("part_number", "")).strip() or not str(p.get("revision", "")).strip():
        problems.append("the manifest does not identify the release (part number and revision)")
    files = m.get("files")
    if not isinstance(files, list) or not files:
        problems.append("the manifest lists no files")
        files = []
    for e in files:
        if not isinstance(e, dict) or not e.get("path") or not e.get("sha256"):
            problems.append(f"a file entry without path or hash: {e!r}")
    profile = m.get("profile", "release")
    if profile not in PROFILES:
        problems.append(f"unknown profile {profile!r}")
        return problems
    required, losses_ok = PROFILES[profile]
    roles = {ROLES.get(os.path.splitext(str(e.get("path", "")))[1].lower(), "file") for e in files
             if isinstance(e, dict)}
    for r in required:
        if r not in roles:
            problems.append(f"a {profile} package needs a {r}; it has none")
    if not losses_ok:
        for x in m.get("losses", []):
            if x.get("critical"):
                problems.append(f"critical loss: {x.get('what', '')}")
    return problems


def verify(folder):
    """Problems found checking the folder against its manifest ([] when the package is complete for its
    profile, free of critical losses, and every file matches)."""
    path = os.path.join(folder, MANIFEST)
    if not os.path.isfile(path):
        return [f"no {MANIFEST}"]
    try:
        with open(path, encoding="utf-8") as f:
            m = json.load(f)
    except (OSError, ValueError) as e:
        return [f"{MANIFEST} cannot be read: {e}"]
    problems = check_manifest(m)
    entries = m.get("files") if isinstance(m, dict) and isinstance(m.get("files"), list) else []
    listed = {e["path"]: e for e in entries if isinstance(e, dict) and e.get("path")}
    present = set(files_in(folder))
    for rel, e in listed.items():
        p = os.path.join(folder, *rel.split("/"))
        if rel not in present:
            problems.append(f"missing: {rel}")
        elif sha256(p) != e.get("sha256"):
            problems.append(f"changed: {rel}")
    for rel in sorted(present - set(listed)):
        problems.append(f"not in the manifest: {rel}")
    return problems


class PackageError(Exception):
    """A package that did not verify; nothing was replaced."""

    def __init__(self, problems):
        super().__init__("; ".join(problems))
        self.problems = problems


def publish_atomically(folder, build, make_zip=True):
    """Make a package in a staging folder beside folder with build(staging) (it writes the files and the
    manifest), verify it, and only then put it in place of folder (and its zip). A package that does not
    verify, or a build that fails half way, leaves the previous package as it was: rebuilding used to
    delete it first. Returns (manifest, zip path or None); raises PackageError."""
    import shutil
    staging = folder + ".staging"
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    os.makedirs(staging)
    try:
        m = build(staging)
        problems = verify(staging)
        if problems:
            raise PackageError(problems)
        z = None
        if make_zip:
            # the zip's root folder carries the final name, not the staging one
            tmp_zip = folder + ".zip.tmp"
            final_name = os.path.basename(os.path.normpath(folder))
            zip_folder(staging, tmp_zip, root=final_name)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    old = folder + ".previous"
    if os.path.isdir(old):
        shutil.rmtree(old)
    if os.path.isdir(folder):
        os.replace(folder, old)
    os.replace(staging, folder)
    shutil.rmtree(old, ignore_errors=True)
    if make_zip:
        z = folder + ".zip"
        os.replace(tmp_zip, z)
    return m, z


def zip_folder(folder, zip_path, root=None):
    """A reproducible zip of the folder (sorted entries, fixed times), with the folder's name (or root) as
    its root folder."""
    base = root or os.path.basename(os.path.normpath(folder))
    names = files_in(folder) + [n for n in (MANIFEST, README) if os.path.isfile(os.path.join(folder, n))]
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in sorted(names):
            info = zipfile.ZipInfo(f"{base}/{rel}", FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(os.path.join(folder, *rel.split("/")), "rb") as f:
                z.writestr(info, f.read())
    return zip_path


def write_csv(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        csv.writer(f, lineterminator="\n").writerows(rows)
    return path


def dict_rows(dicts, columns):
    return [columns] + [[d.get(c, "") for c in columns] for d in dicts]


def write_text(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text if text.endswith("\n") else text + "\n")
    return path


def today():
    return datetime.date.today().isoformat()


def safe_name(text):
    keep = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(text).strip())
    return keep.strip("._") or "part"


def main(argv=None):
    import sys
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) == 2 and argv[0] == "verify":
        problems = verify(argv[1])
        out = io.StringIO()
        for p in problems:
            print(p, file=out)
        print(out.getvalue() or "all files match the manifest", end="" if problems else "\n")
        return 1 if problems else 0
    print("usage: python -m nxstyle.package verify FOLDER")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
