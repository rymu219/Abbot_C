# Abbot

Private automation hub for managing Monks.

## Setup

```bash
# Install uv (if not installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Copy and configure environment
cp .env.example .env
# Edit .env with your Kalshi API key, private key path, and database URL

# Verify Kalshi authentication
uv run python scripts/verify_kalshi_auth.py

# Run tests
uv run pytest

# Run CLI
uv run abbot --help
```

## Project Structure

- `src/abbot/types/` — Core type system (enums, models, validation)
- `src/abbot/kalshi/` — Kalshi API access and ingestion
- `src/abbot/pipeline/` — Distillation, features, state classification, candidate discovery
- `src/abbot/monk/` — Monk configuration, testing, approval, deployment
- `src/abbot/monitor/` — Activity logging, audit trail, performance metrics
- `src/abbot/cli/` — Command-line interface
- `src/abbot/web/` — Web UI for review and analysis
- `configs/` — Versioned scoring weights and Monk configurations
- `docs/` — Specification documents
