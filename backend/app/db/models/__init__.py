"""Importing every model here means one import gives Alembic the full metadata."""

from app.db.models.analysis import AnalysisResult
from app.db.models.dataset import Dataset
from app.db.models.sales import Category, Customer, Product, SalesRecord
from app.db.models.user import User

__all__ = [
    "AnalysisResult",
    "Dataset",
    "Category",
    "Customer",
    "Product",
    "SalesRecord",
    "User",
]
