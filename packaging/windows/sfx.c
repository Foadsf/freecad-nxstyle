/* SPDX-License-Identifier: LGPL-2.1-or-later
 *
 * The single-file NX-Style.exe: a payload appended to this program (packaging/windows/sfx_pack.py describes the
 * layout) holds FreeCAD and NX-Style. At the first start it is unpacked once into
 *     %LOCALAPPDATA%\FreeCAD-NXStyle\runtime\<key>      (or NXSTYLE_RUNTIME_DIR\<key>, for a USB stick)
 * where <key> is the version and a hash of the payload, so every later start goes straight to FreeCAD and a new
 * build never reuses an old copy. The payload is one zstd frame, decompressed as a stream with zstd's decoder
 * (built in from zstd's own sources, BSD licence) and written file by file. Unpacking goes to "<key>.partial" and is renamed only when complete, under a named mutex,
 * so an interrupted first start or two simultaneous starts never leave a half-unpacked runtime in use.
 */
#define WIN32_LEAN_AND_MEAN
#define _CRT_SECURE_NO_WARNINGS
#ifndef UNICODE
#define UNICODE
#endif
#include <windows.h>
#include <commctrl.h>
#include <shellapi.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

#include "sfx.h"
#include "zstd.h"

#define END_MAGIC "NXSTYLE-SFX-END!"
#define PK_MAGIC "NXSFXZS1"
#define MAX_WINDOW_LOG 27 /* 128 MiB: the decoder's memory stays bounded whatever the payload claims */
#define IDX_MAGIC "NXIDX1\0\0"
#define WPATH (MAX_PATH * 4)

typedef struct {
    HANDLE exe;
    unsigned long long off, size;
    char key[33];
} payload;

static int read_at(HANDLE h, unsigned long long pos, void *buf, DWORD n)
{
    OVERLAPPED ov;
    memset(&ov, 0, sizeof ov);
    ov.Offset = (DWORD)(pos & 0xFFFFFFFFu);
    ov.OffsetHigh = (DWORD)(pos >> 32);
    DWORD got = 0;
    return ReadFile(h, buf, n, &got, &ov) && got == n;
}

static int find_payload(const wchar_t *exe_path, payload *p)
{
    memset(p, 0, sizeof *p);
    p->exe = CreateFileW(exe_path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, NULL);
    if (p->exe == INVALID_HANDLE_VALUE)
        return 0;
    LARGE_INTEGER size;
    unsigned char t[64];
    if (!GetFileSizeEx(p->exe, &size) || size.QuadPart < 64 || !read_at(p->exe, size.QuadPart - 64, t, 64) ||
        memcmp(t + 48, END_MAGIC, 16) != 0) {
        CloseHandle(p->exe);
        p->exe = INVALID_HANDLE_VALUE;
        return 0;
    }
    memcpy(&p->off, t, 8);
    memcpy(&p->size, t + 8, 8);
    memcpy(p->key, t + 16, 32);
    p->key[32] = 0;
    for (char *c = p->key; *c; c++) /* the key becomes a folder name */
        if (!((*c >= '0' && *c <= '9') || (*c >= 'a' && *c <= 'z') || (*c >= 'A' && *c <= 'Z') || *c == '.' ||
              *c == '-' || *c == '_'))
            *c = '_';
    return p->off + p->size + 64 == (unsigned long long)size.QuadPart;
}

/* ---------------------------------------------------------------- progress window (no console) */
static HWND g_win, g_bar;

static void pump(void)
{
    MSG m;
    while (PeekMessageW(&m, NULL, 0, 0, PM_REMOVE)) {
        TranslateMessage(&m);
        DispatchMessageW(&m);
    }
}

static void progress_open(const char *key)
{
    INITCOMMONCONTROLSEX icc = {sizeof icc, ICC_PROGRESS_CLASS};
    InitCommonControlsEx(&icc);
    HINSTANCE inst = GetModuleHandleW(NULL);
    WNDCLASSW wc;
    memset(&wc, 0, sizeof wc);
    wc.lpfnWndProc = DefWindowProcW;
    wc.hInstance = inst;
    wc.hIcon = LoadIconW(inst, MAKEINTRESOURCEW(1));
    wc.hCursor = LoadCursorW(NULL, (LPCWSTR)IDC_WAIT);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    wc.lpszClassName = L"NXStyleUnpack";
    RegisterClassW(&wc);
    int w = 460, h = 130;
    g_win = CreateWindowExW(WS_EX_TOPMOST, wc.lpszClassName, L"NX-Style", WS_CAPTION | WS_VISIBLE,
                            (GetSystemMetrics(SM_CXSCREEN) - w) / 2, (GetSystemMetrics(SM_CYSCREEN) - h) / 2, w, h,
                            NULL, NULL, inst, NULL);
    wchar_t text[160];
    _snwprintf(text, 160, L"First start of NX-Style %hs: unpacking FreeCAD and NX-Style. Later starts skip this.",
               key);
    text[159] = 0;
    HWND label = CreateWindowExW(0, L"STATIC", text, WS_CHILD | WS_VISIBLE, 16, 12, w - 40, 36, g_win, NULL, inst, NULL);
    SendMessageW(label, WM_SETFONT, (WPARAM)GetStockObject(DEFAULT_GUI_FONT), TRUE);
    g_bar = CreateWindowExW(0, PROGRESS_CLASSW, NULL, WS_CHILD | WS_VISIBLE, 16, 54, w - 40, 20, g_win, NULL, inst, NULL);
    SendMessageW(g_bar, PBM_SETRANGE32, 0, 1000);
    pump();
}

static void progress(sfx_say_fn say, int gui, unsigned long long done, unsigned long long total)
{
    static int last = -1;
    int permille = total ? (int)(done * 1000 / total) : 1000;
    if (permille == last)
        return;
    last = permille;
    if (gui && g_bar) {
        SendMessageW(g_bar, PBM_SETPOS, permille, 0);
        pump();
    } else if (!gui && permille % 50 == 0) {
        say("unpacking: %d %%\n", permille / 10);
    }
}

static void progress_close(void)
{
    if (g_win)
        DestroyWindow(g_win);
    g_win = g_bar = NULL;
}

/* ---------------------------------------------------------------- unpacking */
static int ensure_dirs(wchar_t *path) /* every folder of path (a file path, "C:\..." or "\\?\C:\..."), created */
{
    wchar_t *start = wcsncmp(path, L"\\\\?\\", 4) == 0 ? path + 7 : path + 3;
    for (wchar_t *c = start; *c; c++) {
        if (*c == L'\\') {
            *c = 0;
            BOOL ok = CreateDirectoryW(path, NULL) || GetLastError() == ERROR_ALREADY_EXISTS;
            *c = L'\\';
            if (!ok)
                return 0;
        }
    }
    return 1;
}

static void remove_tree(const wchar_t *dir)
{
    wchar_t from[WPATH + 2];
    memset(from, 0, sizeof from);
    wcsncpy(from, dir, WPATH); /* SHFileOperation wants a double-NUL-terminated list */
    SHFILEOPSTRUCTW op;
    memset(&op, 0, sizeof op);
    op.wFunc = FO_DELETE;
    op.pFrom = from;
    op.fFlags = FOF_NO_UI;
    SHFileOperationW(&op);
}

typedef struct {
    sfx_say_fn say;
    int gui;
    const wchar_t *root;   /* the .partial folder */
    unsigned char *idx;    /* the index, collected until complete */
    size_t idx_len, idx_cap, idx_pos;
    unsigned files, file_no;
    int idx_done;
    HANDLE out;            /* the file being written */
    unsigned long long left;
    char err[300];
} unpacker;

/* the next file of the index: open it (a zero-length one is created and closed at once) */
static int next_file(unpacker *u)
{
    while (u->file_no < u->files) {
        if (u->idx_pos + 4 > u->idx_len)
            goto bad;
        unsigned len;
        memcpy(&len, u->idx + u->idx_pos, 4);
        if (len == 0 || len > 1000 || u->idx_pos + 4 + len + 8 > u->idx_len)
            goto bad;
        const char *name = (const char *)u->idx + u->idx_pos + 4;
        unsigned long long size;
        memcpy(&size, u->idx + u->idx_pos + 4 + len, 8);
        u->idx_pos += 4 + len + 8;
        u->file_no++;
        wchar_t rel[WPATH];
        int n = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, name, (int)len, rel, WPATH - 1);
        if (n <= 0)
            goto bad;
        rel[n] = 0;
        for (wchar_t *c = rel; *c; c++)
            if (*c == L'/')
                *c = L'\\';
        if (rel[0] == L'\\' || wcschr(rel, L':') || wcsstr(rel, L"..\\") || wcscmp(rel, L"..") == 0 ||
            (wcslen(rel) >= 3 && wcscmp(rel + wcslen(rel) - 3, L"\\..") == 0)) {
            _snprintf(u->err, sizeof u->err, "unsafe path in the payload: %s", "(rejected)");
            return 0;
        }
        wchar_t full[WPATH];
        if (_snwprintf(full, WPATH, L"\\\\?\\%s\\%s", u->root, rel) < 0) {
            _snprintf(u->err, sizeof u->err, "path too long");
            return 0;
        }
        full[WPATH - 1] = 0;
        if (!ensure_dirs(full)) {
            _snprintf(u->err, sizeof u->err, "cannot create a folder (error %lu)", GetLastError());
            return 0;
        }
        HANDLE h = CreateFileW(full, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
        if (h == INVALID_HANDLE_VALUE) {
            _snprintf(u->err, sizeof u->err, "cannot write %ls (error %lu)", rel, GetLastError());
            return 0;
        }
        if (size == 0) {
            CloseHandle(h);
            continue;
        }
        u->out = h;
        u->left = size;
        return 1;
    }
    return 1; /* no more files */
bad:
    _snprintf(u->err, sizeof u->err, "the payload's index is damaged");
    return 0;
}

static int feed(unpacker *u, const unsigned char *p, size_t n)
{
    while (n) {
        if (!u->idx_done) {
            /* collect bytes until the whole index is here: 8 magic + 4 count + entries */
            if (u->idx_len + n > u->idx_cap) {
                size_t cap = u->idx_cap ? u->idx_cap * 2 : (1 << 22);
                while (cap < u->idx_len + n)
                    cap *= 2;
                unsigned char *q = (unsigned char *)realloc(u->idx, cap);
                if (!q) {
                    _snprintf(u->err, sizeof u->err, "out of memory");
                    return 0;
                }
                u->idx = q;
                u->idx_cap = cap;
            }
            /* find out how much of p belongs to the index */
            size_t before = u->idx_len;
            memcpy(u->idx + u->idx_len, p, n);
            u->idx_len += n;
            if (u->idx_len < 12)
                return 1;
            if (memcmp(u->idx, IDX_MAGIC, 8) != 0) {
                _snprintf(u->err, sizeof u->err, "the payload has no index");
                return 0;
            }
            memcpy(&u->files, u->idx + 8, 4);
            size_t pos = 12;
            unsigned i;
            for (i = 0; i < u->files; i++) {
                if (pos + 4 > u->idx_len)
                    break;
                unsigned len;
                memcpy(&len, u->idx + pos, 4);
                if (pos + 4 + len + 8 > u->idx_len)
                    break;
                pos += 4 + len + 8;
            }
            if (i < u->files)
                return 1; /* the index continues in the next block */
            u->idx_done = 1;
            u->idx_pos = 12;
            size_t used = pos - before; /* bytes of p that were index */
            u->idx_len = pos;
            p += used;
            n -= used;
            if (!next_file(u))
                return 0;
            continue;
        }
        if (!u->out) {
            _snprintf(u->err, sizeof u->err, "the payload has more data than its index lists");
            return 0;
        }
        DWORD chunk = (DWORD)(u->left < n ? u->left : n), w = 0;
        if (!WriteFile(u->out, p, chunk, &w, NULL) || w != chunk) {
            _snprintf(u->err, sizeof u->err, "write failed (error %lu): is the disk full?", GetLastError());
            return 0;
        }
        p += chunk;
        n -= chunk;
        u->left -= chunk;
        if (!u->left) {
            CloseHandle(u->out);
            u->out = NULL;
            if (!next_file(u))
                return 0;
        }
    }
    return 1;
}

static int unpack(payload *pl, const wchar_t *dest, sfx_say_fn say, int gui, char *err, size_t errn)
{
    unsigned char head[20];
    if (pl->size < 20 || !read_at(pl->exe, pl->off, head, 20) || memcmp(head, PK_MAGIC, 8) != 0) {
        _snprintf(err, errn, "the payload header is damaged");
        return 0;
    }
    unsigned long long logical;
    unsigned wlog;
    memcpy(&logical, head + 8, 8);
    memcpy(&wlog, head + 16, 4);
    if (wlog < 10 || wlog > MAX_WINDOW_LOG) {
        _snprintf(err, errn, "unknown payload format (window log %u)", wlog);
        return 0;
    }
    ULARGE_INTEGER avail;
    wchar_t drive[WPATH];
    wcsncpy(drive, dest, WPATH - 1);
    drive[WPATH - 1] = 0;
    wchar_t *cut = wcsrchr(drive, L'\\');
    if (cut)
        *cut = 0;
    if (GetDiskFreeSpaceExW(drive, &avail, NULL, NULL) && avail.QuadPart < logical + (200ull << 20)) {
        _snprintf(err, errn, "not enough disk space: unpacking needs %llu MB, %llu MB are free",
                  (logical >> 20) + 200, avail.QuadPart >> 20);
        return 0;
    }
    size_t in_cap = ZSTD_DStreamInSize(), out_cap = ZSTD_DStreamOutSize() * 4;
    unsigned char *in = (unsigned char *)malloc(in_cap), *outbuf = (unsigned char *)malloc(out_cap);
    ZSTD_DCtx *dctx = ZSTD_createDCtx();
    unpacker u;
    memset(&u, 0, sizeof u);
    u.say = say;
    u.gui = gui;
    u.root = dest;
    int ok = 0, frame_done = 0;
    if (!in || !outbuf || !dctx) {
        _snprintf(err, errn, "out of memory");
        goto done;
    }
    ZSTD_DCtx_setParameter(dctx, ZSTD_d_windowLogMax, (int)wlog);
    unsigned long long pos = pl->off + 20, end = pl->off + pl->size, done_bytes = 0;
    while (pos < end && !frame_done) {
        DWORD want = (DWORD)(end - pos < in_cap ? end - pos : in_cap);
        if (!read_at(pl->exe, pos, in, want)) {
            _snprintf(err, errn, "cannot read the payload (error %lu)", GetLastError());
            goto done;
        }
        pos += want;
        ZSTD_inBuffer zin = {in, want, 0};
        while (zin.pos < zin.size) {
            ZSTD_outBuffer zout = {outbuf, out_cap, 0};
            size_t r = ZSTD_decompressStream(dctx, &zout, &zin);
            if (ZSTD_isError(r)) {
                _snprintf(err, errn, "the payload does not decompress (%s): the file is damaged, download it again",
                          ZSTD_getErrorName(r));
                goto done;
            }
            if (zout.pos && !feed(&u, outbuf, zout.pos)) {
                _snprintf(err, errn, "%s", u.err);
                goto done;
            }
            done_bytes += zout.pos;
            progress(say, gui, done_bytes, logical);
            if (r == 0) {
                frame_done = 1;
                break;
            }
        }
    }
    /* flush what the decoder still holds */
    for (int more = 1; more && frame_done == 0;) {
        ZSTD_inBuffer zin = {in, 0, 0};
        ZSTD_outBuffer zout = {outbuf, out_cap, 0};
        size_t r = ZSTD_decompressStream(dctx, &zout, &zin);
        if (ZSTD_isError(r))
            break;
        if (zout.pos && !feed(&u, outbuf, zout.pos)) {
            _snprintf(err, errn, "%s", u.err);
            goto done;
        }
        done_bytes += zout.pos;
        more = zout.pos > 0;
        frame_done = r == 0;
    }
    if (!frame_done || u.out || u.file_no != u.files || !u.idx_done || done_bytes != logical) {
        _snprintf(err, errn, "the payload ended early (%u of %u files, %llu of %llu bytes)", u.file_no, u.files,
                  done_bytes, logical);
        goto done;
    }
    ok = 1;
done:
    if (u.out)
        CloseHandle(u.out);
    ZSTD_freeDCtx(dctx);
    free(u.idx);
    free(in);
    free(outbuf);
    return ok;
}

int sfx_bundle_dir(const wchar_t *exe_path, wchar_t *out, size_t outn, sfx_say_fn say, int gui, char *err, size_t errn)
{
    payload pl;
    if (!find_payload(exe_path, &pl)) {
        if (pl.exe && pl.exe != INVALID_HANDLE_VALUE) {
            CloseHandle(pl.exe);
            _snprintf(err, errn, "the payload trailer does not match the file size: the download is incomplete");
            return -1;
        }
        return 0;
    }
    wchar_t base[WPATH], dir[WPATH], partial[WPATH], mark[WPATH];
    DWORD n = GetEnvironmentVariableW(L"NXSTYLE_RUNTIME_DIR", base, WPATH);
    if (!n || n >= WPATH) {
        n = GetEnvironmentVariableW(L"LOCALAPPDATA", base, WPATH);
        if (!n || n >= WPATH - 64) {
            _snprintf(err, errn, "LOCALAPPDATA is not set");
            CloseHandle(pl.exe);
            return -1;
        }
        wcsncat(base, L"\\FreeCAD-NXStyle\\runtime", WPATH - wcslen(base) - 1);
    }
    _snwprintf(dir, WPATH, L"%s\\%hs", base, pl.key);
    _snwprintf(partial, WPATH, L"%s.partial", dir);
    _snwprintf(mark, WPATH, L"%s\\.nxstyle-complete", dir);
    dir[WPATH - 1] = partial[WPATH - 1] = mark[WPATH - 1] = 0;

    int rc = 1;
    DWORD a = GetFileAttributesW(mark);
    if (a == INVALID_FILE_ATTRIBUTES) {
        wchar_t mname[96];
        _snwprintf(mname, 96, L"Local\\FreeCAD-NXStyle-unpack-%hs", pl.key);
        mname[95] = 0;
        HANDLE mutex = CreateMutexW(NULL, FALSE, mname);
        if (mutex)
            WaitForSingleObject(mutex, INFINITE);
        if (GetFileAttributesW(mark) == INVALID_FILE_ATTRIBUTES) { /* nobody unpacked it while we waited */
            say("First start of NX-Style %s: unpacking FreeCAD and NX-Style into %ls\n", pl.key, dir);
            remove_tree(partial);
            remove_tree(dir);
            wchar_t probe[WPATH];
            _snwprintf(probe, WPATH, L"%s\\x", partial);
            probe[WPATH - 1] = 0;
            if (!ensure_dirs(probe)) {
                _snprintf(err, errn, "cannot create %ls (error %lu)", partial, GetLastError());
                rc = -1;
            } else {
                if (gui)
                    progress_open(pl.key);
                DWORD t0 = GetTickCount();
                int ok = unpack(&pl, partial, say, gui, err, errn);
                progress_close();
                if (!ok) {
                    remove_tree(partial);
                    rc = -1;
                } else {
                    wchar_t pmark[WPATH];
                    _snwprintf(pmark, WPATH, L"%s\\.nxstyle-complete", partial);
                    pmark[WPATH - 1] = 0;
                    HANDLE h = CreateFileW(pmark, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
                    if (h != INVALID_HANDLE_VALUE)
                        CloseHandle(h);
                    if (h == INVALID_HANDLE_VALUE || !MoveFileExW(partial, dir, 0)) {
                        _snprintf(err, errn, "cannot finish unpacking into %ls (error %lu)", dir, GetLastError());
                        remove_tree(partial);
                        rc = -1;
                    } else {
                        say("unpacked in %lu s\n", (GetTickCount() - t0) / 1000);
                    }
                }
            }
        }
        if (mutex) {
            ReleaseMutex(mutex);
            CloseHandle(mutex);
        }
    }
    CloseHandle(pl.exe);
    if (rc == 1) {
        wcsncpy(out, dir, outn - 1);
        out[outn - 1] = 0;
    }
    return rc;
}
