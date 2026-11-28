# RAHBAR starter Makefile. `make` or `make help` lists the targets.
# Targets marked (needs yours) work once you have written the Dockerfiles or manifests.

SHELL := /bin/bash
NS ?= rahbar
TAG ?= dev
PY ?= python3
VENV ?= .venv
BIN := $(abspath $(VENV))/bin
# The Ingress address. On Linux this is the minikube IP. On macOS or Windows with the
# docker driver, run `minikube tunnel` in another terminal and use INGRESS_IP=127.0.0.1.
INGRESS_IP ?= $(shell minikube ip 2>/dev/null)
HOST ?= rahbar.local

.DEFAULT_GOAL := help
.PHONY: help install test lint dev cluster images apply secret index ask batch-load ingest reports ops eval-suite eval-results golden-check trace trace-report fetch eval eval-fixtures check coverage coverage-compare
help: ## list the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-14s %s\n", $$1, $$2}'

install: ## create .venv and install the api, indexer and tool dependencies
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -q --upgrade pip
	$(BIN)/pip install -q -r api/requirements-dev.txt -r indexer/requirements-dev.txt

test: ## run the api and indexer tests (stubs only: no cluster, no model, no network)
	cd api && $(BIN)/pytest -q
	cd indexer && $(BIN)/pytest -q

lint: ## ruff and mypy over everything in Python
	$(BIN)/ruff check api indexer eval corpus
	cd api && $(BIN)/mypy app
	cd indexer && $(BIN)/mypy pipeline

dev: ## run the API with stubs on http://localhost:8000, serving the chat UI too
	cd api && SERVE_UI_DIR=../ui RETRIEVER=stub LLM_PROVIDER=stub $(BIN)/uvicorn app.main:app --reload --port 8000

cluster: ## start minikube with Calico, then enable metrics-server and ingress
	minikube start --driver=docker --cni=calico --memory=6144 --cpus=4
	minikube addons enable metrics-server
	minikube addons enable ingress

images: ## build the three images and load them into minikube (needs yours: Dockerfiles)
	docker build -t rahbar-api:$(TAG) api
	docker build -t rahbar-indexer:$(TAG) indexer
	docker build -t rahbar-ui:$(TAG) ui
	docker build -t rahbar-eval:$(TAG) eval
	minikube image load rahbar-api:$(TAG)
	minikube image load rahbar-indexer:$(TAG)
	minikube image load rahbar-ui:$(TAG)
	minikube image load rahbar-eval:$(TAG)

apply: ## apply the dev overlay (needs yours: manifests)
	kubectl apply -k k8s/overlays/dev

secret: ## create the LLM key Secret from the LLM_API_KEY variable; never from a file
	@test -n "$$LLM_API_KEY" || { echo "export LLM_API_KEY=... first"; exit 1; }
	kubectl create secret generic rahbar-secret -n $(NS) \
	  --from-literal=LLM_API_KEY="$$LLM_API_KEY" --dry-run=client -o yaml | kubectl apply -f -

index: ## run the indexer once, from the CronJob's template (needs yours: CronJob reindex)
	kubectl create job --from=cronjob/reindex reindex-$$(date +%s) -n $(NS)
	@echo "watch it with: kubectl get jobs -n $(NS) -w"

ask: ## ask through the Ingress: make ask Q="What DC does the Hide action need?" (add RAW=1 for the full JSON)
	@curl -s -X POST "http://$(INGRESS_IP)/api/ask" -H "Host: $(HOST)" \
	  -H 'Content-Type: application/json' -d "$$(Q="$(Q)" $(PY) -c 'import json,os; print(json.dumps({"question": os.environ["Q"]}))')" \
	  | $(if $(RAW),$(PY) -m json.tool,Q="$(Q)" $(PY) scripts/pretty_answer.py)

batch-load: ## put a batch of new documents in the data lake: make batch-load DIR=eval/batch_b/docs
	scripts/load-corpus.sh $(DIR)

ingest: ## run the ingestion Job now (verify, quarantine, incremental) and print its report
	@n=ingest-$$(date +%s); kubectl create job --from=cronjob/reindex $$n -n $(NS) >/dev/null && echo "running $$n ..." && \
	  (kubectl wait --for=condition=complete job/$$n -n $(NS) --timeout=$(or $(WAIT),3600s) || true) && \
	  kubectl logs job/$$n -n $(NS) | grep -v '^{"ts"'; kubectl logs job/$$n -n $(NS) | grep '"ingest summary"' | cut -c1-700

reports: ## copy the verification reports from the cluster into eval/results/ (commit them)
	NS=$(NS) scripts/copy-reports.sh

ops: ## data-lake commands: make ops ARGS="list" | ARGS="counts --source X" | ARGS="rollback NAME"
	NS=$(NS) TAG=$(TAG) scripts/ops.sh $(ARGS)

eval-suite: ## run the RAGOps test suite as a Job (part B, F2); WAIT=1800s to change the timeout
	@kubectl -n $(NS) delete job eval-suite --ignore-not-found >/dev/null; kubectl apply -f k8s/eval-job.yaml >/dev/null && echo "running eval-suite ..." && \
	(kubectl -n $(NS) wait --for=condition=complete job/eval-suite --timeout=$(or $(WAIT),3600s) || true) && kubectl -n $(NS) logs job/eval-suite | tail -60

eval-results: ## copy the suite result files from the cluster into eval/results/
	NS=$(NS) scripts/fetch-results.sh

golden-check: ## check eval/golden.jsonl against the handout rules
	$(PY) eval/golden_lint.py

trace: ## everything behind one answer (RAGOps D2): make trace ID=<trace id or prefix>
	@kubectl -n $(NS) exec deploy/api -- sh -c 'cat /traces/*.jsonl' | $(PY) scripts/trace_show.py $(ID) -

trace-report: ## summarise the trace log (RAGOps D3): make trace-report SINCE=1h
	@kubectl -n $(NS) exec deploy/api -- sh -c 'cat /traces/*.jsonl' | $(PY) scripts/trace_report.py - --since $(or $(SINCE),24h)

fetch: ## download the documents listed in corpus/sources.yaml
	$(BIN)/python corpus/fetch.py

eval: ## score eval/golden.yaml through the Ingress and apply the CI gate
	$(BIN)/python eval/run_eval.py --api "http://$(INGRESS_IP)" --host $(HOST)

eval-fixtures: ## score the CI fixture golden set against a local `make dev`
	$(BIN)/python eval/run_eval.py --api http://localhost:8000 --golden eval/fixtures/golden.fixture.yaml --out /tmp/rahbar-fixture-results.json

check: ## run the submission checker
	$(PY) scripts/check_submission.py

.PHONY: corpus-load corpus-load-fixtures cov manifests reindex status
corpus-load: ## copy corpus/raw into the corpus PVC for the indexer Job
	scripts/load-corpus.sh corpus/raw

corpus-load-fixtures: ## copy the tiny CI fixture corpus into the corpus PVC
	scripts/load-corpus.sh eval/fixtures

cov: ## tests with coverage (api needs >= 60%)
	cd api && $(BIN)/pytest -q --cov=app --cov-fail-under=60
	cd indexer && $(BIN)/pytest -q

manifests: ## kustomize build + kubeconform for every overlay (needs kubectl + kubeconform)
	for o in dev prod ci; do kubectl kustomize k8s/overlays/$$o | kubeconform -strict -summary; done

reindex: ## re-index with no redeploy
	kubectl create job --from=cronjob/reindex manual-reindex-$$(date +%s) -n $(NS)

status: ## everything in the namespace
	kubectl get pods,jobs,svc,hpa,ingress,pvc -n $(NS)

.PHONY: coverage coverage-compare
coverage: ## run Part E's 40-question retrieval coverage gate
	$(PY) eval/coverage.py --api "http://$(INGRESS_IP)" --host $(HOST) --out eval/coverage/before.json

coverage-compare: ## compare Part E before/after corpus-drift reports
	$(PY) eval/coverage.py --compare eval/coverage/before.json eval/coverage/after-drift.json
