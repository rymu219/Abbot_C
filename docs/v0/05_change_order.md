# Change Order — CO-001

## Abbot-C → Abbot-C v0 (The Calculator)

|                      |                                                            |
|----------------------|------------------------------------------------------------|
|**Change Order #**    |CO-001                                                      |
|**Project (Original)**|Abbot-C — Kalshi Trend Identification System                |
|**Project (Revised)** |Abbot-C v0 — The Calculator                                 |
|**Originator**        |Ryan Murphy                                                 |
|**Date Issued**       |April 13, 2026                                              |
|**Effective Date**    |April 13, 2026                                              |
|**Disposition**       |**Reset / New Project Designation** (not in-place amendment)|
|**Status**            |Approved by originator, pending execution                   |

-----

## 1. Reason for Change

The original Abbot-C scope — *bulk ingestion of Kalshi market data across all sports and market types for the purpose of trend identification* — has been determined to be premature. Two failure modes were observed:

1. **Infrastructure failure.** Bulk ingestion exhausted the Neon free-tier quota within hours of initial run. Workarounds added structural complexity to the data model that did not serve any downstream feature.
1. **Methodology failure.** Trend identification was specified before the underlying paper-trading engine existed. Analysis was being designed against data that had no execution context — *cart before the horse*.

The originator has reframed the program: **the engine must exist and be proven before any analysis layer is built on top of it.** This change order formalizes that reframe.

-----

## 2. Nature of Change

This is a **reset**, not a modification. The revised project shares only the following with the original:

- Kalshi as a data source
- MLB as the initial sport of interest
- The "Abbot-C" name (with `v0` designation appended)

Everything else — purpose, scope, data model, storage strategy, success criteria, UI — is new. A new repository and (preferably) a new Neon project will be created. The original Abbot-C codebase and database become **archived reference material**, retained but not actively maintained.

Rationale for reset vs. amendment: the two projects have incompatible mental models. Amending in place would require reconciling them in one repo and one schema, propagating the original project's complexity into the new one. The reset eliminates that risk entirely.

-----

## 3. Scope Changes — Summary Table

|Dimension                 |Original Scope                                 |Revised Scope (v0)                     |
|--------------------------|-----------------------------------------------|---------------------------------------|
|**Purpose**               |Identify trends across Kalshi markets          |Apply one fixed rule and report PnL    |
|**Project type**          |Analysis platform                              |Calculator                             |
|**Sports covered**        |All Kalshi sports                              |MLB only                               |
|**Market types**          |Moneyline, spreads, totals, props, player props|Moneyline only                         |
|**Bots / rules**          |Implicit; trend-derived                        |One bot, one fixed rule                |
|**Rule**                  |None defined                                   |YES on the favorite (higher-priced YES)|
|**Stake model**           |Not defined                                    |$10 flat per bet                       |
|**Decision timing**       |Not defined                                    |T-30 minutes before first pitch        |
|**Execution mode**        |Not defined                                    |Paper only                             |
|**Data ingestion**        |Bulk historical, all markets                   |On-demand, today's MLB moneylines only |
|**Storage**               |Neon, schema contorted to dodge quota          |Neon, narrow 4-table schema            |
|**Resolution source**     |Unspecified                                    |Kalshi market resolution               |
|**Display context source**|None                                           |MLB Stats API (free, public)           |
|**UI**                    |Not defined                                    |Summary, equity curve, bet ledger      |
|**Success criterion**     |Trends discovered                              |Engine runs unattended end-to-end      |

-----

## 4. Specification Changes — Detail

### 4.1 SPEC-001: Project Identity

- **Was:** Abbot-C, single ongoing project
- **Now:** Abbot-C v0 (The Calculator), new project. Original Abbot-C archived.
- **Artifact:** `01_charter.md`

### 4.2 SPEC-002: Purpose Statement

- **Was:** "Identify trends in Kalshi market data."
- **Now:** "Answer one question: *If I took YES on every MLB moneyline favorite at T-30 minutes with a $10 flat stake, what would have happened?*"
- **Notes:** Purpose is now binary-testable. Engine either answers it or does not.

### 4.3 SPEC-003: Data Ingestion Strategy

- **Was:** Bulk pull of Kalshi markets across all sports and types, hundreds of thousands of records, no defined consumer.
- **Now:** On-demand fetch of `KXMLB*` moneyline markets only, two snapshots per game (one per team's YES contract) at T-30 minutes before first pitch. Estimated ~5 rows per game, ~12,150 rows per full MLB season.
- **Impact:** Quota concern eliminated. Free-tier headroom estimated at >99%.

### 4.4 SPEC-004: Storage Schema

- **Was:** Schema contorted to work around quota limits; structure not aligned with engine needs.
- **Now:** Four tables — `games`, `market_snapshots`, `bets`, `settlements` — plus three read-only views (`v_bet_detail`, `v_summary`, `v_equity_curve`).
- **Artifact:** `02_schema.md`
- **Migration:** No data migrated. Original Neon instance to be cleared, or new Neon project created (preferred).

### 4.5 SPEC-005: Decision Logic

- **Was:** None defined.
- **Now:** Frozen rule. For each MLB game, at T-30 minutes before first pitch, capture both YES contract prices, identify the higher-priced YES (the favorite), record one paper bet of $10 on that contract.
- **Notes:** *Correction from prior conversational shorthand:* the favorite is the **higher-priced** YES contract, not lower. YES pays $1 on win, so a higher YES price implies higher market-implied probability of winning. This correction is reflected in all artifacts.

### 4.6 SPEC-006: Settlement Logic

- **Was:** None defined.
- **Now:** Kalshi market resolution drives outcome. YES resolves to $1 = win, $0 = loss. Kalshi market void = bet void, stake returned, PnL = $0.
- **Notes:** Settlement is fully delegated to Kalshi. The calculator does not independently verify game outcomes via MLB Stats API; that source is for display only.

### 4.7 SPEC-007: Display Strategy

- **Was:** Not defined.
- **Now:** Three views — summary strip (record, total PnL, ROI, hit rate, today's pending), equity curve (running PnL line chart), bet ledger (per-bet detail rows). Visual, branded, deliberately bare-bones. Team identification by color-tiled abbreviations (no licensed logos in v0).
- **Artifact:** `04_ui_mockup.html`
- **Constraint:** UI must degrade gracefully if MLB Stats API is unavailable. Bets and PnL continue to compute; only display context (team names, scores) is affected.

### 4.8 SPEC-008: Definition of Done

- **Was:** Implicit / undefined.
- **Now:** Six measurable criteria, all of which must be true. See `01_charter.md` §"Definition of done."

### 4.9 SPEC-009: Out-of-Scope Items (Parking Lot)

- **Was:** No formal exclusions; everything was implicitly in scope.
- **Now:** Explicit parking lot of nine deferred items, plus a dictionary section listing terms that have no meaning in v0 (`edge`, `mispricing`, `form`, `streak`, `Kelly`, `strategy`, `signal`, `model`, etc.). Use of these terms in v0 code, schema, or PRs is grounds for rejection.
- **Artifact:** `01_charter.md` and `03_data_dictionary.md`

-----

## 5. Deliverables Affected

|Deliverable                 |Status                     |Reference              |
|----------------------------|---------------------------|-----------------------|
|Project Charter             |New                        |`01_charter.md`        |
|Database Schema             |New                        |`02_schema.md`         |
|Data Dictionary             |New                        |`03_data_dictionary.md`|
|UI Mockup + Annotations     |New                        |`04_ui_mockup.html`    |
|Change Order (this document)|New                        |`05_change_order.md`   |
|Original Abbot-C codebase   |Archived                   |(existing repo)        |
|Original Abbot-C Neon DB    |To be cleared or deprecated|(existing Neon project)|
|Kalshi discovery probe spec |Outstanding                |TBD                    |
|Engine runbook              |Outstanding                |TBD (post-build)       |

-----

## 6. Risk and Cost Impact

|Risk / Cost           |Original Trajectory           |Revised Trajectory                                               |
|----------------------|------------------------------|-----------------------------------------------------------------|
|Neon free-tier overrun|Already triggered             |Eliminated (<0.5% of quota for full season)                      |
|Schema rework debt    |Accumulating                  |Cleared via reset                                                |
|Time-to-first-result  |Indefinite (no working engine)|Days to weeks (MLB games run daily during season)                |
|Cash outlay           |$0 (but compounding tech debt)|$0 (clean foundation)                                            |
|Scope creep risk      |High (no formal exclusions)   |Mitigated (explicit parking lot, frozen rule, calculator framing)|

-----

## 7. Approval and Execution

The originator (Ryan Murphy) is the sole approver of this change order. By proceeding with the actions in §4, the change order is considered executed.

**Immediate next actions, in order:**

1. Decide: new Neon project (recommended) or clear existing.
1. Create new repo `abbot-c-v0`.
1. Apply schema from `02_schema.md`.
1. Draft Kalshi discovery probe spec.
1. Implement Discover stage against the probe-validated assumptions.

-----

## 8. Reopen Conditions

This change order does not preclude future work on the items in the parking lot. Each parked item may be reintroduced via a new change order (CO-002, CO-003, etc.) **only after v0 meets its Definition of Done.** Reintroducing parked scope before v0 is complete requires a written justification and explicit re-approval.

The intent of this clause is to protect the calculator from becoming, by drift, the analysis platform it was reset away from.

-----

*End of Change Order CO-001.*
