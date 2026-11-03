"""One-shot repo cleanup: remove the starter-kit leftovers and bring text up to date.

Run from the repo root:  python cleanup.py     (then delete this file)
Safe to run twice: it skips anything already done.
"""
from pathlib import Path

ROOT = Path(".")


def read(path):
    raw = Path(path).read_bytes().decode("utf-8")
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def write(path, text, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    Path(path).write_bytes(text.encode("utf-8"))


def sub(path, old, new):
    p = Path(path)
    if not p.exists():
        print("missing :", path)
        return
    text, crlf = read(p)
    if old not in text:
        print("skip    :", path, "|", old[:55].replace("\n", " "))
        return
    write(p, text.replace(old, new), crlf)
    print("fixed   :", path)


def remove(path):
    p = Path(path)
    if p.exists():
        p.unlink()
        print("deleted :", path)


# ---------------------------------------------------------------- delete what is not needed
for f in [
    "STARTER.md",                      # starter-kit handout; the case study is the source of truth
    "docs/adr/0000-template.md",       # ADR template; the four real ADRs exist
    "scripts/push-commits.sh",         # bootstrap script for the starter; points at deleted files
    "k8s/base/.gitkeep",               # these folders have real files now
    "k8s/overlays/dev/.gitkeep",
    "k8s/overlays/prod/.gitkeep",
    ".github/workflows/.gitkeep",
]:
    remove(f)

# ---------------------------------------------------------------- leftover FAST-NUCES text
sub("indexer/pipeline/models.py", "e.g. Academic_Rules_Handbook_2026.pdf", "e.g. srd-5-2-1-2024.pdf")
sub("indexer/pipeline/models.py", 'e.g. "2026-06"; from corpus/sources.yaml', 'e.g. "5.2.1"; from corpus/sources.yaml')
sub("indexer/pipeline/models.py", 'e.g. "5.4 Academic Warning"', 'e.g. "Exhaustion [Condition]"')
sub("api/app/services/intent.py", 'r"prospectus|report)\\b"', 'r"srd|compendium|errata|report)\\b"')
sub("corpus/fetch.py",
    'sys.exit("corpus/sources.yaml not found. Copy corpus/sources.example.yaml to "\n                 "corpus/sources.yaml and keep the documents you want.")',
    'sys.exit("corpus/sources.yaml not found: it lists the corpus documents.")')

# ---------------------------------------------------------------- README
sub("README.md",
    "cp corpus/sources.example.yaml corpus/sources.yaml; make fetch   # download the corpus",
    "make fetch                         # download the corpus (or: python corpus/fetch.py)")
sub("README.md", 'make ask Q="What is the minimum attendance to sit the final exam?"',
    'make ask Q="What DC does the Hide action need?"')
sub("README.md",
    "The `dev` overlay starts in stub mode (dummy index); see `k8s/README.md` to switch to the real pipeline.\n",
    "The `dev` overlay runs the real pipeline: Chroma retrieval and Ollama on your laptop (`host.minikube.internal:11434`).\n")
sub("README.md", "![screenshot](docs/evidence/screenshot.png)  <!-- TODO: add after the first run -->\n\n", "")
sub("README.md",
    ", and `MANUAL-STEPS.md` for what is still open.",
    ".")

# ---------------------------------------------------------------- dev overlay: real mode, no stubs
OVERLAY = """# Local minikube: the real pipeline. Chroma retrieval, Ollama on the laptop for embeddings and
# generation (see the ConfigMap in ../../base), images built locally and tagged `dev` (make images).
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
resources: [../../base]
images:
  - {name: rahbar-api, newTag: dev}
  - {name: rahbar-indexer, newTag: dev}
  - {name: rahbar-ui, newTag: dev}
"""
p = Path("k8s/overlays/dev/kustomization.yaml")
if p.exists() and "--dummy" in p.read_text(encoding="utf-8"):
    write(p, OVERLAY, False)
    print("rewrote :", str(p))
else:
    print("skip    :", str(p))

# ---------------------------------------------------------------- what is genuinely still open
MANUAL = """# What is still open

Written by hand, kept honest. Delete this file before submitting.

## Needs the cluster or GitHub (nothing here can be faked)
1. `make cluster`, `make images`, `kubectl apply -k k8s/overlays/dev`, `make corpus-load`, wait for the indexer Job.
2. GitHub: protect `main` (PR + CI + 1 approval), add `DOCKERHUB_USERNAME` / `DOCKERHUB_TOKEN`, open the first PR from `dev` naming the corpus.
3. Evidence screenshots in `docs/evidence/`: branch protection, the blocked merge, `kubectl top pods`, `kubectl get endpoints`, `kubectl get hpa`.

## Needs numbers from running the system
4. Indexer: headings from font size and two-column extraction, so `section` is a real heading and not a page footer.
5. Run `eval/run_eval.py`; confirm every `section` in `eval/golden.yaml`; fix the two "Armor" entries.
6. Measure three (size, overlap) configurations; set `RELEVANCE_FLOOR` and `CACHE_THRESHOLD` from data.
7. `--update-baseline`; commit `eval/baseline.json`, `eval/results.json`, `eval/fixtures/baseline.fixture.json`.
8. Fill `docs/PIPELINE.md`, `docs/FAILURE-ANALYSIS.md` (four broken stages), `docs/ENGINEERING-NOTES.md` (seven answers with line numbers), finish `docs/adr/0002`, update `docs/AI-USAGE.md`.
9. `python scripts/check_submission.py` until clean.
"""
write(Path("MANUAL-STEPS.md"), MANUAL, False)
print("rewrote : MANUAL-STEPS.md")
print("\nDone. Review with: git status && git diff")