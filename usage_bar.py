"""
Usage — Windows tray app: Claude Code va agy (Google Antigravity CLI) limitlarini bir joyda ko'rsatadi.

macOS'dagi "usage-bar" (Swift) dasturining Windows uchun Python porti.
  * Tray ikonka: tashqi halqa + raqam = asosiy Claude akkauntining 5 soatlik limiti (% ishlatilgan).
  * Chap tugma: popover oyna (Claude kartalari, agy qatorlari).  O'ng tugma: menyu.

Ishga tushirish:   pythonw usage_bar.py
Tekshirish:        python usage_bar.py --check
Gmail akkauntlar: agy-acc (= python usage_bar.py acc ...), qo'llanma: AGY_AKKAUNTLAR.md

Hech qanday token diskka yoki logga yozilmaydi. Tarmoq: faqat api.anthropic.com (o'zingizning tokeningiz bilan).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

IS_WIN = sys.platform == "win32"
HOME = Path.home()
APP_NAME = "UsageBar"
USAGE_URL = os.environ.get("USAGE_BAR_API") or "https://api.anthropic.com/api/oauth/usage"
AGY_ACCOUNTS_DIR = HOME / ".agy-accounts"
CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010


def _config_path() -> Path:
    p = os.environ.get("USAGE_BAR_CONFIG")
    return Path(os.path.expanduser(p)) if p else HOME / ".config" / "usage-bar" / "config.json"


def _cache_path() -> Path:
    p = os.environ.get("USAGE_BAR_CACHE")
    if p:
        return Path(os.path.expanduser(p)) / "cache.json"
    base = os.environ.get("LOCALAPPDATA") if IS_WIN else None
    return (Path(base) if base else HOME / ".cache") / "usage-bar" / "cache.json"


CONFIG_PATH = _config_path()
CACHE_PATH = _cache_path()


def expand(p: str) -> str:
    return os.path.normpath(os.path.expandvars(os.path.expanduser(p)))


def same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.abspath(expand(a))) == os.path.normcase(os.path.abspath(expand(b)))


# ───────────────────────────── config ─────────────────────────────

def normalize_config(raw: dict) -> dict:
    cfg = {
        "refreshMinutes": int(raw.get("refreshMinutes") or 5),
        "menuBarAccount": raw.get("menuBarAccount"),
        "trayIcon": raw.get("trayIcon") or "number",
        "theme": raw.get("theme") or "auto",
        "agyPath": raw.get("agyPath"),
        "agyCredential": raw.get("agyCredential") or None,
        "claude": [],
        "agy": [],
        "quotaFile": raw.get("quotaFile"),
    }
    for c in raw.get("claude") or []:
        if not isinstance(c, dict) or not c.get("name") or not c.get("configDir"):
            raise ValueError('har bir "claude" yozuvida "name" va "configDir" bo\'lishi kerak')
        cfg["claude"].append({"name": str(c["name"]), "label": c.get("label") or None, "configDir": str(c["configDir"])})
    for a in raw.get("agy") or []:
        if not isinstance(a, dict) or not a.get("name"):
            raise ValueError('har bir "agy" yozuvida "name" bo\'lishi kerak')
        cfg["agy"].append({"name": str(a["name"]), "home": a.get("home") or None,
                           "enabled": a.get("enabled", True) is not False, "env": a.get("env") or None})
    return cfg


def load_config() -> tuple[dict, str | None]:
    if not CONFIG_PATH.exists():
        cfg = autodetect()
        save_config(cfg)
        return cfg, None
    try:
        return normalize_config(json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))), None
    except Exception as e:  # a broken file is reported, never overwritten
        return autodetect(), f"config.json xato: {e}"


def save_config(cfg: dict) -> None:
    out = {
        "refreshMinutes": cfg["refreshMinutes"],
        "menuBarAccount": cfg.get("menuBarAccount"),
        "trayIcon": cfg.get("trayIcon", "number"),
        "theme": cfg.get("theme", "auto"),
        "agyPath": cfg.get("agyPath"),
        **({"agyCredential": cfg["agyCredential"]} if cfg.get("agyCredential") else {}),
        "claude": [{k: v for k, v in c.items() if v is not None} for c in cfg["claude"]],
        "agy": [{k: v for k, v in a.items() if v is not None} for a in cfg["agy"]],
        "quotaFile": cfg.get("quotaFile"),
    }
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, CONFIG_PATH)


def _looks_like_claude_dir(p: Path) -> bool:
    return p.is_dir() and any((p / n).exists() for n in
                              ["settings.json", ".credentials.json", "projects", "sessions", "statsig", "todos", "CLAUDE.md"])


def autodetect() -> dict:
    cfg = normalize_config({})
    dirs = [HOME / ".claude"] if _looks_like_claude_dir(HOME / ".claude") else []
    try:
        dirs += sorted(p for p in HOME.iterdir() if p.name.startswith(".claude-") and _looks_like_claude_dir(p))
    except OSError:
        pass
    used: set[str] = set()
    for d in dirs:
        name = "main" if d.name == ".claude" else d.name[len(".claude-"):].lower()
        if not name or name in used:
            name = f"claude{len(used) + 1}"
        used.add(name)
        cfg["claude"].append({"name": name, "label": None, "configDir": "~/" + d.name})
    cfg["menuBarAccount"] = cfg["claude"][0]["name"] if cfg["claude"] else None

    if find_agy(cfg):   # on Windows this account takes over the login agy already has (see agy-acc)
        cfg["agy"].append({"name": "gmail1" if swap_mode_available() else "agy", "home": None, "enabled": True, "env": None})
    if AGY_ACCOUNTS_DIR.is_dir() and not swap_mode_available():
        for d in sorted(p for p in AGY_ACCOUNTS_DIR.iterdir() if p.is_dir()):
            cfg["agy"].append({"name": d.name, "home": "~/.agy-accounts/" + d.name, "enabled": True, "env": None})
    return cfg


def swap_mode_available() -> bool:
    return IS_WIN or bool(os.environ.get("USAGE_BAR_FAKE_CREDS"))


def is_swap_account(a: dict) -> bool:
    """On Windows every agy account without a "home" is a saved login (see "credential swap" below)."""
    return swap_mode_available() and not a.get("home")


# ───────────────────────────── finding binaries ─────────────────────────────

def _extra_dirs() -> list[Path]:
    dirs = [HOME / ".local" / "bin", HOME / ".bun" / "bin", HOME / ".antigravity" / "bin", HOME / ".claude" / "local"]
    if IS_WIN:
        for var, subs in (("APPDATA", ["npm"]),
                          ("LOCALAPPDATA", ["Programs\\Antigravity\\bin", "Programs\\agy", "Programs\\antigravity",
                                            "Microsoft\\WinGet\\Links", "Programs\\claude"])):
            base = os.environ.get(var)
            if base:
                dirs += [Path(base) / s for s in subs]
    else:
        dirs += [Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
    return dirs


def find_binary(name: str) -> str | None:
    hit = shutil.which(name)
    if hit:
        return hit
    exts = [".exe", ".cmd", ".bat"] if IS_WIN else [""]
    for d in _extra_dirs():
        for e in exts:
            p = d / (name + e)
            if p.is_file():
                return str(p)
    return None


def find_agy(cfg: dict) -> str | None:
    p = cfg.get("agyPath")
    if p and Path(expand(p)).is_file():
        return expand(p)
    return find_binary("agy")


# ───────────────────────────── cache ─────────────────────────────

def load_cache() -> dict:
    try:
        c = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        return {"claude": c.get("claude") or {}, "agy": c.get("agy") or {}}
    except Exception:
        return {"claude": {}, "agy": {}}


def save_cache(cache: dict) -> None:
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = CACHE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache), encoding="utf-8")
        os.replace(tmp, CACHE_PATH)
    except OSError:
        pass


def parse_iso(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.strip().replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ───────────────────────────── Claude ─────────────────────────────

def claude_token(acct: dict) -> tuple[str, str | None]:
    """('ok', token) | ('expired', None) | ('missing', None). Claude Code on Windows keeps it in <configDir>/.credentials.json."""
    f = Path(expand(acct["configDir"])) / ".credentials.json"
    try:
        j = json.loads(f.read_text(encoding="utf-8-sig"))
    except Exception:
        return "missing", None
    o = j.get("claudeAiOauth") or j
    tok = o.get("accessToken")
    if not tok:
        return "missing", None
    exp = o.get("expiresAt")
    if isinstance(exp, (int, float)) and exp / 1000 < time.time():
        return "expired", None
    return "ok", tok


def _window(d) -> dict | None:
    if not isinstance(d, dict) or d.get("utilization") is None:
        return None
    return {"used": float(d["utilization"]), "resets": parse_iso(d.get("resets_at"))}


def call_usage_api(token: str):
    req = urllib.request.Request(USAGE_URL, headers={
        "Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20", "User-Agent": "usage-bar-windows"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(r.read().decode("utf-8"))
            return "ok", (_window(j.get("five_hour")), _window(j.get("seven_day")))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            ra = e.headers.get("Retry-After")
            try:
                return "rate", float(ra) if ra else None
            except ValueError:
                return "rate", None
        if e.code in (401, 403):
            return "unauth", None
        return "fail", f"Usage API HTTP {e.code} qaytardi"
    except Exception as e:
        return "fail", f"Tarmoq xatosi: {getattr(e, 'reason', e)}"


def fetch_claude(acct: dict, prior: dict | None) -> dict:
    rec = dict(prior or {})
    now = time.time()
    rec["source"] = acct["configDir"]
    rec["lastAttempt"] = now
    state, tok = claude_token(acct)
    if state == "missing":
        rec["error"] = "Claude login topilmadi. Menyu → Claude akkauntlar → Kirish."
        return rec
    if state == "expired":
        rec["error"] = "Claude tokeni eskirgan. Shu akkauntda Claude Code'ni bir marta oching."
        return rec
    rec["lastAPICall"] = now
    kind, val = call_usage_api(tok)
    if kind == "ok":
        rec["five"], rec["week"] = val
        rec.update(fetchedAt=now, error=None, backoffUntil=None, backoffSecs=None)
    elif kind == "rate":
        secs = min(val, 6 * 3600) if val and val > 0 else min((rec.get("backoffSecs") or 450) * 2, 3600)
        rec.update(backoffSecs=secs, backoffUntil=now + secs, error="Anthropic limit (429). Oxirgi ma'lum raqamlar ko'rsatilmoqda.")
    elif kind == "unauth":
        rec["error"] = "Claude tokeni rad etildi. Shu akkauntda Claude Code'ga qayta kiring."
    else:
        rec["error"] = val
    return rec


# ───────────────────────────── agy ─────────────────────────────

EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x1b\x07]*(?:\x07|\x1b\\)")
PCT = re.compile(r"(\d+(?:\.\d+)?)\s*%")
ISO = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?")


def parse_agy(text: str) -> tuple[dict | None, dict | None]:
    """Rows look like `Group<TAB>Label<TAB>NN%<TAB>ISO-UTC` (NN = REMAINING %). Also accepts space/box-drawn tables.
    Returns (gemini, claude_gpt) groups as {"week": win, "five": win} with % USED."""
    groups = {"gemini": {}, "claude": {}}
    for line in ANSI.sub("", text).splitlines():
        cols = [c.strip() for c in re.split(r"\t|\s{2,}|[│|]", line) if c.strip()]
        if len(cols) < 3:
            continue
        g = None
        for c in (cols[0].lower(), cols[1].lower()):   # group column first, so "Gemini" in a Claude label doesn't win
            if "gemini" in c:
                g = "gemini"
            elif "claude" in c or "gpt" in c:
                g = "claude"
            if g:
                break
        if not g:
            continue
        # the value is the right-most % column; a % inside the label must not be taken
        pi = next((i for i in range(len(cols) - 1, 0, -1) if PCT.search(cols[i])), None)
        if pi is None:
            continue
        m = PCT.search(cols[pi])
        label = " ".join(cols[:pi]).lower()
        if re.search(r"week|7[- ]?day", label):
            win = "week"
        elif re.search(r"five|5[- ]?h|5[- ]?hour|5[- ]?soat", label):
            win = "five"
        else:
            continue
        iso = ISO.search(" ".join(cols[pi:]))   # reset time follows the value, never a date in the label
        rem = float(m.group(1))
        groups[g][win] = {"used": min(max(100 - rem, 0), 100), "resets": parse_iso(iso.group(0)) if iso else None}
    return groups["gemini"] or None, groups["claude"] or None


def agy_env(acct: dict) -> dict:
    env = dict(os.environ)
    home = acct.get("home")
    if home and not same_path(home, str(HOME)):
        h = expand(home)
        Path(h).mkdir(parents=True, exist_ok=True)
        env["HOME"] = h
        if IS_WIN:
            env["USERPROFILE"] = h   # Node/Go read the home folder from USERPROFILE on Windows
    for k, v in (acct.get("env") or {}).items():
        env[str(k)] = expand(str(v))
    return env


def run_capture(args: list[str], env: dict, timeout: float) -> tuple[str, bool, str | None]:
    """(merged output, timed_out, launch_error). No console window flashes on Windows."""
    kw = {}
    if IS_WIN:
        kw["creationflags"] = CREATE_NO_WINDOW
    try:
        p = subprocess.Popen(args, env=env, cwd=tempfile.gettempdir(), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **kw)
    except OSError as e:
        return "", False, str(e)
    try:
        out, _ = p.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        timed_out = True
        if IS_WIN:   # .cmd shims start grandchildren: kill the whole tree
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True, creationflags=CREATE_NO_WINDOW)
        else:
            p.kill()
        try:
            out, _ = p.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            out = b""
    return (out or b"").decode("utf-8", errors="replace"), timed_out, None


def internet_up(timeout: float = 3) -> bool:
    """Can we reach Google's token endpoint? Offline, agy can't refresh its token and opens a sign-in page in the
    browser (e.g. right after Windows starts, before Wi-Fi is up), so nothing is checked until this is true."""
    try:
        socket.create_connection(("oauth2.googleapis.com", 443), timeout=timeout).close()
        return True
    except OSError:
        return False


def fetch_agy(acct: dict, prior: dict | None, agy_bin: str | None) -> dict:
    rec = dict(prior or {})
    rec["source"] = acct.get("home")
    rec["lastAttempt"] = time.time()
    if not agy_bin:
        rec["error"] = "agy topilmadi. O'rnating yoki config.json'da \"agyPath\" ni yozing."
        return rec
    out, timed_out, err = run_capture([agy_bin, "-p", "/quota"], agy_env(acct), timeout=45)
    if err:
        rec["error"] = err
        return rec
    gem, cla = parse_agy(out)
    if gem or cla:
        rec.update(gemini=gem, claude=cla, fetchedAt=rec["lastAttempt"], needsLogin=False, error=None)
        m = EMAIL_RX.search(ANSI.sub("", out))
        if m:
            rec["outEmail"] = m.group(0)
        return rec
    low = out.lower()
    if any(k in low for k in ("authentication", "not signed in", "sign in", "not logged in", "log in", "login")):
        rec.update(needsLogin=True, error=None)
    elif timed_out:
        rec["error"] = "agy /quota javob bermadi (timeout)"
    else:
        tail = out.strip()
        rec["error"] = tail[-200:] if tail else "agy kvota ma'lumotini qaytarmadi"
    return rec


# ───────────────────────────── agy accounts on Windows (credential swap) ─────────────────────────────
#
# On Windows agy (and the Antigravity desktop app) keep ONE Google login in Credential Manager, generic
# credential "gemini:antigravity" — a different HOME does not give a different account. So every account's
# login is saved into its own Credential Manager item ("usage-bar/agy/<name>", still protected by Windows),
# and swapped into "gemini:antigravity" when that account is needed. Never use /logout inside agy for a saved
# account: it can revoke the refresh token. "acc new" only clears the local login.

SLOT_PREFIX = "usage-bar/agy/"
BACKUP_SLOT = "usage-bar/agy-backup"
STATE_PATH = CACHE_PATH.parent / "agy-accounts.json"


class CredStore:
    """Generic credentials: {"type", "user", "blob": bytes, "persist"}. Windows Credential Manager, or a JSON
    file when USAGE_BAR_FAKE_CREDS is set (tests on other systems)."""

    def __init__(self):
        self.fake = os.environ.get("USAGE_BAR_FAKE_CREDS")
        if not self.fake and IS_WIN:
            self._init_win()

    @property
    def available(self) -> bool:
        return bool(self.fake) or IS_WIN

    def _init_win(self):
        import ctypes
        from ctypes import wintypes as wt

        class FILETIME(ctypes.Structure):
            _fields_ = [("lo", wt.DWORD), ("hi", wt.DWORD)]

        class CREDENTIALW(ctypes.Structure):
            _fields_ = [("Flags", wt.DWORD), ("Type", wt.DWORD), ("TargetName", wt.LPWSTR), ("Comment", wt.LPWSTR),
                        ("LastWritten", FILETIME), ("CredentialBlobSize", wt.DWORD),
                        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wt.DWORD),
                        ("AttributeCount", wt.DWORD), ("Attributes", ctypes.c_void_p), ("TargetAlias", wt.LPWSTR),
                        ("UserName", wt.LPWSTR)]

        adv = ctypes.WinDLL("advapi32", use_last_error=True)
        PC = ctypes.POINTER(CREDENTIALW)
        adv.CredReadW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.POINTER(PC)]
        adv.CredReadW.restype = wt.BOOL
        adv.CredWriteW.argtypes = [PC, wt.DWORD]
        adv.CredWriteW.restype = wt.BOOL
        adv.CredDeleteW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD]
        adv.CredDeleteW.restype = wt.BOOL
        adv.CredFree.argtypes = [ctypes.c_void_p]
        self._ct, self._adv, self._C, self._PC = ctypes, adv, CREDENTIALW, PC

    def _fake_all(self) -> dict:
        try:
            return json.loads(Path(self.fake).read_text(encoding="utf-8"))
        except Exception:
            return {}

    def read(self, target: str) -> dict | None:
        if self.fake:
            c = self._fake_all().get(target)
            return None if c is None else {"type": 1, "user": c.get("user"), "blob": c["blob"].encode("latin-1"), "persist": 2}
        if not IS_WIN:
            return None
        ct = self._ct
        p = self._PC()
        if not self._adv.CredReadW(target, 1, 0, ct.byref(p)):   # CRED_TYPE_GENERIC
            return None
        try:
            c = p.contents
            return {"type": c.Type, "user": c.UserName, "persist": c.Persist or 2,
                    "blob": ct.string_at(c.CredentialBlob, c.CredentialBlobSize) if c.CredentialBlobSize else b""}
        finally:
            self._adv.CredFree(p)

    def write(self, target: str, cred: dict, comment: str | None = None) -> None:
        if self.fake:
            allc = self._fake_all()
            allc[target] = {"user": cred.get("user"), "blob": cred["blob"].decode("latin-1")}
            Path(self.fake).write_text(json.dumps(allc), encoding="utf-8")
            return
        ct = self._ct
        blob = cred["blob"]
        buf = (ct.c_ubyte * max(len(blob), 1)).from_buffer_copy(blob or b"\0")
        c = self._C()
        c.Type = 1
        c.TargetName = target
        c.Comment = comment
        c.CredentialBlobSize = len(blob)
        c.CredentialBlob = ct.cast(buf, ct.POINTER(ct.c_ubyte))
        c.Persist = cred.get("persist") or 2   # CRED_PERSIST_LOCAL_MACHINE
        c.UserName = cred.get("user")
        if not self._adv.CredWriteW(ct.byref(c), 0):
            raise OSError(f"CredWrite({target}) xatosi {ct.get_last_error()}")

    def delete(self, target: str) -> None:
        if self.fake:
            allc = self._fake_all()
            allc.pop(target, None)
            Path(self.fake).write_text(json.dumps(allc), encoding="utf-8")
        elif IS_WIN:
            self._adv.CredDeleteW(target, 1, 0)

    def enumerate(self, pattern: str) -> list[tuple[str, int, str | None]]:
        """(target, blob size, user) of credentials whose name matches e.g. "*gemini*". No secrets."""
        if self.fake:
            pat = pattern.strip("*").lower()
            return [(k, len(v["blob"]), v.get("user")) for k, v in self._fake_all().items() if pat in k.lower()]
        if not IS_WIN:
            return []
        ct = self._ct
        from ctypes import wintypes as wt
        PPC = ct.POINTER(self._PC)
        self._adv.CredEnumerateW.argtypes = [wt.LPCWSTR, wt.DWORD, ct.POINTER(wt.DWORD), ct.POINTER(PPC)]
        self._adv.CredEnumerateW.restype = wt.BOOL
        n, arr = wt.DWORD(), PPC()
        if not self._adv.CredEnumerateW(pattern, 0, ct.byref(n), ct.byref(arr)):
            return []
        try:
            return [(arr[i].contents.TargetName, arr[i].contents.CredentialBlobSize, arr[i].contents.UserName) for i in range(n.value)]
        finally:
            self._adv.CredFree(arr)


class CrossProcessLock:
    """Only one process at a time may swap the agy login (the tray app and the agy-acc command).
    Waits in short steps, so Ctrl+C works and a waiting command can say why it waits."""

    NAME = "Local\\UsageBarAgyCredential"

    def __init__(self):
        self._t = threading.RLock()
        self._h = None
        self._k32 = None

    def _kernel32(self):
        if self._k32 is None:
            import ctypes
            from ctypes import wintypes as wt
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
            k.CreateMutexW.restype = wt.HANDLE
            k.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
            k.WaitForSingleObject.restype = wt.DWORD
            k.ReleaseMutex.argtypes = [wt.HANDLE]
            k.CloseHandle.argtypes = [wt.HANDLE]
            self._k32 = k
        return self._k32

    def acquire(self, wait=True, notice=None, limit=300) -> bool:
        self._t.acquire()
        self._depth = getattr(self, "_depth", 0)
        if self._depth:   # this thread already holds it (e.g. "run" calls "use")
            self._depth += 1
            return True
        if not IS_WIN:
            self._depth = 1
            return True
        k = self._kernel32()
        h = k.CreateMutexW(None, False, self.NAME)
        r = k.WaitForSingleObject(h, 0)
        if r == 0x102:   # WAIT_TIMEOUT: someone else is swapping right now
            if not wait:
                k.CloseHandle(h)
                self._t.release()
                return False
            if notice:
                print(notice, flush=True)
            deadline = time.time() + limit
            try:
                while r == 0x102 and time.time() < deadline:
                    r = k.WaitForSingleObject(h, 250)
            except BaseException:
                k.CloseHandle(h)
                self._t.release()
                raise
            if r == 0x102:
                k.CloseHandle(h)
                self._t.release()
                raise TimeoutError("agy login band (boshqa jarayon ishlatyapti)")
        self._h = h
        self._depth = 1
        return True

    def release(self):
        self._depth -= 1
        if self._depth:
            self._t.release()
            return
        if IS_WIN and self._h:
            k = self._kernel32()
            k.ReleaseMutex(self._h)
            k.CloseHandle(self._h)
            self._h = None
        self._t.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()


CRED_LOCK = CrossProcessLock()


JWT = re.compile(r"eyJ[\w-]+\.(eyJ[\w-]+)\.[\w-]*")


def _blob_texts(b: bytes) -> list[str]:
    """Readable forms of a saved login: plain, UTF-16, go-keyring base64/hex wrappers, bare base64."""
    import base64
    import binascii
    texts = [b.decode("utf-8", "ignore")]
    if b.count(b"\0") > len(b) // 4:
        texts.append(b.decode("utf-16-le", "ignore"))
    for t in list(texts):
        t = t.strip().strip("\0")
        for pre, dec in (("go-keyring-base64:", base64.b64decode), ("go-keyring-encoded:", binascii.unhexlify)):
            if t.startswith(pre):
                try:
                    texts.append(dec(t[len(pre):]).decode("utf-8", "ignore"))
                except Exception:
                    pass
        if re.fullmatch(r"[A-Za-z0-9+/=_-]{40,}", t):
            try:
                texts.append(base64.b64decode(t + "=" * (-len(t) % 4), altchars=b"-_" if "-" in t or "_" in t else None)
                             .decode("utf-8", "ignore"))
            except Exception:
                pass
    return texts


def describe_cred(cred: dict | None) -> str:
    """Shape of a saved login for troubleshooting: size, encoding, JSON key names, token kinds. Never values."""
    if cred is None:
        return "yo'q"
    b = cred.get("blob") or b""
    utf16 = b.count(b"\0") > len(b) // 4
    texts = _blob_texts(b)
    t = texts[-1]
    parts = [f"{len(b)} bayt", "utf-16" if utf16 else "utf-8"]
    m = re.match(r"\s*(go-keyring-[a-z0-9]+:)", texts[1 if utf16 else 0])
    if m:
        parts.append(m.group(1))
    elif len(texts) > (2 if utf16 else 1):
        parts.append("base64")
    try:
        j = json.loads(t)
        def keys(o, pre=""):
            out = []
            if isinstance(o, dict):
                for k, v in o.items():
                    out.append(pre + k)
                    out += keys(v, pre + k + ".")
            return out
        parts.append("json kalitlari: " + ", ".join(keys(j)[:25]))
    except Exception:
        parts.append("json emas")
    parts.append(f"JWT: {len(JWT.findall(t))}")
    for label, rx in (("ya29 access", r"ya29\.[\w-]+"), ("1// refresh", r"1//[\w-]+")):
        if re.search(rx, t):
            parts.append(label)
    ident = cred_identity(cred)
    parts.append(f"email: {ident or 'topilmadi'}")
    parts.append("refresh-kalit: " + ("bor" if refresh_key(cred) else "yo'q"))
    return " · ".join(parts)


def cred_identity(cred: dict | None) -> str | None:
    """Google account e-mail (or subject) from the id_token inside agy's saved login, if it can be read."""
    if not cred or not cred.get("blob"):
        return None
    import base64
    texts = _blob_texts(cred["blob"])
    for t in texts:
        for m in JWT.finditer(t):
            seg = m.group(1)
            try:
                payload = json.loads(base64.urlsafe_b64decode(seg + "=" * (-len(seg) % 4)))
            except Exception:
                continue
            ident = payload.get("email") or payload.get("sub")
            if ident:
                return str(ident)
        m = re.search(r'"email"\s*:\s*"([^"]+@[^"]+)"', t)
        if m:
            return m.group(1)
    return None


def refresh_key(cred: dict | None) -> str | None:
    """Fingerprint of the Google refresh token inside a saved login. Unlike the access token (and the id_token,
    which a refreshed login may no longer carry) it stays the same when agy refreshes, so it identifies the account."""
    if not cred or not cred.get("blob"):
        return None
    import hashlib
    for t in _blob_texts(cred["blob"]):
        found = None
        try:
            stack = [json.loads(t)]
            while stack and not found:
                o = stack.pop()
                if isinstance(o, dict):
                    for k, v in o.items():
                        if isinstance(v, str) and k.replace("_", "").lower() == "refreshtoken" and v:
                            found = v
                            break
                        stack.append(v)
                elif isinstance(o, list):
                    stack.extend(o)
        except Exception:
            pass
        if not found:
            m = re.search(r"1//[\w-]{20,}", t)
            found = m.group(0) if m else None
        if found:
            return hashlib.sha256(found.encode()).hexdigest()[:16]
    return None


def same_login(a: dict | None, b: dict | None) -> bool:
    if not a or not b:
        return False
    if a["blob"] == b["blob"]:
        return True
    ra, rb = refresh_key(a), refresh_key(b)
    if ra and rb:
        return ra == rb
    ia, ib = cred_identity(a), cred_identity(b)
    return bool(ia and ia == ib)


class AgyAccounts:
    """Saved agy logins and which one is active in "gemini:antigravity"."""

    def __init__(self, cfg: dict):
        self.target = cfg.get("agyCredential") or "gemini:antigravity"
        self.cs = CredStore()

    # state: which saved account is currently in the shared credential
    @staticmethod
    def _state() -> dict:
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def _save_state(st: dict) -> None:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(st, indent=1), encoding="utf-8")

    def active(self) -> str | None:
        return self._state().get("active")

    def set_active(self, name: str | None) -> None:
        st = self._state()
        st["active"] = name
        self._save_state(st)

    def set_email(self, name: str, email: str | None) -> None:
        """The gmail of an account, for logins that don't carry it (typed by the user or seen in agy output)."""
        st = self._state()
        emails = st.setdefault("emails", {})
        if email:
            emails[name] = email
        else:
            emails.pop(name, None)
        self._save_state(st)

    def email(self, name: str, slot: dict | None = None) -> str | None:
        if slot is None:
            slot = self.cs.read(SLOT_PREFIX + name)
        known = self._state().get("emails", {}).get(name)
        mail = cred_identity(slot)
        if mail and not known:
            self.set_email(name, mail)
        return mail or known

    def has(self, name: str) -> bool:
        return self.cs.read(SLOT_PREFIX + name) is not None

    def current(self) -> dict | None:
        return self.cs.read(self.target)

    def save_slot(self, name: str, cred: dict) -> None:
        mail = cred_identity(cred)
        if mail and not self._state().get("emails", {}).get(name):
            self.set_email(name, mail)   # a refreshed login may drop the id_token: remember the gmail now
        self.cs.write(SLOT_PREFIX + name, cred, f"usage-bar: agy account {name}")

    def matching(self, cred: dict | None) -> str | None:
        """Name of the saved account whose login is exactly `cred` (None if unknown)."""
        if not cred:
            return None
        for n in self.names():
            if same_login(self.cs.read(SLOT_PREFIX + n), cred):
                return n
        return None

    def names(self) -> list[str]:
        cfg, _ = load_config()
        return [a["name"] for a in cfg["agy"] if not a.get("home")]

    def recover(self) -> None:
        """A crash in the middle of a swap leaves the user's login in the backup item: put it back."""
        b = self.cs.read(BACKUP_SLOT)
        if b is not None:
            if b["blob"] == b"<none>":
                self.cs.delete(self.target)
            else:
                self.cs.write(self.target, b)
            self.cs.delete(BACKUP_SLOT)

    def sync_active(self) -> None:
        """agy refreshes its token now and then: keep the active account's saved copy current."""
        cur = self.current()
        who = self.matching(cur)
        if who:   # only when the current login is provably that account (never overwrite with someone else)
            self.save_slot(who, cur)
            self.set_active(who)

    def swap_in(self, name: str) -> dict | None:
        """Puts `name` into the shared credential; returns what was there (to restore with swap_out)."""
        prev = self.current()
        self.cs.write(BACKUP_SLOT, prev or {"type": 1, "user": None, "blob": b"<none>", "persist": 2})
        self.cs.write(self.target, self.cs.read(SLOT_PREFIX + name))
        return prev

    def swap_out(self, name: str, prev: dict | None) -> None:
        """Saves `name`'s (possibly refreshed) login back to its slot and restores the previous one."""
        now = self.current()
        if now and (same_login(now, self.cs.read(SLOT_PREFIX + name)) or not cred_identity(now)):
            self.save_slot(name, now)
        if prev:
            self.cs.write(self.target, prev)
        else:
            self.cs.delete(self.target)
        self.cs.delete(BACKUP_SLOT)


def agy_running() -> bool:
    """agy or the Antigravity desktop app is open: they hold the login in memory and write it back on refresh."""
    if not IS_WIN:
        return bool(os.environ.get("USAGE_BAR_FAKE_AGY_RUNNING"))
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10,
                             creationflags=CREATE_NO_WINDOW).stdout.lower()
    except Exception:
        return False
    return any(f'"{n}"' in out for n in ("agy.exe", "antigravity.exe"))


def fetch_agy_swapped(accounts: list[dict], priors: dict, agy_bin: str | None, cfg: dict) -> dict:
    """Quota for saved (credential-swap) accounts, one after another. Accounts other than the active one are
    skipped while agy / Antigravity is open, so a running session is never disturbed."""
    out = {}
    acc = AgyAccounts(cfg)
    if not CRED_LOCK.acquire(wait=False):   # agy-acc run/use holds it: check again next round
        return out
    try:
        acc.recover()
        acc.sync_active()
        active = acc.matching(acc.current())
        busy = None
        for a in accounts:
            n = a["name"]
            prior = priors.get(n.lower())
            cur = acc.current()
            if not acc.has(n) and cur and not acc.matching(cur):
                acc.save_slot(n, cur)   # first run: the login agy already has belongs to this account
                acc.set_active(n)
                active = n
            if not acc.has(n):
                rec = dict(prior or {})
                rec.update(source=None, lastAttempt=time.time(), needsLogin=True,
                           error=None)
                out[n.lower()] = rec
                continue
            if n == active:
                out[n.lower()] = fetch_agy(a, prior, agy_bin)
                acc.sync_active()
                continue
            if busy is None:
                busy = agy_running()
            if busy:
                rec = dict(prior or {})
                rec.update(source=None, lastAttempt=time.time() - 9 * 60,   # try again in about a minute
                           error="agy / Antigravity ochiq — bu akkaunt ular yopilganda yangilanadi.")
                out[n.lower()] = rec
                continue
            prev = acc.swap_in(n)
            try:
                out[n.lower()] = fetch_agy(a, prior, agy_bin)
            finally:
                acc.swap_out(n, prev)
        for a in accounts:   # which gmail each account is, for the popover
            r = out.get(a["name"].lower())
            if r is not None:
                r["email"] = acc.email(a["name"]) or r.get("outEmail") or r.get("email")
                if r.get("outEmail") and not acc.email(a["name"]):
                    acc.set_email(a["name"], r["outEmail"])
    finally:
        CRED_LOCK.release()
    return out


def python_console_exe() -> str:
    exe = sys.executable
    if exe.lower().endswith("pythonw.exe"):
        c = exe[:-len("pythonw.exe")] + "python.exe"
        if os.path.exists(c):
            return c
    return exe


# ───────────────────────────── agy-acc command line ─────────────────────────────

ACC_HELP = """\
agy-acc — bir nechta Google (gmail) akkauntni agy uchun boshqarish

  agy-acc list              saqlangan akkauntlar (* = hozir agy ishlatayotgani)
  agy-acc save NOM          hozir agy'da kirilgan akkauntni NOM nomi bilan saqlash
  agy-acc add NOM           yangi gmail qo'shish: agy ochiladi, kirasiz, /quit — avtomatik saqlanadi
  agy-acc use NOM           agy (va Antigravity) uchun NOM akkauntiga o'tish
  agy-acc open NOM          NOM ga o'tib, agy'ni ochish  (qisqasi: shunchaki  NOM  deb yozing, masalan  agy1)
  agy-acc login NOM         NOM akkauntiga qayta kirish (token eskirgan bo'lsa)
  agy-acc rename ESKI YANGI akkaunt nomini o'zgartirish
  agy-acc email NOM GMAIL   akkaunt qaysi gmail ekanini yozib qo'yish (ro'yxatda ko'rinmasa)
  agy-acc remove NOM        saqlangan akkauntni o'chirish
  agy-acc current           hozirgi akkaunt
  agy-acc quota [--json]    har bir akkaunt limiti (% ishlatilgan)
  agy-acc run "vazifa"      vazifani agy'ga berish (joriy papkada fayllarni o'zgartira oladi): limiti ko'p qolgan
                            gmail o'zi tanlanadi (batafsil: run --help)
  agy-acc doctor            muammoni aniqlash uchun loginlar tuzilishi (tokenlarsiz)

  --force                   agy ochiq bo'lsa ham bajarish (tavsiya etilmaydi)

Eslatma: saqlangan akkaunt uchun agy ichida /logout QILMANG — token bekor bo'lib qolishi mumkin.
"""


SHORTCUT_MARK = "rem usage-bar agy shortcut"
APP_DIR = Path(os.path.abspath(__file__)).parent


def sync_shortcuts() -> None:
    """agy1.bat, agy2.bat… next to agy-acc.bat (that folder is on PATH): typing the account name opens agy with it."""
    if not IS_WIN and not os.environ.get("USAGE_BAR_FAKE_CREDS"):
        return
    cfg, err = load_config()
    if err:
        return
    names = {a["name"] for a in cfg["agy"] if is_swap_account(a) and re.fullmatch(r"[\w.-]{1,40}", a["name"])}
    for f in APP_DIR.glob("*.bat"):   # drop shortcuts of removed / renamed accounts
        try:
            if SHORTCUT_MARK in f.read_text(encoding="utf-8", errors="ignore") and f.stem not in names:
                f.unlink()
        except OSError:
            pass
    for n in names:
        f = APP_DIR / f"{n}.bat"
        if n.lower() in ("agy", "agy-acc", "start", "check", "install") or (f.exists() and SHORTCUT_MARK not in f.read_text(encoding="utf-8", errors="ignore")):
            continue   # never shadow agy itself or overwrite a file that isn't ours
        try:
            f.write_text(f"@echo off\r\n{SHORTCUT_MARK}\r\ncall \"%~dp0agy-acc.bat\" open {n} %*\r\n", encoding="utf-8")
        except OSError:
            pass


def _ensure_config_account(name: str) -> None:
    cfg, err = load_config()
    if err:
        return
    if not any(a["name"].lower() == name.lower() for a in cfg["agy"]):
        cfg["agy"].append({"name": name, "home": None, "enabled": True, "env": None})
        save_config(cfg)


def _run_agy_interactive(cfg: dict) -> int:
    agy = find_agy(cfg)
    if not agy:
        print("agy topilmadi. O'rnating yoki config.json'da \"agyPath\" ni yozing.")
        return 1
    return subprocess.call([agy], cwd=tempfile.gettempdir())


# ───────────────────────────── agy-acc quota / run (also used by the Claude Code skill) ─────────────────────────────

EXHAUSTED_RX = re.compile(r"resource[_ ]exhausted|quota (?:exceeded|exhausted|reached)|out of quota|"
                          r"usage limit|rate[- ]limit|limit (?:reached|exceeded)|\b429\b", re.I)
GROUPS = {"gemini": "gemini", "claude": "claude", "gpt": "claude"}


def _used(g: dict | None) -> float | None:
    vals = [w["used"] for w in ((g or {}).get("five"), (g or {}).get("week")) if w]
    return max(vals) if vals else None


def agy_quota_rows(refresh: bool = False, max_age: float | None = None) -> list[dict]:
    """Per-account agy quota (% used) from the tray's cache. Checks again: everything (refresh), only numbers older
    than max_age seconds, or otherwise whatever is due on the normal schedule. Checking means running agy per account."""
    st = Store()
    if refresh:
        st.refresh(force=True, wait=True, agy_only=True)
    else:
        st.refresh(wait=True, agy_only=True, agy_max_age=max_age)
    st.load()
    active = AgyAccounts(st.config).active()

    def win(w):
        return None if not w else {"used": round(w["used"]), "resets": fmt_reset(w["resets"]) if w["resets"] else None}

    rows = []
    for a in st.view["agy"]:
        rows.append({
            "name": a["id"], "email": a.get("email"), "active": a["id"] == active, "enabled": a["enabled"],
            "needsLogin": a["needsLogin"], "error": a["error"],
            "gemini": {"five": win((a["gemini"] or {}).get("five")), "week": win((a["gemini"] or {}).get("week"))},
            "claude": {"five": win((a["claude"] or {}).get("five")), "week": win((a["claude"] or {}).get("week"))},
            "geminiUsed": _used(a["gemini"]), "claudeUsed": _used(a["claude"]),
        })
    return rows


def cmd_quota(args: list[str]) -> int:
    rows = agy_quota_rows(refresh="--refresh" in args)
    if "--json" in args:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print("agy akkaunt yo'q. Qo'shish: agy-acc add NOM")
        return 1

    def cell(w):
        return "–" if not w else f"{w['used']}%"
    print(f"   {'NOM':<8} {'GMAIL':<34} {'GEMINI 5s/hafta':<17} {'CLAUDE&GPT 5s/hafta':<20} HOLAT")
    for r in rows:
        state = ("o'chiq" if not r["enabled"] else "kirish kerak" if r["needsLogin"] else (r["error"] or "ok"))[:40]
        g, c = r["gemini"], r["claude"]
        print(f" {'*' if r['active'] else ' '} {r['name']:<8} {(r['email'] or '')[:34]:<34} "
              f"{cell(g['five']) + ' / ' + cell(g['week']):<17} {cell(c['five']) + ' / ' + cell(c['week']):<20} {state}")
    return 0


def _run_streaming(cmd: list[str]) -> tuple[int, str]:
    """Runs agy, passing its output through as it comes; returns (exit code, last lines)."""
    from collections import deque
    tail: deque = deque(maxlen=40)
    p = subprocess.Popen(cmd, cwd=os.getcwd(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    for raw in iter(p.stdout.readline, b""):
        line = raw.decode("utf-8", errors="replace")
        sys.stdout.write(line)
        sys.stdout.flush()
        tail.append(ANSI.sub("", line))
    return p.wait(), "".join(tail)


RUN_HELP = """\
agy-acc run — vazifani agy'ga berish; limiti eng ko'p qolgan gmail o'zi tanlanadi

  agy-acc run "savol yoki vazifa"
  agy-acc run --group claude "..."     Claude & GPT limitiga qarab tanlash (standart: gemini)
  agy-acc run --account agy2 "..."     aniq akkaunt bilan
  agy-acc run --file prompt.txt        vazifani fayldan o'qish
  agy-acc run --include a.py:10-80 "…" fayl (yoki satrlar) mazmunini vazifaga qo'shish; bir necha marta berish mumkin
  agy-acc run --read-only "..."        agy'ga hech qanday vosita (fayl o'qish/yozish, buyruq) ruxsat etilmaydi —
                                        faqat javob beradi; kodni --include bilan bering
  agy-acc run --refresh "..."          avval hamma akkaunt limitini qayta tekshirish

agy JORIY papkada ishlaydi va standart holatda unga hamma ruxsat beriladi (--dangerously-skip-permissions):
fayllarni o'qiydi, yaratadi, tahrirlaydi, o'chiradi va buyruqlar ishga tushiradi. Natijani git diff bilan tekshiring.
Limit tugagani ko'rinsa, keyingi akkaunt bilan qayta urinadi.
"""


def cmd_run(args: list[str]) -> int:
    group, account, refresh, prompt_file, rest, includes, read_only = "gemini", None, False, None, [], [], False
    it = iter(args)
    for x in it:
        if x == "--group":
            group = GROUPS.get(next(it, "").lower(), "")
        elif x == "--account":
            account = next(it, None)
        elif x == "--file":
            prompt_file = next(it, None)
        elif x == "--refresh":
            refresh = True
        elif x == "--include":
            includes.append(next(it, ""))
        elif x == "--read-only":
            read_only = True
        elif x in ("-h", "--help"):
            print(RUN_HELP)
            return 0
        else:
            rest.append(x)
    if not group:
        print("--group: gemini yoki claude")
        return 2
    prompt = Path(prompt_file).read_text(encoding="utf-8-sig") if prompt_file else " ".join(rest)
    if not prompt.strip():
        print(RUN_HELP)
        return 2
    # with --read-only agy -p cannot use any tool, so the code to look at goes into the prompt itself
    for spec in includes:
        m = re.fullmatch(r"(.+?)(?::(\d+)(?:-(\d+))?)?", spec.strip())
        path, a, b = m.group(1), m.group(2), m.group(3)
        try:
            lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError as e:
            print(f"--include {spec}: o'qib bo'lmadi ({e})")
            return 2
        lo = int(a) if a else 1
        hi = int(b) if b else (lo if a else len(lines))
        chunk = "\n".join(lines[lo - 1:hi])
        where = f"{path} (lines {lo}-{min(hi, len(lines))})" if a else path
        prompt += f"\n\n### {where}\n```\n{chunk}\n```"
    if len(prompt) > 30000:
        print(f"Vazifa juda uzun ({len(prompt)} belgi, Windows chegarasi ~30000). --include'da satrlar oralig'ini toraytiring.")
        return 2
    cfg, _ = load_config()
    agy = find_agy(cfg)
    if not agy:
        print("agy topilmadi. O'rnating yoki config.json'da \"agyPath\" ni yozing.")
        return 2
    if agy.lower().endswith((".cmd", ".bat")) and re.search(r'[&|<>^%"\r\n]', prompt):
        print("agy .cmd orqali ishlayapti — vazifada & | < > ^ % \" yoki yangi qator bo'lmasin "
              "(yoki config.json'da \"agyPath\" ni agy.exe ga yo'naltiring).")
        return 2

    if not internet_up():   # offline agy can't refresh its token and opens a Google sign-in page instead
        print("Internet yo'q — agy ishga tushirilmadi. Ulanishni tekshirib, qayta urinib ko'ring.")
        return 5
    started = time.time()
    rows = agy_quota_rows(refresh, max_age=30 * 60)   # the tray keeps these fresh; a stale pick is fixed by the fallback
    usable = [r for r in rows if r["enabled"] and not r["needsLogin"]]
    if account:
        order = [r for r in usable if r["name"].lower() == account.lower()]
        if not order:
            print(f"'{account}' ishlatib bo'lmaydi (yo'q, o'chiq yoki kirish kerak). Ro'yxat: agy-acc quota")
            return 2
    else:
        key = group + "Used"
        order = sorted((r for r in usable if (r[key] if r[key] is not None else 0) < 99.5),
                       key=lambda r: (r[key] if r[key] is not None else 50, not r["active"]))
    if not order:
        print(f"Hamma akkauntlarda {group} limiti tugagan. Holat: agy-acc quota")
        return 3

    acc = AgyAccounts(cfg)
    try:
        CRED_LOCK.acquire(notice="Tray dasturi hozir agy kvotasini tekshiryapti — kutyapman…")
    except TimeoutError as e:
        print(e)
        return 4
    try:
        running = agy_running()
        tried = []
        for r in order:
            name = r["name"]
            current = acc.matching(acc.current())
            if name != current:
                if running:   # an open agy/Antigravity holds the login: only the current account can be used
                    if current and any(o["name"] == current for o in order) and current not in tried:
                        name = current
                    else:
                        print("agy yoki Antigravity ilovasi ochiq, hozirgi akkauntni esa ishlatib bo'lmaydi. Ularni yoping va qayta urinib ko'ring.")
                        return 4
                elif cmd_acc(["use", name]) != 0:
                    continue
            tried.append(name)
            sys.stdout.flush()
            email = next((o["email"] for o in rows if o["name"] == name), None)
            print(f"[agy-acc] {name}" + (f" ({email})" if email else "") + " bilan bajarilmoqda…", file=sys.stderr, flush=True)
            t0 = time.time()
            # agy works as a coding subagent: -p can't ask for permission, so tools are pre-approved unless --read-only
            rc, tail = _run_streaming([agy] + ([] if read_only else ["--dangerously-skip-permissions"]) + ["-p", prompt])
            print(f"[agy-acc] {time.time() - t0:.0f} s (agy) · jami {time.time() - started:.0f} s", file=sys.stderr, flush=True)
            if rc != 0 and EXHAUSTED_RX.search(tail):
                print(f"\n[agy-acc] {name} limiti tugadi — keyingi akkauntga o'tyapman.", file=sys.stderr, flush=True)
                if running:
                    break
                continue
            return rc
        print(f"[agy-acc] Ishlatish mumkin bo'lgan akkaunt qolmadi ({', '.join(tried) or '—'}). Holat: agy-acc quota", file=sys.stderr)
        return 3
    finally:
        CRED_LOCK.release()


def cmd_acc(args: list[str]) -> int:
    force = "--force" in args
    args = [a for a in args if a != "--force"]
    if not args or args[0] in ("-h", "--help", "help"):
        print(ACC_HELP)
        return 0
    if args[0] == "quota":
        return cmd_quota(args[1:])
    if args[0] == "run":
        return cmd_run(args[1:])
    if args[0] == "shortcuts":
        sync_shortcuts()
        print("Qisqa buyruqlar yangilandi: " + ", ".join(sorted(f.stem for f in APP_DIR.glob("*.bat")
                                                            if SHORTCUT_MARK in f.read_text(encoding="utf-8", errors="ignore"))))
        return 0
    if args[0] == "open":   # switch, then open agy interactively (what the agy1/agy2 shortcuts run)
        if len(args) < 2:
            print("Ishlatish:  agy-acc open NOM")
            return 1
        rc = cmd_acc(["use", args[1]] + (["--force"] if force else []))
        if rc != 0:
            return rc
        cfg, _ = load_config()
        agy = find_agy(cfg)
        if not agy:
            print("agy topilmadi.")
            return 1
        print(f">>> agy ochilmoqda ({args[1]}). Chiqish: /quit", flush=True)
        try:
            rc = subprocess.call([agy] + args[2:])
        except OSError as e:
            print(f"agy ishga tushmadi: {e}  ({agy})")
            return 1
        if rc != 0:
            print(f"agy {rc} kodi bilan yopildi ({agy}).")
        return rc
    cfg, _ = load_config()
    acc = AgyAccounts(cfg)
    if not acc.cs.available:
        print("Bu buyruq faqat Windows uchun (agy logini Credential Manager'da).")
        return 1
    op, name = args[0], (args[1] if len(args) > 1 else None)
    if op in ("save", "add", "use", "login", "remove", "rename", "email") and not name:
        print(f"Nom kerak:  agy-acc {op} NOM")
        return 1
    if name and not re.fullmatch(r"[\w.@+-]{1,40}", name):
        print("Nom faqat harf, raqam va . _ - @ + belgilaridan iborat bo'lsin.")
        return 1

    if op == "doctor":
        print(f"agy:        {find_agy(cfg) or 'TOPILMADI'}")
        print(f"faol login: {acc.target} → {describe_cred(acc.current())}")
        for n in acc.names():
            print(f"{n:<11} → {describe_cred(acc.cs.read(SLOT_PREFIX + n))}"
                  + (f" · yozilgan email: {acc.email(n)}" if acc.email(n) else ""))
        seen = set()
        print("\nCredential Manager'dagi tegishli yozuvlar:")
        for pat in ("*gemini*", "*antigravity*", "*agy*", "*google*"):
            for tgt, size, user in acc.cs.enumerate(pat):
                if tgt not in seen:
                    seen.add(tgt)
                    print(f"  {tgt}  ({size} bayt, user={user})")
        return 0

    if op in ("list", "current"):   # read-only: never wait for the tray
        if CRED_LOCK.acquire(wait=False):
            try:
                acc.recover()
                acc.sync_active()
            finally:
                CRED_LOCK.release()
        cur = acc.current()
        active = acc.matching(cur)
        names = acc.names()
        if True:
            who = active
            if op == "current":
                print(who or ("(saqlanmagan akkaunt)" if cur else "(hech kim kirmagan)"))
                return 0
            if not names:
                print("Saqlangan akkaunt yo'q. Boshlash:  agy-acc save NOM  (hozirgi login)  yoki  agy-acc add NOM")
            for n in names:
                mark = "*" if n == who else " "
                slot = acc.cs.read(SLOT_PREFIX + n)
                email = acc.email(n, slot)
                print(f" {mark} {n:<12}" + (f" {email}" if email else "")
                      + ("" if slot else "   (login saqlanmagan — agy-acc login " + n + ")"))
            if cur and not who:
                print("\nagy'da hozir saqlanmagan akkaunt bor. Saqlash:  agy-acc save NOM")
            return 0

    try:
        CRED_LOCK.acquire(notice="Tray dasturi hozir agy kvotasini tekshiryapti — tugashini kutyapman (Ctrl+C — bekor qilish)…")
    except TimeoutError as e:
        print(e)
        return 1
    try:
        acc.recover()
        acc.sync_active()
        cur = acc.current()
        active = acc.matching(cur)
        names = acc.names()
        rc = _acc_change(op, name, args, force, acc, cfg, cur, active, names)
        if op in ("save", "add", "login", "rename", "remove"):
            sync_shortcuts()
        return rc
    finally:
        CRED_LOCK.release()


def _acc_change(op, name, args, force, acc, cfg, cur, active, names) -> int:
    if True:

        if op == "save":
            if not cur:
                print("agy'da hech kim kirmagan. Avval `agy` ni oching, Google bilan kiring, /quit — so'ng qayta urinib ko'ring.")
                return 1
            other = acc.matching(cur)
            if other and other != name and not force:
                print(f"Bu login allaqachon '{other}' nomi bilan saqlangan.\n"
                      f"Nomini o'zgartirish uchun:  agy-acc rename {other} {name}")
                return 1
            acc.save_slot(name, cur)
            acc.set_active(name)
            _ensure_config_account(name)
            email = cred_identity(cur)
            print(f"Saqlandi: {name}" + (f" ({email})" if email else "") + " — hozir faol")
            return 0

        if op == "rename":
            new = args[2] if len(args) > 2 else None
            if not new or not re.fullmatch(r"[\w.@+-]{1,40}", new):
                print("Ishlatish:  agy-acc rename ESKI YANGI")
                return 1
            slot = acc.cs.read(SLOT_PREFIX + name)
            if not slot:
                print(f"'{name}' saqlanmagan. Ro'yxat: agy-acc list")
                return 1
            if acc.has(new):
                print(f"'{new}' nomi band.")
                return 1
            acc.save_slot(new, slot)
            acc.cs.delete(SLOT_PREFIX + name)
            if acc.active() == name:
                acc.set_active(new)
            old_mail = acc._state().get("emails", {}).get(name)
            if old_mail:
                acc.set_email(new, old_mail)
                acc.set_email(name, None)
            cfg2, err = load_config()
            if not err:
                for a in cfg2["agy"]:
                    if a["name"] == name:
                        a["name"] = new
                if not any(a["name"] == new for a in cfg2["agy"]):
                    cfg2["agy"].append({"name": new, "home": None, "enabled": True, "env": None})
                save_config(cfg2)
            print(f"'{name}' → '{new}' qilib o'zgartirildi.")
            return 0

        if op == "email":
            mail = args[2] if len(args) > 2 else ""
            if not acc.has(name):
                print(f"'{name}' saqlanmagan. Ro'yxat: agy-acc list")
                return 1
            if not EMAIL_RX.fullmatch(mail):
                print("Ishlatish:  agy-acc email NOM siz@gmail.com")
                return 1
            acc.set_email(name, mail)
            print(f"{name} → {mail}")
            return 0

        if op == "remove":
            acc.set_email(name, None)
            acc.cs.delete(SLOT_PREFIX + name)
            if active == name:
                acc.set_active(None)
            cfg2, err = load_config()
            if not err:
                cfg2["agy"] = [a for a in cfg2["agy"] if a["name"] != name]
                save_config(cfg2)
            print(f"O'chirildi: {name}  (agy'dagi hozirgi login o'zgarmadi)")
            return 0

        running = agy_running()
        if running and not force:
            print("agy yoki Antigravity ilovasi ochiq. Avval ularni yoping (agy'da /quit), so'ng qayta urinib ko'ring.")
            return 1
        if cur and not active and not force:
            print("agy'dagi hozirgi login hech qayerda saqlanmagan — yo'qolmasligi uchun avval uni saqlang:\n"
                  "  agy-acc save NOM\n(yoki --force bilan davom eting)")
            return 1

        if op == "use":
            if not acc.has(name):
                print(f"'{name}' saqlanmagan. Ro'yxat: agy-acc list")
                return 1
            acc.cs.write(acc.target, acc.cs.read(SLOT_PREFIX + name))
            acc.set_active(name)
            _ensure_config_account(name)
            print(f"Endi agy '{name}' akkauntidan foydalanadi. (Antigravity ilovasi ham shu akkauntda bo'ladi.)")
            return 0

        if op in ("add", "login"):
            if op == "add" and acc.has(name):
                print(f"'{name}' allaqachon bor. Qayta kirish uchun:  agy-acc login {name}")
                return 1
            prev_name = active
            acc.cs.write(BACKUP_SLOT, cur or {"type": 1, "user": None, "blob": b"<none>", "persist": 2})
            acc.cs.delete(acc.target)   # local logout only: the saved tokens stay valid
            print(f"\n>>> agy ochilmoqda. '{name}' uchun Google akkaunt bilan kiring, so'ng /quit yozing.\n")
            _run_agy_interactive(cfg)
            new = acc.current()
            if not new:
                print("Kirilmadi — hech narsa o'zgarmadi.")
                acc.recover()
                return 1
            dup = acc.matching(new)
            if dup and dup != name:
                print(f"Bu gmail allaqachon '{dup}' nomi bilan saqlangan — boshqa Google akkaunt bilan kiring.")
                acc.recover()
                return 1
            acc.save_slot(name, new)
            acc.cs.delete(BACKUP_SLOT)
            acc.set_active(name)
            _ensure_config_account(name)
            email = cred_identity(new)
            if not email:
                try:
                    typed = input("\nQaysi gmail bilan kirdingiz? (agy bannerida ko'ringan; Enter — o'tkazib yuborish): ").strip()
                except EOFError:
                    typed = ""
                if EMAIL_RX.fullmatch(typed):
                    acc.set_email(name, typed)
                    email = typed
            print(f"\nSaqlandi: {name}" + (f" ({email})" if email else "") + " — hozir faol." + (f"  Avvalgisiga qaytish: agy-acc use {prev_name}" if prev_name and prev_name != name else ""))
            return 0

    print(f"Noma'lum buyruq: {op}\n")
    print(ACC_HELP)
    return 1


# ───────────────────────────── quotaFile (optional) ─────────────────────────────

def read_quota_file(path: str) -> dict | None:
    try:
        j = json.loads(Path(expand(path)).read_text(encoding="utf-8-sig"))
    except Exception:
        return None

    def win(d, remaining):
        if not isinstance(d, dict):
            return None
        v = d.get("remaining" if remaining else "pct")
        return None if v is None else {"used": 100 - v if remaining else v, "resets": d.get("resets")}

    def grp(d):
        return {"week": win(d.get("week"), True), "five": win(d.get("five"), True)} if isinstance(d, dict) else None

    ts = j.get("ts")
    out = {"ts": ts, "claude": {}, "agy": {}}
    for k, q in (j.get("claude") or {}).items():
        out["claude"][k.lower()] = {"five": win(q.get("five_hour"), False), "week": win(q.get("seven_day"), False),
                                    "fetchedAt": q.get("ts", ts), "error": q.get("error")}
    for k, q in (j.get("agy") or {}).items():
        out["agy"][k.lower()] = {"gemini": grp(q.get("gemini")), "claude": grp(q.get("claude")), "fetchedAt": q.get("ts", ts),
                                 "needsLogin": bool(q.get("needs_login")), "error": q.get("error")}
    return out


# ───────────────────────────── store ─────────────────────────────

def severity(p: float) -> int:
    return 0 if p < 70 else 1 if p < 85 else 2 if p < 95 else 3


class Store:
    """Fetches Claude + agy limits (or reads quotaFile) and builds the view model. Thread-safe."""

    def __init__(self, on_change=lambda: None):
        self.on_change = on_change
        self.lock = threading.RLock()
        self.cache = load_cache()
        self.config, self.problem = load_config()
        self._mtime = self.config_mtime()
        self.refreshing = False
        self.view: dict = {}
        self.offline = False
        self.load()

    def _saved_email(self, a: dict) -> str | None:
        """The gmail inside a saved agy login, read once (before the first quota check has recorded it)."""
        cache = self.__dict__.setdefault("_emails", {})
        if a["name"] not in cache and is_swap_account(a):
            try:
                cache[a["name"]] = AgyAccounts(self.config).email(a["name"])
            except Exception:
                cache[a["name"]] = None
        return cache.get(a["name"])

    # derived view model (no network)
    def load(self) -> None:
        now = time.time()
        cfg = self.config
        with self.lock:
            crecs, arecs = dict(self.cache["claude"]), dict(self.cache["agy"])
        names = [c["name"] for c in cfg["claude"]]
        updated = None
        problem = self.problem or ("Internet yo'q — ulanish tiklangach yangilanadi" if self.offline else None)
        qf = (cfg.get("quotaFile") or "").strip()
        if qf:
            r = read_quota_file(qf)
            if r:
                crecs, arecs, updated = r["claude"], r["agy"], r["ts"]
                known = {n.lower() for n in names}
                names += sorted(k for k in r["claude"] if k not in known)
            else:
                problem = problem or f"quotaFile o'qilmadi: {os.path.basename(qf)}"
        else:
            stamps = [crecs.get(c["name"].lower(), {}).get("fetchedAt") for c in cfg["claude"]]
            stamps += [arecs.get(a["name"].lower(), {}).get("fetchedAt") for a in cfg["agy"] if a["enabled"]]
            stamps = [s for s in stamps if s]
            updated = max(stamps) if stamps else None

        def live(w):
            if not w:
                return None
            if w.get("resets") and w["resets"] < now:
                return {"used": 0.0, "resets": None}
            return {"used": float(w["used"]), "resets": w.get("resets")}

        def grp(g):
            return {"week": live(g.get("week")), "five": live(g.get("five"))} if g else None

        claude = []
        for n in names:
            rec = crecs.get(n.lower()) or {}
            label = next((c.get("label") for c in cfg["claude"] if c["name"] == n), None)
            claude.append({"id": n, "name": n.upper(), "label": label, "quiet": (label or "").lower() == "reserve",
                           "five": live(rec.get("five")), "week": live(rec.get("week")), "error": rec.get("error"),
                           "stale": bool(rec.get("error") and rec.get("five"))})
        agy = []
        typed_emails = AgyAccounts._state().get("emails", {})
        for a in cfg["agy"]:
            rec = arecs.get(a["name"].lower()) or {}
            agy.append({"id": a["name"], "enabled": a["enabled"], "needsLogin": bool(rec.get("needsLogin")),
                        "gemini": grp(rec.get("gemini")), "claude": grp(rec.get("claude")), "error": rec.get("error"),
                        "email": typed_emails.get(a["name"]) or rec.get("email") or self._saved_email(a),
                        "fetched": bool(rec.get("fetchedAt"))})

        mb = next((c for c in claude if c["id"].lower() == (cfg.get("menuBarAccount") or "").lower()), claude[0] if claude else None)
        stale = updated is None or now - updated > 15 * 60
        attention = stale or any(a["enabled"] and a["needsLogin"] for a in agy) or \
            any(c["error"] and (c["five"] is None or c["stale"]) for c in claude)
        alert = problem
        if not alert:
            hits = []
            for c in claude:
                for lbl, w in (("5 soat", c["five"]), ("hafta", c["week"])):
                    if w and w["used"] >= 85:
                        hits.append((w["used"], f"{c['name']} {lbl}: {round(w['used'])}%"
                                     + (f" — {fmt_reset_short(w['resets'])} da tiklanadi" if w["resets"] else "")))
            if hits:
                alert = max(hits)[1]
        if mb:
            menu_name, five, week = mb["name"], mb["five"] and mb["five"]["used"], mb["week"] and mb["week"]["used"]
        else:   # no Claude account: the tray shows the busiest agy account instead
            def worst(key):
                vals = [g[key]["used"] for a in agy if a["enabled"] for g in (a["gemini"], a["claude"]) if g and g.get(key)]
                return max(vals) if vals else None
            menu_name, five, week = ("AGY" if agy else None), worst("five"), worst("week")
        self.view = {"claude": claude, "agy": agy, "updated": updated, "alert": alert, "attention": attention,
                     "menu_name": menu_name, "five": five, "week": week,
                     "worst": max([w["used"] for c in claude for w in (c["five"], c["week"]) if w] or [0])}

    # refreshing
    def _claude_due(self, a, force, now):
        r = self.cache["claude"].get(a["name"].lower())
        if not r or r.get("source") != a["configDir"]:
            return True
        if (r.get("backoffUntil") or 0) > now:
            return False
        if force and not r.get("lastAPICall"):
            return True
        return now >= (r.get("lastAttempt") or 0) + max(self.config["refreshMinutes"], 5) * 60   # never poll faster than 5 min

    def _agy_due(self, a, force, now, max_age=None):
        r = self.cache["agy"].get(a["name"].lower())
        if not r or r.get("source") != a.get("home"):
            return True
        if max_age is not None:   # callers that only need roughly current numbers
            return now >= (r.get("fetchedAt") or 0) + max_age and now >= (r.get("lastAttempt") or 0) + 60
        return now >= (r.get("lastAttempt") or 0) + (30 if force else max(self.config["refreshMinutes"], 1) * 60)

    def refresh(self, force=False, wait=False, agy_only=False, agy_max_age=None) -> None:
        if (self.config.get("quotaFile") or "").strip():
            self.load()
            self.on_change()
            return
        with self.lock:
            if self.refreshing:
                return
            now = time.time()
            cj = [] if agy_only else [a for a in self.config["claude"] if self._claude_due(a, force, now)]
            aj = [a for a in self.config["agy"] if a["enabled"] and self._agy_due(a, force and agy_max_age is None, now, agy_max_age)]
            if not cj and not aj:
                self.load()
                self.on_change()
                return
            self.refreshing = True
            prior_c, prior_a = dict(self.cache["claude"]), dict(self.cache["agy"])
        self.on_change()
        agy_bin = find_agy(self.config)

        def work():
            try:
                self.offline = not internet_up()
                if self.offline:   # nothing is marked as attempted, so the next tick (1 min) tries again
                    return
                with ThreadPoolExecutor(max_workers=6) as ex:
                    fc = {a["name"].lower(): ex.submit(fetch_claude, a, prior_c.get(a["name"].lower())) for a in cj}
                    fa = {a["name"].lower(): ex.submit(fetch_agy, a, prior_a.get(a["name"].lower()), agy_bin)
                          for a in aj if not is_swap_account(a)}
                    swapped = [a for a in aj if is_swap_account(a)]
                    fs = ex.submit(fetch_agy_swapped, swapped, prior_a, agy_bin, self.config) if swapped else None
                    res_c = {k: f.result() for k, f in fc.items()}
                    res_a = {k: f.result() for k, f in fa.items()}
                    if fs:
                        res_a.update(fs.result())
                with self.lock:
                    self.cache["claude"].update(res_c)
                    self.cache["agy"].update(res_a)
                    save_cache(self.cache)
            finally:
                with self.lock:
                    self.refreshing = False
                self.load()
                self.on_change()

        t = threading.Thread(target=work, daemon=True)
        t.start()
        if wait:
            t.join()

    # config actions
    def config_mtime(self):
        try:
            return CONFIG_PATH.stat().st_mtime
        except OSError:
            return None

    def reload_if_changed(self):
        m = self.config_mtime()
        if m != getattr(self, "_mtime", m):
            self.reload_config()
        self._mtime = m

    def reload_config(self):
        self._mtime = self.config_mtime()
        self.config, self.problem = load_config()
        self.load()
        self.refresh(force=True)

    def set_agy_enabled(self, name, on):
        for a in self.config["agy"]:
            if a["name"] == name:
                a["enabled"] = on
        save_config(self.config)
        self.load()
        if on:
            self.refresh()
        self.on_change()

    def add_agy_account(self, name: str | None = None) -> dict:
        taken = {a["name"].lower() for a in self.config["agy"]}
        if not name:
            i = 2
            while f"agy{i}" in taken:
                i += 1
            name = f"agy{i}"
        if name.lower() in taken:
            return next(a for a in self.config["agy"] if a["name"].lower() == name.lower())
        home = AGY_ACCOUNTS_DIR / name
        home.mkdir(parents=True, exist_ok=True)
        acct = {"name": name, "home": "~/.agy-accounts/" + name, "enabled": True, "env": None}
        self.config["agy"].append(acct)
        save_config(self.config)
        self.load()
        return acct

    def sign_in_agy(self, name, new=False):
        a = next((a for a in self.config["agy"] if a["name"] == name), None)
        if new or (a and is_swap_account(a)):
            op = "add" if new else "login"
            open_console([python_console_exe(), os.path.abspath(__file__), "acc", op, name], dict(os.environ),
                         f"agy-acc {op} {name}")
        elif a:
            open_console([find_agy(self.config) or "agy"], agy_env(a), f"agy — {name}: Google akkaunt bilan kiring, keyin /quit")

    def start_claude(self, name):
        a = next((a for a in self.config["claude"] if a["name"] == name), None)
        if not a:
            return
        env = dict(os.environ)
        if not same_path(a["configDir"], "~/.claude"):
            env["CLAUDE_CONFIG_DIR"] = expand(a["configDir"])
        open_console([find_binary("claude") or "claude"], env, f"claude — {name}")


def open_console(cmd: list[str], env: dict, title: str) -> None:
    """Opens a new console window running cmd (for sign-in), with the given environment."""
    if IS_WIN:
        line = subprocess.list2cmdline(cmd)
        safe = re.sub(r'[&|<>^"%]', " ", title)
        # cmd /k "...": cmd strips the outer quotes, so the inner quoted exe path survives
        subprocess.Popen(f'cmd.exe /k "title {safe} & {line}"', env=env, cwd=env.get("USERPROFILE", str(HOME)),
                         creationflags=CREATE_NEW_CONSOLE)
    else:
        print(f"[{title}] run:", " ".join(cmd))


# ───────────────────────────── formatting ─────────────────────────────

WEEKDAYS = ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"]


def _wd(ts: float) -> str:
    d = datetime.fromtimestamp(ts)
    return f"{WEEKDAYS[d.weekday()]} {d:%H:%M}"


def fmt_reset(ts: float | None) -> str:
    if not ts:
        return "—"
    s = ts - time.time()
    if s <= 0:
        return "—"
    if s < 20 * 3600:
        h, m = int(s) // 3600, (int(s) % 3600 + 59) // 60
        if m == 60:
            h, m = h + 1, 0
        return f"{m}m" if h == 0 else f"{h}h {m:02d}m"
    return _wd(ts)


def fmt_reset_short(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M") if ts - time.time() < 20 * 3600 else _wd(ts)


def fmt_ago(ts: float | None) -> str:
    if not ts:
        return "ma'lumot yo'q"
    s = int(time.time() - ts)
    if s < 5:
        return "hozirgina yangilandi"
    if s < 60:
        return f"{s} s oldin"
    if s < 3600:
        return f"{s // 60} daq oldin"
    return f"{s // 3600} soat oldin"


def pct(w) -> str:
    return f"{round(w['used'])}%" if w else "–"


# ───────────────────────────── drawing (Pillow) ─────────────────────────────

STOPS = [((0x22, 0xD3, 0xEE), (0x34, 0xD3, 0x99)),   # calm: cyan → emerald
         ((0xFD, 0xE0, 0x47), (0xF5, 0x9E, 0x0B)),   # amber
         ((0xFD, 0xBA, 0x74), (0xF9, 0x73, 0x16)),   # orange
         ((0xFC, 0xA5, 0xA5), (0xEF, 0x44, 0x44))]   # red
ORANGE = (0xFB, 0x92, 0x3C)


def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _font(size: int, bold=True):
    from PIL import ImageFont
    names = (["segoeuib.ttf", "arialbd.ttf"] if bold else ["segoeui.ttf", "arial.ttf"]) + ["DejaVuSans-Bold.ttf", "DejaVuSans.ttf"]
    for n in names:
        for base in ([os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")] if IS_WIN else []) + ["", "/usr/share/fonts/truetype/dejavu"]:
            try:
                return ImageFont.truetype(os.path.join(base, n) if base else n, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def taskbar_is_light() -> bool:
    if not IS_WIN:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "SystemUsesLightTheme")[0] == 1
    except OSError:
        return False


def _arc(draw, box, frac, width, sev, n=72):
    """Gradient arc from 12 o'clock, clockwise."""
    if frac <= 0.005:
        return
    a, b = STOPS[sev]
    steps = max(2, int(n * frac))
    span = 360 * frac
    for i in range(steps):
        s = -90 + span * i / steps
        e = -90 + span * (i + 1) / steps + 0.8
        draw.arc(box, s, min(e, -90 + span), fill=_mix(a, b, i / (steps - 1)), width=width)


def make_tray_icon(five, week, attention, style="number", light=False):
    from PIL import Image, ImageDraw
    S = 256
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fg = (20, 20, 24) if light else (240, 240, 245)
    track = (0, 0, 0, 55) if light else (255, 255, 255, 60)
    if style == "rings":
        for box, w, p in (((14, 14, S - 14, S - 14), 34, five), ((70, 70, S - 70, S - 70), 34, week)):
            d.ellipse(box, outline=track, width=w)
            if p is not None:
                _arc(d, box, min(max(p / 100, 0), 1), w, severity(p))
    else:
        box, w = (8, 8, S - 8, S - 8), 30
        d.ellipse(box, outline=track, width=w)
        if five is not None:
            _arc(d, box, min(max(five / 100, 0), 1), w, severity(five))
        txt = "–" if five is None else str(min(round(five), 100))
        f = _font(136 if len(txt) <= 2 else 96)
        d.text((S / 2, S / 2 + 4), txt, font=f, fill=fg, anchor="mm")
    if attention:
        d.ellipse((S - 92, 0, S, 92), fill=(0, 0, 0, 0))
        d.ellipse((S - 80, 8, S - 8, 80), fill=ORANGE)
    return img.resize((64, 64), Image.LANCZOS)


# ───────────────────────────── Windows helpers ─────────────────────────────

def work_area():
    """(left, top, right, bottom) of the primary monitor minus the taskbar, in physical pixels."""
    if IS_WIN:
        import ctypes
        from ctypes import wintypes
        r = wintypes.RECT()
        if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0):
            return r.left, r.top, r.right, r.bottom
    return None


def single_instance() -> bool:
    if not IS_WIN:
        return True
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    single_instance._h = k32.CreateMutexW(None, False, "Local\\UsageBarWindowsSingleton")
    return ctypes.get_last_error() != 183   # ERROR_ALREADY_EXISTS


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _launch_command() -> str:
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        w = exe[:-len("python.exe")] + "pythonw.exe"
        if os.path.exists(w):
            exe = w
    return f'"{exe}" "{os.path.abspath(__file__)}"'


def launch_at_login() -> bool:
    if not IS_WIN:
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            return bool(winreg.QueryValueEx(k, APP_NAME)[0])
    except OSError:
        return False


def set_launch_at_login(on: bool) -> None:
    if not IS_WIN:
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, _launch_command())
        else:
            try:
                winreg.DeleteValue(k, APP_NAME)
            except OSError:
                pass


def open_in_editor(path: Path) -> None:
    if IS_WIN:
        subprocess.Popen(["notepad.exe", str(path)])
    else:
        print("config:", path)


# ───────────────────────────── UI (tkinter popover + pystray) ─────────────────────────────

PALETTES = {
    "dark": {
        "panel": (32, 32, 36), "key": (1, 2, 3), "border": (255, 255, 255, 26),
        "card": (255, 255, 255, 11), "card_hover": (255, 255, 255, 19), "card_quiet": (255, 255, 255, 6),
        "card_border": (255, 255, 255, 14),
        "fg": (244, 244, 247), "fg2": (165, 167, 178), "fg3": (112, 114, 126),
        "track": (255, 255, 255, 24), "chip": (255, 255, 255, 16), "btn_hover": (255, 255, 255, 22),
        "accent": (110, 120, 245), "accent_hover": (128, 138, 250), "accent_fg": (255, 255, 255),
        "alert_bg": (251, 146, 60, 34), "alert_fg": (253, 186, 116), "warn": (251, 146, 60),
        "sev": [(110, 231, 183), (252, 211, 77), (253, 166, 96), (248, 113, 113)],
    },
    "light": {
        "panel": (246, 246, 248), "key": (196, 196, 201), "border": (0, 0, 0, 30),
        "card": (255, 255, 255, 235), "card_hover": (255, 255, 255, 255), "card_quiet": (255, 255, 255, 140),
        "card_border": (0, 0, 0, 16),
        "fg": (22, 22, 26), "fg2": (88, 90, 102), "fg3": (138, 140, 150),
        "track": (0, 0, 0, 20), "chip": (0, 0, 0, 10), "btn_hover": (0, 0, 0, 12),
        "accent": (79, 70, 229), "accent_hover": (99, 90, 240), "accent_fg": (255, 255, 255),
        "alert_bg": (234, 88, 12, 26), "alert_fg": (180, 65, 12), "warn": (217, 98, 12),
        "sev": [(5, 150, 105), (202, 138, 4), (234, 88, 12), (220, 38, 38)],
    },
}


def apps_use_light_theme() -> bool:
    if not IS_WIN:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as k:
            return winreg.QueryValueEx(k, "AppsUseLightTheme")[0] == 1
    except OSError:
        return False


_FONT_CACHE: dict = {}


def ui_font(px: int, weight: str = "regular"):
    """Segoe UI on Windows (regular / semibold / bold), DejaVu elsewhere."""
    key = (px, weight)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    from PIL import ImageFont
    names = {"regular": ["segoeui.ttf", "DejaVuSans.ttf"],
             "semibold": ["seguisb.ttf", "segoeuib.ttf", "DejaVuSans-Bold.ttf"],
             "bold": ["segoeuib.ttf", "DejaVuSans-Bold.ttf"]}[weight]
    dirs = [os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts")] if IS_WIN else []
    dirs += ["/usr/share/fonts/truetype/dejavu", ""]
    font = None
    for n in names:
        for d in dirs:
            try:
                font = ImageFont.truetype(os.path.join(d, n) if d else n, px)
                break
            except OSError:
                continue
        if font:
            break
    _FONT_CACHE[key] = font or ImageFont.load_default(px)
    return _FONT_CACHE[key]


def icon_font(px: int):
    """Segoe Fluent Icons (Win 11) / Segoe MDL2 Assets (Win 10), or None."""
    key = ("icons", px)
    if key not in _FONT_CACHE:
        from PIL import ImageFont
        _FONT_CACHE[key] = None
        if IS_WIN:
            for n in ("SegoeIcons.ttf", "segmdl2.ttf"):
                try:
                    _FONT_CACHE[key] = ImageFont.truetype(os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", n), px)
                    break
                except OSError:
                    continue
    return _FONT_CACHE[key]


class Painter:
    """Draws the whole popover as one anti-aliased image and returns clickable regions.
    Sizes are in 96-dpi pixels and scaled by `scale`."""

    W = 372
    PAD = 16
    SS = 4   # supersampling for shapes

    def __init__(self, scale: float, theme: str):
        from PIL import Image, ImageDraw
        self.Image, self.ImageDraw = Image, ImageDraw
        self.k = scale
        self.p = PALETTES[theme]
        self.theme = theme

    def s(self, v) -> int:
        return int(round(v * self.k))

    def f(self, px, weight="regular"):
        return ui_font(max(6, self.s(px)), weight)

    # primitives
    def rrect(self, box, r, fill, outline=None, width=1):
        Image, ImageDraw = self.Image, self.ImageDraw
        x0, y0, x1, y1 = [int(round(v)) for v in box]
        w, h = x1 - x0, y1 - y0
        if w <= 0 or h <= 0:
            return
        S = self.SS
        if fill is not None:
            m = Image.new("L", (w * S, h * S), 0)
            ImageDraw.Draw(m).rounded_rectangle((0, 0, w * S - 1, h * S - 1), radius=r * S, fill=255)
            self._paint(m.resize((w, h), Image.LANCZOS), (x0, y0), fill)
        if outline is not None:
            m = Image.new("L", (w * S, h * S), 0)
            ImageDraw.Draw(m).rounded_rectangle((0, 0, w * S - 1, h * S - 1), radius=r * S, outline=255, width=max(1, int(width * S)))
            self._paint(m.resize((w, h), Image.LANCZOS), (x0, y0), outline)

    def _paint(self, mask, xy, color):
        a = color[3] if len(color) == 4 else 255
        if a < 255:
            mask = mask.point(lambda v: v * a // 255)
        layer = self.Image.new("RGBA", mask.size, tuple(color[:3]) + (255,))
        layer.putalpha(mask)
        self.img.alpha_composite(layer, dest=(int(xy[0]), int(xy[1])))

    def shape(self, xy, size, fn):
        """fn(draw, S) draws at SS-times size on an RGBA layer, which is then downsampled and composited."""
        Image = self.Image
        w, h = int(size[0]), int(size[1])
        S = self.SS
        layer = Image.new("RGBA", (w * S, h * S), (0, 0, 0, 0))
        fn(self.ImageDraw.Draw(layer), S)
        self.img.alpha_composite(layer.resize((w, h), Image.LANCZOS), dest=(int(xy[0]), int(xy[1])))

    def text(self, xy, s, font, fill, anchor="la"):
        self.draw.text(xy, s, font=font, fill=tuple(fill[:3]), anchor=anchor)

    def tw(self, s, font) -> float:
        return font.getlength(s)

    def wrap(self, s, font, maxw):
        lines, cur = [], ""
        for word in s.split():
            t = (cur + " " + word).strip()
            if self.tw(t, font) <= maxw or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = word
        if cur:
            lines.append(cur)
        return lines

    def bar(self, x, y, w, h, p, quiet=False):
        Image = self.Image
        self.rrect((x, y, x + w, y + h), h / 2, self.p["track"])
        if p is None or p <= 0.4:
            return
        fw = max(h, int(round(w * min(p, 100) / 100)))
        a, b = STOPS[severity(p)]
        row = Image.new("RGBA", (fw, 1))
        row.putdata([_mix(a, b, i / max(fw - 1, 1)) + (170 if quiet else 255,) for i in range(fw)])
        grad = row.resize((fw, h))
        S = self.SS
        m = Image.new("L", (fw * S, h * S), 0)
        self.ImageDraw.Draw(m).rounded_rectangle((0, 0, fw * S - 1, h * S - 1), radius=h * S / 2, fill=255)
        m = m.resize((fw, h), Image.LANCZOS)
        alpha = Image.composite(grad.getchannel("A"), Image.new("L", (fw, h), 0), m)
        grad.putalpha(alpha)
        self.img.alpha_composite(grad, dest=(int(x), int(y)))

    def ring(self, x, y, d, p):
        track = self.p["track"]

        def fn(dr, S):
            w = max(2, d * S // 7)
            box = (w // 2, w // 2, d * S - w // 2 - 1, d * S - w // 2 - 1)
            dr.ellipse(box, outline=track, width=w)
            if p is not None and p > 0.4:
                _arc(dr, box, min(p / 100, 1), w, severity(p), n=90)
        self.shape((x, y), (d, d), fn)

    def chevron(self, x, y, size, down, color):
        def fn(dr, S):
            z = size * S
            lw = max(1, int(1.6 * self.k * S))
            if down:
                pts = [(z * 0.2, z * 0.38), (z * 0.5, z * 0.66), (z * 0.8, z * 0.38)]
            else:
                pts = [(z * 0.38, z * 0.2), (z * 0.66, z * 0.5), (z * 0.38, z * 0.8)]
            dr.line(pts, fill=tuple(color[:3]) + (255,), width=lw, joint="curve")
            for px, py in (pts[0], pts[2]):
                dr.ellipse((px - lw / 2, py - lw / 2, px + lw / 2, py + lw / 2), fill=tuple(color[:3]) + (255,))
        self.shape((x, y), (size, size), fn)

    def refresh_glyph(self, x, y, size, color):
        f = icon_font(self.s(15))
        if f:
            self.draw.text((x + size / 2, y + size / 2), "\uE72C", font=f, fill=tuple(color[:3]), anchor="mm")
            return

        def fn(dr, S):
            z = size * S
            lw = max(1, int(1.7 * self.k * S))
            m = z * 0.2
            import math
            dr.arc((m, m, z - m, z - m), 320, 250, fill=tuple(color[:3]) + (255,), width=lw)
            cx = cy = z / 2
            r = (z - 2 * m) / 2 - lw / 2
            t = math.radians(250)                       # arc end; clockwise tangent = (-sin, cos)
            ex, ey = cx + r * math.cos(t), cy + r * math.sin(t)
            dx, dy = -math.sin(t), math.cos(t)
            nx, ny = math.cos(t), math.sin(t)
            a = z * 0.17
            dr.polygon([(ex + dx * a, ey + dy * a), (ex - dx * a * 0.3 + nx * a, ey - dy * a * 0.3 + ny * a),
                        (ex - dx * a * 0.3 - nx * a, ey - dy * a * 0.3 - ny * a)], fill=tuple(color[:3]) + (255,))
        self.shape((x, y), (size, size), fn)

    def dots(self, cx, cy, color):
        f = icon_font(self.s(16))
        if f:
            self.draw.text((cx, cy), "\uE712", font=f, fill=tuple(color[:3]), anchor="mm")
            return
        r = max(1.5, 1.6 * self.k)
        gap = self.s(6)
        for i in (-1, 0, 1):
            self.shape((cx + i * gap - r - 1, cy - r - 1), (2 * r + 2, 2 * r + 2),
                       lambda dr, S, r=r: dr.ellipse((S, S, (2 * r + 1) * S, (2 * r + 1) * S), fill=tuple(color[:3]) + (255,)))

    # the popover
    def render(self, view, expanded, hover, refreshing, max_h=None, scroll=0):
        Image, ImageDraw = self.Image, self.ImageDraw
        P, s = self.p, self.s
        W = s(self.W)
        self.img = Image.new("RGBA", (W, s(2400)), tuple(P["panel"]) + (255,))
        self.draw = ImageDraw.Draw(self.img)
        regions = []
        pad = s(self.PAD)
        x0, x1 = pad, W - pad
        y = s(14)

        # header
        self.text((x0, y + s(15)), "Usage", self.f(18, "semibold"), P["fg"], "ls")
        bsz = s(30)
        bx, by = x1 - bsz + s(6), y - s(5)
        if hover == "refresh":
            self.rrect((bx, by, bx + bsz, by + bsz), s(8), P["btn_hover"])
        self.refresh_glyph(bx + s(6), by + s(6), s(18), P["fg2"] if refreshing else P["fg"])
        regions.append(((bx, by, bx + bsz, by + bsz), ("refresh",), "refresh"))
        status = "yangilanmoqda…" if refreshing else fmt_ago(view.get("updated"))
        self.text((bx - s(6), y + s(14)), status, self.f(12), P["fg3"], "rs")
        y += s(30)

        if view.get("alert"):
            y += s(4)
            fa = self.f(12.5)
            lines = self.wrap(view["alert"], fa, x1 - x0 - s(40))
            h = s(16) + len(lines) * s(17)
            self.rrect((x0, y, x1, y + h), s(9), P["alert_bg"])
            self.shape((x0 + s(12), y + s(13)), (s(8), s(8)), lambda dr, S: dr.ellipse((0, 0, 8 * self.k * S - 1, 8 * self.k * S - 1), fill=tuple(P["warn"]) + (255,)))
            for i, ln in enumerate(lines):
                self.text((x0 + s(28), y + s(8) + i * s(17)), ln, fa, P["alert_fg"])
            y += h + s(6)

        def section(title):
            nonlocal y
            y += s(12)
            self.text((x0 + s(2), y), title, self.f(11, "semibold"), P["fg3"])
            y += s(22)

        def row(label, w, quiet=False, indent=0):
            nonlocal y
            fl, fp, fr = self.f(13), self.f(13, "semibold"), self.f(12)
            cy = y + s(11)
            self.text((x0 + s(14) + indent, cy), label, fl, P["fg2"], "lm")
            bx0 = x0 + s(82) + indent
            bx1 = x1 - s(140)
            self.bar(bx0, cy - s(3), bx1 - bx0, s(6), w["used"] if w else None, quiet)
            if w:
                sev = severity(w["used"])
                col = P["fg"] if sev == 0 else P["sev"][sev]
                if quiet:
                    col = P["fg2"]
                self.text((x1 - s(78), cy), pct(w), fp, col, "rm")
                self.text((x1 - s(14), cy), fmt_reset(w["resets"]), fr, P["fg3"], "rm")
            else:
                self.text((x1 - s(78), cy), "–", fp, P["fg3"], "rm")
            y += s(25)

        def card(top, bottom, hid=None, quiet=False):
            fill = P["card_quiet"] if quiet else (P["card_hover"] if hid and hover == hid else P["card"])
            self.rrect((x0, top, x1, bottom), s(10), fill, P["card_border"])

        # cards are drawn after their content height is known: draw content on a scratch layer
        def boxed(draw_fn, hid=None, quiet=False):
            nonlocal y
            top = y
            saved = self.img
            self.img = Image.new("RGBA", saved.size, (0, 0, 0, 0))
            self.draw = ImageDraw.Draw(self.img)
            y += s(10)
            draw_fn()
            y += s(8)
            content = self.img
            self.img, self.draw = saved, ImageDraw.Draw(saved)
            card(top, y, hid, quiet)
            self.img.alpha_composite(content)
            self.draw = ImageDraw.Draw(self.img)
            y += s(8)
            return top

        claude, agy = view["claude"], view["agy"]
        if claude:
            section("CLAUDE CODE")
            for c in claude:
                def body(c=c):
                    nonlocal y
                    fname = self.f(14, "semibold")
                    cy = y + s(10)
                    self.text((x0 + s(14), cy), c["name"], fname, P["fg2"] if c["quiet"] else P["fg"], "lm")
                    nx = x0 + s(14) + self.tw(c["name"], fname) + s(8)
                    if c["label"]:
                        fl = self.f(11)
                        lw = self.tw(c["label"], fl) + s(14)
                        self.rrect((nx, cy - s(9), nx + lw, cy + s(9)), s(9), P["chip"])
                        self.text((nx + lw / 2, cy), c["label"], fl, P["fg2"], "mm")
                    nodata = c["five"] is None and c["week"] is None
                    if c["error"] and nodata:
                        self.text((x1 - s(14), cy), "login yo'q", self.f(12), P["fg3"], "rm")
                        y += s(22)
                        for ln in self.wrap(c["error"], self.f(12), x1 - x0 - s(28)):
                            self.text((x0 + s(14), y), ln, self.f(12), P["fg3"])
                            y += s(17)
                        return
                    if c["stale"]:
                        self.text((x1 - s(14), cy), "eski ma'lumot", self.f(11), P["warn"], "rm")
                    y += s(26)
                    row("5 soat", c["five"], c["quiet"])
                    row("Hafta", c["week"], c["quiet"])
                    if c["error"] and c["stale"]:
                        for ln in self.wrap(c["error"], self.f(11.5), x1 - x0 - s(28)):
                            self.text((x0 + s(14), y), ln, self.f(11.5), P["fg3"])
                            y += s(16)
                boxed(body, quiet=c["quiet"])

        if agy:
            section("AGY · GEMINI")
            for a in agy:
                hid = "agy:" + a["id"]
                is_open = a["id"] in expanded and a["enabled"] and not a["needsLogin"]

                def body(a=a, is_open=is_open, hid=hid):
                    nonlocal y
                    top = y - s(10)
                    fname = self.f(14, "semibold")
                    cy = y + s(10)
                    on = a["enabled"]
                    self.chevron(x0 + s(10), cy - s(8), s(16), is_open, P["fg2"] if on else P["fg3"])
                    self.text((x0 + s(30), cy), a["id"].upper(), fname, P["fg"] if on else P["fg3"], "lm")
                    email = a.get("email")
                    if email:   # which gmail this account is
                        fe = self.f(11.5)
                        while len(email) > 4 and self.tw(email, fe) > x1 - x0 - s(44):
                            email = email[:-2] + "…" if not email.endswith("…") else email[:-3] + "…"
                        self.text((x0 + s(30), cy + s(17)), email, fe, P["fg3"], "lm")
                        y += s(16)
                    regions.append(((x0, top, x1, cy + s(18) + (s(16) if email else 0)), ("toggle", a["id"]), hid))
                    if not on:
                        self.text((x1 - s(14), cy), "o'chiq", self.f(12), P["fg3"], "rm")
                        y += s(22)
                        return
                    if a["needsLogin"]:
                        fb = self.f(12, "semibold")
                        bw = self.tw("Kirish", fb) + s(22)
                        bxx = x1 - s(12) - bw
                        bid = "signin:" + a["id"]
                        self.rrect((bxx, cy - s(12), bxx + bw, cy + s(12)), s(7), P["accent_hover"] if hover == bid else P["accent"])
                        self.text((bxx + bw / 2, cy), "Kirish", fb, P["accent_fg"], "mm")
                        regions.insert(0, ((bxx, cy - s(12), bxx + bw, cy + s(12)), ("signin", a["id"]), bid))
                        self.text((bxx - s(10), cy), "kirish kerak", self.f(12), P["warn"], "rm")
                        y += s(22)
                        return
                    if not is_open:
                        fl, fp = self.f(11.5), self.f(12.5, "semibold")
                        xr = x1 - s(14)
                        for title, g in (("Claude", a["claude"]), ("Gemini", a["gemini"])):
                            w = g and g.get("week")
                            five = g and g.get("five")
                            show = max([v["used"] for v in (w, five) if v] or [0]) if (w or five) else None
                            label = "–" if show is None else f"{round(show)}%"
                            sev = severity(show or 0)
                            self.text((xr, cy), label, fp, P["fg"] if sev == 0 else P["sev"][sev], "rm")
                            xr -= max(self.tw(label, fp), self.tw("88%", fp)) + s(5)
                            self.ring(xr - s(14), cy - s(7), s(14), show)
                            xr -= s(14) + s(5)
                            self.text((xr, cy), title, fl, P["fg3"], "rm")
                            xr -= self.tw(title, fl) + s(14)
                        y += s(22)
                    else:
                        y += s(24)
                        for title, g in (("Gemini", a["gemini"]), ("Claude & GPT", a["claude"])):
                            self.text((x0 + s(14), y + s(6)), title, self.f(11.5, "semibold"), P["fg3"], "lm")
                            y += s(16)
                            row("5 soat", g and g.get("five"))
                            row("Hafta", g and g.get("week"))
                            y += s(2)
                    if a["error"]:
                        y += s(4)
                        for ln in self.wrap(a["error"], self.f(11.5), x1 - x0 - s(28)):
                            self.text((x0 + s(14), y), ln, self.f(11.5), P["warn"])
                            y += s(16)
                    elif not a["fetched"]:
                        y += s(2)
                        self.text((x0 + s(30), y), "yuklanmoqda…", self.f(11.5), P["fg3"])
                        y += s(16)
                boxed(body, hid=hid, quiet=not a["enabled"])

        if not claude and not agy:
            y += s(16)
            self.text((W / 2, y), "Akkaunt topilmadi — ••• → Sozlamalarni ochish", self.f(12.5), P["fg3"], "mt")
            y += s(30)

        # footer
        y += s(4)
        n_agy = len([a for a in agy if a["enabled"]])
        parts = ([f"{len(claude)} Claude"] if claude else []) + ([f"{n_agy} agy"] if agy else [])
        self.text((x0 + s(2), y + s(13)), " · ".join(parts), self.f(12), P["fg3"], "lm")
        mw, mh = s(38), s(26)
        mx = x1 - mw
        if hover == "menu":
            self.rrect((mx, y, mx + mw, y + mh), s(7), P["btn_hover"])
        self.dots(mx + mw / 2, y + mh / 2, P["fg"])
        regions.append(((mx, y, mx + mw, y + mh), ("menu",), "menu"))
        y += mh + s(12)

        # window: rounded panel over the transparent key colour
        H = y
        vis = H if not max_h or H <= max_h else max_h
        scroll = max(0, min(scroll, H - vis))
        body = self.img.crop((0, scroll, W, scroll + vis))
        out = Image.new("RGBA", (W, vis), tuple(P["key"]) + (255,))
        S = self.SS
        m = Image.new("L", (W * S, vis * S), 0)
        r = s(12)
        ImageDraw.Draw(m).rounded_rectangle((0, 0, W * S - 1, vis * S - 1), radius=r * S, fill=255)
        out.paste(body, (0, 0), m.resize((W, vis), Image.LANCZOS))
        self.img, self.draw = out, ImageDraw.Draw(out)
        self.rrect((0, 0, W, vis), r, None, P["border"], width=1)
        regions = [((bx0, by0 - scroll, bx1, by1 - scroll), act, hid) for (bx0, by0, bx1, by1), act, hid in regions]
        return out.convert("RGB"), regions, H, scroll


class App:
    WIDTH = 360

    def __init__(self, show=False):
        import queue
        import tkinter as tk
        if IS_WIN:
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                pass
        self.tk = tk
        self.q = queue.Queue()
        self.root = tk.Tk()
        self.root.withdraw()
        if hasattr(setup_logging, "hook"):
            self.root.report_callback_exception = setup_logging.hook
        self.scale = self.root.winfo_fpixels("1i") / 96.0
        self.images = []
        self.expanded: set[str] = set()
        self.menu_open = False
        self.last_icon_key = None
        self.store = Store(on_change=lambda: self.q.put(("changed",)))
        self.win = None
        self.icon = None
        self._build_window()
        self._start_tray()
        self.store.refresh()
        self.root.after(100, self._poll)
        self.root.after(10_000, self._tick10)
        self.root.after(60_000, self._tick60)
        if show:
            self.root.after(500, self.show)

    def S(self, v):
        return int(round(v * self.scale))

    # tray (runs in its own thread; talks to tk only through the queue)
    def _start_tray(self):
        try:
            import pystray
        except Exception as e:
            notify(f"Tray ikonka ishga tushmadi (pystray): {e}")
            return
        M = pystray.MenuItem
        menu = pystray.Menu(
            M("Ko'rsatish", lambda: self.q.put(("toggle",)), default=True),
            M("Hozir yangilash", lambda: self.q.put(("refresh",))),
            M("agy akkaunt qo'shish…", lambda: self.q.put(("add_agy",))),
            M("Sozlamalarni ochish", lambda: self.q.put(("open_config",))),
            M("Sozlamalarni qayta yuklash", lambda: self.q.put(("reload",))),
            pystray.Menu.SEPARATOR,
            M("Chiqish", lambda: self.q.put(("quit",))),
        )
        self.icon = pystray.Icon(APP_NAME, self._icon_image(), "Usage", menu)
        self.icon.run_detached()

    def _icon_image(self):
        v = self.store.view
        return make_tray_icon(v.get("five"), v.get("week"), v.get("attention"), self.store.config.get("trayIcon", "number"),
                              taskbar_is_light())

    def _update_tray(self):
        if not self.icon:
            return
        v = self.store.view
        key = (v.get("five") and round(v["five"]), v.get("week") and round(v["week"]), v.get("attention"),
               self.store.config.get("trayIcon"), taskbar_is_light())
        if key != self.last_icon_key:
            self.last_icon_key = key
            self.icon.icon = self._icon_image()
        tip = "Usage"
        if v.get("menu_name"):
            tip = f"{v['menu_name']}: 5 soat {pct({'used': v['five']}) if v.get('five') is not None else '–'}" \
                  f" · hafta {pct({'used': v['week']}) if v.get('week') is not None else '–'}"
        self.icon.title = tip[:120]

    # event loop glue
    def _poll(self):
        import queue
        try:
            while True:
                msg = self.q.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "changed":
            self._update_tray()
            if self.visible():
                self.render()
        elif kind == "toggle":
            self.hide() if self.visible() else self.show()
        elif kind == "refresh":
            self.store.refresh(force=True)
        elif kind == "add_agy":
            self.add_agy()
        elif kind == "open_config":
            open_in_editor(CONFIG_PATH)
        elif kind == "reload":
            self.store.reload_config()
        elif kind == "quit":
            self.quit()

    def _tick10(self):
        self.store.load()
        self._update_tray()
        if self.visible():
            self.render()
        self.root.after(10_000, self._tick10)

    def _tick60(self):
        self.store.reload_if_changed()   # e.g. agy-acc added an account
        self.store.refresh()   # every account has its own minimum interval
        self.root.after(60_000, self._tick60)

    # popover window: one borderless window showing the Painter's image
    def _theme(self):
        t = (self.store.config.get("theme") or "auto").lower()
        if t in ("dark", "light"):
            return t
        return "light" if apps_use_light_theme() else "dark"

    def _build_window(self):
        tk = self.tk
        w = tk.Toplevel(self.root)
        w.withdraw()
        w.overrideredirect(True)
        w.attributes("-topmost", True)
        w.bind("<Escape>", lambda e: self.hide())
        w.bind("<FocusOut>", self._focus_out)
        self.win = w
        self.label = tk.Label(w, bd=0, highlightthickness=0, cursor="arrow")
        self.label.pack()
        self.label.bind("<Motion>", self._motion)
        self.label.bind("<Leave>", lambda e: self._set_hover(None))
        self.label.bind("<Button-1>", self._click)
        self.label.bind("<MouseWheel>", self._wheel)
        self.regions = []
        self.hover = None
        self.scroll = 0
        self.photo = None

    def visible(self):
        return self.win is not None and self.win.winfo_viewable()

    def _no_taskbar_button(self):
        """A tool window gets no taskbar button (otherwise a Python icon shows up there every time)."""
        if not IS_WIN:
            return
        try:
            import ctypes
            from ctypes import wintypes as wt
            u32 = ctypes.windll.user32
            u32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
            u32.GetAncestor.restype = wt.HWND
            get = getattr(u32, "GetWindowLongPtrW", u32.GetWindowLongW)
            put = getattr(u32, "SetWindowLongPtrW", u32.SetWindowLongW)
            get.argtypes, get.restype = [wt.HWND, ctypes.c_int], ctypes.c_ssize_t
            put.argtypes, put.restype = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t], ctypes.c_ssize_t
            self.win.update_idletasks()
            hwnd = u32.GetAncestor(self.win.winfo_id(), 2)   # GA_ROOT
            ex = get(hwnd, -20)                                # GWL_EXSTYLE
            new = (ex | 0x00000080) & ~0x00040000              # + WS_EX_TOOLWINDOW, - WS_EX_APPWINDOW
            if new != ex:
                put(hwnd, -20, new)
        except Exception:
            pass

    def _focus_out(self, _e):
        def check():
            if not self.menu_open and self.visible() and self.win.focus_get() is None:
                self.hide()
        self.root.after(150, check)

    def show(self):
        self.store.reload_if_changed()   # accounts added with agy-acc show up right away
        self.store.load()
        upd = self.store.view.get("updated")
        if not upd or time.time() - upd > 120:
            self.store.refresh()
        self.scroll = 0
        self.render()
        self._no_taskbar_button()   # before the window is shown, so Windows never adds the button
        self.win.deiconify()
        self.win.lift()
        self.win.focus_force()

    def hide(self):
        self.win.withdraw()

    def _work_area(self):
        wa = work_area()
        if wa:
            return wa
        return 0, 0, self.win.winfo_screenwidth(), self.win.winfo_screenheight() - self.S(48)

    def render(self):
        import base64
        import io
        theme = self._theme()
        painter = Painter(self.scale, theme)
        _, t, r, b = self._work_area()
        img, self.regions, full_h, self.scroll = painter.render(
            self.store.view, self.expanded, self.hover, self.store.refreshing, max_h=b - t - self.S(24), scroll=self.scroll)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        self.photo = self.tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
        self.label.configure(image=self.photo, bg="#%02x%02x%02x" % PALETTES[theme]["key"])
        self.win.configure(bg="#%02x%02x%02x" % PALETTES[theme]["key"])
        try:   # rounded corners: the key colour around the panel becomes see-through (Windows)
            self.win.attributes("-transparentcolor", "#%02x%02x%02x" % PALETTES[theme]["key"])
        except Exception:
            pass
        w, h = img.size
        self.win.geometry(f"{w}x{h}+{r - w - self.S(12)}+{b - h - self.S(12)}")

    def _hit(self, x, y):
        for (x0, y0, x1, y1), act, hid in self.regions:
            if x0 <= x < x1 and y0 <= y < y1:
                return act, hid
        return None, None

    def _set_hover(self, hid):
        if hid != self.hover:
            self.hover = hid
            self.label.configure(cursor="hand2" if hid else "arrow")
            self.render()

    def _motion(self, e):
        self._set_hover(self._hit(e.x, e.y)[1])

    def _wheel(self, e):
        self.scroll = max(0, self.scroll - int(e.delta / 120 * self.S(60)))
        self.render()

    def _click(self, e):
        act, _ = self._hit(e.x, e.y)
        if not act:
            return
        kind = act[0]
        if kind == "refresh":
            self.store.refresh(force=True)
            self.render()
        elif kind == "menu":
            self._menu(e)
        elif kind == "toggle":
            self._toggle_expand(act[1])
        elif kind == "signin":
            self.store.sign_in_agy(act[1])

    def _toggle_expand(self, name):
        self.expanded ^= {name}
        self.render()

    def _menu(self, e):
        tk = self.tk
        m = tk.Menu(self.win, tearoff=0)
        m.add_command(label="Hammasini ochish / yopish", command=self._expand_all)
        m.add_command(label="Hozir yangilash", command=lambda: self.store.refresh(force=True))
        m.add_separator()
        agy = tk.Menu(m, tearoff=0)
        for a in self.store.config["agy"]:
            var = tk.BooleanVar(value=a["enabled"])
            self.images.append(var)
            agy.add_checkbutton(label=a["name"], variable=var, command=lambda n=a["name"], v=var: self.store.set_agy_enabled(n, v.get()))
        agy.add_separator()
        for a in self.store.config["agy"]:
            agy.add_command(label=f"Kirish: {a['name']}…", command=lambda n=a["name"]: self.store.sign_in_agy(n))
        if swap_mode_available():
            agy.add_separator()
            for a in self.store.config["agy"]:
                if is_swap_account(a):
                    agy.add_command(label=f"Terminal/agy uchun tanlash: {a['name']}", command=lambda n=a["name"]: open_console(
                        [python_console_exe(), os.path.abspath(__file__), "acc", "use", n], dict(os.environ), f"agy-acc use {n}"))
        agy.add_separator()
        agy.add_command(label="Yangi agy akkaunt qo'shish…", command=self.add_agy)
        m.add_cascade(label="agy akkauntlar", menu=agy)
        cl = tk.Menu(m, tearoff=0)
        for c in self.store.config["claude"]:
            cl.add_command(label=f"Claude ochish / kirish: {c['name']}", command=lambda n=c["name"]: self.store.start_claude(n))
        if not self.store.config["claude"]:
            cl.add_command(label="(config.json'da Claude akkaunt yo'q)", state="disabled")
        m.add_cascade(label="Claude akkauntlar", menu=cl)
        m.add_separator()
        m.add_command(label="Sozlamalarni ochish…", command=lambda: open_in_editor(CONFIG_PATH))
        m.add_command(label="Sozlamalarni qayta yuklash", command=self.store.reload_config)
        if IS_WIN:
            var = tk.BooleanVar(value=launch_at_login())
            self.images.append(var)
            m.add_checkbutton(label="Windows bilan birga ishga tushirish", variable=var, command=lambda: set_launch_at_login(var.get()))
        m.add_separator()
        m.add_command(label="Chiqish", command=self.quit)
        self.menu_open = True
        try:
            m.tk_popup(e.x_root, e.y_root)
        finally:
            m.grab_release()
            self.root.after(300, self._menu_closed)

    def _menu_closed(self):
        self.menu_open = False
        if self.visible():
            self.win.focus_force()

    def _expand_all(self):
        names = {a["id"] for a in self.store.view["agy"]}
        self.expanded = set() if names <= self.expanded else names
        self.render()

    def add_agy(self):
        if not swap_mode_available():
            acct = self.store.add_agy_account()
            self.store.sign_in_agy(acct["name"])
            self.q.put(("changed",))
            return
        from tkinter import simpledialog
        taken = {a["name"].lower() for a in self.store.config["agy"]}
        i = 1
        while f"gmail{i}" in taken:
            i += 1
        self.menu_open = True
        name = simpledialog.askstring("agy akkaunt qo'shish", "Yangi akkaunt nomi (masalan gmail2):",
                                      initialvalue=f"gmail{i}", parent=self.root)
        self.root.after(300, self._menu_closed)
        if name and re.fullmatch(r"[\w.@+-]{1,40}", name.strip()):
            self.store.sign_in_agy(name.strip(), new=True)

    def quit(self):
        if self.icon:
            self.icon.stop()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


# ───────────────────────────── entry point ─────────────────────────────

def install_skill() -> int:
    """Copies skills/agy/SKILL.md to ~/.claude/skills/agy/ with this folder's path filled in (Claude Code skill)."""
    src = APP_DIR / "skills" / "agy" / "SKILL.md"
    if not src.exists():
        print(f"Topilmadi: {src}")
        return 1
    dest = HOME / ".claude" / "skills" / "agy" / "SKILL.md"
    dest.parent.mkdir(parents=True, exist_ok=True)
    app = str(Path(os.path.abspath(__file__))).replace("\\", "/")
    dest.write_text(src.read_text(encoding="utf-8").replace("{{APP}}", app), encoding="utf-8")
    print(f"Claude Code skill o'rnatildi: {dest}")
    print("Claude Code'ni qayta oching va so'rang, masalan: \"agy bilan shu faylni review qildir\" yoki /agy")
    return 0


def cmd_check():
    s = Store()
    s.refresh(force=True, wait=True)
    s.load()
    v = s.view
    print(f"python: {sys.executable} ({sys.version.split()[0]})")
    print(f"config: {CONFIG_PATH}")
    print(f"log:    {LOG_PATH}")
    print(f"agy:    {find_agy(s.config) or 'TOPILMADI'}")
    for c in v["claude"]:
        print(f"claude {c['id']}: 5h={pct(c['five'])} week={pct(c['week'])}" + (f"  error={c['error']}" if c["error"] else ""))
    for a in v["agy"]:
        g = lambda x: f"wk={pct(x and x.get('week'))} 5h={pct(x and x.get('five'))}"
        print(f"agy {a['id']}: enabled={a['enabled']} needsLogin={a['needsLogin']} gemini[{g(a['gemini'])}] claude[{g(a['claude'])}]"
              + (f"  error={a['error']}" if a["error"] else ""))


def main(argv):
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream and not stream.isatty():
                stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if "--check" in argv:
        cmd_check()
        return
    if "--install-skill" in argv:
        sys.exit(install_skill())
    if argv and argv[0] == "acc":
        sys.exit(cmd_acc(argv[1:]))
    if "--add-agy" in argv:
        i = argv.index("--add-agy")
        name = argv[i + 1] if i + 1 < len(argv) and not argv[i + 1].startswith("-") else None
        if swap_mode_available():
            sys.exit(cmd_acc(["add", name or "gmail2"]))
        s = Store()
        acct = s.add_agy_account(name)
        print(f"Qo'shildi: {acct['name']}  (HOME = {expand(acct['home'])})")
        print("Yangi oynada agy ochiladi: boshqa Google akkaunt bilan kiring, so'ng /quit yozing.")
        s.sign_in_agy(acct["name"])
        return
    log = setup_logging()
    if not deps_ok():
        sys.exit(1)
    if not single_instance():
        notify("Usage allaqachon ishlayapti — ikonka soat yonida (^ strelka ichida bo'lishi mumkin).\n"
               "Qayta ishga tushirish uchun: ikonka → o'ng tugma → Chiqish, so'ng yana ishga tushiring.")
        return
    print("Usage ishga tushdi. Ikonka soat yonida (ko'rinmasa — ^ strelka ichida).", flush=True)
    print(f"Log fayl: {log}", flush=True)
    print("Bu oynani yopsangiz dastur ham yopiladi. Fon rejimida ishlatish: start.bat", flush=True)
    App(show="--show" in argv).run()


LOG_PATH = CACHE_PATH.parent / "usage-bar.log"


def setup_logging() -> Path:
    """Errors (and native crashes) go to usage-bar.log; under pythonw there is no console at all."""
    import faulthandler
    import traceback
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    f = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    f.write(f"\n=== {datetime.now():%Y-%m-%d %H:%M:%S} start · Python {sys.version.split()[0]} · {sys.executable}\n")
    faulthandler.enable(f)
    if sys.stderr is None:   # pythonw
        sys.stderr = f
    if sys.stdout is None:
        sys.stdout = f

    def hook(t, v, tb):
        text = "".join(traceback.format_exception(t, v, tb))
        f.write(text)
        if sys.stderr is not f:
            sys.stderr.write(text)
    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)
    setup_logging.hook = hook
    return LOG_PATH


def notify(msg: str) -> None:
    """Prints, and also shows a message box when there is no console (pythonw)."""
    try:
        print(msg, flush=True)
    except Exception:
        pass
    if IS_WIN and (sys.stdout is None or not getattr(sys.stdout, "isatty", lambda: False)()):
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, msg, "Usage", 0x40)
        except Exception:
            pass


def deps_ok() -> bool:
    import importlib.util
    missing = [pkg for mod, pkg in (("PIL", "pillow"), ("pystray", "pystray")) if importlib.util.find_spec(mod) is None]
    no_tk = importlib.util.find_spec("tkinter") is None
    if not missing and not no_tk:
        return True
    lines = []
    if missing:
        lines.append(f"Kerakli kutubxonalar o'rnatilmagan: {', '.join(missing)}.\nShu buyruqni terminalda ishga tushiring:\n\n"
                     f'  & "{sys.executable}" -m pip install {" ".join(missing)}\n')
    if no_tk:
        lines.append("Bu Python'da tkinter yo'q. python.org dan Python o'rnating (\"tcl/tk and IDLE\" belgilangan bo'lsin).")
    notify("\n".join(lines))
    return False


if __name__ == "__main__":
    main(sys.argv[1:])
