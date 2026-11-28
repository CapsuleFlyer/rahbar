# The RAGOps test suite as an image: runs as a Kubernetes Job (k8s/eval-job.yaml).
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN pip install --no-cache-dir httpx==0.28.1
WORKDIR /app
COPY . /app/eval/
RUN rm -rf /app/eval/tests /app/eval/results && mkdir -p /results && chown 10001:10001 /results
USER 10001
CMD ["python", "-m", "eval.suite", "--out", "/results"]
