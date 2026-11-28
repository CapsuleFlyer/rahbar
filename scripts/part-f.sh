#!/usr/bin/env bash
# Part F release workflow for RAHBAR.
# Run from the repository root after the dev overlay is deployed and images are loaded.
set -Eeuo pipefail

NS="${NS:-rahbar}"
PY="${PY:-.venv/bin/python}"
WAIT="${WAIT:-3600s}"
BASELINE="${BASELINE:-eval/experiments/baseline.json}"
CANDIDATE="${CANDIDATE:-eval/experiments/candidate/candidate.json}"
GATE_CM="rahbar-gate-thresholds"

die() { echo "ERROR: $*" >&2; exit 1; }
need_file() { [[ -f "$1" ]] || die "file not found: $1"; }
need_tools() {
  command -v kubectl >/dev/null || die "kubectl is required"
  command -v python3 >/dev/null || die "python3 is required"
}
apply_gate_config() {
  local file="$1"
  kubectl -n "$NS" create configmap "$GATE_CM" \
    --from-file="thresholds.json=$file" --dry-run=client -o yaml | kubectl apply -f -
}
get_gate_config() {
  local output="$1"
  kubectl -n "$NS" get configmap "$GATE_CM" \
    -o go-template='{{index .data "thresholds.json"}}' > "$output"
  [[ -s "$output" ]] || die "ConfigMap $GATE_CM has no thresholds.json"
}
run_gate() {
  local thresholds="$1"
  need_file "$BASELINE"
  need_file "$CANDIDATE"
  [[ -x "$PY" ]] || die "Python environment not found at $PY (set PY=python3 if dependencies are installed)"
  PYTHONPATH=. "$PY" eval/experiment_gate.py \
    --baseline "$BASELINE" --candidate "$CANDIDATE" \
    --thresholds "$thresholds" --json-out eval/experiments/candidate-gate.json
}
wait_job() {
  local name="$1"
  echo "Waiting for job/$name ..."
  if ! kubectl -n "$NS" wait --for=condition=complete "job/$name" --timeout="$WAIT"; then
    kubectl -n "$NS" describe "job/$name" || true
    kubectl -n "$NS" logs "job/$name" --all-containers=true --tail=120 || true
    die "job/$name did not complete successfully"
  fi
  kubectl -n "$NS" logs "job/$name" --all-containers=true
}

install_candidate() {
  need_file "eval/experiment_thresholds.json"
  apply_gate_config "eval/experiment_thresholds.json"
  kubectl apply -f - <<'YAML'
apiVersion: v1
kind: ConfigMap
metadata:
  name: rahbar-candidate-config
  namespace: rahbar
data:
  CHROMA_COLLECTION: "rahbar-candidate"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-candidate
  namespace: rahbar
  labels:
    app.kubernetes.io/name: api-candidate
    app.kubernetes.io/part-of: rahbar
spec:
  replicas: 1
  revisionHistoryLimit: 5
  selector:
    matchLabels:
      app.kubernetes.io/name: api-candidate
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  template:
    metadata:
      labels:
        app.kubernetes.io/name: api-candidate
        app.kubernetes.io/part-of: rahbar
    spec:
      serviceAccountName: rahbar-api
      automountServiceAccountToken: false
      terminationGracePeriodSeconds: 30
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: api
          image: rahbar-api:dev
          imagePullPolicy: IfNotPresent
          ports:
            - name: http
              containerPort: 8000
          envFrom:
            - configMapRef:
                name: rahbar-config
            - configMapRef:
                name: rahbar-candidate-config
            - secretRef:
                name: rahbar-secret
                optional: true
          env:
            - name: TRACE_DIR
              value: /traces
            - name: POD_NAME
              valueFrom:
                fieldRef:
                  fieldPath: metadata.name
          startupProbe:
            httpGet:
              path: /healthz
              port: 8000
            failureThreshold: 30
            periodSeconds: 2
          livenessProbe:
            httpGet:
              path: /healthz
              port: 8000
            periodSeconds: 20
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /readyz
              port: 8000
            periodSeconds: 10
            failureThreshold: 3
            timeoutSeconds: 3
          resources:
            requests:
              cpu: 100m
              memory: 192Mi
            limits:
              cpu: 500m
              memory: 512Mi
          lifecycle:
            preStop:
              exec:
                command: ["sh", "-c", "sleep 10"]
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            - name: traces
              mountPath: /traces
      volumes:
        - name: tmp
          emptyDir: {}
        - name: traces
          persistentVolumeClaim:
            claimName: traces-data
---
apiVersion: v1
kind: Service
metadata:
  name: api-candidate
  namespace: rahbar
  labels:
    app.kubernetes.io/name: api-candidate
spec:
  type: ClusterIP
  selector:
    app.kubernetes.io/name: api-candidate
  ports:
    - name: http
      port: 8000
      targetPort: 8000
---
# NetworkPolicies are additive. These rules grant the candidate only the same dependencies
# the production API uses, and allow the eval Job to call the candidate Service.
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-candidate-ingress
  namespace: rahbar
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: api-candidate
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: eval
      ports:
        - protocol: TCP
          port: 8000
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: api-candidate-egress
  namespace: rahbar
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: api-candidate
  policyTypes: [Egress]
  egress:
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: chroma
      ports:
        - protocol: TCP
          port: 8000
    - to:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: redis
      ports:
        - protocol: TCP
          port: 6379
    - to:
        - ipBlock:
            cidr: 192.168.49.10/32
      ports:
        - protocol: TCP
          port: 11434
    - to:
        - ipBlock:
            cidr: 0.0.0.0/0
            except: [10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16]
      ports:
        - protocol: TCP
          port: 443
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: chroma-from-api-candidate
  namespace: rahbar
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: chroma
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: api-candidate
      ports:
        - protocol: TCP
          port: 8000
---
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: redis-from-api-candidate
  namespace: rahbar
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: redis
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: api-candidate
      ports:
        - protocol: TCP
          port: 6379
YAML
  local unavailable
  unavailable="$(kubectl -n "$NS" get deployment api -o jsonpath='{.spec.strategy.rollingUpdate.maxUnavailable}')"
  [[ "$unavailable" == "0" ]] || die "production api must have maxUnavailable: 0 (found: $unavailable)"
  kubectl -n "$NS" rollout status deployment/api-candidate --timeout=300s
  echo "Candidate Deployment and Service installed. Collection: rahbar-candidate"
  echo "Next: $0 candidate-index"
}

candidate_index() {
  kubectl -n "$NS" delete job candidate-indexer --ignore-not-found >/dev/null
  kubectl apply -f - <<'YAML'
apiVersion: batch/v1
kind: Job
metadata:
  name: candidate-indexer
  namespace: rahbar
  labels:
    app.kubernetes.io/name: indexer
    app.kubernetes.io/component: candidate-indexer
    app.kubernetes.io/part-of: rahbar
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels:
        app.kubernetes.io/name: indexer
        app.kubernetes.io/component: candidate-indexer
        app.kubernetes.io/part-of: rahbar
    spec:
      restartPolicy: Never
      serviceAccountName: rahbar-indexer
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: indexer
          image: rahbar-indexer:dev
          imagePullPolicy: IfNotPresent
          args: ["python", "-m", "pipeline.run"]
          envFrom:
            - configMapRef:
                name: rahbar-config
            - configMapRef:
                name: rahbar-candidate-config
          env:
            - name: CORPUS_DIR
              value: /corpus
            - name: CORPUS_WAIT_SECONDS
              value: "600"
          resources:
            requests:
              cpu: 250m
              memory: 512Mi
            limits:
              cpu: "1"
              memory: 1536Mi
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          volumeMounts:
            - name: corpus
              mountPath: /corpus
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: corpus
          persistentVolumeClaim:
            claimName: corpus-data
        - name: tmp
          emptyDir: {}
YAML
  wait_job candidate-indexer
}

candidate_eval() {
  kubectl -n "$NS" delete job eval-suite-candidate --ignore-not-found >/dev/null
  kubectl apply -f - <<'YAML'
apiVersion: batch/v1
kind: Job
metadata:
  name: eval-suite-candidate
  namespace: rahbar
  labels:
    app.kubernetes.io/name: eval
    app.kubernetes.io/component: eval-suite-candidate
    app.kubernetes.io/part-of: rahbar
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 86400
  template:
    metadata:
      labels:
        app.kubernetes.io/name: eval
        app.kubernetes.io/component: eval-suite-candidate
        app.kubernetes.io/part-of: rahbar
    spec:
      restartPolicy: Never
      serviceAccountName: rahbar-eval
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 10001
        runAsGroup: 10001
        fsGroup: 10001
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: eval
          image: rahbar-eval:dev
          imagePullPolicy: IfNotPresent
          args: ["python", "-m", "eval.suite", "--api", "http://api-candidate:8000", "--out", "/results", "--delay", "3", "--repeat", "2", "--batch-b"]
          envFrom:
            - configMapRef:
                name: rahbar-config
            - configMapRef:
                name: rahbar-candidate-config
            - secretRef:
                name: rahbar-secret
                optional: true
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          resources:
            requests:
              cpu: 50m
              memory: 96Mi
            limits:
              cpu: 500m
              memory: 256Mi
          volumeMounts:
            - name: results
              mountPath: /results
            - name: tmp
              mountPath: /tmp
      volumes:
        - name: results
          persistentVolumeClaim:
            claimName: eval-results
        - name: tmp
          emptyDir: {}
YAML
  wait_job eval-suite-candidate
  mkdir -p eval/experiments/candidate
  local incoming report
  incoming="eval/experiments/.incoming-candidate-$(date +%s)"
  bash scripts/fetch-results.sh "$incoming"
  report="$(find "$incoming" -maxdepth 1 -type f -name 'suite-*.json' -printf '%T@ %p\n' | sort -nr | head -n 1 | cut -d' ' -f2-)"
  [[ -n "$report" ]] || die "candidate suite did not leave a JSON report on eval-results PVC"
  cp "$report" "$CANDIDATE"
  if [[ -f "${report%.json}.md" ]]; then
    cp "${report%.json}.md" "${CANDIDATE%.json}.md"
  fi
  rm -rf "$incoming"
  echo "Candidate report saved: $CANDIDATE"
}

gate() {
  local tmp
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' RETURN
  get_gate_config "$tmp"
  run_gate "$tmp"
}

threshold_demo() {
  local original strict
  original="$(mktemp)"
  strict="$(mktemp)"
  get_gate_config "$original"
  python3 - "$original" "$strict" <<'PY'
import json
import sys
from pathlib import Path

data = json.loads(Path(sys.argv[1]).read_text())
data.setdefault("rules", {}).setdefault("module.gap", {})["min_delta"] = 0.5
Path(sys.argv[2]).write_text(json.dumps(data, indent=2) + "\n")
PY
  echo "Changing ConfigMap threshold only; no image build or deployment restart."
  apply_gate_config "$strict"
  if run_gate "$strict"; then
    apply_gate_config "$original"
    rm -f "$original" "$strict"
    die "strict threshold unexpectedly passed; inspect the candidate report"
  else
    echo "Expected result: candidate rejected by the stricter ConfigMap threshold."
  fi
  apply_gate_config "$original"
  echo "Restored original thresholds in ConfigMap."
  if run_gate "$original"; then
    echo "Original threshold outcome: PASS (same images, no rebuild)."
  else
    echo "Original threshold outcome: FAIL; candidate already violates the normal gate."
  fi
  rm -f "$original" "$strict"
}

promote() {
  gate
  echo "Gate passed. Promoting the candidate collection to the production API."
  kubectl -n "$NS" set env deployment/api CHROMA_COLLECTION=rahbar-candidate
  kubectl -n "$NS" rollout status deployment/api --timeout=300s
  echo "Production API now serves rahbar-candidate."
}

rollback_demo() {
  local before
  before="$(kubectl -n "$NS" get deployment api -o jsonpath='{.spec.template.spec.containers[0].env[?(@.name=="CHROMA_COLLECTION")].value}')"
  if [[ -z "$before" ]]; then
    before="$(kubectl -n "$NS" get configmap rahbar-config -o jsonpath='{.data.CHROMA_COLLECTION}')"
  fi
  echo "Current release collection: $before"
  echo "Applying a deliberately invalid collection and embedding pin."
  kubectl -n "$NS" set env deployment/api \
    CHROMA_COLLECTION=rahbar-f-does-not-exist EMBED_MODEL=rahbar-invalid-embedding
  if kubectl -n "$NS" rollout status deployment/api --timeout=180s; then
    die "bad release unexpectedly became Ready; do not continue without investigating"
  else
    echo "Bad release did not become Ready. maxUnavailable=0 keeps the previous replicas available."
  fi
  kubectl -n "$NS" rollout undo deployment/api
  kubectl -n "$NS" rollout status deployment/api --timeout=300s
  echo "Rollback complete. Previous collection should be: $before"
  echo "Now run: make ask Q=\"What does the Dodge action do?\""
  echo "Then:   make trace ID=<trace-id>"
  echo "The trace should show collection.name=$before and embedding.index_embed_model=nomic-embed-text."
}

status() {
  kubectl -n "$NS" get all,pvc,configmap,cronjob,job
}

resources() {
  kubectl -n "$NS" top pods
  kubectl top nodes
}

need_tools
case "${1:-}" in
  install) install_candidate ;;
  candidate-index) candidate_index ;;
  candidate-eval) candidate_eval ;;
  gate) gate ;;
  threshold-demo) threshold_demo ;;
  promote) promote ;;
  rollback-demo) rollback_demo ;;
  status) status ;;
  resources) resources ;;
  *)
    cat <<'HELP'
Usage: scripts/part-f.sh <command>

  install          create gate ConfigMap, candidate Deployment/Service and policies
  candidate-index  index the current corpus into rahbar-candidate
  candidate-eval  run the golden suite against api-candidate and save its report
  gate             apply the current ConfigMap thresholds to baseline/candidate reports
  threshold-demo   tighten one ConfigMap threshold, show rejection, restore and re-run
  promote          promote rahbar-candidate only if the gate passes
  rollback-demo    deploy a deliberately bad config, rollout undo, then trace
  status           kubectl get all,pvc,configmap,cronjob,job
  resources        kubectl top pods and nodes

Override BASELINE, CANDIDATE, PY, NS or WAIT through environment variables.
HELP
    exit 2
    ;;
esac
