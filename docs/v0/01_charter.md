# Abbot-C v0 — Project Charter

**Project name:** Abbot-C v0 — The Calculator
**Originator:** Ryan Murphy
**Date:** April 13, 2026

-----

## Purpose

Answer one question:

> *If I took YES on every MLB moneyline favorite at T-30 minutes with a $10 flat stake, what would have happened?*

That is the entire scope. The engine either answers it or it does not.

-----

## What the calculator does

1. **Discover** — At T-30 minutes before each MLB game's first pitch, fetch the two Kalshi YES contracts for that game (one per team).
2. **Decide** — Identify the favorite (higher-priced YES). Record one paper bet: YES on the favorite, $10 stake.
3. **Settle** — After Kalshi resolves the market, record the outcome (win, loss, void) and compute PnL.
4. **Display** — Show: record, total PnL, ROI, equity curve, bet ledger.

One bot. One rule. No exceptions.

-----

## The rule (frozen)

| Parameter       | Value                                    |
|-----------------|------------------------------------------|
| Market          | Kalshi MLB moneyline (KXMLB*)            |
| Side            | YES                                      |
| Pick            | The favorite (higher-priced YES contract)|
| Timing          | T-30 minutes before scheduled first pitch|
| Stake           | $10.00 flat                              |
| Mode            | Paper only                               |
| Exceptions      | None                                     |

The rule does not change in v0. There are no parameters to tune, no conditions to override, no inputs to vary. If the rule needs to change, that is a new change order (CO-002+).

-----

## Data sources

| Source        | Used for                                      | Required? |
|---------------|-----------------------------------------------|-----------|
| Kalshi API    | Market prices (entry), market resolution (settlement) | Yes |
| MLB Stats API | Game schedule, team names, final scores (display context) | No — UI degrades gracefully without it |

-----

## Definition of done

All six criteria must be true:

1. **Discover works.** The engine fetches today's MLB moneyline markets from Kalshi at T-30 and writes two `market_snapshots` rows per game.
2. **Decide works.** The engine identifies the favorite and writes one `bets` row per game with the correct entry price, stake, and contracts.
3. **Settle works.** After Kalshi resolves, the engine writes one `settlements` row per bet with the correct outcome and PnL.
4. **Display works.** The UI renders the summary strip, equity curve, and bet ledger from live data. Team colors and names are visible. No raw tickers exposed.
5. **End-to-end unattended.** The engine runs a full day's slate (discover → decide → settle) without manual intervention. Scheduler or cron triggers each stage.
6. **Schema is clean.** The Neon database contains exactly the four tables and three views from `02_schema.md`. No orphan tables, no legacy columns, no speculative fields.

-----

## What is not in scope (parking lot)

These items are explicitly deferred. Each may be reintroduced via a new change order **only after v0 meets its Definition of Done.**

1. Multiple bots or multiple rules
2. Live (real-money) betting
3. Non-MLB sports
4. Non-moneyline market types (spreads, totals, props, player props)
5. Pitcher, injury, lineup, or weather data
6. Rule tuning, parameter sweeps, or optimization
7. Historical backfill or backtesting
8. Multi-user access or authentication
9. Mobile or responsive UI

-----

## Banned vocabulary

The following terms have no meaning in v0 and must not appear in v0 code, schema, comments, or pull requests:

*edge, mispricing, fair value, true probability, exception, override, blacklist, whitelist, form, streak, momentum, trend, unit, bankroll allocation, Kelly fraction, strategy, signal, model*

See `03_data_dictionary.md` for the complete list and rationale.

-----

## Relationship to original Abbot-C

This project is a **reset**, not a continuation. See `05_change_order.md` (CO-001) for the full rationale. The original Abbot-C codebase and database are archived reference material. This project shares only:

- Kalshi as a data source
- MLB as the sport
- The "Abbot-C" name

Everything else is new.

-----

*End of charter.*
