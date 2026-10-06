# Lead Engine — Bhiwadi · Khushkhera · Tapukara · Neemrana

Automated B2B lead generation for an industrial construction contractor (PEB, civil, factory/warehouse, EPC).
It finds industrial companies and public projects/tenders in the four clusters, verifies them with AI, scores
them HOT / HIGH / WARM / LOW, finds public business contacts, writes evidence-based emails, sends them within
safe limits, and stops automatically on reply, decline, bounce or unsubscribe.

```
Sources ─► Collectors ─► Documents ─► keyword pre-filter ─► OpenAI verification ─► Project (+Evidence)
 (news RSS, web search,                                         is it relevant? current?      │
  RIICO notices, e-tenders,                                     facts, stage, size, cluster   ▼
  company websites)                                                                      Scoring 0-100
                                                                                               │
 Company discovery / size assessment ─► Contacts (public pages + search snippets) ─────────────┤
                                                                                               ▼
                         Outreach planner ─► AI email (facts only, number-checked) ─► approval / auto
                                                                                               ▼
                 Send queue (window, daily/hourly/domain limits, suppression, dedupe) ─► SMTP
                                                                                               ▼
                 IMAP poller ─► reply / decline / unsubscribe / bounce ─► stop sequence + notify
```

## Stack

| Layer | Tech |
|---|---|
| API | FastAPI, SQLAlchemy 2, Alembic, PostgreSQL |
| Workers | Celery (default/crawl queues + a single-process `email` queue), Celery beat, Redis |
| AI | OpenAI structured outputs (`OPENAI_MODEL`, default `gpt-4.1-mini`) |
| Dashboard | Next.js 15 (App Router), cookie session proxied to the API |

## Quick start (Docker)

```bash
cp .env.example .env        # fill in OPENAI_API_KEY, sender identity, SMTP/IMAP, admin password
docker compose up -d --build
```

- Dashboard: http://localhost:3000 (sign in with `ADMIN_EMAIL` / `ADMIN_PASSWORD`)
- API docs: http://localhost:8000/docs
- The `api` container runs migrations and seeds the default sources on start.

**Go-live checklist**
1. Keep `EMAIL_SEND_MODE=dry_run` for the first days. Review leads and the rendered emails in **Email queue → Dry run**.
2. Switch to `approval` in **Settings** and approve emails by hand for a while.
3. Only then enable `auto`. It is refused unless SMTP, `SENDER_EMAIL` and `SENDER_ADDRESS` are set, and it only
   sends for leads at or above `AUTO_SEND_MIN_GRADE` (default HOT).
4. `PUBLIC_BASE_URL` must be publicly reachable, because unsubscribe links point to `/u/<token>` on the API.
5. Use a sending domain with SPF, DKIM and DMARC configured, and warm it up with low limits.

## Local development (without Docker)

```bash
# backend
cd backend
python -m venv .venv && .venv/Scripts/activate       # Windows (use bin/activate on Linux/macOS)
pip install -r requirements-dev.txt
alembic upgrade head && python -m app.seed
uvicorn app.main:app --reload
celery -A app.workers.celery_app worker -Q default,crawl,email -l INFO --pool=solo   # --pool=solo on Windows
celery -A app.workers.celery_app beat -l INFO
pytest                                                # 23 tests, SQLite, no network

# frontend
cd frontend
npm install
BACKEND_URL=http://localhost:8000 npm run dev
```

## What runs when (Celery beat, IST)

| Job | Schedule | What it does |
|---|---|---|
| dispatch-due-sources | every 5 min | Runs each enabled source whose interval has elapsed |
| process-pending-documents | every 10 min | Retries documents that were not processed or waited for the AI |
| monitor-company-websites | daily 05:30 | Re-crawls company home/news/press pages; only changed text goes to the AI |
| discover-companies | 07:00, 19:00 | Web search → AI extracts industrial companies per cluster |
| assess-companies | hourly | AI size/quality assessment of new companies |
| enrich-contacts | hourly | Public contact discovery for companies with WARM+ current projects |
| plan-outreach | every 15 min | Drafts emails for HIGH+ leads that have a reachable contact |
| schedule-followups | every 30 min | Drafts due follow-ups (threaded, deduplicated) |
| send-queue | every 1 min | Sends at most one email per tick within all limits |
| poll-inbox | every 5 min | Classifies replies/bounces and stops sequences |
| rescore-all | daily 02:15 | Re-applies recency decay |
| daily-digest | daily 09:00 | Slack/Telegram/email summary |

## Sources

Seeded by default (edit them in **Sources**):

- **Google News RSS**: 4 queries per cluster, every 3 h (free, no key).
- **Web search** via SerpAPI or Google Programmable Search: 3 queries per cluster, every 12 h. These need
  `SEARCH_PROVIDER` and a key. Search also powers company discovery and contact search.
- **RIICO**: notices, press releases and public notices on riico.rajasthan.gov.in. Only document links are read,
  and PDF text is extracted.
- **Rajasthan e-Proc**: the "Latest Tenders" table on the home page. The full active-tender search sits behind a
  captcha, which this system does not bypass. RIICO's own tenders are published here.
- **CPPP**: the latest active tenders list.

Tender rows are kept only when they mention the target locations and construction work. Tenders are shown on
the dashboard and trigger notifications, but they are never emailed (you bid on the portal).

Crawling etiquette: honours robots.txt, uses an identifying User-Agent, applies per-host throttling (shared via
Redis) and does not scrape search-engine result pages or LinkedIn.

## Scoring (0–100)

Points are added for each factor, then multiplied by the AI's confidence (0.55–1.0):

| Factor | Max |
|---|---|
| Project type (factory/PEB 20, warehouse/expansion 18, EPC 17 …) | 20 |
| Stage (tendering 22, approved/land acquired 20, planning 18, announced 15, under construction 10, completed 0) | 22 |
| Recency of the latest evidence (≤30 d 15 … >1 y 0) | 15 |
| Location in a target cluster | 10 |
| Size (investment ₹ Cr, area or tender value) | 15 |
| Company tier + quality | 12 |
| Evidence strength (official > news > search) and number of sources | 12 |
| Reachable decision-maker contact | 8 |

Grades: **HOT ≥ 75 · HIGH ≥ 55 · WARM ≥ 35 · LOW**. Hard caps: a lead that is not current or not relevant scores
at most 30, and a closed tender at most 20. Every lead page shows the full breakdown.

## Email safety

- **Facts only:** the AI receives only the verified facts for the project and your `SENDER_*` profile. Any number
  in a draft that does not appear in those inputs causes the draft to be rejected, and a deterministic template is
  used instead.
- **Contacts:** only addresses published on the company's own domain, or added by you, are used. Role mailboxes
  such as HR, careers, sales and investor relations are excluded, and addresses are never guessed. Domains are
  checked for MX records.
- **Duplicate protection:**
  - One outreach per project and contact.
  - At most one active sequence per company.
  - A cool-down period per company.
  - One email per sequence step.
  - The Message-ID is fixed before sending.
  - A row stuck in `sending` is never retried automatically.
- **Limits:** daily, hourly and per-domain caps, minimum spacing between sends, a send window in IST, and an
  optional weekday-only rule.
- **Stops:** a reply, decline, unsubscribe (link, one-click `List-Unsubscribe-Post`, or the word "unsubscribe"
  in a reply) or bounce cancels all pending emails. Declines, unsubscribes and bounces also go on the global
  suppression list, which is checked again immediately before every send. Unsubscribes cannot be removed from
  the dashboard.
- **Footer:** every email carries your company name, postal address and an unsubscribe link.

## Configuration

All variables are documented in [.env.example](.env.example). Runtime controls (mode, grades, limits, window,
follow-up delays, cool-down, notification grade) can also be changed live in **Settings**.

## Project layout

```
backend/app
  config.py, db.py, models.py           settings, engine, 12 tables
  services/
    collectors/sources.py               news RSS, web search, listing pages, tender tables
    pipeline.py                         ingest → prefilter → AI → project; website monitoring; discovery
    ai.py                               OpenAI structured outputs + hallucination guard
    scoring.py, entities.py             scoring; company/project dedupe & merge
    contacts.py                         public contact discovery, role mapping, MX check
    outreach.py                         planning, composing, send queue, follow-ups
    inbox.py, suppression.py            IMAP replies/bounces; unsubscribe tokens & suppression
    notifications.py, http.py           Slack/Telegram/email; polite fetcher
  workers/                              Celery app, beat schedule, tasks
  api/routes/                           auth, dashboard, leads, companies/contacts, emails, admin, public
frontend/app                            dashboard, leads, lead detail, companies, email queue, sources, settings
```

## Compliance notes

This is not legal advice. Named business email addresses are personal data under India's Digital Personal Data
Protection Act 2023, so check your obligations with counsel before going live. In practice:
- Keep volumes modest.
- Contact only relevant business roles.
- Honour opt-outs immediately (the system does this automatically).
- Delete data you no longer need.
- Review each site's terms before adding it as a source.
