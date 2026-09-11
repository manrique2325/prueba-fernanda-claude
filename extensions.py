"""Extensiones compartidas. Se instancian aca para evitar imports circulares."""
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
