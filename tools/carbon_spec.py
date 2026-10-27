# SPDX-License-Identifier: LGPL-2.1-or-later
"""Refresh tests/data/carbon-openapi.json: the operations nxstyle/carbon.py calls, cut from Carbon's
published OpenAPI document (https://app.carbon.ms/api/v1/openapi.json, the interface Carbon publishes for
generating clients). tests/test_carbon.py checks every request the client sends against these schemas.

    python tools/carbon_spec.py                     # fetch the published document
    python tools/carbon_spec.py openapi.json        # or cut from a copy (a self-hosted server's /api/v1/openapi.json)
"""

import datetime
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "NXStyle"))
from nxstyle import carbon  # noqa: E402

SPEC = "https://app.carbon.ms/api/v1/openapi.json"
OUT = ROOT / "tests" / "data" / "carbon-openapi.json"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv:
        src, doc = argv[0], json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    else:
        src = SPEC
        with urllib.request.urlopen(urllib.request.Request(SPEC, headers={"User-Agent": carbon.USER_AGENT}),
                                    timeout=120) as r:
            doc = json.loads(r.read())
    paths, missing = {}, []
    for op in carbon.OPERATIONS:
        path = "/" + op.replace(".", "/")
        if path in doc["paths"]:
            paths[path] = doc["paths"][path]
        else:
            missing.append(op)
    out = {"openapi": doc.get("openapi"), "info": doc.get("info"), "servers": doc.get("servers"),
           "x-nxstyle": {"source": src, "fetched": datetime.date.today().isoformat(),
                         "operations": len(paths), "of": len(doc["paths"])},
           "components": {"schemas": {"Error": doc["components"]["schemas"]["Error"]},
                          "securitySchemes": doc["components"].get("securitySchemes", {})},
           "paths": paths}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{OUT}: {len(paths)} operations of {len(doc['paths'])}")
    if missing:
        print("not in the document (renamed or removed?): " + ", ".join(missing), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
