# Abbot-C v0 — Data Dictionary

**Purpose:** Every term used in this project has exactly one meaning. If a term is not defined here, it is not a term of art in this project. Ambiguity in definitions is where scope creep enters.

-----

## Core concepts

### Calculator

The system itself. A process that applies a fixed rule to market data and records the result. Not a strategy engine, not an analysis tool.

### Rule

The single decision logic the calculator executes. In v0: *"Take YES on the higher-priced YES contract in each MLB moneyline market, 30 minutes before first pitch, $10 stake."* The rule is frozen for v0 and does not take inputs or exceptions.

### Bot

Singular and nominal in v0. The calculator runs one bot. "Bot" and "the calculator" are effectively synonyms in v0 usage. The word exists to preserve continuity with future multi-bot architecture.

### Paper bet

A recorded bet that was not placed on any venue. It exists only as a row in the `bets` table. No money changes hands. Used for shadowing, testing, and analyzing the rule.

### Live bet

A bet placed with real money on a real venue. **Not in v0.** The word exists only so the `mode` column has a meaningful enum.

-----

## Market terms

### Moneyline

A bet on which team wins the game outright. No point spread, no run total. Binary outcome: team wins or team does not win.

### YES contract

A Kalshi contract that pays $1 if a named team wins, $0 if it does not. One YES contract exists per team per game — so a single MLB game produces two YES contracts on Kalshi (one for the home team, one for the away team), priced inversely.

### Favorite

In v0, defined as: *the team whose YES contract has the higher price at the time of the snapshot.* Higher YES price implies the market considers that team more likely to win.

On Kalshi, a YES contract pays $1 on win. A team considered more likely to win has a *higher* YES price (closer to $1), not lower. A 62¢ YES means the market gives that team a ~62% chance. So the favorite is the team with the **higher** YES price.

### Underdog

The team whose YES contract has the lower price. Not bet on in v0.

### Entry price

The YES price (in cents, 1–99) at the moment the snapshot is taken and the bet is locked. Stored in `bets.entry_price_cents`. Does not update.

### Contracts

The number of Kalshi contracts a $10 stake buys at the entry price. Computed as `stake_dollars / (entry_price_cents / 100)`. Can be fractional for accounting purposes even though Kalshi trades whole contracts; v0 records the math cleanly rather than rounding.

-----

## Timing terms

### T-30min (or "T minus 30")

Thirty minutes before a given game's scheduled first pitch, in UTC. The moment the calculator locks its pick for that game.

### First pitch

The scheduled start time of the game as reported by the MLB Stats API, in UTC. If a game is rescheduled, the new first-pitch time governs.

### Placed at

The timestamp when the bet row was written to the database. Should be within a few seconds of T-30min under normal operation.

### Settled at

The timestamp when Kalshi's resolution was observed and written to the `settlements` table. Lags game end by Kalshi's resolution latency (typically minutes to hours for MLB).

-----

## Outcome and PnL terms

### Outcome

One of three values on a settled bet:

- **win** — the picked team won the game and Kalshi resolved the YES contract to $1.
- **loss** — the picked team did not win the game and Kalshi resolved the YES contract to $0.
- **void** — Kalshi voided or cancelled the market (postponed game past resolution deadline, scoring error reversed, etc.). Stake is returned; PnL is $0.

### Payout

Gross dollars returned on settlement. Computed as `contracts × $1` on a win, `$0` on a loss, `stake_dollars` on a void.

### PnL (Profit and Loss)

Net dollars for a single bet. Computed as `payout_dollars - stake_dollars`. A win produces positive PnL (e.g., +$6.13 on a 62¢ favorite). A loss produces negative PnL equal to `-stake_dollars` (e.g., -$10.00). A void produces $0.

### Total PnL

Sum of `pnl_dollars` across all settled bets. The headline number on the summary view.

### Total staked

Sum of `stake_dollars` across all settled bets. Used as the denominator for ROI.

### ROI (Return on Investment)

`total_pnl / total_staked`. Displayed as a percentage. Undefined (shown as "—") when total_staked is 0.

### Record

Wins and losses, displayed as `W–L` (e.g., `47–39`). Voids are excluded from the record but tracked separately.

### Equity curve

A line chart of running PnL over time, where each point is `(settled_at, cumulative_pnl_through_that_settlement)`. The x-axis is time; the y-axis is dollars. Starts at $0.

-----

## Data source terms

### Kalshi

The exchange. Source of truth for: market identity (`kalshi_ticker`), entry price (`yes_price_cents`), and resolution (`outcome`). If Kalshi says it happened, it happened, for purposes of the calculator's math.

### Kalshi ticker

The string identifier Kalshi uses for a market, following the pattern `KXMLB-<date>-<team>` (exact format to be confirmed during the discovery probe). Stored in `kalshi_ticker` columns.

### MLB Stats API

The free, public MLB data service. Source of: game schedule, team names, final scores, game status. Used for **display context only**. The calculator's math does not depend on it. If it is unavailable, the UI degrades (no scores, no team names) but bets still settle and PnL still computes.

### gamePk

MLB Stats API's identifier for a game. Stored as text in `games.game_id`. The join key between `games` and everything else.

### Snapshot

A single row in `market_snapshots`. Captures one YES contract's price at one moment. The calculator writes two snapshots per game at T-30min (home YES, away YES), then selects the favorite for the bet.

-----

## UI terms

### Summary view

The top section of the UI. Shows: record, total PnL, ROI, total bets, voids. Three-to-five numbers, large type.

### Equity curve view

A line chart showing running PnL over time. One line. X-axis: time. Y-axis: dollars. Zero line rendered.

### Detail view

A scrollable list of per-bet rows. Each row shows: date, matchup, picked team, entry price, outcome, PnL. Sorted newest first.

### Bare bones but visual

The agreed v0 UI standard. Means: no terminal strings, no raw tickers exposed to the user, team names and final scores rendered legibly, at least one logo or color treatment per team, typographic hierarchy present. Does not mean: polished, animated, responsive across every breakpoint, or designed for public release.

-----

## Status terms for `games.status`

- **scheduled** — game is on the schedule, first pitch in the future
- **live** — game in progress
- **final** — game complete, scores populated, `winning_team_abbr` set
- **postponed** — game pushed to a later date; `first_pitch_utc` should be updated when the new time is announced
- **cancelled** — game will not be played; any corresponding bet should settle as `void` once Kalshi reflects this

-----

## Terms deliberately not defined (parking lot)

The following terms are referenced in conversation but have **no meaning in v0** and must not be used in v0 code, schema, or UI:

- *edge, mispricing, fair value, true probability*
- *exception, override, blacklist, whitelist*
- *form, streak, momentum, trend*
- *unit, bankroll allocation, Kelly fraction*
- *strategy, signal, model*

If one of these words appears in a v0 pull request, that pull request is out of scope.
