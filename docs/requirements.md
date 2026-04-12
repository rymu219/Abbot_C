# Abbot -- Requirements & Control Document (MVP)

---

## Section 1: System Constraints & Non-Negotiables

### Purpose

Define what Abbot is not allowed to become.

### Constraints

Abbot is not:

- a SaaS product
- multi-user
- a collaboration tool
- a consulting product
- a generic dashboard
- a reporting tool for its own sake
- a customer-facing platform
- a marketplace

### Interaction Constraints

- not a chat interface
- not a copilot
- not conversational-first

### Decision Constraints

- not a black box
- not opaque AI logic

All outputs must be: explainable, traceable, auditable.

### Autonomy Constraints

- no autonomous deployment
- no autonomous capital allocation

System may: suggest, test, analyze.

Operator must: approve, deploy, manage.

### Optimization Constraints

Do not optimize for: max backtest profit.

Optimize for: robustness, repeatability, simplicity.

### Dependency Constraints

- no dependence on external validation
- no reliance on customers/users

### Architecture Constraints

- modular
- no premature abstraction
- narrow before flexible

### Control Principle

Clarity, control, and trust override everything.

---

## Section 2: Core System Loop

### Pipeline

1. Ingest
2. Distill
3. Classify
4. Detect Transitions
5. Identify Candidates
6. Generate Config
7. Test
8. Analyze
9. Approve
10. Deploy
11. Monitor
12. Review
13. Refine

### Rules

- no stage skipped
- each stage produces outputs
- each stage is inspectable
- each stage is logged

### Separation

- ingest != interpret
- test != approve
- deploy != refine

### Human Boundary

System suggests. Operator decides.

---

## Section 3: Signal & Monk Discovery

### Principle

Only create Monks from recurring, tradable structure.

### Gate 1: Structural Reality

- >= 5-10 occurrences
- consistent structure
- belongs to a family

### Gate 2: Tradability

- sufficient liquidity
- acceptable spread
- enough time to act

### Gate 3: Repeatability

- consistent behavior
- not one-off
- testable sample size

### Gate 4: Distinctness

- not redundant with existing Monks

### Outputs

- IGNORE
- WATCH
- DISCOVERY_CANDIDATE
- MONK_CANDIDATE

---

## Section 4: Monk Configuration

### Principle

Monk = explicit, versioned rule system.

### Logic Sources

- observed data
- known strategy archetypes
- prior Monk performance
- external validated principles

### Required Fields

**Identity:** name, archetype, platform, domain, family

**Entry:** trigger (state/transition), thresholds, liquidity rules, spread rules, timing

**Exit / Kill:** exit logic, invalidation, kill conditions

**Risk:** exposure, limits, cooldown

**Deployment:** mode, approval status

**Metadata:** version, parent, rationale

---

## Section 5: Testing & Monk Discipline

### Priority Order

1. sample size
2. robustness
3. profitability
4. drawdown
5. explainability

### Rules

- no conclusions from low sample size
- robustness required before trust
- profitability meaningless without robustness

### Single-Purpose Rule

One Monk = one job.

### Cross-Monk Logic

- future capability only
- not MVP

---

## Section 6: Visibility & Logging

### Principle

Surface significance. Preserve everything.

### Always Visible

- major transitions
- candidate Monks
- deployable Monks
- performance changes
- drawdown events
- risk alerts

### Drill-Down Required

Every metric must trace to: source data, features, thresholds, config version.

### Full Logging

Log everything: ingestion, features, states, transitions, candidates, configs, tests, deployments, trades, errors.

---

## Section 7: Risk Controls

### Stop Conditions

**Risk:** drawdown breach, exposure breach, loss clustering

**Behavior:** invalid triggers, logic deviation

**Market:** low liquidity, wide spreads

**System:** API failures, stale data

**Data:** missing/corrupt inputs

### Actions

pause, kill, downgrade, require review

### Rule

When in doubt, stop.

---

## Section 8: Evolution & Monk Lineage

### Core Rule

No two active Monks do the same job.

### New Monk

Only when: new structure exists, current Monks miss it.

### Versioning

- versions refine, do not multiply
- one live version per Monk

### Shadowing

- allowed for testing
- not parallel live deployment

### Promotion

Must pass: testing, robustness, risk constraints.

### Replacement

- explicit
- old version paused/retired

### Retirement

When: obsolete, degraded, replaced.

---

## Section 9: Capture, Coverage, and Opportunity Accounting

### Purpose

Define what "capture" means and how system coverage is measured.

### 9.1 Core Principle

Capture is not "all possible trades." Capture is: participation in eligible opportunity units.

### 9.2 Eligible Opportunity Unit

A unit is: a distinct event, within a defined family, that reaches ACTIONABLE state, and meets liquidity thresholds, spread thresholds, and timing constraints.

### 9.3 Capture Definitions

**Portfolio Capture:** captured opportunity units / total eligible opportunity units. A unit is captured if at least one Monk acted on it.

**Monk Capture:** units acted on by Monk / units eligible for that Monk.

**Overlap Rate:** multi-Monk units / captured units.

**Unique Contribution:** units captured only by this Monk / captured units.

### 9.4 Coverage Layers

1. Data Capture -- How much of universe is ingested
2. Structural Capture -- How much structure is recognized
3. Candidate Capture -- How much structure becomes Monk candidates
4. Execution Capture -- How much eligible opportunity is acted on

### 9.5 Uncaptured Opportunity

Eligible opportunity units that were observed, were tradable, but no Monk acted on. This is the primary signal for refinement or new Monk creation.

### 9.6 MVP Simplification

- Opportunity Unit = ACTIONABLE event
- Captured = >= 1 Monk acted
- Uncaptured = none acted
- Duplicate = > 1 Monk acted

Track: total units, captured units, uncaptured units, duplicate units.

### 9.7 Control Principles

- capture is conditional, not absolute
- portfolio capture matters more than raw trade count
- duplication must be measured
- unique contribution determines Monk value

---

## Summary

100% capture means: all eligible opportunity units within the defined system scope are acted on. Not all theoretical trades.

---

## Final Summary

Abbot is a controlled system that:

- ingests market data
- distills it into structure
- identifies opportunities
- generates Monk logic
- tests Monks
- requires human approval
- deploys Monks
- monitors performance
- measures capture
- evolves through disciplined lineage

Core rules:

- explainability over opacity
- robustness over optimization
- discipline over proliferation
- one Monk, one job
- human control at all critical decisions

This is the full MVP operating doctrine.
