.PHONY: up down sample full sample-db test lint seed seed-cid10 migrate validate-env clean ml reset-sih scan-sih assert-sih spike-pysus spike-pysus-sinan backfill-raca-cor verify-raca-cor assert-sim ingest-sinan assert-sinan cluster-snapshots cluster-snapshots-uf retrain-forecasts assert-ml-snapshots backfill-dt-notific verify-dt-notific

# Overridable full-run scope. SIM and SIH run as separate pipeline passes
# (--sim-only / --sih-only) so each source has its own year range: SIH 2025
# is published, SIM 2025 is not yet final. SIH_UFS applies to both passes.
# Override on the command line for scoped rehearsals, e.g.:
#   make full SIH_UFS=AC,SE SIM_ANOS=2023 SIH_ANOS=2023
SIH_UFS = AC,AL,AM,AP,BA,CE,DF,ES,GO,MA,MG,MS,MT,PA,PB,PE,PI,PR,RJ,RN,RO,RR,RS,SC,SE,SP,TO
SIM_ANOS = 2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024
SIH_ANOS = 2010,2011,2012,2013,2014,2015,2016,2017,2018,2019,2020,2021,2022,2023,2024,2025

# Overridable full-run scope (3 agravos x 2015-2024 = 30 national download
# units). The grid is 3 agravos x 10 years -- NOT 3 x 27 UFs: pysus.sinan()
# has no state= parameter (live-verified, docs/pysus-270-sinan-spike-findings.md),
# so every download is already one national file spanning all 27 UFs. There is
# therefore deliberately no SINAN_UFS variable -- scoping a rehearsal means
# fewer agravos or years, never fewer UFs. Override on the command line for a
# scoped rehearsal, e.g.:
#   make ingest-sinan SINAN_AGRAVOS=ANIM SINAN_ANOS=2023
SINAN_AGRAVOS = DENG,CHIK,ANIM
SINAN_ANOS = 2015,2016,2017,2018,2019,2020,2021,2022,2023,2024

# Cluster snapshot years: run_clustering.py's --ano-referencia is
# required with no default, so a snapshot re-run means one
# invocation per year in this list -- there is no multi-year loop inside the
# Python runner itself. 2021 and 2024 are the two years the
# prospective-risk comparison needs (>=3 years apart); a pre-existing 2023
# row, if present, is left in place and does not need to be in this list.
CLUSTER_ANOS = 2021 2024

# Start PostgreSQL and run migrations
up:
	docker compose up -d db
	docker compose run --rm migrate

# Stop all services
down:
	docker compose down

# Run migrations only
migrate:
	docker compose run --rm migrate

# Load seeds (requires PostgreSQL running)
seed: validate-env
	cd backend && python -m seeds.cid10_loader
	cd backend && python -m seeds.ibge_loader
	cd backend && python -m seeds.tcu_loader
	cd backend && python -m seeds.faixa_etaria_loader

# Sample mode: no PostgreSQL required
sample:
	SAMPLE_MODE=true python scripts/generate_sample.py
	cd backend && SAMPLE_MODE=true python -m etl.sample_loader

# Seed full CID-10 catalog from DataSUS FTP DBF (requires PostgreSQL running)
seed-cid10: validate-env
	python scripts/seed_cid10_from_dbf.py

# Full pipeline: download DataSUS + ETL + materialized view refresh + ML runners
# Iterates SIH_UFS x SIM_ANOS for SIM (default: 27 UFs x 2010-2024) and
# SIH_UFS x SIH_ANOS for SIH (default: 27 UFs x 2010-2025). Resumable:
# interrupt and re-run -- already-audited (UF, ano) units are skipped via
# audit_ingestao.hash_md5 dedup, so a partial run never re-downloads or re-loads
# completed units. See docs/sih-reingestion-runbook.md for the full operator procedure.
# Also runs the SINAN pass (SINAN_AGRAVOS x SINAN_ANOS, default: 3 agravos x
# 2015-2024 = 30 units) via the ingest-sinan sub-make target. SINAN's year
# range is independent of SIM_ANOS/SIH_ANOS -- it is not coupled to the passes above,
# since python -m etl.pipeline takes a single --ano list per invocation and
# the two sources have different, independently-overridable year ranges. See
# docs/sinan-ingestion-runbook.md for the full operator procedure.
full: validate-env up seed
	$(MAKE) seed-cid10
	cd backend && python -m etl.pipeline --uf $(SIH_UFS) --ano $(SIM_ANOS) --sim-only
	cd backend && python -m etl.pipeline --uf $(SIH_UFS) --ano $(SIH_ANOS) --sih-only
	$(MAKE) ingest-sinan
	$(MAKE) ml

# One-time destructive SIH reset: clears fato_internacoes, SIH
# audit_ingestao rows and cached data/raw/SIH_*.parquet files. Run before the
# first pysus 2.7.0 full re-ingestion. SIM data is never touched.
reset-sih:
	python scripts/reset_sih_data.py --confirm

# Scan the pysus DuckLake catalog for SIH-RD file availability, no downloads.
scan-sih:
	python scripts/scan_sih_catalog.py

# Post-run completeness gate: asserts every UF-year combo in the 405-combo
# grid has plausible fato_internacoes row counts (allowlist-aware).
assert-sih:
	python scripts/assert_sih_completeness.py

# Post-run SIM completeness + duplicate gate: asserts every
# UF-year combo in the 405-combo grid has plausible fato_obitos row counts
# (allowlist-aware, with a per-UF 2024 breakout) AND that zero numero_do
# values map to more than one row (the (numero_do, revisao_numero) upsert
# key held through re-ingestion). Operator-invoked, not part of `full`.
assert-sim:
	python scripts/assert_sim_completeness.py

# One-time raca_cor backfill: reads cached SIM_*.parquet files
# directly and runs targeted UPDATEs against already-loaded fato_obitos rows
# (bypasses audit_ingestao hash dedup, which would otherwise make
# already-loaded 2010-2023 rows unreachable). Run explicitly after the SIM
# 2024 re-ingest (`make full`) completes -- not auto-triggered inside `full`.
backfill-raca-cor:
	python scripts/backfill_raca_cor.py --confirm

# Coverage gate: compares the raw-source raca_cor blank rate (from cached
# SIM_*.parquet) against the DB NULL rate, failing the run on divergence.
verify-raca-cor:
	python scripts/backfill_raca_cor.py --verify

# Re-run the pysus 2.7.0 API verification spike against live DataSUS data.
spike-pysus:
	python scripts/spike_pysus_270.py

# Re-run the SINAN field-name/API verification spike against live DataSUS data.
spike-pysus-sinan:
	python scripts/spike_pysus_270_sinan.py

# SINAN-only ingestion pass, kept separate from the SIM/SIH pass above because
# python -m etl.pipeline takes a single --ano list per invocation and SINAN's
# year range (SINAN_ANOS) is independent of SIH's (SIH_ANOS). Iterates
# SINAN_AGRAVOS x SINAN_ANOS (default: 3 agravos x 2015-2024 = 30 national
# download units). Resumable: interrupt and re-run -- already-audited
# (agravo, ano) units are skipped via audit_ingestao.hash_md5 dedup, so a
# partial run never re-downloads or re-loads completed units. See
# docs/sinan-ingestion-runbook.md for the full operator procedure.
#
# Deliberately no reset-sinan target: unlike SIH, SINAN has no prior
# ingestion to clear, so the first run is naturally clean -- do not add one.
# Deliberately no scan-sinan target: pysus's list_files() helper crashed the
# interpreter when called repeatedly in a loop on Windows during
# research; `make spike-pysus-sinan` is the reliable catalog-evidence path
# instead -- do not add one.
ingest-sinan:
	cd backend && python -m etl.pipeline --sinan-only --agravo $(SINAN_AGRAVOS) --ano $(SINAN_ANOS)

# Post-run completeness gate: asserts every (agravo, ano) combo in the
# SINAN_AGRAVOS x SINAN_ANOS grid has plausible fato_notificacoes row counts
# (allowlist-aware), plus 27-UF coverage per agravo. Operator-invoked, not
# part of `full`, matching the assert-sih/assert-sim convention.
assert-sinan:
	python scripts/assert_sinan_completeness.py

# One-time dt_notific backfill: reads cached
# SINAN_*.parquet files directly and runs targeted UPDATEs against
# already-loaded fato_notificacoes rows (bypasses audit_ingestao hash
# dedup, which would otherwise make the already-loaded ANIM/2023 rehearsal
# rows unreachable). Run explicitly whenever cached SINAN Parquet exists
# that predates migration 0020 -- not auto-triggered inside `full`.
backfill-dt-notific:
	python scripts/backfill_dt_notific.py --confirm

# Coverage gate: verifies every cached-Parquet (numero_notificacao,
# tipo_agravo) row has a non-NULL dt_notific in fato_notificacoes.
verify-dt-notific:
	python scripts/backfill_dt_notific.py --verify

# Load sample Parquet into local PostgreSQL (dev + API testing)
sample-db: validate-env up seed
	cd backend && SAMPLE_MODE=true python -m etl.pipeline

# Run ML runners: forecasting (AutoARIMA + Prophet) and clustering (K-Means).
# Requires PostgreSQL running with seeds loaded: make up seed
# Clustering loops CLUSTER_ANOS (default 2021 2024) -- one --ano-referencia
# invocation per year; `|| exit 1` inside the loop fails the whole
# make invocation if any single year's run fails, rather than the loop
# swallowing the error and reporting success.
ml: validate-env
	cd backend && python -m ml.run_forecasting
	for ano in $(CLUSTER_ANOS); do \
		(cd backend && python -m ml.run_clustering --ano-referencia $$ano) || exit 1; \
		(cd backend && python -m ml.run_clustering --grain uf --k 5 --ano-referencia $$ano) || exit 1; \
	done

# Clustering snapshots only, without the multi-hour forecast
# retrain -- lets the operator redo cluster snapshots in isolation. Loops
# CLUSTER_ANOS the same way the ml target does. See
# docs/ml-retraining-runbook.md Step 2.
cluster-snapshots: validate-env
	for ano in $(CLUSTER_ANOS); do \
		(cd backend && python -m ml.run_clustering --ano-referencia $$ano) || exit 1; \
	done

# UF-grain cluster snapshots -- ClusterScatterPlot's national view.
# A genuinely independent KMeans+PCA fit on 27 UF-level feature rows, not an
# aggregate of municipio_cluster_assignments (averaging municipio-level PCA
# scores per UF collapsed pca_y toward zero for every UF, since PCA scores
# are mean-centered at zero by construction). --k 5 by default: 27 data
# points don't support the municipio-grain default of 6 clusters as
# meaningfully. Loops CLUSTER_ANOS the same way cluster-snapshots does.
cluster-snapshots-uf: validate-env
	for ano in $(CLUSTER_ANOS); do \
		(cd backend && python -m ml.run_clustering --grain uf --k 5 --ano-referencia $$ano) || exit 1; \
	done

# Forecast retrain only, without touching cluster snapshots.
# _ANO_REFERENCIA is 2024 inside run_forecasting.py -- every
# forecast_resultados row written by this target is labelled 2024. See
# docs/ml-retraining-runbook.md Step 3.
retrain-forecasts: validate-env
	cd backend && python -m ml.run_forecasting

# Post-run completeness gate:
# asserts municipio_cluster_assignments holds >=2 ano_referencia snapshots
# >=3 years apart, forecast_resultados is anchored to ano_referencia=2024
# with a 2025-2027 horizon, and mv_taxa_municipio_ano was refreshed with
# 2024 SIM data. Operator-invoked, not part of `full`, matching the
# assert-sih/assert-sim/assert-sinan convention. See
# docs/ml-retraining-runbook.md Step 4.
assert-ml-snapshots:
	python scripts/assert_ml_snapshots.py

# Run tests (sample mode, no PostgreSQL)
test:
	cd backend && SAMPLE_MODE=true CORS_ORIGINS=http://localhost:5173 \
		pytest tests/ -v --tb=short \
			--cov=app --cov=ml --cov=etl \
			--cov-report=term-missing --cov-fail-under=70

# Lint and type check
lint:
	cd backend && ruff check . && ruff format --check .
	cd backend && mypy app etl ml
	cd frontend && npm run build 2>&1 | grep -E "error|warning" || true

# Validate environment variables
validate-env:
	python scripts/validate_env.py

# Remove generated artifacts (not data/sample — those are committed)
clean:
	find backend -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find backend -name "*.pyc" -delete 2>/dev/null || true
	rm -rf frontend/dist frontend/node_modules/.vite
