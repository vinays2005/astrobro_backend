# AstroBro AI Backend

Deterministic Vedic astrology engine + AI reasoning layer.

**Core rule:** the engine calculates, the LLM only interprets. Charts, panchang, transits, dashas, Guna Milan,
muhurat, numerology and tarot draws are all computed in code (Swiss Ephemeris and published rule tables), so
they are fast, free of LLM rate limits and give the same answer every time. The LLM is used for conversation,
long-form predictions, voice transcription and PDF report text.

Astrology is offered as guidance and entertainment, not as medical, legal or financial advice.

---

## Stack

| Layer | Tech |
|-------|------|
| API | FastAPI + Uvicorn (one worker; Swiss Ephemeris state is not thread-safe) |
| Astrology engine | pyswisseph, sidereal Lahiri ayanamsa |
| LLM | Groq (`qwen/qwen3.8-27b` chat, `openai/gpt-oss-120b` long reports, `whisper-large-v3-turbo` speech) |
| RAG | Qdrant Cloud + fastembed (`all-MiniLM-L6-v2`, 384-dim) with a hybrid retriever |
| DB | SQLite (dev) / PostgreSQL (prod) |
| Payments | Razorpay |
| Auth | `X-API-Key` header on every `/api/*` route |
| Deploy | Docker image on Railway |

---

## Quick start (local)

```bash
git clone https://github.com/vinays2005/astrobro_backend
cd astrobro_backend
cp .env.example .env        # fill in GROQ_API_KEY, QDRANT_URL, QDRANT_API_KEY
python -m venv venv311 && source venv311/bin/activate   # Windows: venv311\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Everything under *Calculated features* below works with no LLM or Qdrant configured. Chat, predictions, reports
and voice need `GROQ_API_KEY`; book-grounded answers also need Qdrant.

Interactive docs are at `/docs` when `DEBUG=true`.

### Authentication

Set `API_KEY` on the server and send it from the app as `X-API-Key`. If `API_KEY` is empty the check is skipped
(local development only). Keep the key out of public files and out of git.

### Deploying on Railway

The `Dockerfile` pre-downloads the embedding model so start-up is quick. Set these variables in the Railway
dashboard (names only; values are never committed): `APP_ENV=production`, `DEBUG=false`, `SECRET_KEY`,
`API_KEY`, `ALLOWED_ORIGINS`, `GROQ_API_KEY`, `GROQ_MODEL`, `QDRANT_URL`, `QDRANT_API_KEY`,
`RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`. Deploy from branch `main`.

---

## API

`GET /api/features` returns a machine-readable catalogue of every feature: what it does, whether it is
calculated, AI or human-delivered, a suggested free/premium tier and its endpoints.

### Calculated features (no LLM)

| Area | Endpoints |
|------|-----------|
| Kundli | `POST /api/kundli/create` |
| Dasha | `POST /api/dasha/timeline` (Vimshottari to pratyantar, Yogini) |
| Doshas | `POST /api/dosha/analyze` (Manglik, Kaal Sarp, Sade Sati, Pitru, Grahan, Guru Chandala, Angarak, Shrapit, Vish, Gand Mool, with cancellations) |
| Remedies | `POST /api/remedies/personal`, `GET /api/remedies/planet/{planet}`, `GET /api/remedies/doshas` |
| Horoscope | `GET /api/horoscope/{sign}?period=daily\|weekly\|monthly\|yearly`, `GET /api/horoscope/all`, `POST /api/horoscope/personal` |
| Transits | `GET /api/transit/current`, `POST /api/transit/natal`, `POST /api/transit/sade-sati`, `GET /api/transit/events` |
| Kundli Milan | `POST /api/kundli/match`, `POST /api/kundli/match/detailed` (36-point Ashtakoota, Nadi/Bhakoot/Gana doshas with cancellations, Rajju, Vedha, Mahendra) |
| Love | `POST /api/love/calculate` |
| Panchang | `GET /api/panchang` (tithi, nakshatra, yoga, karana, sun and moon rise/set, Rahu Kaal, Choghadiya, Hora, lunar month, Vikram Samvat, Shaka, Ritu) |
| Calendar | `GET /api/calendar/festivals`, `GET /api/calendar/upcoming`, `GET /api/calendar/today` |
| Muhurat | `GET /api/muhurat/types`, `POST /api/muhurat/find` |
| Numerology | `POST /api/numerology/profile`, `POST /api/numerology/compatibility`, `GET /api/numerology/daily` |
| Tarot | `GET /api/tarot/spreads`, `GET /api/tarot/cards`, `GET /api/tarot/cards/{id}`, `GET /api/tarot/daily`, `POST /api/tarot/draw` |
| Vastu | `POST /api/vastu/analyze`, `GET /api/vastu/guidelines` |
| Concern routing | `POST /api/intent/classify`, `GET /api/intent/categories` |
| Notifications | `POST /api/notifications/feed` (the app schedules the push alerts from this feed) |
| Languages | `GET /api/languages` |

### AI features (need `GROQ_API_KEY`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat/` | AI astrologer chat, grounded in the chart and reference texts |
| POST | `/api/chat/stream` | Same, streamed (SSE) |
| POST | `/api/prediction/` | Topic prediction (large prompts; needs a paid Groq tier) |
| GET | `/api/prediction/topics` | Supported topics |
| POST | `/api/kundli/predict` | Full AI prediction |
| POST | `/api/voice/transcribe` | Speech to text for spoken questions |
| POST | `/api/report/generate` | PDF kundli report (free) or AI-personalised premium report |

Answers are available in 13 languages (English, Hindi, Marathi, Gujarati, Bengali, Tamil, Telugu, Kannada,
Malayalam, Punjabi, Odia, Assamese, Urdu). Calculated content such as horoscope text and panchang labels is
currently English only.

### Other

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | System health |
| POST | `/api/payment/create-order`, `/api/payment/verify` | Razorpay checkout (plans: weekly, monthly, quarterly, yearly) |
| POST | `/api/books/ingest` | Upload a PDF to the knowledge base |
| GET | `/api/books/list` | List indexed books (API key required) |

---

## Accuracy notes

- **Panchang, transits, dashas, chart:** computed with the Swiss Ephemeris. Saturn and Jupiter sign ingress
  dates match the published dates exactly.
- **Guna Milan:** tables follow the classical Ashtakoota (verified against an open-source reference and by hand).
- **Festival calendar:** matches published dates about 9 times in 10 over 2019 to 2027 (23 of 23 in 2026). The
  remainder differ by one day because of regional rules such as which tithi-time is observed. Treat festival
  dates as a guide and confirm with a local panchang for a ritual.
- **Muhurat:** skips Chaturmas, Kharmas, Adhika masa, Pitru Paksha and the Venus/Jupiter combust periods, then
  keeps only days whose weekday, tithi, nakshatra and yoga suit the event, and returns time windows that avoid
  Rahu Kaal, Yamagandam, Gulika and Bhadra. It is not matched to anyone's personal horoscope, so weddings and
  housewarmings still need an astrologer to check the family's charts.
- **Horoscope scores** are relative rankings of the day's transits from the Moon sign, not predictions of events.
- **Love calculator, tarot and numerology** are for entertainment.
- **Vastu** is traditional guidance, not structural or legal advice.

The human marketplace (live chat, call and video with astrologers, puja booking, live sessions) is not part of
this backend; `/api/features` lists it as `out_of_scope`.

## LLM limits

On Groq's free tier a chat answer uses about 4,000 prompt tokens against an 8,000 tokens-per-minute budget, so
only about two chats per minute can be served across all users, and the large prediction prompts do not fit.
Calculated endpoints are unaffected. Move to a paid Groq tier before real traffic.

## Knowledge base (RAG)

Reference books are chunked and stored in Qdrant. Only texts that are public domain or otherwise legally free
to redistribute should be ingested. Do not upload copyrighted books to the public repository or the knowledge
base.

---

## Running tests

```bash
pip install pytest pytest-asyncio httpx
pytest tests/ -q
```

The suite needs no API keys or network access (LLM and vector-DB calls are stubbed) and covers the engine,
matching, panchang, calendar, muhurat, transits, horoscope, numerology, tarot, vastu, payments, reports,
start-up resilience and the API surface.
