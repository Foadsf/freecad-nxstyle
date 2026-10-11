# SPDX-License-Identifier: LGPL-2.1-or-later
# NXStyle: NX-like user interface for an unmodified FreeCAD.
# FreeCAD exec()s this file with separate globals and locals, so top-level
# functions cannot see each other; all logic lives in the nxstyle package.
import nxstyle.boot

nxstyle.boot.schedule()
