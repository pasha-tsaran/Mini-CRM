FROM python:3.12-slim-bookworm@sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e AS base

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements-runtime.txt constraints.txt ./
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 crm \
    && useradd --uid 10001 --gid crm --no-create-home crm \
    && mkdir /data /bot-state \
    && chown crm:crm /data /bot-state
COPY app ./app
COPY api ./api
COPY bot ./bot
COPY database ./database
COPY integrations ./integrations
COPY models ./models
COPY workers ./workers
COPY templates ./templates
COPY static ./static

FROM base AS test
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY tests ./tests
COPY pytest.ini ./
USER 10001:10001
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp=/tmp/crm-tests"]

FROM base AS runtime
USER 10001:10001
EXPOSE 5000
CMD ["waitress-serve", "--listen=0.0.0.0:5000", "--threads=4", "--call", "app.main:create_app"]
