from aiogram import Router

from bot.handlers.admin import router as admin_router
from bot.handlers.favorites import router as favorites_router
from bot.handlers.filters import router as filters_router
from bot.handlers.menu import router as menu_router
from bot.handlers.search import router as search_router
from bot.handlers.start import router as start_router


def build_root_router() -> Router:
    r = Router()
    # admin — первым: команды только для админов, для остальных просто молчит
    r.include_router(admin_router)
    # menu — затем: его callback'и должны срабатывать сразу;
    # FSM-роутер фильтра (filters) обрабатывает только своё состояние.
    r.include_router(menu_router)
    r.include_router(start_router)
    r.include_router(filters_router)
    r.include_router(search_router)
    r.include_router(favorites_router)
    return r


__all__ = ["build_root_router"]
