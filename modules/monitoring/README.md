MonitoringModule
=================

Minimal MonitoringModule exposing Prometheus metrics (`/metrics`) and a basic
health endpoint (`/health`). Intended to be mounted into the ApiModule's FastAPI
app, for example:

```py
from modules.monitoring import MonitoringModule

mon = MonitoringModule()
app.include_router(mon.router, prefix="/monitor")
```

Extend `health_endpoint` to include checks for storage, DB, or external services.
