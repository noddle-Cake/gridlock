# Single image: FastAPI at /api + built React app at /. Build from the repo root:
#   docker build -f backend/Dockerfile .
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv/backend

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/app ./app
COPY backend/scripts ./scripts
COPY sample_data /srv/sample_data
COPY source_docs/extracted /srv/source_docs/extracted
COPY --from=web /web/dist /srv/frontend/dist

EXPOSE 8000
CMD ["uvicorn", "app.serve:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
