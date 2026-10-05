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

### Accounts and payments (signed-in user, Firebase ID token)

The app sends `Authorization: Bearer <Firebase ID token>` next to the API key. The server checks the token against
Google's public keys (no secret needed), so premium time, the daily chat allowance and wallet money are kept on the
server and cannot be edited from the app. With `REQUIRE_ID_TOKEN=false` (the default) older app versions that send
only the API key keep working, with a per-address limit.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/me` | Plan, premium expiry, chats used and left today, wallet balance |
| GET | `/api/wallet` | Wallet balance and the last 30 ledger entries |
| GET | `/api/billing/plans` | Plan prices and lengths, report price, top-up limits |
| POST | `/api/billing/orders` | Start a Razorpay order for a `plan`, a one-off `report` or a `wallet` top-up |
| POST | `/api/billing/verify` | Verify the payment signature and grant premium, wallet money or the report |
| POST | `/api/billing/webhook` | Razorpay webhook (off until `RAZORPAY_WEBHOOK_SECRET` is set) |

The detailed PDF report is included with any premium plan; otherwise one paid `report` order buys one report and is
handed back if generating it fails.

### Human astrologers, wallet and bookings (signed-in user)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/astrologers`, `/api/astrologers/{uid}` | Directory (language, specialty, mode, online, sort) and a profile with reviews |
| POST | `/api/astrologer/apply` | Apply to become an astrologer; the owner approves |
| GET/PUT | `/api/astrologer/me` | Own profile, status and earnings |
| POST | `/api/astrologer/presence` | Go online or offline (also the heartbeat) |
| GET | `/api/astrologer/requests?wait=20` | Waiting requests and the active consultation (long-poll) |
| GET | `/api/astrologer/earnings` | Amount owed and the ledger |
| POST | `/api/me/accept-terms` | 18+ and consultation terms, needed before the first consultation |
| POST | `/api/consult/sessions` | Request a chat, call or video; the wallet must cover 5 minutes |
| POST | `/api/consult/sessions/{id}/accept`, `/decline`, `/cancel`, `/end` | Lifecycle |
| GET/POST | `/api/consult/sessions/{id}/messages` | Chat; GET takes `after` and `wait` (long-poll, ~instant delivery) |
| POST | `/api/consult/sessions/{id}/review`, `/report` | Rate a consultation; report abuse |
| GET | `/api/services`; POST `/api/bookings`; GET `/api/bookings` | Puja/pandit catalogue and bookings, paid through `/api/billing` |

How the money works (all in one database transaction, locking session, astrologer, wallet in that order):
a minute is charged to the user's wallet when it starts (minute 1 when the astrologer accepts); the astrologer earns
the charge minus `PLATFORM_COMMISSION_PERCENT` (30%); a session ends when either side ends it, the wallet cannot pay
the next minute, a chat sits idle for 10 minutes, it reaches 3 hours, or the astrologer stops checking in; a chat the
astrologer never answered is refunded in full. Every ledger row has a unique reference, so repeating a step never
charges twice. Phone numbers, emails and links are refused in chat (`BLOCK_CONTACT_SHARING`).

The owner's tools are under `/api/admin/*` and need a signed-in user whose verified email is in `ADMIN_EMAILS`:
approve or reject astrologers, record payouts (sent by hand by UPI or bank), correct wallets, block accounts, handle
abuse reports, manage the service catalogue and bookings, and `GET /api/admin/summary` for the money picture.

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

Free live-streamed sessions with astrologers are not built; `/api/features` lists them as `out_of_scope`.

## LLM limits

Groq's free tier limits tokens per minute for each model separately (8,000 for qwen and each gpt-oss model), and a
chat prompt is about 2,100 tokens. The provider keeps a pool of models (`GROQ_MODEL` then `GROQ_FALLBACK_MODELS`):
a rate-limited call moves to the next model at once, and the limited model is skipped for its cool-down. Measured
live, six simultaneous chats all finished in about a second. That is roughly 6 to 7 chats a minute and 2,000 a day on
the free tier (before: about 2 a minute). Calculated endpoints are not affected.

For more, set `LLM_FALLBACK_BASE_URL`, `LLM_FALLBACK_API_KEY` and `LLM_FALLBACK_MODEL` to any OpenAI-compatible
provider; it answers only when every Groq model is busy. When nothing can answer, AI routes return 503 and the
user's chat is given back.

The chart and dasha are sent to the model as compact text (`app/llm/chart_text.py`) instead of pretty-printed
JSON, which halved the prompt (4,100 to 2,100 tokens) without dropping any fact.

## Knowledge base (RAG)

Reference books are chunked and stored in Qdrant, in two collections:

| Collection | Holds | Read by |
|------------|-------|---------|
| `vedic_books` (`BOOKS_COLLECTION`) | Vedic astrology texts | every chat and prediction |
| `specialist_books` (`SPECIALIST_COLLECTION`) | tarot, numerology, Vastu, festivals, calendar science, Puranic lore | only questions on those topics |

Each question is routed by its detected topic (`app/rag/scope.py`): tarot and numerology questions read only their
own books; Vastu, panchang, muhurat and remedy questions read the Vedic collection plus the matching specialist
domains; everything else reads the Vedic collection only. A tarot book can therefore never answer a question about
Saturn's transit. `HIDDEN_TITLES` in the same file lists titles in the Vedic collection that belong to other
traditions (Hellenistic, medieval Christian, modern Western) and are never quoted; edit it to change that.
If the specialist collection is missing, searches skip it and the chat keeps working.

Only texts that are public domain or otherwise legally free to redistribute should be ingested. Do not upload
copyrighted books to the public repository or the knowledge base.

### Public-domain specialist books

`app/rag/free_books.py` lists each book with its source, licence and the reason it is free to use; the
downloaded texts stay in `books_free/` (git-ignored).

| Domain | Books |
|--------|-------|
| tarot | The Pictorial Key to the Tarot (A.E. Waite, 1911) |
| numerology | The Kabala of Numbers (Sepharial, 1911); Cheiro's Book of Numbers (1926) |
| vastu | Essay on the Architecture of the Hindus (Ram Raz, 1834) |
| festivals | Hindu Holidays and Ceremonials (B.A. Gupte, 1916) |
| calendar | The Indian Calendar (Sewell and Dikshit, 1896); Surya-Siddhanta (Burgess, 1860) |
| lore | Agni Purana and Garuda Purana (M.N. Dutt translations, 1903-08), keeping the passages on planets, gems, house building and vratas |

```bash
python scripts/free_books.py plan              # chunk counts per book; uploads nothing
python scripts/free_books.py fetch             # download the texts from the Internet Archive
python scripts/free_books.py ingest            # embed and upload (idempotent)
python scripts/free_books.py verify            # counts and sample searches per domain
python scripts/free_books.py rollback --yes    # remove everything this batch uploaded
```

---

## Running tests

```bash
pip install pytest pytest-asyncio httpx
pytest tests/ -q
```

The suite needs no API keys or network access (LLM and vector-DB calls are stubbed) and covers the engine,
matching, panchang, calendar, muhurat, transits, horoscope, numerology, tarot, vastu, payments, reports,
start-up resilience and the API surface.
