# Career Agent

AI-powered personal career automation platform.

## Overview
This platform monitors a private Telegram channel for job postings, evaluates relevance using AI (Gemini), attempts automated applications across multiple channels (career portals, Google Forms, cold email), and notifies the user about outcomes.

## Architecture
The system is an event-driven modular monolith built with:
- **Python 3.12**
- **FastAPI**
- **SQLAlchemy 2.x & Alembic** (PostgreSQL)
- **Cloud Tasks** (Async workers)
- **Playwright** (Portal automation)
- **Telethon** (Telegram MTProto integration)
- **Gemini 2.5 Flash** (AI extraction & tailoring)

## Setup for Development

1. **Clone the repository**
2. **Copy environment variables**
   ```bash
   cp .env.example .env
   ```
   Fill in the required secrets.
3. **Start local infrastructure (Postgres, Redis)**
   ```bash
   docker-compose up -d
   ```
4. **Install dependencies**
   ```bash
   python -m venv venv
   source venv/bin/activate  # Or .\venv\Scripts\activate on Windows
   pip install -e .[dev]
   ```
5. **Run migrations**
   ```bash
   alembic upgrade head
   ```
6. **Run the server**
   ```bash
   uvicorn src.main:app --reload
   ```

## Production
The application is designed to be deployed as a single Cloud Run service, with a `min-instances=1` configuration to maintain the persistent Telegram connection.
