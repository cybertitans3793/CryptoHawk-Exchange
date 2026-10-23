# CryptoHawk Exchange

FastAPI app for FRC Team 8726's competition "stock market" — team stock price is driven by TBA (The Blue Alliance) ranking point performance at the event.

## Current version (V1.5)

- **Individual traders**: enter your team number, get a random scientist/engineer name (cookie-saved), and invest a one-time 100 Talons in HawkBits at the current price.
- One stock (`TEAM_KEY`, default `frc8726`); price compounds per scored qual match from TBA ranking points: 0 RP = -10%, each RP +10%.
- **Trader leaderboard** (net worth) and **team leaderboard** sorted by *average* trader net worth, so extra accounts don't help a team.
- Pages: `/` claim, `/me` your account, `/tv` phone rankings, `/display` pit TV, `/admin` (Basic auth).
- Runs in Docker on `pimedia`, served via Cloudflare tunnel.

### Config (.env)

`TBA_API_KEY`, `EVENT_KEY`, `ADMIN_USER`, `ADMIN_PASS` (required — admin is disabled if unset), optional `TEAM_KEY`, `STOCK_NAME`, `DB_PATH`.

### Replay mode (testing / demos)

Set `REPLAY_MODE=1` and point `EVENT_KEY`/`TEAM_KEY` at a past event. The price then only counts the first N scored matches, and `/admin` gets **Next Match** / **Reset** buttons to step through the event.

## Running locally

```
pip install -r requirements.txt
cp .env.example .env   # fill in TBA_API_KEY, set a real ADMIN_PASS
uvicorn main:app --reload
```

## V2 — what we're building next

Planned, not yet started (V1.5 already added individual accounts + names):

- **Every team at the event** gets a tradeable stock (not just 8726), priced by the same TBA RP formula.
- **Buy/sell trading** between matches, gated by an admin Open/Close Market toggle (works around TBA's data delay).
- **Anonymous usernames**: random scientist/engineer name assigned via cookie on first visit — no user-chosen names.
- New tables needed: `accounts` (username, cash), `holdings` (username, team, shares), plus a `market_open` flag.

Open question: is the starting balance just a flat grant, or layered with a one-time claim mechanic too?
