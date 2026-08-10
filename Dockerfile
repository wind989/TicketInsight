FROM python:3.11-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu --constraint requirements.lock torch==2.13.0+cpu
# Install dependencies before application code so ordinary API changes do not
# repeatedly download the large CPU model runtime during Docker rebuilds.
RUN mkdir app && touch app/__init__.py
RUN pip install --no-cache-dir --constraint requirements.lock ".[p1,p1-model,p2,p3,p3-model]"

COPY README.md ./
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY scripts ./scripts
COPY evaluation_sets ./evaluation_sets

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
