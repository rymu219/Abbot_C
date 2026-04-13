-- Abbot-C v0 schema
-- Source of truth: docs/v0/02_schema.md + docs/v0/06_build_spec.md §6.2
-- Run against a clean Neon Postgres instance.

-- ============================================================
-- Table 1: games
-- ============================================================

CREATE TABLE games (
    game_id          TEXT PRIMARY KEY,
    game_date        DATE NOT NULL,
    first_pitch_utc  TIMESTAMPTZ NOT NULL,
    home_team_abbr   TEXT NOT NULL,
    away_team_abbr   TEXT NOT NULL,
    home_team_name   TEXT NOT NULL,
    away_team_name   TEXT NOT NULL,
    status           TEXT NOT NULL
                     CHECK (status IN ('scheduled','live','final','postponed','cancelled')),
    home_score       INTEGER,
    away_score       INTEGER,
    winning_team_abbr TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_games_date ON games(game_date);
CREATE INDEX idx_games_first_pitch ON games(first_pitch_utc);

-- ============================================================
-- Table 2: market_snapshots
-- ============================================================

CREATE TABLE market_snapshots (
    snapshot_id      BIGSERIAL PRIMARY KEY,
    game_id          TEXT NOT NULL REFERENCES games(game_id),
    kalshi_ticker    TEXT NOT NULL,
    team_abbr        TEXT NOT NULL,
    yes_price_cents  INTEGER NOT NULL
                     CHECK (yes_price_cents BETWEEN 1 AND 99),
    captured_at      TIMESTAMPTZ NOT NULL,
    is_favorite      BOOLEAN NOT NULL,  -- true = higher-priced YES in the game
    UNIQUE (game_id, team_abbr, captured_at)
);

CREATE INDEX idx_snapshots_game ON market_snapshots(game_id);
CREATE INDEX idx_snapshots_ticker ON market_snapshots(kalshi_ticker);

-- ============================================================
-- Table 3: bets
-- ============================================================

CREATE TABLE bets (
    bet_id           BIGSERIAL PRIMARY KEY,
    game_id          TEXT NOT NULL REFERENCES games(game_id),
    snapshot_id      BIGINT NOT NULL REFERENCES market_snapshots(snapshot_id),
    kalshi_ticker    TEXT NOT NULL,
    team_abbr        TEXT NOT NULL,
    side             TEXT NOT NULL DEFAULT 'YES'
                     CHECK (side IN ('YES','NO')),
    entry_price_cents INTEGER NOT NULL,
    stake_dollars    NUMERIC(10,2) NOT NULL,
    contracts        NUMERIC(10,4) NOT NULL,
    placed_at        TIMESTAMPTZ NOT NULL,
    mode             TEXT NOT NULL DEFAULT 'paper'
                     CHECK (mode IN ('paper','live')),
    UNIQUE (game_id)
);

CREATE INDEX idx_bets_placed_at ON bets(placed_at);

-- ============================================================
-- Table 4: settlements
-- ============================================================

CREATE TABLE settlements (
    settlement_id    BIGSERIAL PRIMARY KEY,
    bet_id           BIGINT NOT NULL UNIQUE REFERENCES bets(bet_id),
    outcome          TEXT NOT NULL
                     CHECK (outcome IN ('win','loss','void')),
    resolution_source TEXT NOT NULL DEFAULT 'kalshi',
    payout_dollars   NUMERIC(10,2) NOT NULL,
    pnl_dollars      NUMERIC(10,2) NOT NULL,
    settled_at       TIMESTAMPTZ NOT NULL
);

CREATE INDEX idx_settlements_settled_at ON settlements(settled_at);

-- ============================================================
-- View 1: v_bet_detail
-- ============================================================

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

-- ============================================================
-- View 2: v_summary
-- ============================================================

CREATE VIEW v_summary AS
SELECT
    COUNT(*) FILTER (WHERE s.outcome = 'win')            AS wins,
    COUNT(*) FILTER (WHERE s.outcome = 'loss')           AS losses,
    COUNT(*) FILTER (WHERE s.outcome = 'void')           AS voids,
    COUNT(*) FILTER (WHERE s.outcome IS NOT NULL)        AS total_settled,
    (SELECT COUNT(*) FROM bets)                          AS total_bets,
    COALESCE(SUM(s.pnl_dollars), 0)                      AS total_pnl,
    COALESCE(SUM(b.stake_dollars) FILTER (WHERE s.outcome IS NOT NULL), 0) AS total_staked,
    CASE
        WHEN COALESCE(SUM(b.stake_dollars) FILTER (WHERE s.outcome IS NOT NULL), 0) = 0 THEN 0
        ELSE COALESCE(SUM(s.pnl_dollars), 0) / SUM(b.stake_dollars) FILTER (WHERE s.outcome IS NOT NULL)
    END                                                  AS roi,
    CASE
        WHEN COUNT(*) FILTER (WHERE s.outcome IN ('win','loss')) = 0 THEN 0
        ELSE COUNT(*) FILTER (WHERE s.outcome = 'win')::NUMERIC
             / COUNT(*) FILTER (WHERE s.outcome IN ('win','loss'))
    END                                                  AS hit_rate,
    AVG(b.entry_price_cents) FILTER (WHERE s.outcome IN ('win','loss'))
                                                         AS implied_hit_rate_cents
FROM bets b
LEFT JOIN settlements s ON s.bet_id = b.bet_id;

-- ============================================================
-- View 3: v_equity_curve
-- ============================================================

CREATE VIEW v_equity_curve AS
SELECT
    s.settled_at,
    s.pnl_dollars,
    SUM(s.pnl_dollars) OVER (ORDER BY s.settled_at) AS running_pnl
FROM settlements s
WHERE s.outcome IN ('win', 'loss')
ORDER BY s.settled_at;
