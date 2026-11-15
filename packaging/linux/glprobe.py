# SPDX-License-Identifier: LGPL-2.1-or-later
"""Can this display give FreeCAD an OpenGL 2+ context? Run by the AppImage's AppRun with FreeCAD's own Python.

Prints one line (renderer, version or why not) and exits 0 when a context of OpenGL 2.0 or newer can be created
and made current, 1 otherwise. AppRun then leaves FreeCAD on the system's driver or switches it to Mesa's software
renderer.
"""

import sys

try:
    from PySide6 import QtGui

    app = QtGui.QGuiApplication(sys.argv[:1])
    ctx = QtGui.QOpenGLContext()
    if not ctx.create():
        print("no OpenGL context can be created")
        sys.exit(1)
    surface = QtGui.QOffscreenSurface()
    surface.setFormat(ctx.format())
    surface.create()
    if not ctx.makeCurrent(surface):
        print("the OpenGL context cannot be made current")
        sys.exit(1)
    fmt = ctx.format()
    version = (fmt.majorVersion(), fmt.minorVersion())
    renderer = ""
    try:
        f = ctx.functions()
        renderer = f"{f.glGetString(0x1F00)} {f.glGetString(0x1F01)}, "    # GL_VENDOR, GL_RENDERER
    except Exception:
        pass
    print(f"{renderer}OpenGL {version[0]}.{version[1]}")
    ctx.doneCurrent()
    sys.exit(0 if version >= (2, 0) else 1)
except SystemExit:
    raise
except Exception as e:                      # no display, no xcb plugin, a driver that fails: all mean no
    print(f"{type(e).__name__}: {e}")
    sys.exit(1)
