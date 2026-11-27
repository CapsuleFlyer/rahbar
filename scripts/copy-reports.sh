#!/usr/bin/env bash
# Copy the verification reports from the corpus volume into the repository, so the results of
# your own runs can be committed.
#   scripts/copy-reports.sh [DEST]        (default: eval/results)
set -euo pipefail
DEST="${1:-eval/results}"; NS="${NS:-rahbar}"; NAME="reports-$(date +%s)"
mkdir -p "$DEST"
kubectl -n "$NS" apply -f - >/dev/null <<YAML
apiVersion: v1
kind: Pod
metadata: {name: $NAME, namespace: $NS}
spec:
  restartPolicy: Never
  containers:
    - name: reader
      image: busybox:1.36.1
      command: ["sleep", "300"]
      volumeMounts: [{name: corpus, mountPath: /corpus, readOnly: true}]
  volumes: [{name: corpus, persistentVolumeClaim: {claimName: corpus-data}}]
YAML
trap 'kubectl -n "$NS" delete pod "$NAME" --wait=false >/dev/null' EXIT
kubectl -n "$NS" wait --for=condition=Ready "pod/$NAME" --timeout=120s >/dev/null
kubectl -n "$NS" exec "$NAME" -- sh -c 'tar -C /corpus/reports -cf - .' | tar -C "$DEST" -xf -
echo "reports now in $DEST:"
ls "$DEST"
