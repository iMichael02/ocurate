FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

RUN useradd --system --no-create-home ocurate
USER ocurate

EXPOSE 8000

# One process only: pending Session tokens live in memory (see README "Run").
CMD ["uvicorn", "app.app:app", "--host", "0.0.0.0", "--port", "8000"]
