# CelestiOS Backend

**Fix your day in 30 seconds.**

CelestiOS is a smart scheduling automation that rescues your focus time. A quick 30-second check-in triggers the engine: it pulls your calendars (Google + Microsoft), reads your body signals (Oura sleep/readiness, Fitbit activity/HR), detects overload, carves out a focus block, and **actually moves the meetings on your calendar** — all before your coffee gets cold.

---

## How It Works

```
  30-Second Check-in                Health Signals
  (sleep, energy, priority)         (auto-pulled)
          |                              |
          v                              v
  +------------------+       +----------------------+       +---------------------+
  |  Pull Calendars  | ----> |   Detect Overload    | ----> |   Fix Your Day      |
  |  Google Calendar  |       |  Drain Score algo    |       | Create focus block  |
  |  Microsoft 365    |       |  + Oura sleep/HRV    |       | Move meetings on    |
  |  (merged view)    |       |  + Fitbit activity   |       | Google & MS 365     |
  +------------------+       |  + Energy mismatch   |       | One-click apply     |
                              |  + Break deficit     |       +---------------------+
                              +----------------------+
```

**Input:** 30-second check-in (how'd you sleep? energy level? top priority today?)  
**Signals:** Oura Ring (sleep score, readiness, HRV, resting HR) + Fitbit (steps, activity score, heart rate zones)  
**Output:** Optimized day — focus block created, conflicting meetings actually moved on your calendar, clear plan for the day.

---

## Architecture

```
                          +------------------+
                          |   Frontend (UI)  |
                          |  Vanilla JS/HTML |
                          +--------+---------+
                                   |
                                   | REST API
                                   v
+----------------------------------------------------------------------+
|                         FastAPI Application                          |
|                            (main.py)                                 |
+----------------------------------------------------------------------+
|                                                                      |
|  +-------------+  +-------------+  +-----------+  +---------------+  |
|  |  api/auth   |  | api/checkin |  | api/burnout|  | api/health   |  |
|  |  OAuth +    |  | 30-sec      |  | Detection  |  | Oura, Fitbit |  |
|  |  Password   |  | Check-in    |  | & Fix Day  |  | Sync & Data  |  |
|  +------+------+  +------+------+  +-----+-----+  +-------+------+  |
|         |                |               |                 |         |
|  +------+------+  +------+------+  +-----+------+  +------+------+  |
|  | api/calendar|  | api/recs    |  | api/visual  |  | scheduler/  |  |
|  | Google & MS |  | Rest-of-Day |  | Daily View  |  | tasks.py    |  |
|  | Sync        |  | Planner     |  |             |  | Cron Jobs   |  |
|  +-------------+  +-------------+  +-------------+  +-------------+  |
|                                                                      |
+-----------------------------------+----------------------------------+
                                    |
                         +----------+-----------+
                         |   Services Layer     |
                         +----------+-----------+
                                    |
          +------------+------------+-------------+------------+
          |            |            |              |            |
  +-------+------+ +---+----+ +----+-----+ +-----+----+ +-----+------+
  | burnout_     | | openai_ | | microsoft| | oura_    | | email_     |
  | detection.py | | service | | _client  | | client   | | sendgrid   |
  |              | | .py     | | .py      | | .py      | | .py        |
  | Drain Score  | | Day     | | Graph API| | Sleep &  | | SendGrid   |
  | Focus Blocks | | Classify| | Calendar | | Readiness| | Transact.  |
  | Meeting Move | | Planner | | Read/Wrt | | HRV Data | | Emails     |
  +--------------+ +---------+ +----------+ +----------+ +------------+
                                    |
                         +----------+-----------+
                         |   Database Layer     |
                         |   db/storage.py      |
                         +----------+-----------+
                                    |
                    +---------------+----------------+
                    |                                |
            +-------+--------+             +--------+-------+
            |   Supabase     |             |    SQLite      |
            |  (PostgreSQL)  |             |   (Fallback)   |
            |   Production   |             |   Local Dev    |
            +----------------+             +----------------+
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Framework** | FastAPI 0.111 + Uvicorn |
| **Language** | Python 3.10+ |
| **Database** | Supabase (PostgreSQL) with SQLite fallback |
| **AI** | OpenAI GPT-4 (day classification + rest-of-day planning) |
| **Auth** | Google OAuth 2.0, Microsoft OAuth 2.0, Email/Password (bcrypt) |
| **Calendar** | Google Calendar API, Microsoft Graph API (read + write) |
| **Health** | Oura Ring API v2, Fitbit API |
| **Email** | SendGrid |
| **Scheduling** | APScheduler |
| **Validation** | Pydantic v2 |

---

## Key Features

### 30-Second Fix My Day
The core loop: user does a quick check-in (sleep, energy, priority) and the system automatically:
1. Pulls today's calendar from **Google Calendar + Microsoft 365** (merged view)
2. Pulls health signals from **Oura Ring** (sleep score, readiness, HRV, resting HR) and **Fitbit** (activity score, steps, heart rate zones)
3. Runs burnout detection — drain score factors in meeting density, energy-to-schedule mismatch, AND biometric data
4. Finds the best focus block in your schedule
5. Identifies meetings to move and calculates new conflict-free times
6. User clicks "Apply" — meetings are **actually moved on Google & Microsoft calendars** via API, focus block is created as a calendar event

### Burnout Detection Engine
Calculates a **Drain Score** from three weighted signals:

```
Drain Score = (0.40 x Meeting Density)
            + (0.35 x Energy Mismatch)
            + (0.25 x Break Deficit)
```

| Score Range | Level | Action |
|-------------|-------|--------|
| 0 - 35% | Healthy | No intervention needed |
| 35 - 50% | Elevated | Protect your focus block |
| 50 - 70% | High | Move 1-2 meetings automatically |
| 70%+ | Critical | Urgent schedule restructure |

### Smart Meeting Classification
Meetings are auto-classified as **non-negotiable** (standup, 1:1, interview, demo) or **moveable** (sync, catch-up, optional) using keyword analysis, organizer detection, and attendee count. Only moveable meetings get suggested for rescheduling.

### Automatic Focus Block Creation
Analyzes gaps between meetings, avoids lunch hours, and carves out the best focus window in your calendar. Prioritizes morning slots (10 AM - 2 PM) for deep work.

### One-Click Meeting Movement
When meetings overlap with your focus block or are scheduled too late, the engine calculates conflict-free time slots, suggests new times, and **actually moves them on your Google & Microsoft 365 calendars** via API — not just a suggestion, a real calendar update with a single click.

### Health-Aware Scheduling
Pulls real biometric data from **Oura Ring** (sleep score, readiness, HRV, resting HR) and **Fitbit** (activity score, steps, heart rate zones) and feeds them directly into the drain score calculation. Bad sleep + low readiness + packed calendar = aggressive schedule restructuring. Good readiness + light day = no intervention needed.

### Rest-of-Day Planner
Starting late? The system generates a realistic plan for your remaining hours based on your energy level, remaining meetings, and top priority.

### Evening Check-in
End-of-day reflection: did you complete your priority? What disrupted you? Feeds back into the system to improve future recommendations.

### Automated Daily Emails
- **Morning "Fix My Day" email** — calendar summary + burnout score + action items, delivered at your preferred time (timezone-aware)
- **Evening check-in reminder** — reflection prompt at 5 PM local time
- **One-click dashboard access** — secure email auth tokens (no password needed)

---

## API Endpoints

| Group | Endpoints | Description |
|-------|-----------|-------------|
| **Auth** | `POST /signup`, `POST /signin`, `GET /login`, `GET /callback` | Google OAuth + email/password auth |
| **Calendar** | `POST /calendar/sync`, `GET /calendar/events` | Google & Microsoft calendar sync |
| **Check-in** | `POST /checkin`, `POST /checkin/evening` | 30-sec morning check-in + evening reflection |
| **Burnout** | `POST /burnout/detect`, `POST /burnout/apply` | Detect overload + apply meeting moves |
| **Recommendations** | `GET /recommendations`, `POST /recommendations/rest-of-day` | Day classification + rest-of-day planner |
| **Health** | `GET /health/auth/oura/login`, `POST /api/health/sync` | Oura & Fitbit integration |
| **Visualization** | `GET /visualization/daily` | Optimized schedule view |

---

## Project Structure

```
celestiOS-backend/
├── main.py                  # FastAPI app entry point
├── requirements.txt         # Python dependencies
├── .env.example             # Environment variable template
│
├── api/                     # Route handlers
│   ├── auth.py              # Authentication (OAuth + password)
│   ├── calendar.py          # Calendar sync endpoints
│   ├── checkin.py           # 30-sec check-in + burnout trigger
│   ├── burnout.py           # Burnout detection + apply changes
│   ├── recommendations.py   # Rest-of-day planner endpoints
│   ├── health.py            # Oura & Fitbit integration
│   └── visualization.py     # Schedule visualization
│
├── services/                # Business logic
│   ├── burnout_detection.py # Drain score algorithm, focus blocks, meeting moves
│   ├── openai_service.py    # GPT-4 day classification + planning
│   ├── microsoft_client.py  # Microsoft Graph API (calendar read/write)
│   ├── oura_client.py       # Oura Ring API client
│   ├── fitbit_client.py     # Fitbit API client
│   ├── email_sendgrid.py    # SendGrid email service
│   └── ics_generator.py     # iCalendar export
│
├── db/                      # Database layer
│   ├── storage.py           # Supabase/SQLite dual-mode storage
│   ├── models.py            # Pydantic data models
│   ├── schema.sql           # PostgreSQL schema
│   ├── schema_sqlite.sql    # SQLite schema (local dev)
│   └── migrations/          # Incremental schema migrations
│
├── core/
│   └── config.py            # Pydantic settings (env var loading)
│
└── scheduler/
    └── tasks.py             # APScheduler background jobs (daily emails)
```

---

## Quick Start

```bash
# Clone
git clone https://github.com/<your-username>/celestiOS-backend-public.git
cd celestiOS-backend-public

# Virtual environment
python -m venv venv
source venv/bin/activate        # Linux/Mac
# venv\Scripts\activate         # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Fill in your API keys and credentials in .env

# Run
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

The API docs are available at `http://localhost:8001/docs` (Swagger UI).

---

## Database

**Production:** Supabase (managed PostgreSQL) with automatic schema initialization.  
**Local development:** Falls back to SQLite automatically when Supabase is unavailable.

Run migrations in order from `db/migrations/` against your Supabase instance.

---

## External Integrations

| Service | Setup Link | Required For |
|---------|-----------|--------------|
| Google Cloud Console | [console.cloud.google.com](https://console.cloud.google.com) | OAuth login + Calendar sync |
| Azure AD | [portal.azure.com](https://portal.azure.com) | Microsoft 365 calendar (read + write) |
| OpenAI | [platform.openai.com](https://platform.openai.com) | Day classification + planning (GPT-4) |
| Oura | [cloud.ouraring.com](https://cloud.ouraring.com) | Sleep & readiness data |
| Fitbit | [dev.fitbit.com](https://dev.fitbit.com) | Activity & heart rate |
| SendGrid | [app.sendgrid.com](https://app.sendgrid.com) | Automated daily emails |
| Supabase | [supabase.com](https://supabase.com) | Database |

---

## License

MIT
