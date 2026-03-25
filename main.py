import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeDefault

from config import BOT_TOKEN
from handlers import commands, request_form, requests_view, statistics, admin, common, group_messages

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize bot and dispatcher
bot = Bot(token=8251658039:AAHg__fHz5fSkeYeI9PFby7aI4IUYRKQnxE)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Register routers
dp.include_router(commands.router)
dp.include_router(request_form.router)
dp.include_router(requests_view.router)
dp.include_router(statistics.router)
dp.include_router(admin.router)
dp.include_router(common.router)
dp.include_router(group_messages.router)


async def set_default_commands(bot: Bot):
    """Set default bot commands"""
    commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="help", description="Справка"),
    ]
    await bot.set_my_commands(commands, BotCommandScopeDefault())


async def main():
    """Main function"""
    # Set default commands
    await set_default_commands(bot)

    # Start polling
    logger.info("Bot started polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
