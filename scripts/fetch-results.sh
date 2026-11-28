#!/usr/bin/env bash
# Copy the test-suite result files from the eval-results volume into eval/results/.
set -euo pipefail
NS="${NS:-rahbar}"; NAME="results-$(date +%s)"; DEST="${1:-eval/results}"
mkdir -p "$DEST"
kubectl -n "$NS" apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata: {name: $NAME, namespace: $NS, labels: {app.kubernetes.io/name: eval, app.kubernetes.io/part-of: rahbar}}
spec:
  restartPolicy: Never
  automountServiceAccountToken: false
  securityContext: {runAsNonRoot: true, runAsUser: 10001, runAsGroup: 10001, fsGroup: 10001, seccompProfile: {type: RuntimeDefault}}
  containers:
    - name: copy
      image: rahbar-eval:dev
      imagePullPolicy: IfNotPresent
      command: ["sleep", "120"]
      securityContext: {allowPrivilegeEscalation: false, readOnlyRootFilesystem: true, capabilities: {drop: [ALL]}}
      volumeMounts: [{name: results, mountPath: /results}]
  volumes: [{name: results, persistentVolumeClaim: {claimName: eval-results}}]
YAML
kubectl -n "$NS" wait --for=condition=Ready "pod/$NAME" --timeout=90s >/dev/null
kubectl -n "$NS" cp "$NAME:/results/." "$DEST"
kubectl -n "$NS" delete pod "$NAME" --wait=false >/dev/null
ls -l "$DEST"
