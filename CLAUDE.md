# Abbot-C v0 — The Calculator

## What this is

A paper-trading calculator for MLB moneyline bets on Kalshi. One bot, one frozen rule: take YES on the favorite (higher-priced YES contract) at T-30 minutes before first pitch, $10 flat stake.

## Current status

CO-001 has been executed. The original Abbot-C 16-phase pipeline is archived. v0 is a reset, not a continuation.

## Active development

All v0 work lives in `docs/v0/` (specs) and will be built as a clean, minimal engine. The existing `src/abbot/` code is **archived reference** — do not extend it.

## Spec documents (read these first)

- `docs/v0/01_charter.md` — purpose, rule, definition of done, parking lot
- `docs/v0/02_schema.md` — 4 tables, 3 views, Neon Postgres
- `docs/v0/03_data_dictionary.md` — every term defined, banned terms listed
- `docs/v0/04_ui_mockup.html` — visual reference for the UI
- `docs/v0/05_change_order.md` — CO-001, the formal reset from original Abbot-C

## The rule (do not change)

| Parameter | Value |
|-----------|-------|
| Market | Kalshi MLB moneyline (KXMLB*) |
| Side | YES |
| Pick | Favorite (higher-priced YES) |
| Timing | T-30 min before first pitch |
| Stake | $10 flat |
| Mode | Paper only |

## Banned terms in v0

Do not use these in code, schema, or comments: *edge, mispricing, fair value, true probability, exception, override, form, streak, momentum, trend, unit, bankroll allocation, Kelly fraction, strategy, signal, model*

## Data sources

- **Kalshi API** — market prices and resolution (required)
- **MLB Stats API** — game schedule, team names, scores (display only, graceful degradation)

## Database

Neon (Postgres). Four tables: `games`, `market_snapshots`, `bets`, `settlements`. Three views: `v_bet_detail`, `v_summary`, `v_equity_curve`. Connection via `DATABASE_URL` in `.env`.
