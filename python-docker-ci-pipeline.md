# CI Pipeline for a Python App — GitHub Actions + Docker (5-developer team)

## The scenario this is built for

- 5 developers, each working on their own branch (`dev1_feature`, `dev2_feature`, etc.)
- Everyone opens a PR into `main`
- CI must run **automatically** on every push and every PR, regardless of whose branch it is
- CI checks: install deps → lint → unit test → build Docker image → (optionally) push image to AWS ECR
- Only if CI passes should a PR be mergeable (branch protection, covered at the end)

---

## Step 0: Assumed project structure

```
DQ_APP/
├── app/
│   ├── main.py
│   └── ...
├── tests/
│   └── test_main.py
├── requirements.txt
├── requirements-dev.txt   # pytest, flake8, coverage — test-only deps
├── Dockerfile
├── .dockerignore
└── .github/
    └── workflows/
        └── ci.yml
```

If your layout differs, the paths in the YAML below just need adjusting — the logic stays identical.

---

## Step 1: `requirements-dev.txt` (test/lint-only dependencies)

```
pytest==8.2.0
pytest-cov==5.0.0
flake8==7.0.0
```

**Why separate from `requirements.txt`:** production dependencies (what your app needs to *run*) should never include test tooling — it bloats the final Docker image and is a minor security surface increase. CI installs both files; the Docker image only installs `requirements.txt`.

---

## Step 2: The Dockerfile, explained line by line

```dockerfile
FROM python:3.11-slim AS base
```
- `FROM` picks the base image. `python:3.11-slim` is the official Python image, `slim` variant — a stripped-down Debian with just enough to run Python, far smaller than the default full image (~120MB vs ~1GB).
- `AS base` names this build stage `base` — used later for multi-stage builds if you want a separate test stage inside Docker too (optional, covered below).

```dockerfile
WORKDIR /app
```
- Sets the working directory inside the container to `/app`. Every subsequent `COPY`, `RUN`, `CMD` executes relative to this path. Docker creates the directory if it doesn't exist.

```dockerfile
COPY requirements.txt .
```
- Copies **only** `requirements.txt` first, not the whole codebase. This is a deliberate ordering trick for **Docker layer caching**: Docker caches each instruction as a layer. If your app code changes but `requirements.txt` doesn't, Docker reuses the cached "pip install" layer instead of reinstalling everything — this alone can cut build times from minutes to seconds.

```dockerfile
RUN pip install --no-cache-dir -r requirements.txt
```
- Installs production dependencies.
- `--no-cache-dir` tells pip not to store its download cache inside the image — pip's cache is useless once the image is built and only adds dead weight to image size.

```dockerfile
COPY . .
```
- Now copies the rest of the application code. This runs *after* the pip install layer specifically so code edits don't invalidate the dependency-install cache.

```dockerfile
EXPOSE 8000
```
- Purely documentation for humans and tooling (like `docker inspect`) — it does **not** actually publish the port. Actual port mapping happens at `docker run -p 8000:8000` or in your ECS/K8s service definition. Set this to whatever port your app actually listens on (e.g., 8000 for FastAPI/Uvicorn default, 5000 for Flask default).

```dockerfile
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
- The default command run when a container starts from this image.
- Exec form (`["executable", "arg1", "arg2"]`) is used instead of shell form (`CMD python ...`) because exec form runs the process as PID 1 directly, without wrapping it in `/bin/sh -c`. This matters for correctly forwarding `SIGTERM` signals — without it, `docker stop` / ECS task shutdowns can hang or force-kill your app instead of letting it shut down gracefully.
- `--host 0.0.0.0` is required inside containers — binding to `127.0.0.1` (localhost) would make the app unreachable from outside the container's own network namespace.
- Adjust this line entirely to match your actual framework — if it's Flask with gunicorn: `CMD ["gunicorn", "-b", "0.0.0.0:8000", "app.main:app"]`.

### Full Dockerfile assembled

```dockerfile
FROM python:3.11-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Step 3: `.dockerignore`

```
__pycache__/
*.pyc
.git
.github
.env
venv/
.pytest_cache
tests/
```

**Why this file matters:** everything in your build context (the folder you `docker build` from) gets sent to the Docker daemon before the build even starts. Without this file, your `.git` history, virtual environments, and cache files all get shipped into that context — slowing builds and occasionally leaking secrets stored in local `.env` files into image layers. This is one of the most commonly skipped, most impactful files in a Docker setup.

---

## Step 4: Create the workflow folder

```bash
mkdir -p .github/workflows
```

GitHub only recognizes workflow files placed exactly at `.github/workflows/*.yml` (or `.yaml`) in the repo root — not anywhere else.

---

## Step 5: `.github/workflows/ci.yml`, explained line by line

```yaml
name: CI
```
- The display name shown in the **Actions** tab of the repo. Purely cosmetic but useful once you have multiple workflows (CI, CD, security scans, etc.).

```yaml
on:
  push:
    branches-ignore:
      - main
  pull_request:
    branches:
      - main
```
- `on:` defines what triggers this workflow.
- `push: branches-ignore: [main]` → runs CI on a push to **any** branch except `main` itself. This is deliberate: with 5 developers all pushing to their own branches, you want fast feedback on every single push, no matter the branch name — you don't want to hardcode `dev1`, `dev2`, `dev3`... branch names into the trigger.
- `pull_request: branches: [main]` → additionally runs CI whenever a PR is opened or updated **targeting** `main`. This is what branch protection will later require to pass before merge is allowed.
- Together these two triggers mean: developers get CI feedback immediately on push, and CI runs again (against the merge result) when they open the PR.

```yaml
jobs:
  build-test:
    runs-on: ubuntu-latest
```
- `jobs:` — a workflow is made of one or more jobs; each runs in its own fresh virtual machine, in parallel by default (unless you set dependencies with `needs:`).
- `build-test` is just the job's ID — used to reference it later (e.g., as a required status check name in branch protection).
- `runs-on: ubuntu-latest` provisions a fresh Ubuntu VM for this job. GitHub tears it down completely after the job finishes — nothing persists between runs unless you explicitly cache or use artifacts.

```yaml
    steps:
      - name: Checkout code
        uses: actions/checkout@v4
```
- Steps run sequentially within a job, top to bottom, in the same VM/filesystem.
- `actions/checkout@v4` is an official GitHub action that clones your repository into the runner's workspace. Without this step, the runner's filesystem is empty — nothing to test or build.
- `@v4` pins a specific major version of the action, protecting you from breaking changes if the action publishes a new major version later.

```yaml
      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'
```
- Installs the specified Python version onto the runner and adds it to PATH. `3.11` should match the version in your Dockerfile's `FROM python:3.11-slim` — keeping dev, CI, and production on the same interpreter version avoids "works in CI but not in prod" bugs.

```yaml
      - name: Cache pip dependencies
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt', 'requirements-dev.txt') }}
          restore-keys: |
            ${{ runner.os }}-pip-
```
- Caches pip's download cache directory between workflow runs so dependencies aren't re-downloaded from PyPI every single run.
- `key` is the cache lookup key. `hashFiles(...)` computes a hash of your requirements files — if either file changes (a dependency added/removed/bumped), the hash changes, producing a new cache key, so the cache correctly invalidates itself.
- `restore-keys` is a fallback prefix match — if there's no exact hash match (because requirements changed slightly), GitHub still restores the closest previous cache instead of starting from zero, then updates it at the end of the job.

```yaml
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt -r requirements-dev.txt
```
- `run: |` starts a multi-line shell script block executed on the runner.
- Upgrading pip first avoids occasional resolver bugs in older bundled pip versions.
- Installing both requirement files means CI has everything needed to both run the app's code paths and execute the test/lint tooling.

```yaml
      - name: Lint with flake8
        run: flake8 app tests --max-line-length=120
```
- Runs static analysis for style violations, unused imports, undefined names, etc., across the `app` and `tests` folders.
- `--max-line-length=120` overrides flake8's overly strict 79-character default — a common, reasonable team convention. Adjust to your team's actual style guide, or remove entirely to use flake8 defaults.
- If this step exits non-zero (lint errors found), the entire job fails immediately, and later steps do not run by default.

```yaml
      - name: Run unit tests with coverage
        run: pytest --cov=app --cov-report=term-missing --cov-report=xml tests/
```
- Runs your `pytest` test suite located under `tests/`.
- `--cov=app` measures code coverage specifically for the `app` package — not third-party libraries.
- `--cov-report=term-missing` prints a per-file coverage table directly in the CI log, including exact line numbers not covered by any test — immediately actionable for developers.
- `--cov-report=xml` additionally writes `coverage.xml` in Cobertura format, which many external tools (Codecov, SonarQube, GitHub PR annotations) can parse to show coverage diffs directly on the pull request.
- If any test fails, `pytest` exits non-zero and fails the job — this is the actual quality gate.

```yaml
      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3
```
- Installs and configures Buildx, Docker's modern build engine (BuildKit), on the runner. Needed for the improved caching, multi-platform build support, and generally faster builds compared to the legacy `docker build` engine. Almost always worth including even for simple single-platform builds.

```yaml
      - name: Build Docker image
        uses: docker/build-push-action@v6
        with:
          context: .
          push: false
          tags: dq_app:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```
- `docker/build-push-action` wraps `docker build` (and optionally `push`) as a first-class GitHub Action with built-in caching support.
- `context: .` — build context is the repo root (where the Dockerfile and `.dockerignore` live).
- `push: false` — at this stage, in CI, we're only proving the image *builds successfully*. We are not yet pushing it anywhere. This is the correct behavior for a CI job whose job is "verify correctness," not "deploy."
- `tags: dq_app:${{ github.sha }}` — tags the locally-built image with the Git commit SHA that triggered this run, giving each build a unique, traceable identifier (rather than reusing `latest` and losing history).
- `cache-from` / `cache-to: type=gha` — stores and retrieves Docker layer cache using GitHub Actions' own cache backend, so repeated builds (e.g., only application code changed, not dependencies) reuse cached layers instead of rebuilding from scratch every time. `mode=max` caches all layers, not just the final one, maximizing future cache hits.

At this point, CI has proven: the code lints clean, the tests pass, and the Docker image builds successfully. That's a complete CI pipeline.

### Optional Step 6 — build and push to AWS ECR (since you're targeting AWS)

Add this only if you want CI itself to publish the image (many teams instead do this only in the CD workflow after merge to `main` — either is valid; doing it here means every PR produces a testable image).

```yaml
      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: ${{ secrets.AWS_REGION }}
```
- Authenticates the runner to your AWS account using credentials stored as encrypted GitHub Secrets (never hardcoded). This action sets short-lived AWS environment variables for subsequent steps in the same job only.

```yaml
      - name: Log in to Amazon ECR
        id: ecr-login
        uses: aws-actions/amazon-ecr-login@v2
```
- Retrieves a temporary Docker login token from AWS and authenticates the local Docker daemon against your ECR registry. `id: ecr-login` lets later steps reference this step's outputs (like the registry URL) via `${{ steps.ecr-login.outputs.registry }}`.

```yaml
      - name: Build, tag, and push image to ECR
        env:
          ECR_REGISTRY: ${{ steps.ecr-login.outputs.registry }}
          ECR_REPOSITORY: dq_app
          IMAGE_TAG: ${{ github.sha }}
        run: |
          docker build -t $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG .
          docker push $ECR_REGISTRY/$ECR_REPOSITORY:$IMAGE_TAG
```
- Builds the image tagged with the ECR registry's full URL (ECR requires images be tagged with their destination registry path before pushing) and the commit SHA, then pushes it.
- Using the commit SHA (not `latest`) as the tag means every image in ECR is traceable back to an exact commit — critical once you're debugging a production incident and need to know precisely what code is running.

**AWS-side prerequisites for the above to work:**
1. Create an ECR repository: AWS Console → ECR → **Create repository** → name it `dq_app`
2. Create an IAM user (or better, use OIDC — see note below) with an inline policy granting `ecr:GetAuthorizationToken`, `ecr:BatchCheckLayerAvailability`, `ecr:PutImage`, `ecr:InitiateLayerUpload`, `ecr:UploadLayerPart`, `ecr:CompleteLayerUpload`
3. Add three GitHub repo secrets: **Settings → Secrets and variables → Actions**:
   - `AWS_ACCESS_KEY_ID`
   - `AWS_SECRET_ACCESS_KEY`
   - `AWS_REGION` (e.g., `ap-south-1`)

**Better practice than long-lived access keys:** use GitHub's OIDC provider with an AWS IAM role trust policy (`aws-actions/configure-aws-credentials` supports `role-to-assume` instead of static keys). No long-lived secret ever sits in GitHub at all. Say the word and I'll write that version out too — it's a bit more AWS-side setup but meaningfully more secure for a 5-person team with shared secrets.

---

## Full assembled `ci.yml` (build-only version, no ECR push)

```yaml
name: CI

on:
  push:
    branches-ignore:
      - main
  pull_request:
    branches:
      - main

jobs:
  build-test:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Cache pip dependencies
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt', 'requirements-dev.txt') }}
          restore-keys: |
            ${{ runner.os }}-pip-

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt -r requirements-dev.txt

      - name: Lint with flake8
        run: flake8 app tests --max-line-length=120

      - name: Run unit tests with coverage
        run: pytest --cov=app --cov-report=term-missing --cov-report=xml tests/

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Build Docker image
        uses: docker/build-push-action@v6
        with:
          context: .
          push: false
          tags: dq_app:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

---

## Step 7: Wire it into branch protection

GitHub → Aakarsh/org repo → **Settings → Branches → Add branch protection rule**:
- Branch name pattern: `main`
- ✅ Require a pull request before merging (require ≥1 approval)
- ✅ Require status checks to pass before merging → search for and select **`build-test`** (the job ID from the YAML above — it only appears in this list after the workflow has run at least once)
- ✅ Require branches to be up to date before merging (forces devs to rebase/merge `main` in before merging, avoiding stale-branch bugs)

Now, with 5 developers each on their own branch: every push gets instant CI feedback, and no PR can merge into `main` unless lint + tests + Docker build all pass — regardless of whose branch it came from.

---

## What's next

This is the complete CI half. The natural next step is the **CD workflow** — triggered only on merge to `main`, which builds the final image, pushes it to ECR (if not already done in CI), and deploys it to your AWS target (ECS, EC2 via SSH, Elastic Beanstalk, or EKS — the deploy step differs a lot by which of these you're using). Let me know which AWS compute target you're deploying to and I'll write that stage next with the same level of detail.
