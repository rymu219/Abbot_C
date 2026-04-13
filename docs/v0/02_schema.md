# Abbot-C v0 — Database Schema

**Target:** Neon (Postgres)
**Principle:** Four tables. Every column earns its place. No speculative fields.

-----

## Pre-flight: clear the existing Neon instance

Before creating this schema, the existing Abbot-C Neon database should be cleared. Two options:

- **Option A (recommended):** Spin up a brand new Neon project named `abbot-c-v0`. Leaves the old bulk-ingestion database intact as archived reference if ever needed. Cleanest separation.
- **Option B:** Drop all tables in the existing Neon project and start fresh within it. Preserves the connection string but loses the "archive" of the old approach.

Either works. Option A is preferred because it mirrors the "new project, not scope amendment" decision at the infra level.

-----

## The four tables

### 1. `games`

One row per MLB game the calculator is aware of. Populated from the MLB Stats API. This is the human-readable layer — the calculator's math does not depend on it.

```sql
CREATE TABLE games (
    game_id          TEXT PRIMARY KEY,              -- MLB Stats API gamePk, as text
    game_date        DATE NOT NULL,
    first_pitch_utc  TIMESTAMPTZ NOT NULL,
    home_team_abbr   TEXT NOT NULL,                 -- e.g., 'NYY'
    away_team_abbr   TEXT NOT NULL,                 -- e.g., 'BOS'
    home_team_name   TEXT NOT NULL,                 -- e.g., 'New York Yankees'
    away_team_name   TEXT NOT NULL,
    status           TEXT NOT NULL,                 -- 'scheduled' | 'live' | 'final' | 'postponed' | 'cancelled'
    home_score       INTEGER,                       -- null until final
    away_score       INTEGER,                       -- null until final
    winning_team_abbr TEXT,                         -- null until final; 'NYY' or 'BOS'
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_games_date ON games(game_date);
CREATE INDEX idx_games_first_pitch ON games(first_pitch_utc);
```

### 2. `market_snapshots`

One row per Kalshi market, captured at decision time (T-30 minutes). This is the *evidence* the calculator used to make its pick. Immutable once written.

```sql
CREATE TABLE market_snapshots (
    snapshot_id      BIGSERIAL PRIMARY KEY,
    game_id          TEXT NOT NULL REFERENCES games(game_id),
    kalshi_ticker    TEXT NOT NULL,                 -- e.g., 'KXMLB-25APR13-NYY'
    team_abbr        TEXT NOT NULL,                 -- which team this YES contract represents
    yes_price_cents  INTEGER NOT NULL,              -- Kalshi YES price in cents (1–99)
    captured_at      TIMESTAMPTZ NOT NULL,          -- when the snapshot was taken
    is_favorite      BOOLEAN NOT NULL,              -- true if this is the higher-priced YES in the game
    UNIQUE (game_id, team_abbr, captured_at)
);

CREATE INDEX idx_snapshots_game ON market_snapshots(game_id);
CREATE INDEX idx_snapshots_ticker ON market_snapshots(kalshi_ticker);
```

### 3. `bets`

One row per paper bet placed by the calculator. The calculator writes exactly one bet per eligible game.

```sql
CREATE TABLE bets (
    bet_id           BIGSERIAL PRIMARY KEY,
    game_id          TEXT NOT NULL REFERENCES games(game_id),
    snapshot_id      BIGINT NOT NULL REFERENCES market_snapshots(snapshot_id),
    kalshi_ticker    TEXT NOT NULL,
    team_abbr        TEXT NOT NULL,                 -- the team we picked (the favorite)
    side             TEXT NOT NULL DEFAULT 'YES',   -- 'YES' or 'NO'; v0 is always 'YES'
    entry_price_cents INTEGER NOT NULL,             -- price at entry, copied from snapshot
    stake_dollars    NUMERIC(10,2) NOT NULL,        -- $10.00 in v0
    contracts        NUMERIC(10,4) NOT NULL,        -- stake / (entry_price_cents/100)
    placed_at        TIMESTAMPTZ NOT NULL,
    mode             TEXT NOT NULL DEFAULT 'paper', -- 'paper' | 'live'; always 'paper' in v0
    UNIQUE (game_id)                                -- exactly one bet per game in v0
);

CREATE INDEX idx_bets_placed_at ON bets(placed_at);
```

### 4. `settlements`

One row per settled bet. Written after Kalshi resolves the market.

```sql
CREATE TABLE settlements (
    settlement_id    BIGSERIAL PRIMARY KEY,
    bet_id           BIGINT NOT NULL UNIQUE REFERENCES bets(bet_id),
    outcome          TEXT NOT NULL,                 -- 'win' | 'loss' | 'void'
    resolution_source TEXT NOT NULL DEFAULT 'kalshi',
    payout_dollars   NUMERIC(10,2) NOT NULL,        -- gross payout; 0 on loss
    pnl_dollars      NUMERIC(10,2) NOT NULL,        -- payout - stake; negative on loss
    settled_at       TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_settlements_settled_at ON settlements(settled_at);
```

-----

## Derived views (read-only, optional but recommended)

The UI needs aggregate numbers (record, ROI, running bankroll). These can be computed on the fly or materialized as views. For v0, simple views are fine.

```sql
-- Per-bet row for the detail UI, joined with context
CREATE VIEW v_bet_detail AS
SELECT
    b.bet_id,
    g.game_date,
    g.first_pitch_utc,
    g.home_team_abbr,
    g.away_team_abbr,
    g.home_team_name,
    g.away_team_name,
    g.home_score,
    g.away_score,
    b.team_abbr         AS picked_team,
    b.entry_price_cents,
    b.stake_dollars,
    b.contracts,
    s.outcome,
    s.pnl_dollars,
    s.settled_at
FROM bets b
JOIN games g ON g.game_id = b.game_id
LEFT JOIN settlements s ON s.bet_id = b.bet_id
ORDER BY g.first_pitch_utc DESC;

-- Running totals for summary UI
CREATE VIEW v_summary AS
SELECT
    COUNT(*) FILTER (WHERE s.outcome = 'win')            AS wins,
    COUNT(*) FILTER (WHERE s.outcome = 'loss')           AS losses,
    COUNT(*) FILTER (WHERE s.outcome = 'void')           AS voids,
    COUNT(*)                                             AS total_settled,
    COALESCE(SUM(s.pnl_dollars), 0)                      AS total_pnl,
    COALESCE(SUM(b.stake_dollars) FILTER (WHERE s.outcome IS NOT NULL), 0) AS total_staked,
    CASE
        WHEN COALESCE(SUM(b.stake_dollars) FILTER (WHERE s.outcome IS NOT NULL), 0) = 0 THEN 0
        ELSE COALESCE(SUM(s.pnl_dollars), 0) / SUM(b.stake_dollars) FILTER (WHERE s.outcome IS NOT NULL)
    END                                                  AS roi
FROM bets b
LEFT JOIN settlements s ON s.bet_id = b.bet_id;

-- Equity curve: running bankroll over time
CREATE VIEW v_equity_curve AS
SELECT
    s.settled_at,
    s.pnl_dollars,
    SUM(s.pnl_dollars) OVER (ORDER BY s.settled_at) AS running_pnl
FROM settlements s
ORDER BY s.settled_at;
```

-----

## Size estimate (free-tier sanity check)

For a full MLB season operating at v0 scope:

- ~2,430 regular-season games
- Per game: 1 game row, 2 snapshot rows (home YES + away YES), 1 bet row, 1 settlement row = **5 rows**
- Full season: ~12,150 rows total
- At roughly 200 bytes per row avg: **~2.4 MB for a full season**

Neon free tier is 0.5 GB. The v0 workload uses **less than 0.5% of the free tier** over an entire season. The prior quota problem was caused by pulling the full Kalshi firehose (all sports, every market, every tick). This schema does not repeat that pattern.

-----

## What is deliberately not in the schema

- No `bots` table (there is only one bot in v0; its config is a constant in code, not a row)
- No `pitchers`, `injuries`, `team_form`, `exceptions` tables (all parking lot)
- No `bet_variants` or `rule_versions` (v0 is one rule, frozen)
- No order-book history or tick-level price data (one snapshot per game is sufficient)
- No `markets` table separate from `market_snapshots` (snapshots are the only market data the calculator needs; a normalized market metadata table adds complexity without v0 benefit)

Each of these becomes necessary at a future version. None are necessary now.
