# Abbot-C v0 — Implementation Reconciliation Memo and Senior Dev Build Spec

**Authoritative build document** consolidating the charter, schema, data dictionary, UI mockup, and implementation fixes.

-----

## Executive decision

Abbot-C v0 remains a calculator, not a strategy engine. The architecture stays narrow: discover → decide → settle → display. This memo freezes the rule, resolves contradictions, adds missing implementation requirements, and defines what an engineer or Claude should build without making assumptions.

-----

## 1. Purpose of this document

This memo supersedes conflicting wording across prior Abbot-C v0 documents. Where the charter, schema, data dictionary, or mockup disagree, this memo is authoritative for implementation.

Its job is to do four things: freeze the rule, define the execution contract, reconcile the schema and UI, and remove ambiguity that would otherwise force the builder to guess.

Nothing in this document expands scope. It sharpens v0 so it can be built cleanly.

-----

## 2. Non-negotiable product statement

- Abbot-C v0 answers one question only: *If the system took YES on every MLB moneyline favorite at T-30 minutes before scheduled first pitch, with a $10 flat paper stake, what would have happened?*
- v0 is paper only.
- v0 has one bot, one frozen rule, and no discretionary exceptions.
- v0 is not expected to be profitable. The success criterion is engine correctness, not edge.

-----

## 3. Authoritative corrections to prior documents

| Area | Prior issue | Authoritative correction | Why it matters |
|------|-------------|--------------------------|----------------|
| Favorite definition | Some prior wording referred to the lower-priced YES contract as the favorite. | Favorite = the team with the higher YES price at snapshot time. | A lower-priced YES is the underdog. Getting this wrong flips the entire strategy. |
| Schema comment | `market_snapshots.is_favorite` was described incorrectly. | `is_favorite` must be true for the higher-priced YES row in the game. | Prevents data-layer contradiction with the rule. |
| MLB Stats API role | Described as display-only in places, while also controlling first pitch timing. | MLB Stats API is the source of truth for game identity and scheduled first pitch. Kalshi is the source of truth for price and settlement. | The decision clock depends on MLB schedule data. |
| UI scope | Mockup includes metrics not fully listed in the charter. | The approved v0 summary includes record, voids, total PnL, total staked, ROI, hit rate, implied hit rate, and pending bets count. | Lets engineering build the UI the mockup actually implies. |
| Logos | Some text implied logos; mockup uses abstracted team tiles. | v0 uses text, team abbreviations, scores, and abstracted color treatment. No licensed logos required. | Avoids unnecessary asset and licensing work. |

-----

## 4. Frozen execution contract

This section is the implementation spine. If code, schema comments, prompts, or UI copy conflict with this section, this section wins.

### 4.1 Rule

- At T-30 minutes before scheduled first pitch, capture the two YES prices for the MLB moneyline market corresponding to that game.
- Identify the favorite as the team with the higher YES price.
- Record one paper bet of $10 on YES for that favorite.
- Do not tune, override, blacklist, or skip games based on judgment.

### 4.2 Time semantics

- All persisted timestamps are stored in UTC.
- `scheduled_first_pitch_utc` comes from MLB Stats API.
- The valid decision window is [T-30:00, T-29:00).
- A game gets at most one decision attempt and at most one bet row.
- If the window is missed, no backfilled bet is created. The miss is logged as an operational failure, not silently repaired with later prices.
- If MLB reschedules a game before the decision window opens, the updated first pitch governs.

### 4.3 Eligibility

- A game is eligible only if it has a valid MLB game record, maps to exactly two Kalshi YES contracts for the same MLB moneyline market, both prices are present and valid, and the market is open and unresolved at capture time.
- If any of those conditions fail, no bet is written.

### 4.4 Price semantics

- The implementation must name and document the exact Kalshi quote field used for entry. Default recommendation: the current YES ask, because the system is simulating a buy of YES rather than a midpoint observation.
- The same exact price field must be used for both contracts within a game and across all games.

### 4.5 Snapshot pairing

- The two contract prices for a game must be captured from the same API response where possible.
- If separate reads are required, both prices must be captured within 5 seconds of one another or the pair is invalid.

### 4.6 Tie handling and invalid data

- If both YES prices are equal, no bet is placed.
- If one side is missing, null, out of range, suspended, or otherwise invalid, no bet is placed.
- All skipped games must be visible in logs or an operator report.

### 4.7 Fill model

- v0 uses clean accounting rather than exchange realism. Fractional contracts are allowed for paper math.
- `stake_dollars` = 10.00 exactly.
- `contracts` = `stake_dollars / (entry_price_cents / 100)`.
- Payout on win = `contracts × 1.00`.
- Payout on loss = `0.00`.
- Payout on void = `stake_dollars`.
- `pnl_dollars` = `payout_dollars - stake_dollars`.
- Fees, slippage, and partial fills are out of scope for v0.

### 4.8 Settlement

- Kalshi is the source of truth for resolution.
- Outcome enum is `win`, `loss`, or `void`.
- A cancelled or voided market settles to `void` with zero PnL.
- Once a settlement row is written, it is final unless there is a documented reconciliation rule added in a future version.

### 4.9 Idempotency

- At most one bet row per game.
- At most one settlement row per bet.
- Retried jobs must upsert or no-op, never create duplicates.

-----

## 5. Engine design and job model

The prior docs define the stages conceptually. This section turns them into buildable workers.

| Worker | Purpose | Cadence | Writes | Failure expectations |
|--------|---------|---------|--------|---------------------|
| Schedule sync | Pull MLB slate and maintain canonical `games` rows. | At startup, then periodic refresh during the day. | `games` | Must update `first_pitch_utc` for reschedules before lock. |
| Discover/decide | Find games entering the decision window, capture paired quotes, determine favorite, write one bet. | Every 1 minute recommended. | `market_snapshots`, `bets` | Must be idempotent and must not backfill missed windows. |
| Settlement poller | Find unresolved bets and read Kalshi resolution until settled. | Every 5–15 minutes recommended. | `settlements` | Must tolerate delayed resolution without duplicating rows. |
| Reconciliation check | Detect eligible games that should have a bet but do not, and bets that should have settled but have not. | Daily plus optional intraday checks. | No core rows; logs/alerts only | Used for unattended reliability. |

-----

## 6. Schema corrections and recommendations

The four-table model is retained. It is the correct v0 shape.

`games` is no longer described as merely cosmetic. It is a canonical dependency because both timing and foreign-key integrity rely on it.

`market_snapshots` remains immutable evidence. Each game should have exactly two snapshot rows for a valid decision event: one home-team YES row and one away-team YES row.

`bets` remains exactly one row per game. `settlements` remains exactly one row per bet.

### 6.1 Required schema-level fixes

- Correct the `market_snapshots.is_favorite` comment so it refers to the higher-priced YES contract.
- Add or verify check constraints or equivalent application validation for `outcome`, `side`, `mode`, and `status` enums.
- Preserve `UNIQUE(game_id)` on `bets` and `UNIQUE(bet_id)` on `settlements`.
- Consider a uniqueness guard on the decision event for snapshots if the discover worker may retry within the same minute bucket.

### 6.2 Recommended database constraints

| Object | Recommendation | Reason |
|--------|---------------|--------|
| `games.status` | Constrain to `scheduled`, `live`, `final`, `postponed`, `cancelled`. | Avoids free-text drift. |
| `market_snapshots.yes_price_cents` | Check between 1 and 99. | Rejects invalid quotes. |
| `bets.side` | Constrain to `YES` or `NO`, even though v0 only writes `YES`. | Keeps future-proof enum clean without changing scope. |
| `bets.mode` | Constrain to `paper` or `live`, even though v0 only writes `paper`. | Prevents garbage values. |
| `settlements.outcome` | Constrain to `win`, `loss`, `void`. | Supports accurate summary math. |

-----

## 7. UI specification, reconciled

The mockup is accepted as the reference direction for v0 display, but the UI must remain bare-bones, legible, and non-cockpit.

### 7.1 Summary strip

- Record shown as wins–losses, with voids as a subordinate count.
- Total PnL.
- Total staked.
- ROI.
- Hit rate = wins / settled bets.
- Implied hit rate = average entry YES price across settled bets.
- Pending bets count for today's already-locked but unresolved slate.

### 7.2 Equity curve

- One line only: cumulative realized PnL over time.
- One point per settled bet.
- Unresolved bets are excluded.
- A visible zero baseline is required.

### 7.3 Bet ledger

- Newest first.
- Must show date/time, matchup, picked team, entry price, result state, and PnL.
- For settled games, show final score when available from MLB Stats API.
- Pending bets stay at the top until settled.
- No pagination in v0.

### 7.4 Explicitly not on screen

- No pitcher data.
- No recent form or trend layer.
- No injuries or lineups.
- No strategy controls.
- No place-bet button.
- No secondary markets.

-----

## 8. Definition of done, upgraded

| Requirement | Done when | Evidence |
|-------------|-----------|----------|
| Discover works | For each eligible game, two valid YES snapshot rows are written within the decision window. | Database inspection and run logs. |
| Decide works | Exactly one bet row is written per eligible game, using the higher-priced YES contract. | Joined bet-detail query and fixture tests. |
| Settle works | Exactly one settlement row is written per bet with correct outcome and PnL. | Fixture tests plus ledger verification. |
| Display works | Summary, curve, and ledger render from live data without manual math. | UI screenshots or local run review. |
| Unattended operation works | A full slate runs without manual intervention, missed windows, or duplicate bets. | Observed daily run plus reconciliation checks. |
| Schema remains narrow | Exactly four tables and three views remain in the core schema. | Migration review. |

-----

## 9. Test cases Claude or engineering should implement before calling v0 complete

| Test case | Expected result |
|-----------|----------------|
| Normal favorite win | Two valid prices; favorite selected; winning settlement; PnL correct. |
| Normal favorite loss | Two valid prices; favorite selected; losing settlement; PnL correct. |
| Equal YES prices | No bet written. |
| One side missing | No bet written. |
| Retry safety | Repeated worker execution still yields one bet per game. |
| Void market | Settlement outcome is void; payout equals stake; PnL = 0. |
| Missed window | No late bet is created. |
| Reschedule before lock | `first_pitch_utc` updates and decision follows the new time. |

-----

## 10. Guidance for Claude or any build agent

This section is deliberately written in a way that is useful to a coding agent.

- Do not expand scope. If a decision is not required to make discover, decide, settle, or display work, do not build it.
- Treat this memo as authoritative over earlier wording.
- Document every assumption that still depends on live API discovery, especially exact Kalshi field names and ticker patterns.
- Build observability that is boring but sufficient: run logs, skipped-game logs, and reconciliation output.
- Prefer deterministic functions and idempotent writes over clever abstractions.
- Do not add a markets table, bots table, historical ingest pipeline, strategy controls, or secondary analytics layer in v0.
- If live API discovery reveals a mismatch with the assumed Kalshi ticker format or quote field names, update only the integration specifics, not the product shape.

-----

## 11. Recommended build order

1. Create the clean Neon schema with four tables and three views.
2. Implement MLB schedule sync and canonical games ingestion.
3. Implement Kalshi market discovery for today's MLB moneyline markets.
4. Implement paired T-30 snapshot capture and favorite selection.
5. Write bets with the frozen fill model.
6. Implement settlement polling and PnL writes.
7. Build `v_summary`, `v_equity_curve`, and `v_bet_detail`-driven UI.
8. Add reconciliation checks and run an unattended dry run over live paper data.

-----

## 12. Final product posture

Abbot-C v0 should feel strict, narrow, and trustworthy. It is not trying to be smart. It is trying to be correct.
