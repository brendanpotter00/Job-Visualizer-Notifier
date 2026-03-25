# Backend Framework Evaluation

**Date:** 2026-03-25
**Decision:** FastAPI + Celery + PostgreSQL
**Status:** Recommended

## Context

The current backend (`src/backend/JobsApi/`) is a .NET 8 API handling job CRUD and scheduled scraping. We're planning a significant expansion of backend capabilities that includes:

- **User authentication** with Google OAuth
- **Notifications** (email, push, or in-app)
- **AI-powered job matching** — run new job postings through OpenAI with a user's resume to produce match scores
- **Background tasks** — hourly web scraper runs (already exists in Python), plus new async matching pipelines
- **CRUD + filtering** — job listings with read-heavy access patterns
- **System prompts and AI context management** — storing and versioning OpenAI system prompts per feature

## Candidates Evaluated

| Criteria | FastAPI | Django + DRF | .NET 8 (current) |
|---|---|---|---|
| Async support | Native `async/await` | Bolt-on (ASGI/channels) | Good (async controllers) |
| Background tasks | Celery (mature, proven) | Celery (same) | Hosted services (built-in) |
| Google OAuth | `authlib` / `fastapi-users` | `django-allauth` (easiest) | ASP.NET Identity |
| OpenAI SDK | `openai` Python SDK (first-class) | Same | OpenAI .NET SDK (less mature) |
| ORM | SQLAlchemy (explicit) | Django ORM (batteries included) | Entity Framework Core |
| Admin dashboard | None built-in | Django Admin (free, excellent) | None built-in |
| Python scraper integration | Native (same runtime) | Native (same runtime) | Process spawning (current approach) |
| Learning curve for team | Low-moderate | Moderate | Already known |
| Community + AI ecosystem | Largest (Python is the AI/ML lingua franca) | Large | Smaller for AI workloads |

## Decision: FastAPI

**FastAPI is the right choice** for this project. Here's why:

### 1. Python is the AI/ML lingua franca

The heaviest new feature — job matching via OpenAI — lives in Python's ecosystem. The `openai` Python SDK is the most mature, best-documented, and first to receive new features. Prompt engineering libraries, embedding utilities, and vector search tools are all Python-first. Choosing FastAPI means AI features are first-class, not cross-language hacks.

### 2. The scrapers are already Python

The existing scraper scripts (`scripts/`) are Python. Today, the .NET backend spawns them as child processes (`ScraperProcessRunner.cs`). With FastAPI + Celery, scrapers become native Celery tasks — no process spawning, no stdout parsing, proper error handling, and shared database connections.

### 3. Async-native for IO-heavy workloads

Every core operation is IO-bound: calling OpenAI, fetching ATS APIs, querying PostgreSQL, sending notifications. FastAPI's native `async/await` handles concurrent IO without threads or process spawning. Django requires ASGI configuration and careful async adoption.

### 4. Celery covers all background task needs

| Task | Schedule | Implementation |
|---|---|---|
| Hourly web scraper | Celery Beat (cron) | Migrate existing Python scripts to Celery tasks |
| Job-resume matching | Triggered on new jobs | Celery worker picks up new jobs, calls OpenAI, stores results |
| Notifications | Triggered on match | Celery worker sends email/push after match completes |

Celery Beat replaces .NET's `AutoScraperService` with a battle-tested scheduler. Workers scale horizontally by adding processes.

### 5. Explicit architecture over magic

FastAPI doesn't impose a structure, which means we define clean layers that match the project's needs:

```
app/
├── routes/              # Controller layer
│   ├── auth.py              # Google OAuth, JWT, sessions
│   ├── jobs.py              # Job CRUD, filtering, pagination
│   ├── matches.py           # Resume match results
│   ├── users.py             # User profile, resume upload
│   └── notifications.py     # Notification preferences
│
├── services/            # Business logic
│   ├── auth_service.py      # Token management, Google OAuth flow
│   ├── openai_service.py    # Prompt management, API calls
│   ├── matching_service.py  # Resume-to-job scoring logic
│   ├── notification_service.py
│   └── job_service.py       # Filtering, search, aggregation
│
├── repositories/        # Data access (SQLAlchemy)
│   ├── job_repo.py
│   ├── user_repo.py
│   ├── match_repo.py
│   └── scrape_repo.py
│
├── tasks/               # Celery async tasks
│   ├── scraper_task.py      # Hourly scraper (Celery Beat)
│   ├── matching_task.py     # New jobs → OpenAI → store matches
│   └── notification_task.py # Deliver notifications
│
├── models/              # SQLAlchemy ORM models
│   ├── user.py
│   ├── job.py
│   ├── match.py
│   └── scrape_run.py
│
├── schemas/             # Pydantic request/response DTOs
│   ├── job_schemas.py
│   ├── user_schemas.py
│   └── match_schemas.py
│
├── core/                # App configuration
│   ├── config.py            # Settings (Pydantic BaseSettings)
│   ├── database.py          # SQLAlchemy engine + session
│   ├── security.py          # JWT utilities
│   └── celery_app.py        # Celery configuration
│
└── prompts/             # OpenAI system prompts (versioned)
    ├── job_match_v1.txt
    └── job_match_v2.txt
```

### Why not Django?

Django's strongest advantages — Admin dashboard, built-in auth, ORM — are nice-to-haves, not must-haves for this project. The tradeoffs:

- **Django Admin** is great, but we'd build a React frontend for user-facing features anyway. Admin is a debugging convenience, not a product feature.
- **django-allauth** makes Google OAuth slightly easier, but `authlib` with FastAPI is straightforward and well-documented.
- **Django ORM** is higher-level than SQLAlchemy, but SQLAlchemy's explicit query building is better for complex filtering and read-heavy access patterns.
- **Django's async story** is still maturing. Mixing sync ORM calls with async views requires careful handling.

### Why not keep .NET?

- OpenAI Python SDK is more mature than the .NET equivalent
- Scrapers would remain as child processes instead of native tasks
- Two runtimes (C# + Python) adds operational complexity
- The Python AI ecosystem (LangChain, embeddings libraries, prompt tooling) is significantly ahead

## Migration Path

### Phase 1: Core API + Auth
- FastAPI project setup with the layered architecture above
- PostgreSQL connection (reuse existing database)
- Google OAuth with JWT tokens
- Migrate job CRUD endpoints from .NET

### Phase 2: Background Tasks
- Celery + Redis setup
- Migrate scrapers from process-spawned scripts to Celery tasks
- Celery Beat for hourly scheduling

### Phase 3: AI Matching Pipeline
- OpenAI integration service with prompt versioning
- Resume upload and storage
- Matching Celery task: new jobs → OpenAI → match scores
- Match results API endpoints

### Phase 4: Notifications
- Notification preferences per user
- Celery task to deliver notifications on new matches
- Email and/or push notification providers

## Technology Stack Summary

| Component | Technology |
|---|---|
| Framework | FastAPI |
| Language | Python 3.12+ |
| ORM | SQLAlchemy 2.0 (async) |
| Validation | Pydantic v2 |
| Database | PostgreSQL (existing) |
| Background tasks | Celery + Redis |
| Scheduled tasks | Celery Beat |
| Auth | Google OAuth via Authlib + JWT (python-jose) |
| AI | OpenAI Python SDK |
| Testing | pytest + httpx (async test client) |
| Deployment | Docker containers (API + Celery worker + Celery Beat) |
