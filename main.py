import os
import random
import secrets
import sqlite3
import threading
import time
from contextlib import asynccontextmanager

import requests
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("DB_PATH", os.path.join(BASE_DIR, "hawkchain.db"))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# CONFIG — all sensitive values come from .env
TEAM_KEY = os.environ.get("TEAM_KEY", "frc8726")          # the team whose stock is traded
STOCK_NAME = os.environ.get("STOCK_NAME", "CryptoHawks")
EVENT_KEY = os.environ.get("EVENT_KEY", "2026mdpas")
TBA_API_KEY = os.environ.get("TBA_API_KEY", "")
ADMIN_USER = os.environ.get("ADMIN_USER", "")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "")
# Replay mode: price only counts the first N scored matches; admin steps N forward.
# Used to test/demo against a past event.
REPLAY_MODE = os.environ.get("REPLAY_MODE", "") == "1"

INVEST_TALONS = 100
COOKIE_NAME = "hawk_id"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30

TBA = requests.Session()
TBA.headers.update({"X-TBA-Auth-Key": TBA_API_KEY, "User-Agent": "CryptoHawk-Exchange"})

STEM_NAMES = [
    "Curie", "Tesla", "Lovelace", "Turing", "Hopper", "Newton", "Einstein", "Noether",
    "Ramanujan", "Feynman", "Franklin", "Katherine Johnson", "Darwin", "Galileo", "Kepler",
    "Faraday", "Maxwell", "Bohr", "Pascal", "Euler", "Gauss", "Hypatia", "Archimedes",
    "Euclid", "Fibonacci", "Babbage", "Edison", "Volta", "Ampere", "Ohm", "Hertz", "Kelvin",
    "Planck", "Heisenberg", "Schrodinger", "Dirac", "Fermi", "Meitner", "Goodall", "Carson",
    "Sagan", "Hawking", "Pasteur", "Mendel", "Mendeleev", "Copernicus", "Brahe", "Herschel",
    "Hubble", "Leavitt", "Sally Ride", "Jemison", "Goddard", "Wright", "Lamarr", "Shannon",
    "Von Neumann", "Boole", "Leibniz", "Descartes", "Fourier", "Laplace", "Riemann", "Hilbert",
    "Godel", "Cantor", "Galois", "Germain", "Mirzakhani", "Chien-Shiung Wu", "Carver",
    "Banneker", "Salk", "Fleming", "Raman", "Bose", "Hodgkin", "McClintock", "Hooke", "Boyle",
    "Dalton", "Lavoisier", "Kwolek", "Wozniak", "Berners-Lee", "Margaret Hamilton", "Vaughan",
    "Mary Jackson", "Ochoa", "Tharp", "Nightingale", "Watt", "Bell", "Morse", "Diesel",
    "Kamen", "Woodie Flowers", "Lister", "Yalow", "Tu Youyou",
]
ROMAN = ["II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"]


@asynccontextmanager
async def lifespan(app):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT UNIQUE NOT NULL,
        name TEXT UNIQUE NOT NULL,
        team_number TEXT NOT NULL,
        hb REAL NOT NULL,
        buy_price REAL NOT NULL,
        created INTEGER NOT NULL)""")
    conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()
    yield


app = FastAPI(lifespan=lifespan)
templates = Jinja2Templates(directory=TEMPLATES_DIR)


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def get_setting(key, default=None):
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, str(value)))
    conn.commit()
    conn.close()


# --- MARKET DATA ---
# Price compounds per scored qual match: 0 RP = -10%, each RP adds +10% (6 RP = +50%).
CACHE_TTL = 60
_market_lock = threading.Lock()
_market = {"result": None, "ts": 0.0, "ok_ts": 0.0}


def _fetch_market():
    r = TBA.get(f"https://www.thebluealliance.com/api/v3/team/{TEAM_KEY}/event/{EVENT_KEY}/matches", timeout=5)
    r.raise_for_status()
    matches = sorted((m for m in r.json() if m["comp_level"] == "qm"), key=lambda m: m.get("time") or 0)
    scored = []
    for m in matches:
        color = "red" if TEAM_KEY in m["alliances"]["red"]["team_keys"] else "blue"
        # score_breakdown is null until TBA posts the score — skip unscored matches
        side = (m.get("score_breakdown") or {}).get(color) or {}
        if "rp" in side:
            scored.append((m["match_number"], side["rp"]))
    total = len(scored)
    if REPLAY_MODE:
        scored = scored[:int(get_setting("replay_n", 0))]
    price, history, labels = 1.0, [1.0], ["Start"]
    for match_number, rp in scored:
        price *= 0.9 + 0.1 * min(max(rp, 0), 6)
        history.append(round(price, 2))
        labels.append(f"Q{match_number}")
    return {"price": round(max(price, 0.1), 2), "history": history, "labels": labels,
            "scored": len(scored), "total_scored": total, "online": True}


def get_market(force=False):
    with _market_lock:
        now = time.time()
        if not force and _market["result"] and now - _market["ts"] < CACHE_TTL:
            return _market["result"]
        try:
            _market["result"] = _fetch_market()
            _market["ok_ts"] = now
        except Exception as e:
            print(f"TBA market data error: {e}")
            if _market["result"]:
                # keep the last good price rather than resetting to 1.0
                _market["result"] = {**_market["result"], "online": False}
        _market["ts"] = now
        return _market["result"]


_teams = {"keys": None, "ts": 0.0}


def get_event_teams():
    """Team numbers at the event, cached 10 min. None if TBA has never answered."""
    now = time.time()
    if _teams["keys"] is None or now - _teams["ts"] > 600:
        try:
            r = TBA.get(f"https://www.thebluealliance.com/api/v3/event/{EVENT_KEY}/teams/keys", timeout=5)
            r.raise_for_status()
            _teams["keys"] = {t.replace("frc", "") for t in r.json()}
            _teams["ts"] = now
        except Exception as e:
            print(f"TBA team list error: {e}")
    return _teams["keys"]


# --- ACCOUNTS / LEADERBOARDS ---

def pick_name(conn):
    used = {r["name"] for r in conn.execute("SELECT name FROM accounts")}
    free = [n for n in STEM_NAMES if n not in used]
    if free:
        return random.choice(free)
    for suffix in ROMAN:
        free = [f"{n} {suffix}" for n in STEM_NAMES if f"{n} {suffix}" not in used]
        if free:
            return random.choice(free)
    return f"{random.choice(STEM_NAMES)} #{secrets.randbelow(10000)}"


def current_account(request: Request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    conn = get_db()
    row = conn.execute("SELECT * FROM accounts WHERE token=?", (token,)).fetchone()
    conn.close()
    return row


def leaderboards(price):
    conn = get_db()
    people = conn.execute("SELECT name, team_number, hb, buy_price FROM accounts ORDER BY hb DESC, created ASC").fetchall()
    teams = conn.execute("""SELECT team_number, COUNT(*) AS members, SUM(hb) AS total_hb, AVG(hb) AS avg_hb
                            FROM accounts GROUP BY team_number
                            ORDER BY avg_hb DESC, members DESC""").fetchall()
    conn.close()
    people = [{"rank": i + 1, "name": p["name"], "team": p["team_number"], "hb": p["hb"],
               "value": p["hb"] * price, "buy_price": p["buy_price"]} for i, p in enumerate(people)]
    teams = [{"rank": i + 1, "team": t["team_number"], "members": t["members"],
              "avg": t["avg_hb"] * price, "total": t["total_hb"] * price} for i, t in enumerate(teams)]
    return people, teams


def market_context(market):
    return {"price": market["price"] if market else 1.0, "online": bool(market and market["online"]),
            "stock_name": STOCK_NAME, "team_label": TEAM_KEY.replace("frc", "")}


# --- PUBLIC PAGES ---

@app.get("/", response_class=HTMLResponse)
def home(request: Request, error: str = ""):
    if current_account(request):
        return RedirectResponse("/me", status_code=303)
    ctx = market_context(get_market())
    ctx.update({"error": error, "bad_team": request.query_params.get("team", ""), "invest": INVEST_TALONS})
    return templates.TemplateResponse(request, "index.html", context=ctx)


@app.post("/claim")
def do_claim(request: Request, team_num: str = Form(...)):
    if current_account(request):
        return RedirectResponse("/me", status_code=303)

    team_num = team_num.strip().lstrip("0")
    if not team_num.isdigit():
        return RedirectResponse("/?error=badteam", status_code=303)
    allowed = get_event_teams()
    market = get_market()
    if allowed is None or market is None:
        return RedirectResponse("/?error=offline", status_code=303)
    if team_num not in allowed:
        return RedirectResponse(f"/?error=notatevent&team={team_num}", status_code=303)

    price = market["price"]
    token = secrets.token_urlsafe(24)
    conn = get_db()
    for _ in range(5):
        try:
            conn.execute("INSERT INTO accounts (token, name, team_number, hb, buy_price, created) VALUES (?, ?, ?, ?, ?, ?)",
                         (token, pick_name(conn), team_num, round(INVEST_TALONS / price, 4), price, int(time.time())))
            conn.commit()
            break
        except sqlite3.IntegrityError:
            continue  # two people grabbed the same name at once — pick again
    conn.close()

    response = RedirectResponse("/me?new=1", status_code=303)
    response.set_cookie(key=COOKIE_NAME, value=token, max_age=COOKIE_MAX_AGE, httponly=True, samesite="lax")
    return response


@app.get("/me", response_class=HTMLResponse)
def my_account(request: Request, new: int = 0):
    acct = current_account(request)
    if not acct:
        return RedirectResponse("/", status_code=303)
    ctx = market_context(get_market())
    people, teams = leaderboards(ctx["price"])
    me = next(p for p in people if p["name"] == acct["name"])
    my_team = next(t for t in teams if t["team"] == acct["team_number"])
    ctx.update({"me": me, "my_team": my_team, "people_count": len(people), "team_count": len(teams),
                "new": bool(new), "invest": INVEST_TALONS})
    return templates.TemplateResponse(request, "me.html", context=ctx)


@app.get("/tv", response_class=HTMLResponse)
def rankings(request: Request):
    ctx = market_context(get_market())
    people, teams = leaderboards(ctx["price"])
    acct = current_account(request)
    ctx.update({"people": people, "teams": teams, "my_name": acct["name"] if acct else None,
                "my_team": acct["team_number"] if acct else None})
    return templates.TemplateResponse(request, "tv.html", context=ctx)


@app.get("/display", response_class=HTMLResponse)
def pit_display(request: Request):
    market = get_market()
    ctx = market_context(market)
    people, teams = leaderboards(ctx["price"])
    ctx.update({"people": people, "teams": teams,
                "graph_data": market["history"] if market else [1.0],
                "graph_labels": market["labels"] if market else ["Start"]})
    return templates.TemplateResponse(request, "display.html", context=ctx)


# --- ADMIN ---
security = HTTPBasic()


def verify_credentials(request: Request, credentials: HTTPBasicCredentials = Depends(security)):
    valid = (
        bool(ADMIN_USER and ADMIN_PASS) and
        secrets.compare_digest(credentials.username, ADMIN_USER) and
        secrets.compare_digest(credentials.password, ADMIN_PASS)
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    # Browsers resend Basic auth automatically, so refuse admin POSTs that come from another site
    origin = request.headers.get("origin")
    if request.method == "POST" and origin and origin.split("://")[-1] != request.headers.get("host"):
        raise HTTPException(status_code=403, detail="Cross-site request refused")
    return credentials.username


def back_to_admin(msg):
    return RedirectResponse(f"/admin?msg={msg}", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request, msg: str = "", username: str = Depends(verify_credentials)):
    market = get_market()
    ctx = market_context(market)
    people, teams = leaderboards(ctx["price"])
    ctx.update({"people": people, "teams": teams, "msg": msg, "event_key": EVENT_KEY,
                "replay": REPLAY_MODE, "market": market})
    return templates.TemplateResponse(request, "admin.html", context=ctx)


@app.post("/admin/grant")
def grant_hb(name: str = Form(...), amount: float = Form(...), username: str = Depends(verify_credentials)):
    conn = get_db()
    cur = conn.execute("UPDATE accounts SET hb = hb + ? WHERE name=?", (amount, name.strip()))
    conn.commit()
    conn.close()
    return back_to_admin(f"Granted {amount:g} HB to {name}" if cur.rowcount else f"No account named {name}")


@app.post("/admin/delete_account")
def delete_account(name: str = Form(...), username: str = Depends(verify_credentials)):
    conn = get_db()
    cur = conn.execute("DELETE FROM accounts WHERE name=?", (name.strip(),))
    conn.commit()
    conn.close()
    return back_to_admin(f"Deleted {name}" if cur.rowcount else f"No account named {name}")


@app.post("/admin/delete_team")
def delete_team(team_num: str = Form(...), username: str = Depends(verify_credentials)):
    conn = get_db()
    cur = conn.execute("DELETE FROM accounts WHERE team_number=?", (team_num.strip(),))
    conn.commit()
    conn.close()
    return back_to_admin(f"Deleted {cur.rowcount} accounts from team {team_num}")


@app.post("/admin/purge")
def purge_db(username: str = Depends(verify_credentials)):
    conn = get_db()
    conn.execute("DELETE FROM accounts")
    conn.commit()
    conn.close()
    return back_to_admin("All accounts purged")


@app.post("/admin/replay")
def replay_step(action: str = Form(...), username: str = Depends(verify_credentials)):
    if not REPLAY_MODE:
        raise HTTPException(status_code=404)
    n = int(get_setting("replay_n", 0))
    total = (get_market(force=True) or {}).get("total_scored", 0)
    n = 0 if action == "reset" else min(n + 1, total)
    set_setting("replay_n", n)
    get_market(force=True)
    return back_to_admin(f"Replay at match {n}")
