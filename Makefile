# Reproducible build for the state-politics project.
#
# Ordered by dependency. Fetches record provenance. Resume support is target-specific:
# retained dumps require matching checksums; incomplete downloads restart, and extraction
# refuses existing outputs rather than overwriting an interrupted run.
#
# The two crawl targets (`platforms`, `bills-dump`) hit third-party servers and take a while;
# they are deliberately not part of `all` so that `make all` on an existing checkout does the
# analysis without re-crawling anyone's website.

PY := uv run python
DATA := data/processed
OUT := outputs
GRAPH_OUT ?= $(OUT)
OPENSTATES_MONTH ?= 2026-10
BILL_DUMP ?= data/raw/openstates/$(OPENSTATES_MONTH)-public.pgdump
CHECKPOINT ?= data/models/modernbert-topics
MODEL_ARGS := --checkpoint "$(CHECKPOINT)"

.DEFAULT_GOAL := help
.PHONY: help setup all analysis figures legacy-figures test lint clean-derived \
        historical registry platforms official-documents caucus-priorities \
        legislators bills-dump audit audit-current source-ledger preview

help:
	@echo "Targets:"
	@echo "  setup        install dependencies (including the local model stack)"
	@echo "  all          historical corpus + analysis + figures (no crawling)"
	@echo "  analysis     classify planks and bills, compute emphasis and divergence"
	@echo "  figures      render current dual-background graphs from pinned saved tables"
	@echo "               GRAPH_OUT=outputs/current-render-REPLAY for a fresh replay"
	@echo "  legacy-figures  old analytical producers (not revalidated findings)"
	@echo "  test lint audit  run tests / lint / traceability audit"
	@echo "  audit-current  verify pinned current research bytes (not scientific certification)"
	@echo "  source-ledger preview  inventory sources / build local-only evidence preview"
	@echo "  clean-derived  disabled: retained evidence and legacy figures must be preserved"
	@echo ""
	@echo "Slow, network-heavy (run explicitly):"
	@echo "  registry     verify all 100 state party websites (~10 min)"
	@echo "  platforms    discover + collect 2018-present platforms (~1 h, polite crawl)"
	@echo "  official-documents  rebuild OCR-only official party documents"
	@echo "  caucus-priorities  collect separately labelled state caucus agenda sources"
	@echo "  bills-dump   download the 10.7 GB dump; extract bills/actions/votes (~25 min)"

setup:
	uv sync --extra dev --extra models --extra ocr

# ---- Stream A: platforms ----------------------------------------------------------------

historical: $(DATA)/platforms_historical.parquet
$(DATA)/platforms_historical.parquet:
	$(PY) -m state_politics.platforms.dataverse

registry:
	$(PY) -m state_politics.platforms.registry

platforms:
	$(PY) -m state_politics.platforms.discover
	$(PY) -m state_politics.platforms.collect --resume
	$(MAKE) official-documents

official-documents:
	uv run --extra ocr python -m state_politics.platforms.official_documents

# Supplemental stated-agenda evidence for states whose party committees publish no platform.
# Intentionally separate from `platforms`: caucus priorities are not party committee platforms.
caucus-priorities:
	$(PY) -m state_politics.caucuses

# ---- Stream B: bills --------------------------------------------------------------------

legislators: $(DATA)/legislators_current.parquet
$(DATA)/legislators_current.parquet:
	$(PY) -m state_politics.bills.people

# Preflight before downloading. Retain the source after extraction for recovery and audit.
bills-dump:
	$(PY) -c "from state_politics.bills.openstates_dump import find_pg_restore; print(find_pg_restore())"
	$(PY) -m state_politics.bills.openstates_dump \
		--dump "$(BILL_DUMP)" --download-month "$(OPENSTATES_MONTH)" --list
	$(PY) -m state_politics.bills.ingest --dump "$(BILL_DUMP)"

# ---- Analysis ---------------------------------------------------------------------------

analysis: historical
	$(PY) -m state_politics.analysis.validate
	$(PY) -m state_politics.analysis.emphasis $(MODEL_ARGS)
	$(PY) -m state_politics.analysis.revealed $(MODEL_ARGS)
	$(PY) -m state_politics.analysis.outcomes
	$(PY) -m state_politics.analysis.validate_bills $(MODEL_ARGS)
	$(PY) -m state_politics.analysis.profiles
	$(PY) -m state_politics.analysis.diffusion
	$(PY) -m state_politics.analysis.intraparty
	$(PY) -m state_politics.analysis.elections
	$(PY) -m state_politics.analysis.terms
	$(PY) -m state_politics.analysis.state_focus $(MODEL_ARGS)
	$(PY) -m state_politics.analysis.trends
	$(PY) -m state_politics.analysis.coverage

figures:
	$(PY) scripts/render_current_graphs.py --out-dir "$(GRAPH_OUT)"

legacy-figures:
	$(PY) scripts/plot_platform_coverage.py
	$(PY) scripts/plot_platform_gap.py
	$(PY) scripts/plot_party_emphasis.py
	$(PY) scripts/plot_stated_vs_revealed.py
	$(PY) scripts/plot_intraparty.py
	$(PY) scripts/plot_state_agenda_coverage.py
	$(PY) scripts/plot_state_focus.py
	$(PY) scripts/plot_all_state_focus.py
	$(PY) scripts/plot_election_focus.py
	$(PY) scripts/plot_bill_trends.py
	$(PY) scripts/plot_outcomes.py

all: analysis figures

source-ledger:
	$(PY) -m state_politics.analysis.coverage --sources-only --out "$(DATA)/source_coverage.json"

preview: source-ledger
	$(PY) scripts/build_site.py

# ---- Checks -----------------------------------------------------------------------------

test:
	uv run pytest

lint:
	uv run ruff check .

audit:
	$(PY) scripts/audit_reproducibility.py
	$(PY) scripts/report_figures.py

audit-current:
	$(PY) scripts/audit_current_research.py

# The legacy broad deletion conflicts with retained source and figure evidence.
clean-derived:
	@printf '%s\n' \
	  "Refusing destructive cleanup of retained tables and legacy figures." \
	  "No files were deleted. Use scripts/reclaim_generated_storage.py with a fresh dry-run report."
	@exit 2
