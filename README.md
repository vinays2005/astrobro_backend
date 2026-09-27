# AstroBro AI Backend

Deterministic Vedic astrology engine + AI reasoning layer.

**Core rule:** LLM reasons. Engine calculates. Never the other way.

---

## Stack

| Layer | Tech |
|-------|------|
| API | FastAPI + Uvicorn |
| Astrology engine | pyswisseph (Swiss Ephemeris) |
| LLM | Ollama (DeepSeek-R1 7B) |
| RAG | ChromaDB + BM25 + cross-encoder reranker |
| DB | SQLite (dev) / PostgreSQL (prod) |
| Auth | Firebase UID passthrough |

---

## Quick Start (Local)

```bash
# 1. Clone and setup
git clone <repo>
cd astrobro_backend
cp .env.example .env
# Edit .env — set SECRET_KEY

# 2. Install Python deps
pip install -r requirements.txt

# 3. Start Ollama and pull models
ollama pull deepseek-r1:7b
ollama pull qwen2.5:1.5b

# 4. Ingest your books (drop PDFs in ./books/)
python scripts/ingest_books.py --books-dir ./books

# 5. Run
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## Docker (Recommended)

```bash
cp .env.example .env
docker-compose up --build

# First run — pull Ollama models (inside container)
docker exec astrobro_ollama_1 ollama pull deepseek-r1:7b
docker exec astrobro_ollama_1 ollama pull qwen2.5:1.5b
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | System health |
| POST | `/api/kundli/create` | Create birth chart (no LLM) |
| POST | `/api/kundli/predict` | Full AI prediction |
| POST | `/api/prediction/` | Topic prediction |
| GET | `/api/prediction/topics` | List supported topics |
| POST | `/api/chat/` | AI astrology chat |
| POST | `/api/chat/stream` | Streaming chat (SSE) |
| POST | `/api/books/ingest` | Upload PDF book |
| GET | `/api/books/list` | List indexed books |
| GET | `/docs` | Swagger UI (dev only) |

---

## Flutter Integration

```dart
// Base URL
const baseUrl = 'http://10.0.2.2:8000';  // Android emulator
// const baseUrl = 'http://localhost:8000'; // web/desktop

// Create kundli
final r = await dio.post('$baseUrl/api/kundli/create', data: {
  'name': 'Vinay',
  'date_of_birth': '1990-08-15',
  'time_of_birth': '14:30',
  'timezone': 'Asia/Kolkata',
  'latitude': 19.0760,
  'longitude': 72.8777,
});

// AI chat
final chat = await dio.post('$baseUrl/api/chat/', data: {
  'question': 'When will my career improve?',
  'birth_data': {...},
});
```

---

## Recommended Vedic Books (put in ./books/)

- `brihat_parashara_hora_shastra.pdf`
- `phaladeepika.pdf`
- `jataka_parijata.pdf`
- `uttara_kalamrita.pdf`
- `saravali.pdf`

Filename must match the key in `scripts/ingest_books.py::KNOWN_BOOKS`.

---

## VRAM Notes (RTX 2050, 4GB)

- DeepSeek-R1 7B Q4 = ~4GB at 4K context
- Set `OLLAMA_NUM_CTX=4096` in .env
- Set `OLLAMA_NUM_GPU=20` (layers on GPU)
- Set `OLLAMA_KEEP_ALIVE=5m` (unload when idle)

---

## Running Tests

```bash
pip install pytest pytest-asyncio httpx
pytest tests/ -v
```

Tests requiring pyswisseph → `tests/test_astrology.py`
API tests (no LLM needed) → `tests/test_api.py`
