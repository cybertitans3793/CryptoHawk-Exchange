import os
import sqlite3
import requests
import time
import secrets
from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.security import HTTPBasic, HTTPBasicCredentials

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "hawkchain.db")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

app = FastAPI()
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# CONFIG — all sensitive values come from .env
TEAM_KEY = "frc8726"
EVENT_KEY = os.environ.get("EVENT_KEY", "2026mdpas")
TBA_API_KEY = os.environ.get("TBA_API_KEY", "")
HEADERS = {"X-TBA-Auth-Key": TBA_API_KEY}
ADMIN_USER = os.environ.get("ADMIN_USER", "8726")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "8726")

# 60-second in-memory cache for TBA market data
_market_cache: dict = {"data": None, "ts": 0.0}
CACHE_TTL = 60


@app.on_event("startup")
async def startup():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS wallets (team_number TEXT PRIMARY KEY, total_hb REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, team_number TEXT, amount REAL, timestamp INTEGER)")
    conn.commit()
    conn.close()


def get_db():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def get_market_data():
    now = time.time()
    if _market_cache["data"] and now - _market_cache["ts"] < CACHE_TTL:
        return _market_cache["data"]
    try:
        url = f"https://www.thebluealliance.com/api/v3/team/{TEAM_KEY}/event/{EVENT_KEY}/matches"
        r = requests.get(url, headers=HEADERS, timeout=5)
        matches = [m for m in r.json() if m['comp_level'] == 'qm' and m['actual_time']]
        price = 1.0
        history, labels = [1.0], ["Start"]
        if matches:
            for i, m in enumerate(sorted(matches, key=lambda x: x.get('time', 0))):
                color = 'red' if TEAM_KEY in m['alliances']['red']['team_keys'] else 'blue'
                rp = m.get('score_breakdown', {}).get(color, {}).get('rp', 0)
                if rp == 0: price *= 0.90
                elif rp == 1: price *= 1.00
                elif rp == 2: price *= 1.10
                elif rp == 3: price *= 1.20
                elif rp == 4: price *= 1.30
                elif rp == 5: price *= 1.40
                elif rp == 6: price *= 1.50
                history.append(round(price, 2))
                labels.append(f"M{i+1}")
        if len(history) < 2:
            history.append(1.0)
            labels.append("Live")
        result = (round(max(price, 0.1), 2), history, labels)
        _market_cache["data"] = result
        _market_cache["ts"] = now
        return result
    except Exception as e:
        print(f"TBA market data error: {e}")
        return 1.0, [1.0, 1.0], ["Start", "Offline"]


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    price, _, _ = get_market_data()
    return templates.TemplateResponse(request, "index.html", context={"price": price})


@app.get("/tv")
async def mobile_tv(request: Request):
    price, _, _ = get_market_data()
    conn = get_db()
    rows = conn.execute("SELECT team_number, total_hb FROM wallets ORDER BY total_hb DESC").fetchall()
    conn.close()
    return templates.TemplateResponse(request, "tv.html", context={"price": price, "wallets": rows})


@app.get("/display")
async def pit_display(request: Request):
    price, history, labels = get_market_data()
    conn = get_db()
    rows = conn.execute("SELECT team_number, total_hb FROM wallets ORDER BY total_hb DESC").fetchall()
    conn.close()
    return templates.TemplateResponse(request, "display.html", context={
        "price": price, "wallets": rows,
        "graph_data": history, "graph_labels": labels
    })


@app.post("/claim")
async def do_claim(request: Request, team_num: str = Form(...)):
    # Fast path: cookie check
    if request.cookies.get("has_claimed_talons") == "true":
        return templates.TemplateResponse(request, "already_claimed.html")

    # Event whitelist verification
    try:
        event_teams_url = f"https://www.thebluealliance.com/api/v3/event/{EVENT_KEY}/teams/keys"
        v_req = requests.get(event_teams_url, headers=HEADERS, timeout=5)
        if v_req.status_code == 200:
            allowed_teams = [t.replace("frc", "") for t in v_req.json()]
            if team_num not in allowed_teams:
                return HTMLResponse(f"<script>alert('TRADING HALTED: Team {team_num} is not at this event. Only teams currently competing at this event can be traded.'); window.location.href='/';</script>")
    except Exception as e:
        print(f"TBA whitelist error: {e}")

    # Process the claim
    price, _, _ = get_market_data()
    added = round(100 / price, 2)
    conn = get_db()
    res = conn.execute("SELECT total_hb FROM wallets WHERE team_number=?", (team_num,)).fetchone()
    new_total = round((res[0] if res else 0) + added, 2)
    conn.execute("INSERT OR REPLACE INTO wallets (team_number, total_hb) VALUES (?, ?)", (team_num, new_total))
    conn.execute("INSERT INTO transactions (team_number, amount, timestamp) VALUES (?, ?, ?)", (team_num, added, int(time.time())))
    conn.commit()
    conn.close()

    response = templates.TemplateResponse(request, "success.html", context={
        "team": team_num, "added": added, "total": new_total, "price": price
    })
    response.set_cookie(key="has_claimed_talons", value="true", max_age=172800, httponly=True, samesite="lax")
    return response


# --- ADMIN ---
security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    valid = (
        secrets.compare_digest(credentials.username, ADMIN_USER) and
        secrets.compare_digest(credentials.password, ADMIN_PASS)
    )
    if not valid:
        raise HTTPException(status_code=401, detail="Unauthorized", headers={"WWW-Authenticate": "Basic"})
    return credentials.username


@app.get("/admin")
async def admin_page(request: Request, username: str = Depends(verify_credentials)):
    price, _, _ = get_market_data()
    conn = get_db()
    wallets = conn.execute("SELECT team_number, total_hb FROM wallets ORDER BY total_hb DESC").fetchall()
    transactions = conn.execute(
        "SELECT team_number, amount, timestamp FROM transactions ORDER BY timestamp DESC LIMIT 50"
    ).fetchall()
    conn.close()
    return templates.TemplateResponse(request, "admin.html", context={
        "status": "ONLINE",
        "wallets": wallets, "transactions": transactions, "price": price
    })


@app.post("/admin/purge")
async def purge_db(username: str = Depends(verify_credentials)):
    conn = get_db()
    conn.execute("DELETE FROM wallets")
    conn.execute("DELETE FROM transactions")
    conn.commit()
    conn.close()
    return {"status": "PURGED"}


@app.post("/admin/grant")
async def grant_hb(team_num: str = Form(...), amount: float = Form(...), username: str = Depends(verify_credentials)):
    conn = get_db()
    res = conn.execute("SELECT total_hb FROM wallets WHERE team_number=?", (team_num,)).fetchone()
    new_total = round((res[0] if res else 0) + amount, 2)
    conn.execute("INSERT OR REPLACE INTO wallets (team_number, total_hb) VALUES (?, ?)", (team_num, new_total))
    conn.commit()
    conn.close()
    return {"status": "GRANTED"}


@app.post("/admin/delete")
async def delete_team(team_num: str = Form(...), username: str = Depends(verify_credentials)):
    conn = get_db()
    conn.execute("DELETE FROM wallets WHERE team_number=?", (team_num,))
    conn.execute("DELETE FROM transactions WHERE team_number=?", (team_num,))
    conn.commit()
    conn.close()
    return {"status": f"Team {team_num} deleted."}
