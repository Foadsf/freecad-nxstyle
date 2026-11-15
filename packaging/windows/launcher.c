/* SPDX-License-Identifier: LGPL-2.1-or-later
 *
 * NX-Style.exe: the Windows release is this one file, NX-Style-<ver>-windows-<arch>.exe. Its payload (sfx.c) is a
 * folder that it unpacks once into %LOCALAPPDATA%\FreeCAD-NXStyle\runtime\<key>:
 *     FreeCAD\            an unmodified FreeCAD release (its portable .7z)
 *     nxstyle\            launch_nx.py, NXStyle\ and vendor\
 * Built without a payload, it runs that folder from beside itself instead (a development build).
 *
 * It runs  FreeCAD\bin\python.exe -E -s nxstyle\launch_nx.py --freecad FreeCAD\bin\freecad.exe <its own arguments>
 * so the launcher's every option works here too (--smoke-test, --list, --profile, files to open, ...).
 *
 * OpenGL: FreeCAD needs OpenGL 2 or newer. A machine without a GPU driver that offers it (a VM, a remote desktop,
 * Windows on Arm without the OpenGL compatibility pack) only has Windows' "GDI Generic" OpenGL 1.1, and FreeCAD's
 * 3D view stays black or FreeCAD fails. This program asks the system's OpenGL first; when it falls short, FreeCAD
 * gets the Mesa software renderer it ships (bin\opengl32sw.dll, copied to bin\opengl32.dll, which Windows loads
 * from the program's folder before System32). NXSTYLE_SOFTWARE_GL=1 forces software rendering, =0 forbids it.
 *
 * Started from Explorer it has no console: output goes to %TEMP%\NX-Style-launch.log and a failure is shown in a
 * message box. Started with redirected output (PowerShell: `& .\NX-Style-....exe --dry-run | Out-Host`; cmd:
 * `start /wait`) it passes output through, waits and returns launch_nx.py's exit code.
 */
#define WIN32_LEAN_AND_MEAN
#define _CRT_SECURE_NO_WARNINGS /* every buffer below is sized and terminated by hand */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <shellapi.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#include "sfx.h"

#define GL_VENDOR 0x1F00
#define GL_RENDERER 0x1F01
#define GL_VERSION 0x1F02

typedef struct {
    wchar_t *p;
    size_t len, cap;
} wbuf;

static void wb_add(wbuf *b, const wchar_t *s, size_t n)
{
    if (b->len + n + 1 > b->cap) {
        size_t cap = (b->cap ? b->cap * 2 : 1024);
        while (cap < b->len + n + 1)
            cap *= 2;
        wchar_t *p = (wchar_t *)realloc(b->p, cap * sizeof(wchar_t));
        if (!p)
            ExitProcess(70);
        b->p = p;
        b->cap = cap;
    }
    memcpy(b->p + b->len, s, n * sizeof(wchar_t));
    b->len += n;
    b->p[b->len] = 0;
}

static void wb_str(wbuf *b, const wchar_t *s) { wb_add(b, s, wcslen(s)); }

/* Append one argument quoted the way CommandLineToArgvW and the C runtime split it again. */
static void wb_arg(wbuf *b, const wchar_t *arg)
{
    if (b->len)
        wb_str(b, L" ");
    if (*arg && !wcspbrk(arg, L" \t\n\v\"")) {
        wb_str(b, arg);
        return;
    }
    wb_str(b, L"\"");
    for (const wchar_t *c = arg;; c++) {
        size_t slashes = 0;
        while (*c == L'\\') {
            slashes++;
            c++;
        }
        if (!*c) {
            for (size_t i = 0; i < slashes * 2; i++)
                wb_str(b, L"\\");
            break;
        }
        if (*c == L'"') {
            for (size_t i = 0; i < slashes * 2 + 1; i++)
                wb_str(b, L"\\");
        } else {
            for (size_t i = 0; i < slashes; i++)
                wb_str(b, L"\\");
        }
        wb_add(b, c, 1);
    }
    wb_str(b, L"\"");
}

static HANDLE g_out = NULL; /* where this program's own messages go, or NULL */

static void say(const char *fmt, ...)
{
    char msg[2048];
    va_list ap;
    va_start(ap, fmt);
    int n = _vsnprintf(msg, sizeof msg - 1, fmt, ap);
    va_end(ap);
    if (n < 0)
        n = (int)strlen(msg);
    msg[sizeof msg - 1] = 0;
    if (g_out) {
        DWORD w;
        WriteFile(g_out, msg, (DWORD)strlen(msg), &w, NULL);
    }
}

static int file_exists(const wchar_t *p)
{
    DWORD a = GetFileAttributesW(p);
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

/* 1 if the system's OpenGL is a hardware driver offering 2.0 or newer; 0 otherwise, with the reason. */
static int system_gl_ok(char *why, size_t n)
{
    typedef HGLRC(WINAPI * create_t)(HDC);
    typedef BOOL(WINAPI * make_t)(HDC, HGLRC);
    typedef BOOL(WINAPI * delete_t)(HGLRC);
    typedef const unsigned char *(WINAPI * string_t)(unsigned int);
    int ok = 0;
    HMODULE gl = LoadLibraryExW(L"opengl32.dll", NULL, LOAD_LIBRARY_SEARCH_SYSTEM32);
    if (!gl) {
        _snprintf(why, n, "no opengl32.dll in System32");
        return 0;
    }
    create_t create = (create_t)(void *)GetProcAddress(gl, "wglCreateContext");
    make_t make = (make_t)(void *)GetProcAddress(gl, "wglMakeCurrent");
    delete_t del = (delete_t)(void *)GetProcAddress(gl, "wglDeleteContext");
    string_t str = (string_t)(void *)GetProcAddress(gl, "glGetString");
    if (!create || !make || !del || !str) {
        _snprintf(why, n, "opengl32.dll lacks the WGL entry points");
        FreeLibrary(gl);
        return 0;
    }
    WNDCLASSW wc;
    memset(&wc, 0, sizeof wc);
    wc.style = CS_OWNDC;
    wc.lpfnWndProc = DefWindowProcW;
    wc.hInstance = GetModuleHandleW(NULL);
    wc.lpszClassName = L"NXStyleGLProbe";
    RegisterClassW(&wc);
    HWND w = CreateWindowExW(0, wc.lpszClassName, L"", WS_OVERLAPPEDWINDOW, 0, 0, 32, 32, NULL, NULL, wc.hInstance, NULL);
    HDC dc = w ? GetDC(w) : NULL;
    PIXELFORMATDESCRIPTOR pfd;
    memset(&pfd, 0, sizeof pfd);
    pfd.nSize = sizeof pfd;
    pfd.nVersion = 1;
    pfd.dwFlags = PFD_DRAW_TO_WINDOW | PFD_SUPPORT_OPENGL | PFD_DOUBLEBUFFER;
    pfd.iPixelType = PFD_TYPE_RGBA;
    pfd.cColorBits = 32;
    pfd.cDepthBits = 24;
    pfd.cStencilBits = 8;
    pfd.iLayerType = PFD_MAIN_PLANE;
    int pf = dc ? ChoosePixelFormat(dc, &pfd) : 0;
    HGLRC rc = NULL;
    if (!pf || !SetPixelFormat(dc, pf, &pfd)) {
        _snprintf(why, n, "no OpenGL pixel format (error %lu)", GetLastError());
    } else if (!(rc = create(dc)) || !make(dc, rc)) {
        _snprintf(why, n, "no OpenGL context (error %lu)", GetLastError());
    } else {
        const char *ver = (const char *)str(GL_VERSION);
        const char *ren = (const char *)str(GL_RENDERER);
        const char *ven = (const char *)str(GL_VENDOR);
        int major = ver ? atoi(ver) : 0;
        if (!ver || !ren)
            _snprintf(why, n, "the OpenGL driver does not name itself");
        else if (major < 2 || strstr(ren, "GDI Generic"))
            _snprintf(why, n, "%s %s, OpenGL %s: below the OpenGL 2 FreeCAD needs", ven ? ven : "", ren, ver);
        else {
            _snprintf(why, n, "%s %s, OpenGL %s", ven ? ven : "", ren, ver);
            ok = 1;
        }
    }
    why[n - 1] = 0;
    if (rc) {
        make(NULL, NULL);
        del(rc);
    }
    if (dc)
        ReleaseDC(w, dc);
    if (w)
        DestroyWindow(w);
    UnregisterClassW(wc.lpszClassName, wc.hInstance);
    FreeLibrary(gl);
    return ok;
}

/* Put FreeCAD on Mesa's software renderer (want=1) or on the system's OpenGL (want=0). Only a bin\opengl32.dll
 * this program placed (marked by opengl32.dll.nxstyle) is ever removed. */
static void use_software_gl(const wchar_t *bin, int want)
{
    wchar_t sw[MAX_PATH * 2], dll[MAX_PATH * 2], mark[MAX_PATH * 2];
    _snwprintf(sw, MAX_PATH * 2, L"%s\\opengl32sw.dll", bin);
    _snwprintf(dll, MAX_PATH * 2, L"%s\\opengl32.dll", bin);
    _snwprintf(mark, MAX_PATH * 2, L"%s\\opengl32.dll.nxstyle", bin);
    if (want) {
        if (file_exists(dll))
            return;
        if (!file_exists(sw)) {
            say("NX-Style: this FreeCAD ships no opengl32sw.dll; it starts on the system's OpenGL\n");
            return;
        }
        if (!CopyFileW(sw, dll, TRUE)) {
            say("NX-Style: cannot switch FreeCAD to software rendering (error %lu copying opengl32sw.dll); is the "
                "folder read-only?\n", GetLastError());
            return;
        }
        HANDLE h = CreateFileW(mark, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        if (h != INVALID_HANDLE_VALUE) {
            DWORD wr;
            const char *t = "opengl32.dll is a copy of opengl32sw.dll (Mesa) placed by NX-Style.exe\r\n";
            WriteFile(h, t, (DWORD)strlen(t), &wr, NULL);
            CloseHandle(h);
        }
    } else if (file_exists(mark)) {
        if (DeleteFileW(dll) || GetLastError() == ERROR_FILE_NOT_FOUND)
            DeleteFileW(mark);
        else
            say("NX-Style: software rendering stays on: opengl32.dll is in use (a FreeCAD of this bundle is still "
                "running)\n");
    }
}

static void show_failure(DWORD code, const wchar_t *log)
{
    char tail[3000] = "";
    HANDLE h = CreateFileW(log, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL, OPEN_EXISTING, 0, NULL);
    if (h != INVALID_HANDLE_VALUE) {
        LARGE_INTEGER size;
        if (GetFileSizeEx(h, &size)) {
            LONGLONG start = size.QuadPart > 2900 ? size.QuadPart - 2900 : 0;
            LARGE_INTEGER pos;
            pos.QuadPart = start;
            SetFilePointerEx(h, pos, NULL, FILE_BEGIN);
            DWORD got = 0;
            ReadFile(h, tail, sizeof tail - 1, &got, NULL);
            tail[got] = 0;
        }
        CloseHandle(h);
    }
    wchar_t wtail[3000];
    MultiByteToWideChar(CP_UTF8, 0, tail, -1, wtail, 3000);
    wchar_t msg[4096];
    _snwprintf(msg, 4096, L"NX-Style could not start FreeCAD (exit code %lu).\n\n%s\n\nFull log: %s", code, wtail, log);
    msg[4095] = 0;
    MessageBoxW(NULL, msg, L"NX-Style", MB_OK | MB_ICONERROR);
}

int WINAPI wWinMain(HINSTANCE inst, HINSTANCE prev, LPWSTR cmdline, int show)
{
    (void)inst;
    (void)prev;
    (void)cmdline;
    (void)show;
    wchar_t self[MAX_PATH * 2];
    DWORD n = GetModuleFileNameW(NULL, self, MAX_PATH * 2);
    if (!n || n >= MAX_PATH * 2 - 64) /* room for the longest suffix appended below */
        return 70;
    wchar_t exe[MAX_PATH * 2];
    wcscpy(exe, self);
    wchar_t *slash = wcsrchr(self, L'\\');
    if (slash)
        *slash = 0; /* self is now the folder of the .exe */

    /* Where output goes: handles a parent passed (redirection), the parent's console, or a log file. */
    SECURITY_ATTRIBUTES sa = {sizeof sa, NULL, TRUE};
    HANDLE in = GetStdHandle(STD_INPUT_HANDLE), out = GetStdHandle(STD_OUTPUT_HANDLE), err = GetStdHandle(STD_ERROR_HANDLE);
    int redirected = out && out != INVALID_HANDLE_VALUE && GetFileType(out) != FILE_TYPE_UNKNOWN;
    int console = 0, gui = 0;
    wchar_t log[MAX_PATH * 2] = L"";
    if (!redirected && AttachConsole(ATTACH_PARENT_PROCESS)) {
        console = 1;
        out = CreateFileW(L"CONOUT$", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, NULL);
        err = out;
        in = CreateFileW(L"CONIN$", GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, OPEN_EXISTING, 0, NULL);
        say("\n");
    } else if (!redirected) {
        gui = 1;
        wchar_t tmp[MAX_PATH];
        GetTempPathW(MAX_PATH, tmp);
        _snwprintf(log, MAX_PATH * 2, L"%sNX-Style-launch.log", tmp);
        out = CreateFileW(log, GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, &sa, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        err = out;
        in = NULL;
    } else {
        if (!err || err == INVALID_HANDLE_VALUE)
            err = out;
        SetHandleInformation(out, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        SetHandleInformation(err, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
        if (in && in != INVALID_HANDLE_VALUE)
            SetHandleInformation(in, HANDLE_FLAG_INHERIT, HANDLE_FLAG_INHERIT);
    }
    g_out = (err && err != INVALID_HANDLE_VALUE) ? err : NULL;

    /* The single-file .exe carries the bundle as a payload, unpacked once into a cache; the folder layout of a
     * development build has it beside the .exe */
    char sfx_err[512] = "";
    wchar_t unpacked[MAX_PATH * 2];
    int sfx = sfx_bundle_dir(exe, unpacked, MAX_PATH * 2 - 64, say, gui, sfx_err, sizeof sfx_err);
    if (sfx < 0) {
        say("NX-Style: %s\n", sfx_err);
        if (gui) {
            wchar_t msg[700];
            _snwprintf(msg, 700, L"NX-Style cannot unpack itself: %hs", sfx_err);
            msg[699] = 0;
            MessageBoxW(NULL, msg, L"NX-Style", MB_OK | MB_ICONERROR);
        }
        return 65;
    }
    if (sfx > 0)
        wcscpy(self, unpacked);

    wchar_t bin[MAX_PATH * 2], python[MAX_PATH * 2], freecad[MAX_PATH * 2], script[MAX_PATH * 2];
    _snwprintf(bin, MAX_PATH * 2, L"%s\\FreeCAD\\bin", self);
    _snwprintf(python, MAX_PATH * 2, L"%s\\python.exe", bin);
    _snwprintf(freecad, MAX_PATH * 2, L"%s\\freecad.exe", bin);
    _snwprintf(script, MAX_PATH * 2, L"%s\\nxstyle\\launch_nx.py", self);

    if (!file_exists(python) || !file_exists(freecad) || !file_exists(script)) {
        say("NX-Style: the bundle is incomplete: FreeCAD\\bin\\python.exe, FreeCAD\\bin\\freecad.exe or "
            "nxstyle\\launch_nx.py is missing next to NX-Style.exe\n");
        if (gui)
            MessageBoxW(NULL, L"The bundle is incomplete: FreeCAD\\bin\\python.exe, FreeCAD\\bin\\freecad.exe or "
                              L"nxstyle\\launch_nx.py is missing. Download NX-Style again.",
                        L"NX-Style", MB_OK | MB_ICONERROR);
        return 66;
    }

    /* OpenGL: hardware if the system offers OpenGL 2+, Mesa's software renderer otherwise */
    wchar_t force[8] = L"";
    GetEnvironmentVariableW(L"NXSTYLE_SOFTWARE_GL", force, 8);
    char why[512] = "";
    int software;
    if (force[0] == L'1') {
        software = 1;
        _snprintf(why, sizeof why, "NXSTYLE_SOFTWARE_GL=1");
    } else if (force[0] == L'0') {
        software = 0;
        _snprintf(why, sizeof why, "NXSTYLE_SOFTWARE_GL=0");
    } else {
        software = !system_gl_ok(why, sizeof why);
    }
    use_software_gl(bin, software);
    SetEnvironmentVariableW(L"NXSTYLE_GL", software ? L"software" : L"hardware");
    say("OpenGL: %s (%s)\n", software ? "Mesa software renderer" : "system driver", why);

    /* python.exe -E -s launch_nx.py --freecad freecad.exe <arguments> */
    wbuf cmd = {0};
    wb_arg(&cmd, python);
    wb_arg(&cmd, L"-E");
    wb_arg(&cmd, L"-s");
    wb_arg(&cmd, script);
    wb_arg(&cmd, L"--freecad");
    wb_arg(&cmd, freecad);
    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    for (int i = 1; argv && i < argc; i++)
        wb_arg(&cmd, argv[i]);

    STARTUPINFOW si;
    memset(&si, 0, sizeof si);
    si.cb = sizeof si;
    si.dwFlags = STARTF_USESTDHANDLES;
    si.hStdInput = in;
    si.hStdOutput = out;
    si.hStdError = err;
    PROCESS_INFORMATION pi;
    /* With the parent's console the child shares it; otherwise its console stays hidden. */
    DWORD flags = console ? 0 : CREATE_NO_WINDOW;
    if (!CreateProcessW(python, cmd.p, NULL, NULL, TRUE, flags, NULL, self, &si, &pi)) {
        DWORD e = GetLastError();
        say("NX-Style: cannot start %ls (error %lu)\n", python, e);
        if (gui)
            show_failure(e, log);
        return 71;
    }
    CloseHandle(pi.hThread);
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 1;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    if (gui) {
        CloseHandle(out);
        if (code != 0)
            show_failure(code, log);
    }
    return (int)code;
}
