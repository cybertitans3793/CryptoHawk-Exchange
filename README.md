# CryptoHawk Exchange

FastAPI app for FRC Team 8726's competition "stock market" — team stock price is driven by TBA (The Blue Alliance) ranking point performance at the event.

## Current version (V1, live)

- Team-based, one-shot claim: each visitor claims Talons for one FRC team once (cookie-gated).
- Only `frc8726`'s stock is tracked; price moves off TBA ranking points per match.
- Admin panel (`/admin`) for granting/purging/deleting wallets.
- Runs in Docker on `pimedia`, served via Cloudflare tunnel.

## Running locally

```
pip install -r requirements.txt
cp .env.example .env   # fill in TBA_API_KEY, set a real ADMIN_PASS
uvicorn main:app --reload
```

## V2 — what we're building next

Planned redesign, not yet started:

- **Individual accounts** instead of one team wallet — everyone gets a starting Talon balance.
- **Every team at the event** gets a tradeable stock (not just 8726), priced by the same TBA RP formula.
- **Buy/sell trading** between matches, gated by an admin Open/Close Market toggle (works around TBA's data delay).
- **Anonymous usernames**: random scientist/engineer name assigned via cookie on first visit — no user-chosen names.
- New tables needed: `accounts` (username, cash), `holdings` (username, team, shares), plus a `market_open` flag.

Open question: is the starting balance just a flat grant, or layered with a one-time claim mechanic too?
