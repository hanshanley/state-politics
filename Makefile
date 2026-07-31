# Reproducible build for the state-politics project.
#
# Ordered by dependency. Every target is idempotent and records provenance for anything it
# fetches, so a rebuild can be interrupted and resumed without re-requesting work already done.
#
# The two crawl targets (`platforms`, `bills-dump`) hit third-party servers and take a while;
# they are deliberately not part of `all` so that `make all` on an existing checkout does the
# analysis without re-crawling anyone's website.

PY := uv run python
DATA := data/processed
OUT := outputs

.DEFAULT_GOAL := help
.PHONY: help setup all analysis figures test lint clean-derived \
        historical registry platforms official-documents caucus-priorities \
        legislators bills-dump audit

help:
	@echo "Targets:"
	@echo "  setup        install dependencies (including the local model stack)"
	@echo "  all          historical corpus + analysis + figures (no crawling)"
	@echo "  analysis     classify planks and bills, compute emphasis and divergence"
	@echo "  figures      regenerate every figure in $(OUT)/"
	@echo "  test lint audit  run tests / lint / traceability audit"
	@echo ""
	@echo "Slow, network-heavy (run explicitly):"
	@echo "  registry     verify all 100 state party websites (~10 min)"
	@echo "  platforms    discover + collect 2018-present platforms (~1 h, polite crawl)"
	@echo "  official-documents  rebuild OCR-only official party documents"
	@echo "  caucus-priorities  collect separately labelled state caucus agenda sources"
	@echo "  bills-dump   download the 10.7 GB Open States dump and extract bills (~20 min)"

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

# Needs pg_restore: `brew install libpq`. Deletes the 10.7 GB dump afterwards; its URL and
# SHA-256 stay in the provenance log so the extraction remains reproducible.
bills-dump:
	$(PY) -c "from state_politics.provenance import ProvenanceLog, download_to_file; \
		r = download_to_file( \
			'https://data.openstates.org/postgres/monthly/2026-07-public.pgdump', \
			'data/raw/openstates/2026-07-public.pgdump', \
			source_org='Open States / Plural Policy (public PostgreSQL dump)', \
			log=ProvenanceLog('data/provenance.jsonl'), timeout=300.0); \
		print('ok' if r.ok else r.error)"
	$(PY) -m state_politics.bills.ingest
	rm -f data/raw/openstates/2026-07-public.pgdump

# ---- Analysis ---------------------------------------------------------------------------

analysis: historical
	$(PY) -m state_politics.analysis.validate
	$(PY) -m state_politics.analysis.emphasis
	$(PY) -m state_politics.analysis.revealed
	$(PY) -m state_politics.analysis.validate_bills
	$(PY) -m state_politics.analysis.profiles
	$(PY) -m state_politics.analysis.diffusion
	$(PY) -m state_politics.analysis.intraparty
	$(PY) -m state_politics.analysis.elections
	$(PY) -m state_politics.analysis.terms
	$(PY) -m state_politics.analysis.state_focus
	$(PY) -m state_politics.analysis.trends
	$(PY) -m state_politics.analysis.coverage

figures:
	$(PY) scripts/plot_platform_coverage.py
	$(PY) scripts/plot_platform_gap.py
	$(PY) scripts/plot_party_emphasis.py
	$(PY) scripts/plot_stated_vs_revealed.py
	$(PY) scripts/plot_intraparty.py
	$(PY) scripts/plot_state_agenda_coverage.py
	$(PY) scripts/plot_state_focus.py
	$(PY) scripts/plot_election_focus.py

all: analysis figures

# ---- Checks -----------------------------------------------------------------------------

test:
	uv run pytest

lint:
	uv run ruff check .

audit:
	$(PY) scripts/audit_reproducibility.py
	$(PY) scripts/report_figures.py

# Derived tables and figures only. Raw downloads and the hand-labelled gold set are kept:
# one is expensive to re-fetch, the other is authored input that cannot be regenerated.
clean-derived:
	rm -f $(DATA)/*.parquet $(DATA)/*.csv $(OUT)/*.png
