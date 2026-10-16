from fastapi import APIRouter

from app.api.routes import analytics, auth, datasets, forecast, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
# Datasets first: its routes are declared with static segments before
# "/{dataset_id}", and the analytics router adds more paths under the same
# prefix. Registration order decides which pattern a request matches.
api_router.include_router(datasets.router)
api_router.include_router(analytics.router)
# Forecasting last: its dataset routes sit under the same "/datasets/{id}"
# prefix, and registration order decides which pattern a request matches.
api_router.include_router(forecast.router)

__all__ = ["api_router"]
