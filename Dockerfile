FROM python:3.11-slim
# demo 
# System deps for pyswisseph + pytesseract
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Swiss Ephemeris data files
RUN python -c "import swisseph; print('swe ok')" || true

COPY . .

# Create data dirs
RUN mkdir -p data/chroma books

EXPOSE 8000

# Fail loud on missing .env — copy .env.example first
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2