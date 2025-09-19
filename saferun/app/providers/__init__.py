"""Providers package exports a small factory used by tests and the app.

This file keeps imports light-weight to avoid circular imports during startup.
"""
from . import factory

__all__ = ["factory"]
