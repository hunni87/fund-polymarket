from fastapi import APIRouter

from app.api.v1 import auth, markets, members, symbols, trading

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(members.router)
api_router.include_router(markets.router)
api_router.include_router(symbols.router)
api_router.include_router(trading.router)

__all__ = ["api_router"]
