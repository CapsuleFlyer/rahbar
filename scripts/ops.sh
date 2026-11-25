#!/usr/bin/env bash
# Run a data-lake command in a one-off pod that mounts the corpus volume (RAGOps A2).
#   scripts/ops.sh list
#   scripts/ops.sh counts [--source NAME]
#   scripts/ops.sh rollback NAME
# The pod carries the indexer's labels, so the NetworkPolicy lets it reach Chroma. Nothing it
# runs writes to Chroma: only the ingestion Job does (see pipeline/ops.py).
set -euo pipefail
NS="${NS:-rahbar}"; TAG="${TAG:-dev}"; NAME="ops-$(date +%s)"
ARGS_JSON=$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' "$@")
kubectl -n "$NS" apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata:
  name: $NAME
  namespace: $NS
  labels: {app.kubernetes.io/name: indexer, app.kubernetes.io/part-of: rahbar}
spec:
  restartPolicy: Never
  serviceAccountName: rahbar-indexer
  automountServiceAccountToken: false
  securityContext: {runAsNonRoot: true, runAsUser: 10001, runAsGroup: 10001, fsGroup: 10001, seccompProfile: {type: RuntimeDefault}}
  containers:
    - name: ops
      image: rahbar-indexer:$TAG
      imagePullPolicy: IfNotPresent
      command: ["python", "-m", "pipeline.ops"]
      args: $ARGS_JSON
      envFrom: [{configMapRef: {name: rahbar-config}}]
      env: [{name: CORPUS_DIR, value: /corpus}]
      securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
      resources:
        requests: {cpu: 50m, memory: 128Mi}
        limits: {cpu: 500m, memory: 512Mi}
      volumeMounts: [{name: corpus, mountPath: /corpus}, {name: tmp, mountPath: /tmp}]
  volumes:
    - {name: corpus, persistentVolumeClaim: {claimName: corpus-data}}
    - {name: tmp, emptyDir: {}}
YAML
for _ in $(seq 1 90); do
  phase=$(kubectl -n "$NS" get pod "$NAME" -o jsonpath='{.status.phase}')
  [ "$phase" = "Succeeded" ] || [ "$phase" = "Failed" ] && break
  sleep 2
done
kubectl -n "$NS" logs "$NAME"
kubectl -n "$NS" delete pod "$NAME" --wait=false >/dev/null
[ "$phase" = "Succeeded" ]
