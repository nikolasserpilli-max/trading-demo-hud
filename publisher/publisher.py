#!/usr/bin/env python3
"""Trading Demo HUD publisher (read-only).

Reads the VantageMultiEA status file and the local Paper Trading AI API,
keeps only a whitelisted set of public fields (no passwords, keys, tokens,
tickets, full account number or local paths) and publishes them as
state.json on `main` of the separate public data repo
nikolasserpilli-max/trading-demo-hud-data, pushed with git over SSH using a
per-repo deploy key (write access only to that data repo, not to the page).

It never sends orders, never writes to MT5/EA/PTA files and never starts
any terminal. Only stdlib. Run hidden with pythonw.exe.

Usage:
  pythonw publisher.py            -> loop forever (default every 60 s)
  python  publisher.py --once     -> one publish and exit
  python  publisher.py --dry      -> build state.json locally, no upload
  python  publisher.py --check    -> check key/known_hosts/git and remote access (never prints keys)
  python  publisher.py --build-from DIR --out FILE   (offline build from saved files)
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

VERSION = "1.1.0"
DATA_REMOTE = "git@github.com:nikolasserpilli-max/trading-demo-hud-data.git"
INTERVAL_S = int(os.environ.get("HUD_INTERVAL_S", "60"))
API_BASE = "http://127.0.0.1:8000"
API_TIMEOUT = 8

APPDATA = Path(os.environ.get("APPDATA", str(Path.home())))
LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
EA_STATUS = APPDATA / "MetaQuotes" / "Terminal" / "Common" / "Files" / "vantage_status.json"
PTA_DIR = Path(os.environ.get(
    "PTA_DIR",
    str(Path.home() / "Documents" / "Codex" / "2026-09-12" / "voglio-che-tu-costruisca-e-configuri")))
SPEND_FILE = PTA_DIR / "work" / "ai_gate" / "monthly_spend.json"
STATE_DIR = LOCALAPPDATA / "TradingDemoHud"
LEDGER_FILE = STATE_DIR / "closed_ledger.json"
CURVE_FILE = STATE_DIR / "equity_curve.json"
LOG_FILE = STATE_DIR / "publisher.log"
LAST_FILE = STATE_DIR / "last_state.json"
KEY_FILE = STATE_DIR / "deploy_ed25519"          # private key: generated on the PC, never read by this script
KNOWN_HOSTS = STATE_DIR / "known_hosts_github"   # github.com host keys (fingerprints verified)
GIT_DIR = STATE_DIR / "git"

MAGICS = {
    26091301: ("pta", "Paper Trading AI"),
    26111801: ("h1", "VantageMultiEA · H1"),
    26111802: ("scalp", "VantageMultiEA · Scalp"),
    26111803: ("swing", "VantageMultiEA · Swing"),
}
MAX_CURVE = 600
MAX_LEDGER = 5000

# ---------------------------------------------------------------- utils

def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 1_000_000:
            LOG_FILE.replace(LOG_FILE.with_suffix(".log.1"))
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
    if sys.stdout is not None:
        try:
            print(line, flush=True)
        except Exception:
            pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_utc(s):
    if not s:
        return None
    try:
        s = str(s).replace("Z", "+00:00")
        d = datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def read_json_file(p: Path):
    try:
        raw = p.read_bytes()
    except Exception:
        return None
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return json.loads(raw.decode(enc))
        except Exception:
            continue
    return None


def write_json_file(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(tmp, p)


def num(v, d=None):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return round(f, d) if d is not None else f


def pick(src, keys, nd=None):
    out = {}
    if not isinstance(src, dict):
        return out
    for k in keys:
        if k in src and src[k] is not None:
            v = src[k]
            if isinstance(v, (int, float)) and not isinstance(v, bool) and nd is not None:
                v = round(float(v), nd)
            out[k] = v
    return out


_local_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api_get(path: str, timeout=API_TIMEOUT):
    try:
        with _local_opener.open(API_BASE + path, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        log(f"API {path}: {type(e).__name__}")
        return None

# ---------------------------------------------------------------- sources

def read_ea():
    # the EA rewrites the file every 15-30 s: retry if we catch it mid-write
    for _ in range(4):
        d = read_json_file(EA_STATUS)
        if isinstance(d, dict):
            return d
        time.sleep(1.5)
    return None


def collect_live() -> dict:
    return {
        "ea": read_ea(),
        "ea_mtime": EA_STATUS.stat().st_mtime if EA_STATUS.exists() else None,
        "health": api_get("/health"),
        "watchdog": api_get("/v1/watchdog"),
        "portfolio": api_get("/portfolio/status"),
        "positions": api_get("/v1/positions"),
        "learning": api_get("/learning/stats"),
        "spend": read_json_file(SPEND_FILE),
    }


def collect_from_dir(d: Path) -> dict:
    def j(n):
        return read_json_file(d / n)
    return {
        "ea": j("vantage_status.json"), "ea_mtime": None,
        "health": j("api_health.json"), "watchdog": j("api_v1_watchdog.json"),
        "portfolio": j("api_portfolio_status.json"), "positions": j("api_v1_positions.json"),
        "learning": j("api_learning_stats.json"), "spend": j("monthly_spend.json"),
    }

# ---------------------------------------------------------------- ledger / curve (local, PC only)

def update_ledger(closed: list) -> dict:
    led = read_json_file(LEDGER_FILE) or {}
    trades = led.get("trades") or {}
    for t in closed:
        key = str(t.get("_id"))
        if key and key != "None" and key not in trades:
            trades[key] = {k: t.get(k) for k in ("time_utc", "magic", "profit", "symbol")}
    if len(trades) > MAX_LEDGER:
        keep = sorted(trades.items(), key=lambda kv: kv[1].get("time_utc") or "")[-MAX_LEDGER:]
        trades = dict(keep)
    led = {"since_utc": led.get("since_utc") or iso(utcnow()), "trades": trades}
    write_json_file(LEDGER_FILE, led)
    return led


def ledger_stats(led: dict) -> dict:
    by = {}
    for t in sorted((led.get("trades") or {}).values(), key=lambda x: x.get("time_utc") or ""):
        p = num(t.get("profit"))
        if p is None:
            continue
        s = by.setdefault(t.get("magic"), {"trades": 0, "wins": 0, "losses": 0, "gp": 0.0, "gl": 0.0,
                                           "cum": 0.0, "peak": 0.0, "mdd": 0.0, "first": t.get("time_utc")})
        s["trades"] += 1
        if p > 0:
            s["wins"] += 1; s["gp"] += p
        elif p < 0:
            s["losses"] += 1; s["gl"] += -p
        s["cum"] += p
        s["peak"] = max(s["peak"], s["cum"])
        s["mdd"] = max(s["mdd"], s["peak"] - s["cum"])
    out = {}
    for m, s in by.items():
        out[m] = {
            "trades": s["trades"], "wins": s["wins"], "losses": s["losses"],
            "win_rate": round(100 * s["wins"] / s["trades"], 2) if s["trades"] else None,
            "net_profit": round(s["cum"], 2),
            "profit_factor": round(s["gp"] / s["gl"], 2) if s["gl"] > 0 else None,
            "max_drawdown_eur": round(s["mdd"], 2),
            "first_trade_utc": s["first"],
        }
    return out


def update_curve(t: str, equity, balance) -> list:
    curve = read_json_file(CURVE_FILE) or []
    if equity is not None:
        if not curve or curve[-1][0] != t:
            curve.append([t, equity, balance])
    if len(curve) > 20000:
        curve = curve[-20000:]
    write_json_file(CURVE_FILE, curve)
    return curve


def downsample(pts, mx=MAX_CURVE):
    if len(pts) <= mx:
        return pts
    step = (len(pts) - 1) / (mx - 1)
    return [pts[round(i * step)] for i in range(mx)]

# ---------------------------------------------------------------- build public state

def bot_of(magic):
    k = MAGICS.get(int(magic)) if isinstance(magic, (int, float)) else None
    return k[0] if k else "other"


def build(src: dict, persist: bool = True) -> dict:
    now = utcnow()
    ea = src.get("ea") if isinstance(src.get("ea"), dict) else None
    out = {"schema": 1, "publisher_version": VERSION, "generated_at_utc": iso(now),
           "bots": {str(m): {"key": k, "label": l} for m, (k, l) in MAGICS.items()}}

    # ---- EA + account
    if ea:
        gen = parse_utc(ea.get("generated_at_utc"))
        out["ea_generated_at_utc"] = iso(gen) if gen else None
        acc = ea.get("account") or {}
        a = pick(acc, ["currency", "trade_mode", "leverage", "balance", "equity", "margin", "free_margin",
                       "margin_level", "day_start_equity", "daily_pnl", "daily_pnl_pct", "daily_pnl_source",
                       "daily_balance_change", "max_equity_seen", "drawdown_pct"])
        login = str(acc.get("login") or "")
        if login:
            a["login_masked"] = "•••" + login[-4:]
        a["broker"] = "Vantage"
        out["account"] = a
        e = ea.get("ea") or {}
        out["ea"] = pick(e, ["name", "version", "running", "trading_allowed", "daily_loss_blocked",
                              "symbols_monitored", "symbols_ready", "max_total_positions"])
        pos = []
        for p in ea.get("open_positions") or []:
            q = pick(p, ["symbol", "side", "volume", "open_price", "current_price", "sl", "tp", "profit",
                         "swap", "open_time_utc", "magic", "strategy"])
            q["bot"] = bot_of(p.get("magic"))
            pos.append(q)
        out["positions"] = pos
        if ea.get("other_positions_count") is not None:
            out["other_positions_count"] = ea.get("other_positions_count")
        closed = []
        for c in ea.get("closed_trades_recent") or []:
            q = pick(c, ["symbol", "side", "volume", "price", "profit", "time_utc", "magic", "strategy"])
            q["bot"] = bot_of(c.get("magic"))
            q["_id"] = c.get("ticket") or c.get("position_id")
            closed.append(q)
        strategies = []
        for key, s in (ea.get("strategies") or {}).items():
            st = pick(s, ["enabled", "magic", "entry_tf", "trend_tfs", "open_positions", "max_positions",
                          "risk_percent", "max_hold_minutes", "symbols_ready", "max_consec_losses",
                          "paused_symbols"])
            st["key"] = key
            if isinstance(s.get("stats_30d"), dict):
                st["stats_30d"] = pick(s["stats_30d"], ["trades", "wins", "losses", "win_rate", "net_profit"])
            strategies.append(st)
        out["ea_stats_30d"] = pick(ea.get("stats") or {}, ["trades_total_30d", "wins", "losses", "win_rate",
                                                            "net_profit_30d"])
        mtf = []
        for m in ea.get("mtf") or []:
            mtf.append(pick(m, ["symbol", "ready", "tfs_ready", "trend", "alignment_score"]))
        out["mtf"] = mtf

        # ledger-based stats (profit factor, drawdown) from trades this publisher has seen
        if persist:
            led = update_ledger(closed)
        else:
            led = {"since_utc": None, "trades": {str(c["_id"]): c for c in closed}}
        ls = ledger_stats(led)
        for st in strategies:
            m = st.get("magic")
            if m in ls:
                st["ledger"] = ls[m]
        out["ledger_since_utc"] = led.get("since_utc")
        out["ledger_trades"] = len(led.get("trades") or {})
        out["strategies"] = strategies
        for c in closed:
            c.pop("_id", None)
        out["closed_recent"] = closed

        if persist:
            curve = update_curve(out["ea_generated_at_utc"], num(acc.get("equity"), 2), num(acc.get("balance"), 2))
        else:
            curve = [[out["ea_generated_at_utc"], num(acc.get("equity"), 2), num(acc.get("balance"), 2)]]
        out["equity_curve"] = downsample(curve)

    # ---- Paper Trading AI
    pta = {}
    h = src.get("health")
    if isinstance(h, dict):
        pta["health"] = pick(h, ["status", "paper_trading_only", "trading_mode", "demo_execution_enabled",
                                 "live_execution", "openai_review_enabled"])
    w = src.get("watchdog")
    if isinstance(w, dict):
        wd = pick(w, ["mode", "new_entries_allowed", "reasons", "timestamp"])
        if isinstance(w.get("components"), dict):
            wd["components"] = {str(k): str(v) for k, v in w["components"].items()}
        pta["watchdog"] = wd
    pf = src.get("portfolio")
    if isinstance(pf, dict):
        assets = {}
        for k, v in (pf.get("assets") or {}).items():
            assets[k] = pick(v, ["signals", "approved", "wait", "no_trade", "closed_trades", "open_positions",
                                 "win_rate", "profit_factor", "pnl_eur", "max_drawdown_eur"])
        pta["assets"] = assets
        pta["execution"] = pick(pf.get("execution") or {}, ["orders_confirmed", "orders_rejected"])
        dec = pf.get("decision") or {}
        pta["last_decision"] = pick(dec, ["asset", "direction", "risk_status", "reason", "rejected_trade_reason"])
    lr = src.get("learning")
    if isinstance(lr, dict):
        pta["signals"] = pick(lr, ["signals_saved", "directions", "risk_statuses", "resolved_outcomes"])
    pp = src.get("positions")
    if isinstance(pp, list):
        op, cl = [], []
        for p in pp:
            q = pick(p, ["asset", "direction", "status", "execution_class", "entry", "current_sl", "tp1", "tp3",
                         "initial_size", "remaining_size", "current_r", "strategy_version", "created_at",
                         "updated_at"], nd=None)
            if isinstance(q.get("current_r"), float):
                q["current_r"] = round(q["current_r"], 2)
            (op if p.get("status") == "OPEN" else cl).append(q)
        cl.sort(key=lambda x: x.get("updated_at") or "", reverse=True)
        pta["paper_positions_open"] = op
        pta["paper_positions_closed"] = cl[:20]
    sp = src.get("spend")
    if isinstance(sp, dict):
        pta["ai_spend"] = pick(sp, ["month", "limit_usd", "estimated_spend_usd", "call_count", "blocked_by_cap",
                                    "warning_80pct", "updated_at"])
    if pta:
        out["pta"] = pta
    return out

# ---------------------------------------------------------------- GitHub push via SSH deploy key

def find_git():
    import shutil
    for c in (shutil.which("git"), r"C:\Program Files\Git\cmd\git.exe", str(STATE_DIR / "PortableGit" / "cmd" / "git.exe")):
        if c and Path(c).exists():
            return c
    return None


def find_ssh():
    for c in (r"C:\Windows\System32\OpenSSH\ssh.exe", r"C:\Program Files\Git\usr\bin\ssh.exe"):
        if Path(c).exists():
            return c
    return "ssh"


def git_env():
    fwd = lambda x: str(x).replace("\\", "/")
    env = dict(os.environ)
    env["GIT_SSH_COMMAND"] = (f'"{fwd(find_ssh())}" -i "{fwd(KEY_FILE)}" -o IdentitiesOnly=yes '
                              f'-o UserKnownHostsFile="{fwd(KNOWN_HOSTS)}" -o StrictHostKeyChecking=yes '
                              f'-o UpdateHostKeys=no -o BatchMode=yes -o ConnectTimeout=20')
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update({"GIT_AUTHOR_NAME": "trading-demo-hud publisher", "GIT_AUTHOR_EMAIL": "publisher@trading-demo-hud.invalid",
                "GIT_COMMITTER_NAME": "trading-demo-hud publisher", "GIT_COMMITTER_EMAIL": "publisher@trading-demo-hud.invalid"})
    return env


def git(args, inp=None, timeout=60):
    import subprocess
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW: never flash a console
    r = subprocess.run([find_git(), "--git-dir", str(GIT_DIR)] + args, input=inp, capture_output=True,
                       env=git_env(), timeout=timeout, creationflags=flags)
    return r.returncode, r.stdout.decode("utf-8", "replace").strip(), r.stderr.decode("utf-8", "replace").strip()


_cycles = 0


def publish(state: dict) -> bool:
    global _cycles
    if not find_git():
        log("git not found; nothing published")
        return False
    if not KEY_FILE.exists() or not KNOWN_HOSTS.exists():
        log("deploy key or known_hosts missing; nothing published")
        return False
    if not (GIT_DIR / "HEAD").exists():
        GIT_DIR.parent.mkdir(parents=True, exist_ok=True)
        c, _, e = git(["init", "--bare", "-q"])
        if c:
            log(f"git init failed: {e[:200]}")
            return False
    content = json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    c, blob, e = git(["hash-object", "-w", "--stdin"], content)
    if c:
        log(f"git hash-object failed: {e[:200]}"); return False
    c, tree, e = git(["mktree"], f"100644 blob {blob}\tstate.json\n".encode())
    if c:
        log(f"git mktree failed: {e[:200]}"); return False
    c, commit, e = git(["commit-tree", tree, "-m", "data: snapshot"])
    if c:
        log(f"git commit-tree failed: {e[:200]}"); return False
    c, _, e = git(["push", "--force", "-q", DATA_REMOTE, f"{commit}:refs/heads/main"], timeout=90)
    if c:
        log(f"git push failed: {e[:300]}"); return False
    _cycles += 1
    if _cycles % 60 == 1:
        git(["prune", "--expire=now"])  # drop old snapshots kept locally
    return True


def check_remote() -> bool:
    c, out, e = git(["ls-remote", DATA_REMOTE, "refs/heads/main"], timeout=60) if (GIT_DIR / "HEAD").exists() else (None, "", "")
    if c is None:
        GIT_DIR.parent.mkdir(parents=True, exist_ok=True)
        git(["init", "--bare", "-q"])
        c, out, e = git(["ls-remote", DATA_REMOTE, "refs/heads/main"], timeout=60)
    print("accesso al repo dati:", "ok" if c == 0 else f"ERRORE {e[:300]}")
    return c == 0

# ---------------------------------------------------------------- main

def single_instance() -> bool:
    if os.name != "nt":
        return True
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    global _mutex
    _mutex = k32.CreateMutexW(None, False, "Local\\TradingDemoHudPublisher")
    return ctypes.get_last_error() != 183  # ERROR_ALREADY_EXISTS


def run_once(dry=False) -> bool:
    state = build(collect_live(), persist=True)
    write_json_file(LAST_FILE, state)
    if dry:
        log(f"DRY ok -> {LAST_FILE}")
        return True
    ok = publish(state)
    if ok:
        acc = state.get("account") or {}
        log(f"published ok (equity {acc.get('equity')}, positions {len(state.get('positions') or [])})")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--build-from")
    ap.add_argument("--out")
    a = ap.parse_args()
    if a.build_from:
        st = build(collect_from_dir(Path(a.build_from)), persist=False)
        Path(a.out or "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
        return
    if a.check:
        print("chiave deploy:", "presente" if KEY_FILE.exists() else "MANCANTE")
        print("known_hosts:", "presente" if KNOWN_HOSTS.exists() else "MANCANTE")
        print("git:", find_git() or "MANCANTE")
        check_remote()
        print("EA status:", "ok" if EA_STATUS.exists() else "non trovato")
        print("API:", "ok" if api_get("/health", 5) else "non raggiungibile")
        return
    if a.once or a.dry:
        sys.exit(0 if run_once(dry=a.dry) else 1)
    if not single_instance():
        log("another publisher is already running; exiting")
        return
    log(f"publisher {VERSION} started, every {INTERVAL_S}s")
    while True:
        t0 = time.time()
        try:
            run_once()
        except Exception as e:
            log(f"ERROR {type(e).__name__}: {e}")
            log(traceback.format_exc().replace(str(Path.home()), "~"))
        time.sleep(max(5, INTERVAL_S - (time.time() - t0)))


if __name__ == "__main__":
    main()
