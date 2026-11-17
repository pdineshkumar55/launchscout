# LaunchScout production image.
# Two stages: the builder has compilers in case a dependency has no prebuilt Linux wheel; the final
# image only gets the finished virtualenv (no compilers), runs as a non-root user, and listens on 8501.

FROM python:3.13-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt


FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/home/app \
    CREWAI_DISABLE_TELEMETRY=true \
    OTEL_SDK_DISABLED=true \
    CREWAI_TRACING_ENABLED=false
# DejaVu Sans has the rupee sign; the PDF export looks for it here.
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 10001 app
COPY --from=builder /opt/venv /opt/venv

WORKDIR /app
COPY --chown=app:app . .
# Writable folders for reports, search cache, run logs and the usage counter. Created here so named
# volumes mounted on them inherit the app user's ownership.
RUN mkdir -p outputs .cache logs data && chown -R app:app outputs .cache logs data

USER app
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"

CMD ["streamlit", "run", "app.py", "--server.address", "0.0.0.0", "--server.port", "8501", \
     "--server.headless", "true", "--browser.gatherUsageStats", "false"]
