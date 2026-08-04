# IntelliDQ — CI Implementation Plan

Derived from `python-docker-ci-pipeline.md`, adapted to this repository as it actually exists
(inspected on branch `abhijeetdq`, remote `Aakarsh183/IntelliDQ`).

---

## 0. How this plan was built

1. Read `python-docker-ci-pipeline.md` — it is a **generic template** that assumes a project layout
   (`app/` + `tests/` + pinned `requirements.txt`) that this repo does not have.
2. Inventoried the real repo: `git ls-files` (101 tracked files), all `backend/*.py` entry points,
   every top-level import, `dq-app/package.json`, `.gitignore`, branch list, remote.
3. Diffed *assumed* vs *actual* → produced the gap table in §1.
4. Traced what would happen if the template's `ci.yml` were committed as-is → found 5 hard blockers
   that make it fail on the first run (§2). Those become Phase 1–3 work.
5. Sequenced everything by dependency: hygiene → dependencies → tests → lint → Docker → workflow →
   branch protection → (optional) ECR/CD. Each phase ends in a **verifiable** state.

Guiding rule: **every phase must leave the pipeline green.** We never commit a workflow that we
know will fail, because a permanently-red CI teaches the team to ignore CI.

---

## 1. Repo reality vs. the template's assumptions

| Template assumes | This repo actually has | Impact |
|---|---|---|
| `app/main.py` package | `backend/main_app.py` (4,686 lines), flat imports (`from grok_client import ...`) | CI/Docker paths change; `backend/` must be on `sys.path` |
| `tests/test_main.py` | **No tests.** `test.py` and `backend/test.py` are scratch scripts that run Spark + read Excel at import | Nothing to gate on; must author real tests |
| Pinned `requirements.txt` | `backend/requirements.txt` — 0 version pins, **missing ~10 packages the code imports** | `pip install` succeeds, then `import` fails |
| Pure-Python app | **PySpark** → needs a JVM | `python:3.11-slim` has no Java; runner needs JDK |
| One app | Python backend + React CRA frontend (`dq-app/`) | Second CI job needed |
| Clean tree | Committed build output, session uploads, generated code | Slow builds, noisy diffs, possible data leak |
| `dev1_feature`…`dev5_feature` | `abhijeetdq`, `LaganDQ`, `Shayan_DQ`, `aakarsh_DQ`, `shivamdq` | Fine — `branches-ignore: [main]` is name-agnostic |

**Live code map** (matters because most of `main_app.py` is dead):

- `backend/main_app.py` lines 1–3180 are four stale copies inside `'''…'''` blocks. **Lines 3181+ are the live app** — `app = FastAPI()` at line 3208, 17 live `@app.post` routes.
- Live imports: `fastapi`, `pyspark`, `pandas`, `pydantic`, `grok_client`, `column_resolver`, `rag`.
- `backend/main.py` and root `main_app.py` / `test.py` / `src/` are **not** the served app — do not point Docker at them.
- `backend/dq_checks.py` is **generated at runtime** by `dq_function_factory.py` (it writes to that file). It is currently committed.

---

## 2. Hard blockers — must be fixed before any workflow can pass

| # | Blocker | Evidence | Fix in |
|---|---|---|---|
| B1 | Hardcoded Windows `JAVA_HOME` at module scope: `os.environ['JAVA_HOME'] = r"C:\Program Files\Java\jdk-17.0.19"` | `backend/main_app.py` (live section, ~line 3183); same in `backend/test.py` | Phase 3 |
| B2 | `requirements.txt` missing `fastapi`, `uvicorn`, `python-multipart`, `pandas`, `openpyxl`, `pyspark`, `rapidfuzz`, `requests`, `httpx`, `langchain-community`, `langchain-text-splitters`, `langchain-classic`, `faiss-cpu`, `sentence-transformers` | compared `grep` of all imports vs. the file | Phase 2 |
| B3 | Zero pinned versions → CI and prod silently drift from dev | `backend/requirements.txt` | Phase 2 |
| B4 | No tests → `pytest` exits code 5 ("no tests collected") and fails the job | no `test_*.py` anywhere | Phase 3 |
| B5 | `flake8` on 17k lines of star-imports and generated code will report hundreds of violations | `from pyspark.sql.functions import *` in `backend/main.py` | Phase 4 |

Two more that bite later, not on day 1:

- **B6 — image size.** `sentence-transformers` pulls `torch` (~2.5 GB). A naive image lands at 4–6 GB → slow ECR pushes, slow cold starts.
- **B7 — runtime writes.** The app writes `dq_checks.py` and `backend/.session_store/`. Containers are ephemeral; this needs a volume/S3 before production. CI is unaffected.

---

## 3. Tools & dependencies

### 3.1 Local machine (currently missing — verified with `Get-Command`)

| Tool | Status | Needed for | Install |
|---|---|---|---|
| Python 3.11 | ⚠️ only the WindowsApps stub is on PATH | run tests locally | python.org installer, or `winget install Python.Python.3.11` |
| JDK 17 | ❌ not on PATH | PySpark locally | `winget install EclipseAdoptium.Temurin.17.JDK` |
| Docker Desktop | ❌ | build/test image locally | docker.com/products/docker-desktop |
| Node 20 | ❌ | frontend job locally | `winget install OpenJS.NodeJS.LTS` |
| GitHub CLI | ❌ | scripting branch protection (optional) | `winget install GitHub.cli` |
| Git | ✅ | — | — |

You *can* do this whole plan without local Docker/Node by iterating in CI — it's just a slower loop
(~3 min per push). Docker Desktop is the single highest-value install.

### 3.2 GitHub Actions (versions to pin)

| Action | Version | Purpose |
|---|---|---|
| `actions/checkout` | `@v4` | clone repo onto runner |
| `actions/setup-python` | `@v5` | Python 3.11, matching Dockerfile |
| `actions/setup-java` | `@v4` (temurin 17) | JVM for PySpark — **added, not in the template** |
| `actions/cache` | `@v4` | pip download cache |
| `actions/setup-node` | `@v4` | frontend job |
| `docker/setup-buildx-action` | `@v3` | BuildKit |
| `docker/build-push-action` | `@v6` | build with GHA layer cache |
| `aws-actions/configure-aws-credentials` | `@v4` | Phase 9 only |
| `aws-actions/amazon-ecr-login` | `@v2` | Phase 9 only |

### 3.3 Dev/CI-only Python deps (`backend/requirements-dev.txt`)

```
pytest==8.2.0
pytest-cov==5.0.0
flake8==7.0.0
httpx==0.27.0          # required by fastapi.testclient
```

### 3.4 External accounts / permissions

- **Repo admin on `Aakarsh183/IntelliDQ`** — required for Phase 8 (branch protection). If you are not
  the owner, this is a hand-off to Aakarsh; everything else you can do yourself.
- Actions enabled on the repo (Settings → Actions → Allow all actions).
- Phase 9 only: AWS account, ECR repo, IAM role for OIDC.

---

## 4. Phased implementation

### Phase 1 — Repo hygiene *(30 min, no CI yet)*

**Why first:** every later phase pays a tax on a dirty tree — build context size, lint noise, cache
misses. Also `backend/.session_store/` contains real uploaded spreadsheets.

Append to `.gitignore`:

```gitignore
# --- CI additions ---
backend/.session_store/
backend/dq_results.json
backend/dq_checks.py          # generated at runtime by dq_function_factory.py
dq-app/temp-build*/
coverage.xml
.coverage
htmlcov/
.pytest_cache/
```

Untrack (keeps local files, removes from git):

```bash
git rm -r --cached backend/.session_store dq-app/temp-build dq-app/temp-build-2 dq-app/temp-build-exec-fix
git rm --cached backend/dq_results.json backend/dq_checks.py
git commit -m "chore: stop tracking generated artifacts and session uploads"
```

> ⚠️ `git rm --cached` removes the file from *future* commits only — the uploaded spreadsheets stay in
> history. If any of them contain client data, that's a separate history-rewrite conversation. Flag it,
> don't silently ignore it.

> ⚠️ Coordinate with the other 4 devs before deleting root-level duplicates (`main_app.py`, `src/`,
> `test.py`, duplicate `.xlsx`). Their branches may touch those paths and you'll create merge conflicts
> for everyone. This plan **excludes** them from lint/Docker instead of deleting them.

**Done when:** `git status` is clean and `git ls-files | wc -l` drops from 101 to ~60.

---

### Phase 2 — Fix and pin dependencies *(1–2 h — the real work of this project)*

**Why:** B2 + B3. This is the highest-risk phase because pinning can surface conflicts
(langchain ↔ openai ↔ pyspark ↔ torch) that were being masked by floating versions.

Do it on a clean venv so you pin *what actually works*, rather than versions I guessed:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

`backend/requirements.txt` — the **complete** set the live code imports (still unpinned at this step):

```
# Web
fastapi
uvicorn[standard]
python-multipart          # required by FastAPI UploadFile/Form

# Data
pandas
openpyxl
pyspark
numpy
scikit-learn
rapidfuzz

# HTTP
requests
httpx

# LangChain / LLM
langchain
langchain-core
langchain-classic
langchain-community
langchain-text-splitters
langchain-openai
openai
langchain-anthropic
langchain-google-genai
google-generativeai
langchain-huggingface
transformers
huggingface-hub
sentence-transformers
faiss-cpu

# Config
python-dotenv
```

Then:

```powershell
pip install -r backend/requirements.txt
python -c "import sys; sys.path.insert(0,'backend'); import main_app; print(len(main_app.app.routes))"
pip freeze > backend/requirements.lock.txt
```

Keep `requirements.txt` as the readable intent, `requirements.lock.txt` as the exact pins, and have
**CI and Docker install the lock file**. That gives reproducibility without forcing you to hand-maintain
40 version numbers.

**Decision required — B6, image size.** `sentence-transformers` + `transformers` pull `torch`. Check
whether the live RAG path uses `HuggingFaceEmbeddings` or only `AzureOpenAIEmbeddings`:

```bash
grep -n "HuggingFaceEmbeddings\|AzureOpenAIEmbeddings" backend/rag.py
```

- If only Azure is used → drop `sentence-transformers`/`transformers`/`torch`. Image goes ~5 GB → ~900 MB.
- If HF is genuinely needed → install CPU-only torch:
  `pip install torch --index-url https://download.pytorch.org/whl/cpu` (saves ~1.5 GB of CUDA payload).

**Done when:** a fresh venv built from `requirements.lock.txt` can `import main_app` with no errors.

---

### Phase 3 — Make the code CI-runnable + write real tests *(2–3 h)*

**3a. Fix B1** — replace the hardcoded Windows `JAVA_HOME` in `backend/main_app.py` (live section) with
something portable:

```python
# JAVA_HOME must come from the environment; hardcoding a Windows path breaks Linux/CI/Docker.
if not os.environ.get("JAVA_HOME") and os.name == "nt":
    os.environ["JAVA_HOME"] = r"C:\Program Files\Java\jdk-17.0.19"
```

Apply the same fix in `backend/test.py`. Verify nothing else hardcodes an absolute path:
`grep -rn "C:\\\\" backend/*.py`.

**3b. Neutralise the scratch scripts.** `test.py` and `backend/test.py` execute Spark jobs and read
Excel at import time. pytest's default collection globs are `test_*.py` / `*_test.py`, so bare
`test.py` is *not* collected today — but it's a landmine one config change away from breaking CI.
Rename them:

```bash
git mv test.py scratch_grok_experiment.py
git mv backend/test.py backend/scratch_pyspark_check.py
```

**3c. `pytest.ini`** at repo root — `pythonpath` is what makes the flat imports (`from grok_client import ...`) resolve:

```ini
[pytest]
pythonpath = backend
testpaths = backend/tests
addopts = -q --strict-markers
```

**3d. `backend/tests/test_dq_function_factory.py`** — pure functions, no Spark, no network, fast:

```python
from dq_function_factory import slugify, build_function_name


def test_slugify_normalises_spaces_and_case():
    assert slugify("Account Number Not Empty") == "account_number_not_empty"


def test_slugify_strips_special_characters():
    assert slugify("Perf. Date <= Period-End!") == "perf_date_period_end"


def test_slugify_falls_back_on_empty_input():
    assert slugify("") == "dq_rule"
    assert slugify(None) == "dq_rule"


def test_build_function_name_prefixes_dq():
    assert build_function_name("Null Check") == "dq_null_check"
```

**3e. `backend/tests/test_app_smoke.py`** — proves the FastAPI app imports and wires its routes.
This is the single most valuable test you can have: it catches every missing dependency and every
import-time crash (exactly the class of bug B1/B2 are).

```python
import main_app


def test_app_imports_and_exposes_expected_routes():
    paths = {r.path for r in main_app.app.routes}
    for expected in ("/upload", "/generate_code", "/execute_code", "/rag_query"):
        assert expected in paths


def test_upload_rejects_missing_files():
    from fastapi.testclient import TestClient
    client = TestClient(main_app.app)
    assert client.post("/upload").status_code == 422
```

> Note: no test here calls Grok/Azure. `GrokClient.__init__` only reads env vars (verified — it does
> not validate them), so importing the app without secrets is safe. Keep it that way: **CI must never
> hit a live LLM API** — it's slow, costs money, and makes CI flaky.

**3f.** Add `backend/tests/__init__.py` (empty) so the package resolves cleanly.

**Verify:**

```bash
pytest                      # expect 6 passed
pytest --cov=backend --cov-report=term-missing
```

**Done when:** `pytest` is green locally and coverage prints a number (it will be low — ~5% — that's fine and expected; we ratchet it in Phase 8+).

---

### Phase 4 — Lint configuration *(45 min)*

**Why deviate from the template:** the template runs `flake8 app tests --max-line-length=120` as a hard
gate. On 17k lines with `import *` and four stale code blocks, that produces hundreds of errors on day 1.
A gate nobody can pass gets disabled. So we use the standard **two-tier bootstrap**: block on real
errors, report style non-blockingly, then ratchet.

`.flake8` at repo root:

```ini
[flake8]
max-line-length = 120
exclude =
    .git,
    __pycache__,
    .venv,
    venv,
    dq-app,
    src,
    backend/.session_store,
    backend/dq_checks.py,
    scratch_grok_experiment.py,
    backend/scratch_pyspark_check.py
# F401 unused import / F403,F405 star-imports: tolerated during bootstrap, ratcheted down later
extend-ignore = E501, W503, F401, F403, F405
```

Two CI steps:

- **Blocking:** `flake8 backend --count --select=E9,F63,F7,F82 --show-source --statistics`
  → syntax errors and undefined names only. These are always genuine bugs, never style opinions.
- **Advisory:** `flake8 backend --count --exit-zero --statistics`
  → full report in the log, never fails the build.

**Ratchet plan:** once the team has cleaned a category, delete it from `extend-ignore` and move it into
the blocking step. Do one category per sprint. Track it in a follow-up issue.

**Done when:** the blocking command exits 0 locally.

---

### Phase 5 — Dockerfile + `.dockerignore` *(1 h)*

Differences from the template, and why:

1. **`openjdk-17-jre-headless` installed** — PySpark needs a JVM; `python:3.11-slim` has none. Without this the container starts and dies the moment any endpoint builds a `SparkSession`.
2. **`WORKDIR /app` + copy `backend/` contents to `/app`** — because `main_app.py` uses flat imports; `backend` is not a package.
3. **`CMD uvicorn main_app:app`** — not `app.main:app`.
4. **Non-root user** — a 5-line change that removes a whole class of container-escape severity.
5. **`HEALTHCHECK`** — so ECS/K8s can tell "started" from "ready".

`Dockerfile` at repo root:

```dockerfile
FROM python:3.11-slim AS base

# PySpark requires a JVM. jre-headless keeps this to ~180MB instead of a full JDK.
# --no-install-recommends + rm -rf lists avoid ~40MB of dead weight in the layer.
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl \
 && rm -rf /var/lib/apt/lists/*

ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, code second — so code edits don't invalidate the pip layer.
COPY backend/requirements.lock.txt ./requirements.lock.txt
RUN pip install --upgrade pip && pip install -r requirements.lock.txt

# backend/ contents land at /app root because main_app.py uses flat imports
# (`from grok_client import GrokClient`) and needs its siblings on sys.path.
COPY backend/ /app/

RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8000/docs || exit 1

CMD ["python", "-m", "uvicorn", "main_app:app", "--host", "0.0.0.0", "--port", "8000"]
```

`.dockerignore` at repo root — this repo needs it more than most, since the build context includes a
React app, three copies of its build output, and OneDrive metadata:

```
.git
.github
.venv
venv/
__pycache__/
*.pyc
.pytest_cache/
.coverage
coverage.xml
htmlcov/
.env
.env.*
dq-app/
src/
database/
backend/tests/
backend/.session_store/
backend/scratch_pyspark_check.py
scratch_grok_experiment.py
*.md
*.xlsx
*.csv
```

> `*.xlsx`/`*.csv` are excluded because the app receives data by upload, not from baked-in files. If
> any live code path reads `sample_source_data.xlsx` from disk at runtime, remove those two lines.
> `backend/main.py` does — but it's a script, not the served app.

**Verify locally** (needs Docker Desktop):

```bash
docker build -t intellidq:local .
docker run --rm -p 8000:8000 intellidq:local
# then open http://localhost:8000/docs
```

**Done when:** the image builds and `/docs` renders.

---

### Phase 6 — `.github/workflows/ci.yml` *(1 h)*

```bash
mkdir -p .github/workflows
```

```yaml
name: CI

on:
  push:
    branches-ignore:
      - main
  pull_request:
    branches:
      - main

# Cancel superseded runs on the same ref. With 5 devs pushing frequently this is
# the single biggest saver of Actions minutes.
concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  backend:
    name: backend (lint + test + docker)
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip
          cache-dependency-path: backend/requirements*.txt

      # Not in the source template: PySpark needs a JVM. ubuntu-latest ships one,
      # but pinning it means a runner-image update can't silently change our Java version.
      - name: Set up JDK 17
        uses: actions/setup-java@v4
        with:
          distribution: temurin
          java-version: '17'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r backend/requirements.lock.txt -r backend/requirements-dev.txt

      - name: Lint (blocking — errors only)
        run: flake8 backend --count --select=E9,F63,F7,F82 --show-source --statistics

      - name: Lint (advisory — full style report)
        run: flake8 backend --count --exit-zero --statistics

      - name: Run unit tests with coverage
        run: pytest --cov=backend --cov-report=term-missing --cov-report=xml

      - name: Upload coverage report
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: coverage-xml
          path: coverage.xml
          if-no-files-found: warn

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build Docker image
        uses: docker/build-push-action@v6
        with:
          context: .
          push: false
          load: true
          tags: intellidq:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Smoke-test the image
        run: |
          docker run -d --name dq -p 8000:8000 intellidq:${{ github.sha }}
          for i in $(seq 1 30); do
            if curl -fsS http://localhost:8000/docs > /dev/null; then echo "app is up"; exit 0; fi
            sleep 2
          done
          echo "app failed to start"; docker logs dq; exit 1

  frontend:
    name: frontend (build + test)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: npm
          cache-dependency-path: dq-app/package-lock.json

      - name: Install dependencies
        working-directory: dq-app
        run: npm ci

      - name: Test
        working-directory: dq-app
        env:
          CI: true
        run: npm test -- --watchAll=false --passWithNoTests

      - name: Build
        working-directory: dq-app
        run: npm run build
```

Notes on choices that differ from the template, and why:

- **`cache: pip` on `setup-python`** replaces the separate `actions/cache` block — same effect, one
  step instead of five lines, and it handles the restore-key fallback internally.
- **`load: true` + smoke test.** The template stops at "the image builds." Building proves the
  Dockerfile is syntactically fine; it does *not* prove the app starts. Given B1 (a bad `JAVA_HOME`
  crashes at runtime, not build time), the smoke test is the step that would actually have caught it.
- **Two independent jobs** run in parallel on separate VMs, so total wall-clock ≈ the slower one.
- **No `paths:` filters.** ⚠️ This is deliberate and important: if you filter the `backend` job to
  `backend/**` and then mark it a *required* status check, a frontend-only PR never runs it and sits
  **"Expected — waiting for status"** forever, unmergeable. Only add path filters together with the
  path-filter + always-passing-gate-job pattern. Simplest correct thing for now: run both jobs always.
- **Known trade-off:** with both `push` and `pull_request` triggers, a push to a branch with an open
  PR runs CI twice (~2× minutes). That's the template's intent (fast feedback pre-PR + a merge-result
  check on the PR). If minutes become a concern, drop the `push` trigger and rely on the PR check.

---

### Phase 7 — Prove it on a real branch *(30 min, expect 2–4 iterations)*

```bash
git checkout -b ci/bootstrap-pipeline
git add .gitignore .flake8 pytest.ini Dockerfile .dockerignore \
        .github/workflows/ci.yml backend/requirements*.txt backend/tests
git commit -m "ci: add GitHub Actions pipeline (lint, test, docker build + smoke test)"
git push -u origin ci/bootstrap-pipeline
```

Watch **Actions** tab. Expect to iterate — the usual first-run failures and their causes:

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError` in tests | Phase 2 pin list still incomplete | add the package, re-pin |
| `JAVA_HOME is not set` / `JavaPackage object is not callable` | B1 not fully fixed | grep again for hardcoded paths |
| `exit code 5` from pytest | tests not found | check `pytest.ini` `testpaths`/`pythonpath` |
| Docker build OOM / >6 GB | B6 (torch) | drop `sentence-transformers` or use the CPU wheel index |
| Smoke test times out | app crashes on import inside the container | read `docker logs dq` in the failed step |
| `npm ci` fails | `package-lock.json` out of sync with `package.json` | run `npm install` locally, commit the lock |

Then open the PR into `main` and confirm both checks report on it.

**Done when:** both jobs are green on a PR into `main`.

---

### Phase 8 — Branch protection *(15 min — needs repo admin)*

GitHub → `Aakarsh183/IntelliDQ` → **Settings → Branches → Add branch protection rule**:

- Branch name pattern: `main`
- ✅ Require a pull request before merging → **Require approvals: 1**
- ✅ Require status checks to pass before merging → select
  **`backend (lint + test + docker)`** and **`frontend (build + test)`**
  (they only appear in this picker *after* the workflow has run at least once — hence Phase 7 first)
- ✅ Require branches to be up to date before merging
- ✅ Require conversation resolution before merging
- ❌ Do **not** tick "Include administrators" yet — keep one break-glass path while the pipeline is new

If you don't have admin on this repo, this phase is a hand-off to Aakarsh. Everything in Phases 1–7
is yours to do.

**Done when:** a PR with a deliberately failing test cannot be merged.

---

### Phase 9 — Optional: push to ECR *(later)*

Only after Phases 1–8 are stable. Two changes from the source doc's version:

1. **Use OIDC, not long-lived access keys.** With 5 people sharing a repo, static
   `AWS_SECRET_ACCESS_KEY` secrets are the wrong default. Add to the job:
   `permissions: { id-token: write, contents: read }` and use
   `role-to-assume: arn:aws:iam::<acct>:role/github-actions-intellidq` — no standing secret in GitHub.
2. **Push from a CD workflow on merge to `main`, not from CI on every PR.** Otherwise 5 devs × N pushes
   fills ECR with images nobody deploys. (Add an ECR lifecycle policy regardless.)

AWS-side prerequisites: ECR repo `intellidq`; an IAM role with `ecr:GetAuthorizationToken`,
`ecr:BatchCheckLayerAvailability`, `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`,
`ecr:CompleteLayerUpload`, `ecr:PutImage`, trusted to GitHub's OIDC provider scoped to
`repo:Aakarsh183/IntelliDQ:ref:refs/heads/main`.

---

## 5. Sequencing and effort

```
Phase 1 hygiene ──► Phase 2 deps ──► Phase 3 code fixes + tests ──┐
                                                                  ├──► Phase 6 ci.yml ──► Phase 7 prove ──► Phase 8 protect ──► Phase 9 ECR
                          Phase 4 lint config ────────────────────┤
                          Phase 5 Dockerfile ────────────────────-┘
```

Phases 4 and 5 are independent of each other and can be done in parallel with Phase 3.
Phase 2 is the critical path and the only one with real unknowns.

| Phase | Effort | Risk |
|---|---|---|
| 1 hygiene | 30 min | low |
| 2 dependencies | 1–2 h | **high** — version conflicts |
| 3 code fixes + tests | 2–3 h | medium |
| 4 lint config | 45 min | low |
| 5 Dockerfile | 1 h | medium — JVM + image size |
| 6 ci.yml | 1 h | low |
| 7 prove on branch | 30 min + iterations | medium |
| 8 branch protection | 15 min | low — blocked on admin rights |
| **Total** | **~1 focused day** | |

---

## 6. Risks and rollback

| Risk | Mitigation |
|---|---|
| Pinning breaks a working local setup | Pin from a *known-good* `pip freeze`, keep the old file as `requirements.txt.bak` for one commit |
| Other 4 devs' branches conflict with hygiene changes | Land Phase 1 as its own small PR and tell the team to rebase that day |
| Docker image too large for practical CI/ECR use | Resolve the torch question in Phase 2 before writing the Dockerfile |
| CI becomes the team's blocker on day 1 | Two-tier lint (Phase 4) + no coverage threshold initially + don't tick "Include administrators" |
| Secrets leak via image layers | `.dockerignore` excludes `.env*`; verify with `docker history --no-trunc intellidq:local` |

**Rollback:** every phase is one commit. Branch protection is a UI toggle. Nothing here changes
application behaviour except the `JAVA_HOME` fix in Phase 3a — which is strictly a portability
improvement (Windows behaviour is preserved by the `os.name == "nt"` guard).

---

## 7. Open decisions — need your call

1. **Torch / `sentence-transformers`** — is `HuggingFaceEmbeddings` live in `rag.py`, or is the app
   Azure-only? Determines whether the image is ~900 MB or ~5 GB.
2. **Root duplicates** (`main_app.py`, `src/`, `test.py`, duplicate `.xlsx`) — delete, or leave and
   exclude? Needs the team's agreement, not just yours.
3. **Frontend in the same workflow, or a separate `ci-frontend.yml`?** Same file is simpler; separate
   files let you evolve them independently.
4. **Do you have admin on `Aakarsh183/IntelliDQ`?** If not, Phase 8 needs Aakarsh.
5. **Session-store spreadsheets already in git history** — do any contain real client data? If yes,
   that's a history rewrite, and it should happen before the repo grows more branches.

---

## 8. Out of scope (deliberately)

CD/deployment. The source doc ends at the same boundary. Once CI is green and enforced, the next
document covers: merge-to-`main` trigger → build → push to ECR → deploy to the chosen AWS target.
The deploy step differs substantially between ECS, EKS, Beanstalk and EC2-over-SSH, and PySpark's JVM
+ memory profile makes that choice non-trivial — worth its own plan.
