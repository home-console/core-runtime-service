FROM python:3.13-slim

# Minimal runner image.
# No plugin code here yet; only runner + sdk if needed later.

WORKDIR /app

# Ship runner as a module: python -m homeconsole_runner
COPY core/execution/runner/__init__.py /app/__init__.py
COPY core/execution/runner/adapter.py /app/adapter.py
COPY core/execution/runner/homeconsole_runner.py /app/homeconsole_runner.py

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "homeconsole_runner"]

