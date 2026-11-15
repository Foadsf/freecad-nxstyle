/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef NXSTYLE_SFX_H
#define NXSTYLE_SFX_H
#include <stddef.h>
#include <wchar.h>

typedef void (*sfx_say_fn)(const char *fmt, ...);

/* The folder the bundle runs from when exe_path carries a payload: unpacked on the first start (with a progress
 * window when gui is set, progress lines through say otherwise). Returns 1 with out set, 0 when exe_path has no
 * payload (a folder layout: run from beside the .exe), -1 on failure with the reason in err. */
int sfx_bundle_dir(const wchar_t *exe_path, wchar_t *out, size_t outn, sfx_say_fn say, int gui, char *err, size_t errn);

#endif
