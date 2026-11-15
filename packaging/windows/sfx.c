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
    /* an antivirus still scanning the files just written can hold a folder open for a moment */
    for (int attempt = 0; attempt < 5 && GetFileAttributesW(dir) != INVALID_FILE_ATTRIBUTES; attempt++) {
        if (attempt)
            Sleep(400);
        SHFileOperationW(&op);
    }
}

/* Writing 35,000 files one after the other is what takes time, not decompressing: an antivirus scans each file
 * as it is closed. Files up to BIG_FILE are therefore collected in memory and written by a pool of threads, with
 * at most IN_FLIGHT_MAX bytes waiting; larger ones are streamed to disk by the decoding thread itself. */
#define MAX_WORKERS 8
#define QCAP 4096
#define BIG_FILE (64ull << 20)
#define IN_FLIGHT_MAX (512ull << 20)

typedef struct {
    wchar_t *path;
    unsigned char *data;
    size_t size;
} job;

typedef struct {
    CRITICAL_SECTION cs;
    CONDITION_VARIABLE changed;
    job q[QCAP];
    unsigned head, count;
    unsigned long long in_flight;
    int stop, failed;
    char err[300];
    HANDLE threads[MAX_WORKERS];
    int nthreads;
} pool;

static int write_file(const wchar_t *path, const unsigned char *data, size_t size, char *err, size_t errn)
{
    wchar_t p[WPATH];
    wcsncpy(p, path, WPATH - 1);
    p[WPATH - 1] = 0;
    if (!ensure_dirs(p)) {
        _snprintf(err, errn, "cannot create a folder for %ls (error %lu)", path + 4, GetLastError());
        return 0;
    }
    HANDLE h = CreateFileW(p, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        _snprintf(err, errn, "cannot write %ls (error %lu)", path + 4, GetLastError());
        return 0;
    }
    while (size) {
        DWORD chunk = size > (1u << 30) ? (1u << 30) : (DWORD)size, w = 0;
        if (!WriteFile(h, data, chunk, &w, NULL) || w != chunk) {
            _snprintf(err, errn, "write failed (error %lu): is the disk full?", GetLastError());
            CloseHandle(h);
            return 0;
        }
        data += chunk;
        size -= chunk;
    }
    if (!CloseHandle(h)) {
        _snprintf(err, errn, "cannot finish %ls (error %lu)", path + 4, GetLastError());
        return 0;
    }
    return 1;
}

static DWORD WINAPI worker(void *arg)
{
    pool *p = (pool *)arg;
    for (;;) {
        EnterCriticalSection(&p->cs);
        while (p->count == 0 && !p->stop)
            SleepConditionVariableCS(&p->changed, &p->cs, INFINITE);
        if (p->count == 0) {
            LeaveCriticalSection(&p->cs);
            return 0;
        }
        job j = p->q[p->head];
        p->head = (p->head + 1) % QCAP;
        p->count--;
        int skip = p->failed;
        LeaveCriticalSection(&p->cs);
        WakeAllConditionVariable(&p->changed);
        char e[300] = "";
        int ok = skip || write_file(j.path, j.data, j.size, e, sizeof e);
        free(j.path);
        free(j.data);
        EnterCriticalSection(&p->cs);
        p->in_flight -= j.size;
        if (!ok && !p->failed) {
            p->failed = 1;
            memcpy(p->err, e, sizeof e);
        }
        LeaveCriticalSection(&p->cs);
        WakeAllConditionVariable(&p->changed);
    }
}

static int pool_start(pool *p)
{
    memset(p, 0, sizeof *p);
    InitializeCriticalSection(&p->cs);
    InitializeConditionVariable(&p->changed);
    SYSTEM_INFO si;
    GetSystemInfo(&si);
    int n = (int)si.dwNumberOfProcessors;
    n = n < 2 ? 2 : n > MAX_WORKERS ? MAX_WORKERS : n;
    for (int i = 0; i < n; i++) {
        p->threads[i] = CreateThread(NULL, 0, worker, p, 0, NULL);
        if (!p->threads[i])
            break;
        p->nthreads++;
    }
    return p->nthreads > 0;
}

/* wait until size more bytes may be held in memory, and count them */
static int pool_reserve(pool *p, size_t size)
{
    EnterCriticalSection(&p->cs);
    while (!p->failed && p->in_flight && p->in_flight + size > IN_FLIGHT_MAX)
        SleepConditionVariableCS(&p->changed, &p->cs, INFINITE);
    int ok = !p->failed;
    if (ok)
        p->in_flight += size;
    LeaveCriticalSection(&p->cs);
    return ok;
}

/* hand a reserved, complete file to the writers (they free path and data) */
static int pool_push(pool *p, wchar_t *path, unsigned char *data, size_t size)
{
    EnterCriticalSection(&p->cs);
    while (!p->failed && p->count == QCAP)
        SleepConditionVariableCS(&p->changed, &p->cs, INFINITE);
    int ok = !p->failed;
    if (ok) {
        job j = {path, data, size};
        p->q[(p->head + p->count) % QCAP] = j;
        p->count++;
    } else {
        p->in_flight -= size;
    }
    LeaveCriticalSection(&p->cs);
    WakeAllConditionVariable(&p->changed);
    if (!ok) {
        free(path);
        free(data);
    }
    return ok;
}

/* wait for every queued file to be written; 1 if all were */
static int pool_finish(pool *p)
{
    EnterCriticalSection(&p->cs);
    p->stop = 1;
    LeaveCriticalSection(&p->cs);
    WakeAllConditionVariable(&p->changed);
    if (p->nthreads)
        WaitForMultipleObjects((DWORD)p->nthreads, p->threads, TRUE, INFINITE);
    for (int i = 0; i < p->nthreads; i++)
        CloseHandle(p->threads[i]);
    p->nthreads = 0;
    DeleteCriticalSection(&p->cs);
    return !p->failed;
}

typedef struct {
    sfx_say_fn say;
    int gui;
    const wchar_t *root;   /* the .partial folder */
    pool *pool;
    unsigned char *idx;    /* the index, collected until complete */
    size_t idx_len, idx_cap, idx_pos;
    unsigned files, file_no;
    int idx_done;
    HANDLE out;            /* a big file, streamed by this thread */
    unsigned long long left;
    wchar_t *cur_path;     /* a small file, collected for the writers */
    unsigned char *cur;
    size_t cur_size, cur_have;
    char err[300];
} unpacker;

static int pool_failed(unpacker *u)
{
    _snprintf(u->err, sizeof u->err, "%s", u->pool->err);
    return 0;
}

/* the next file of the index: big ones are opened here, small ones get a buffer; empty ones are queued at once */
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
            _snprintf(u->err, sizeof u->err, "unsafe path in the payload: %ls", rel);
            return 0;
        }
        wchar_t full[WPATH];
        if (_snwprintf(full, WPATH, L"\\\\?\\%s\\%s", u->root, rel) < 0) {
            _snprintf(u->err, sizeof u->err, "path too long: %ls", rel);
            return 0;
        }
        full[WPATH - 1] = 0;
        if (size >= BIG_FILE) {
            if (!ensure_dirs(full)) {
                _snprintf(u->err, sizeof u->err, "cannot create a folder for %ls (error %lu)", rel, GetLastError());
                return 0;
            }
            HANDLE h = CreateFileW(full, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
            if (h == INVALID_HANDLE_VALUE) {
                _snprintf(u->err, sizeof u->err, "cannot write %ls (error %lu)", rel, GetLastError());
                return 0;
            }
            u->out = h;
            u->left = size;
            return 1;
        }
        wchar_t *path = _wcsdup(full);
        if (!path || !pool_reserve(u->pool, (size_t)size)) {
            free(path);
            return path ? pool_failed(u) : (_snprintf(u->err, sizeof u->err, "out of memory"), 0);
        }
        unsigned char *buf = size ? (unsigned char *)malloc((size_t)size) : NULL;
        if (size && !buf) {
            EnterCriticalSection(&u->pool->cs);
            u->pool->in_flight -= (size_t)size;
            LeaveCriticalSection(&u->pool->cs);
            WakeAllConditionVariable(&u->pool->changed);
            free(path);
            _snprintf(u->err, sizeof u->err, "out of memory");
            return 0;
        }
        if (size == 0) {
            if (!pool_push(u->pool, path, NULL, 0))
                return pool_failed(u);
            continue;
        }
        u->cur_path = path;
        u->cur = buf;
        u->cur_size = (size_t)size;
        u->cur_have = 0;
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
                return 1; /* the index continues in the next piece */
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
        if (u->out) {
            DWORD chunk = (DWORD)(u->left < n ? u->left : n), w = 0;
            if (!WriteFile(u->out, p, chunk, &w, NULL) || w != chunk) {
                _snprintf(u->err, sizeof u->err, "write failed (error %lu): is the disk full?", GetLastError());
                return 0;
            }
            p += chunk;
            n -= chunk;
            u->left -= chunk;
            if (!u->left) {
                BOOL closed = CloseHandle(u->out);
                u->out = NULL;
                if (!closed) {
                    _snprintf(u->err, sizeof u->err, "cannot finish a file (error %lu)", GetLastError());
                    return 0;
                }
                if (!next_file(u))
                    return 0;
            }
        } else if (u->cur) {
            size_t chunk = u->cur_size - u->cur_have < n ? u->cur_size - u->cur_have : n;
            memcpy(u->cur + u->cur_have, p, chunk);
            u->cur_have += chunk;
            p += chunk;
            n -= chunk;
            if (u->cur_have == u->cur_size) {
                wchar_t *path = u->cur_path;
                unsigned char *data = u->cur;
                u->cur_path = NULL;
                u->cur = NULL;
                if (!pool_push(u->pool, path, data, u->cur_size))
                    return pool_failed(u);
                if (!next_file(u))
                    return 0;
            }
        } else {
            _snprintf(u->err, sizeof u->err, "the payload has more data than its index lists");
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
    int ok = 0, frame_done = 0, pool_up = 0;
    pool *writers = (pool *)malloc(sizeof(pool));
    if (!in || !outbuf || !dctx || !writers) {
        _snprintf(err, errn, "out of memory");
        goto done;
    }
    if (!pool_start(writers)) {
        _snprintf(err, errn, "cannot start the writer threads (error %lu)", GetLastError());
        DeleteCriticalSection(&writers->cs);
        goto done;
    }
    pool_up = 1;
    u.pool = writers;
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
    if (!frame_done || u.out || u.cur || u.file_no != u.files || !u.idx_done || done_bytes != logical) {
        _snprintf(err, errn, "the payload ended early (%u of %u files, %llu of %llu bytes)", u.file_no, u.files,
                  done_bytes, logical);
        goto done;
    }
    pool_up = 0;
    if (!pool_finish(writers)) { /* every queued file written, or the first failure */
        _snprintf(err, errn, "%s", writers->err);
        goto done;
    }
    ok = 1;
done:
    if (pool_up)
        pool_finish(writers); /* after a failure: the writers skip what is left and stop */
    if (u.out)
        CloseHandle(u.out);
    free(u.cur_path);
    free(u.cur);
    free(writers);
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
