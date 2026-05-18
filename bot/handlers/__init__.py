from aiogram import Router

from bot.handlers.filters import router as filters_router
from bot.handlers.start import router as start_router


def build_root_router() -> Router:
    r = Router()
    r.include_router(start_router)
    r.include_router(filters_router)
    return r


__all__ = ["build_root_router"]
