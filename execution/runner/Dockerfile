FROM python:3.11-slim

# Minimal runner image for D3.1 MVP.
# No plugin code here yet; only runner + sdk if needed later.

WORKDIR /app

# Ship runner as a module: python -m homeconsole_runner
COPY execution/runner/homeconsole_runner.py /app/homeconsole_runner.py

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python", "-m", "homeconsole_runner"]

