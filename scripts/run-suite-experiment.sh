#!/usr/bin/env bash
# Run the Part C three-level evaluation against a selected TOP_K value.
#
#   scripts/run-suite-experiment.sh run baseline 5
#   scripts/run-suite-experiment.sh run top-k-1 1
#   scripts/run-suite-experiment.sh run top-k-8 8
#   scripts/run-suite-experiment.sh restore
#
# Build/load rahbar-eval:dev after changing eval/suite/runner.py.
set -euo pipefail

NS="${NS:-rahbar}"
BASELINE_TOP_K="${BASELINE_TOP_K:-5}"
WAIT="${WAIT:-3600s}"

die() {
  echo "error: $*" >&2
  exit 1
}

run_experiment() {
  name="$1"
  top_k="$2"

  [[ "$name" =~ ^[a-z0-9-]{1,24}$ ]] || die "name must be 1-24 lowercase letters, digits or dashes"
  [[ "$top_k" =~ ^[0-9]+$ ]] || die "TOP_K must be an integer"
  (( top_k >= 1 && top_k <= 50 )) || die "TOP_K must be between 1 and 50"

  echo "Setting TOP_K=$top_k"
  kubectl -n "$NS" patch configmap rahbar-config --type merge \
    -p "{\"data\":{\"TOP_K\":\"$top_k\"}}"
  kubectl -n "$NS" rollout restart deployment/api
  kubectl -n "$NS" rollout status deployment/api --timeout=300s
  kubectl -n "$NS" exec deployment/redis -- redis-cli FLUSHALL >/dev/null

  job="exp-$name-$(date +%s)"
  sed "s/^  name: eval-suite$/  name: $job/" k8s/eval-job.yaml | kubectl apply -f -
  echo "Waiting for job/$job (TOP_K=$top_k)"
  if ! kubectl -n "$NS" wait --for=condition=complete "job/$job" --timeout="$WAIT"; then
    kubectl -n "$NS" logs "job/$job" --tail=100 || true
    die "evaluation job failed"
  fi
  kubectl -n "$NS" logs "job/$job" | tail -60

  incoming="eval/experiments/.incoming-$job"
  mkdir -p eval/experiments
  bash scripts/fetch-results.sh "$incoming"
  report="$(find "$incoming" -maxdepth 1 -type f -name 'suite-*.json' | sort | tail -n 1)"
  [[ -n "$report" ]] || die "no suite JSON report found in the results PVC"
  stem="${report%.json}"
  cp "$report" "eval/experiments/$name.json"
  [[ -f "$stem.md" ]] && cp "$stem.md" "eval/experiments/$name.md"
  rm -rf "$incoming"

  echo
  echo "Saved: eval/experiments/$name.json"
  echo "Saved: eval/experiments/$name.md"
  echo "Gate command:"
  echo ".venv/bin/python eval/experiment_gate.py --baseline eval/experiments/baseline.json --candidate eval/experiments/$name.json"
}

case "${1:-}" in
  run)
    [[ $# -eq 3 ]] || die "usage: $0 run <name> <top_k>"
    run_experiment "$2" "$3"
    ;;
  restore)
    kubectl -n "$NS" patch configmap rahbar-config --type merge \
      -p "{\"data\":{\"TOP_K\":\"$BASELINE_TOP_K\"}}"
    kubectl -n "$NS" rollout restart deployment/api
    kubectl -n "$NS" rollout status deployment/api --timeout=300s
    kubectl -n "$NS" exec deployment/redis -- redis-cli FLUSHALL >/dev/null
    echo "Restored TOP_K=$BASELINE_TOP_K"
    ;;
  *)
    die "usage: $0 run <name> <top_k> | restore"
    ;;
esac
