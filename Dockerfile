# ---------- stage 1: build the React UI ----------
FROM node:20-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- stage 2: API + static UI ----------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PAT_DATABASE_URL=sqlite:////home/data/assessment.db \
    PAT_STATIC_DIR=/app/frontend/dist \
    PAT_DOMAIN_PACKS_DIR=/app/domain_packs
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ backend/
COPY domain_packs/ domain_packs/
COPY --from=ui /ui/dist frontend/dist
# App Service mounts persistent storage at /home at runtime (WEBSITES_ENABLE_APP_SERVICE_STORAGE=true)
RUN mkdir -p /home/data
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
