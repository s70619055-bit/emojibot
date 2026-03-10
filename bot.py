import sys
import logging
import asyncio
import os

# Настраиваем логирование, чтобы ВСЁ писать в консоль
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

logger.info("="*50)
logger.info("ЗАПУСК БОТА")
logger.info("="*50)

# 1. Сначала проверим самую частую причину - токен
logger.info("Проверяем переменную BOT_TOKEN...")
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("🚨 КРИТИЧЕСКАЯ ОШИБКА: Переменная BOT_TOKEN не найдена!")
    logger.critical("Убедись, что ты добавил её в разделе Environment на Render.")
    sys.exit(1)
else:
    logger.info("✅ BOT_TOKEN найден")

# 2. Попробуем импортировать библиотеки и поймать ошибку
logger.info("Пробуем импортировать библиотеки...")
try:
    import json
    import gzip
    from datetime import datetime
    from typing import Dict, List, Optional
    logger.info("✅ Стандартные библиотеки импортированы")

    from aiogram import Bot, Dispatcher, types, F
    from aiogram.filters import Command
    from aiogram.types import LabeledPrice, PreCheckoutQuery
    from aiogram.utils.keyboard import InlineKeyboardBuilder
    logger.info("✅ aiogram импортирован")

    from dotenv import load_dotenv
    logger.info("✅ dotenv импортирован")

    from lottie import objects
    from lottie.parsers import tgz
    from lottie.utils import animation as anim_utils
    logger.info("✅ lottie импортирован")

except Exception as e:
    logger.critical(f"🚨 ОШИБКА ИМПОРТА БИБЛИОТЕКИ: {e}", exc_info=True)
    sys.exit(1)

# 3. Проверим наличие папки с шаблонами
logger.info("Проверяем папку templates...")
if not os.path.exists("templates"):
    logger.critical("🚨 Папка 'templates' не найдена!")
    sys.exit(1)
else:
    files = os.listdir("templates")
    logger.info(f"✅ Папка templates найдена, в ней {len(files)} файлов")

# 4. Теперь попробуем создать минимального бота
logger.info("Создаём экземпляр бота...")
try:
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    logger.info("✅ Бот создан")
except Exception as e:
    logger.critical(f"🚨 Ошибка создания бота: {e}", exc_info=True)
    sys.exit(1)

# 5. Добавим простую команду для проверки
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("✅ Бот работает!")

# 6. Запускаем с обработкой ошибок
async def main():
    try:
        logger.info("Удаляем вебхук...")
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Вебхук удалён")

        logger.info("🚀 Запускаем поллинг...")
        await dp.start_polling(bot)
    except Exception as e:
        logger.critical(f"🚨 Ошибка во время поллинга: {e}", exc_info=True)
        sys.exit(1)

if name == "main":
    logger.info("Запускаем main()...")
    try:
        asyncio.run(main())
    except Exception as e:
        logger.critical(f"🚨 Критическая ошибка: {e}", exc_info=True)
        sys.exit(1)
      

