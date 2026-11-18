# DEPLOY.md — Local / Containerized / Cloud

Grounded in [HLD.md §8](./HLD.md) topology. All config via env ([.env.example](../.env.example)); zero hardcoded secrets.

## Services (docker-compose)
`frontend` (Next.js) · `api` (FastAPI) · `worker` (Celery) · `litellm` (gateway) · `postgres` · `qdrant` · `minio` · `redis`.

## Run the applications outside containers

Generate the demo dataset and create `.env` in the repository root as described in [本地启动](#本地启动). Start the infrastructure from the root.

```bash
docker compose up -d postgres qdrant minio redis litellm
cd backend
cp ../.env .env
# In backend/.env, use localhost and the published ports for the service URLs.
uv sync --locked
uv run alembic upgrade head
uv run python -m app.db.seed
uv run uvicorn app.main:app --reload
```

In a second shell from `backend/`, run `uv run celery -A app.worker.celery_app worker -l info`. In a third shell from `frontend/`, run `npm ci` and `npm run dev`.

## 本地启动

准备 Python 3.11 或更新版本和 Docker Compose。在仓库根目录运行以下 PowerShell 命令来生成演示材料和两份样例保单。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install fpdf2 numpy Pillow
.\.venv\Scripts\python.exe -m scripts.generate_docs
.\.venv\Scripts\python.exe -m scripts.generate_gold_policy
.\.venv\Scripts\python.exe -m scripts.generate_silver_policy
.\.venv\Scripts\python.exe -m scripts.generate_unknown
Copy-Item .env.example .env
```

macOS 和 Linux 使用 `.venv/bin/python` 和 `cp`。在 `.env` 中填写 `GROQ_API_KEY` 与 `HUGGINGFACE_API_KEY` 后启动服务。

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
docker compose exec api python -m app.db.seed
```

管理页默认为 `http://localhost:3000`，接口文档为 `http://localhost:8000/docs`。用 `ADMIN_USERNAME` 和 `ADMIN_PASSWORD` 登录，本地默认均为 `admin`。在管理页建立审核员和提交者账号，上传 `dataset/policies/` 中的 PDF 并绑定 `GOLD` 和 `SILVER` 后，即可演示条款检索和理赔材料上传。

## Reset ingested claims to a fresh state
Clears submitted-claim data (`cases`, `documents`, `agent_outputs`, `llm_calls`, `audit_events`, their MinIO files, and per-case LangGraph checkpoints) while **keeping** seeded members/claim_history, users (incl. the bootstrap admin), and the Qdrant policy vectors — i.e. the state right after a fresh build, before any claim was submitted.
```bash
docker compose exec api uv run python -m app.db.clear_cases                  # DB + files + checkpoints
docker compose exec api uv run python -m app.db.clear_cases --keep-files     # DB only
```

## Env vars (→ `.env.example`)
| Var | Purpose |
|---|---|
| `GROQ_API_KEY` | Groq (vision + reasoning) |
| `HUGGINGFACE_API_KEY` | HF Inference API (bge-large embeddings) |
| `LITELLM_MASTER_KEY` | LiteLLM proxy auth |
| `LANGSMITH_API_KEY`, `LANGCHAIN_TRACING_V2` | Tracing (PII-scrubbed) |
| `DATABASE_URL` | Postgres (asyncpg) |
| `QDRANT_URL` | Qdrant |
| `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `MINIO_BUCKET` | Object store |
| `REDIS_URL` | Celery broker + LiteLLM cache + eval run-registry |
| `JWT_SECRET`, `JWT_ALGORITHM`, `JWT_EXPIRY_MIN` | Auth tokens (HS256, 24h default). **`JWT_SECRET` must be set outside local** (fail-closed check). |
| `ADMIN_USERNAME`, `ADMIN_PASSWORD` | Bootstrap admin created by `seed` (dev default `admin`/`admin`; override outside local). |
| `APP_ENV` | `local` \| non-local. Non-local enforces required secrets (no dev defaults). |
| `LLM_MIN_INTERVAL_S`, `LLM_MAX_ATTEMPTS`, `LLM_RETRY_INITIAL_S`, `LLM_RETRY_MAX_S` | LLM pacing/retry. Worker sets a **higher** `LLM_MIN_INTERVAL_S` (e.g. 30s) during batch eval to stay under free-tier tokens/min. |
| `EVAL_CAPTURE_PATH`, `EVAL_CASE_DELAY_S` | Live-eval capture location (shared api↔worker volume) + inter-case delay. |
| `WEB_PORT`, `API_PORT`, `LITELLM_PORT` | Host ports for the frontend, API, and model gateway. Defaults are 3000, 8000, and 4000. |
| `POSTGRES_PORT`, `QDRANT_PORT`, `MINIO_PORT`, `MINIO_CONSOLE_PORT`, `REDIS_PORT` | Host ports for data services. Defaults are 5432, 16333, 19000, 19001, and 16379. |

## CI
Order (fail-closed): **security red-team** → unit → integration → eval. `eval/run_eval.py` asserts Decision Correctness ≥ 60%, overall ≥ 70% ([EVAL_PLAN.md](./EVAL_PLAN.md)).

## Cloud (later)
Same images to K8s/ECS; managed Postgres, Qdrant Cloud, S3 (swap MinIO), managed Redis. Autoscaling/SSO are [EXTENSIONS.md](./EXTENSIONS.md).
