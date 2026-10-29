# SPDX-License-Identifier: LGPL-2.1-or-later
"""FreeCAD-Nxt (github.com/obelisk79/FreeCAD-Nxt, LGPL-2.1) next to NXStyle: off by default, on with --nxt or
"nxt": true. Nxt stays unforked; NXStyle only sets Nxt's own preferences in the NX profile, before Nxt loads.

FreeCAD runs the classic Mod InitGui.py files (NXStyle's) before the freecad.* namespace packages (Nxt's
freecad.nxt.init_gui), so what prepare() writes is in place when Nxt reads it.
"""

import os

import FreeCAD as App

GROUP = "User parameter:BaseApp/Preferences/Mod/Nxt"   # Nxt's core/settings.py GROUP


def expected():
    """The launcher loads Nxt (bundled, or a copy in the NX profile) when this is set."""
    return os.environ.get("NXSTYLE_NXT_EXPECTED", "0") == "1"


def loaded():
    import sys
    return "freecad.nxt" in sys.modules


def prepare():
    """Nxt's settings for the NX profile, written before Nxt starts. Its addon update check (app/update_check.py)
    looks for updates of every installed add-on and opens the Addon Manager's Update All dialog; in the NX profile
    the bundled add-ons are pinned submodules, so the check is switched off with Nxt's own CheckAddonUpdates."""
    if not expected():
        return
    App.ParamGet(GROUP).SetBool("CheckAddonUpdates", False)
