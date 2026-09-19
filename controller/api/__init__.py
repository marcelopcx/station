"""Composición FastAPI. Importar `controller.api.app:app` desde uvicorn."""

from controller.api.app import app, create_app, create_station

__all__ = ["app", "create_app", "create_station"]
