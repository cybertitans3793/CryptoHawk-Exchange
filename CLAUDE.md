# CryptoHawk Exchange: working notes for Claude Code

## Layout
- `main.py`: the whole FastAPI app (TBA price feed, accounts, leaderboards, admin). `templates/`: Jinja pages.
- `tests/`: pytest. TBA is faked (`tests/conftest.py`: `FakeTBA`, `qm()` helper); `tests/fixtures/` holds real TBA responses from past events. Tests never hit the network.

## Checks
- `.venv/bin/pytest` and `.venv/bin/ruff check . && .venv/bin/ruff format .`
- Hooks in `.claude/settings.json` run these automatically: ruff after every edit to a .py file, pytest before a turn ends (only when app/test files changed). A blocked hook means fix it, not bypass it.
- New behavior gets a test. When a planned change flips current behavior (e.g. the V2 price formula or DQ rule), update the test in the same change. The xfail in `test_market.py` marks one of these.

## Where things run
- This clone is a working copy. The deployed copy is on pimedia (`/home/pi/frc/cryptohawk-app`, bind-mounted into the `cryptohawk-web` container). Python changes need `docker restart cryptohawk-web` there; templates reload live.
- Deploy flow: commit here → `git push pimedia <branch>` → on pimedia, merge into main → restart. Ask before deploying or pushing to GitHub.

## V2
Design notes are kept outside this public repo: `~/frc/cryptohawk-v2-handoff.md`. Read it before any V2 work. Keep game-balance details out of this repo, the UI, and commit messages.
