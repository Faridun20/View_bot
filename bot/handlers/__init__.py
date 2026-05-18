from aiogram import Router

from bot.handlers.filters import router as filters_router
from bot.handlers.menu import router as menu_router
from bot.handlers.search import router as search_router
from bot.handlers.start import router as start_router


def build_root_router() -> Router:
    r = Router()
    # menu — первым: его callback'и должны срабатывать сразу;
    # FSM-роутер фильтра (filters) обрабатывает только своё состояние.
    r.include_router(menu_router)
    r.include_router(start_router)
    r.include_router(filters_router)
    r.include_router(search_router)
    return r


__all__ = ["build_root_router"]
