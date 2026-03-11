import os
import sys
import json
import gzip
import io
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional

from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ParseMode, ContentType, LabeledPrice, PreCheckoutQuery
from aiogram.utils import executor
from aiogram.utils.callback_data import CallbackData
from aiogram.utils.exceptions import MessageNotModified
from dotenv import load_dotenv

from lottie import objects
from lottie.parsers import tgz
from lottie.utils import animation as anim_utils

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(name)

# Загрузка переменных окружения
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.critical("❌ НЕТ ТОКЕНА! Добавь BOT_TOKEN в переменные окружения Render.")
    sys.exit(1)

# Список администраторов (ID через запятую)
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

# Настройки
TEMPLATES_DIR = "templates"
GENERATED_DIR = "generated"
PRICE_PER_EMOJI = 1
TEMPLATES_PER_PAGE = 8

# Хранилища данных
user_selections: Dict[int, List[int]] = {}
user_context: Dict[int, str] = {}
user_page: Dict[int, int] = {}
user_nick: Dict[int, str] = {}
user_free_mode: Dict[int, bool] = {}  # Флаг бесплатного режима для админов

# Инициализация бота и хранилища состояний
storage = MemoryStorage()
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(bot, storage=storage)

# Callback data фабрики
page_cb = CallbackData("page", "num")
tmpl_cb = CallbackData("tmpl", "id")
select_all_cb = CallbackData("select_all")
preview_cb = CallbackData("preview")
checkout_cb = CallbackData("checkout")
pay_cb = CallbackData("pay", "stars")
back_cb = CallbackData("back")
my_sets_cb = CallbackData("my_sets")
topup_cb = CallbackData("topup")
referrals_cb = CallbackData("referrals")
admin_free_cb = CallbackData("admin_free")  # Бесплатная генерация для админа
admin_exit_cb = CallbackData("admin_exit")  # Выход из админ-меню

# --- FSM состояния ---
class Form(StatesGroup):
    waiting_for_nick = State()   # Ожидание ввода ника

# --- Вспомогательные функции ---
def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_templates_list() -> List[Dict]:
    templates = []
    try:
        for filename in os.listdir(TEMPLATES_DIR):
            if filename.endswith('.json'):
                template_id = int(filename.replace('.json', ''))
                templates.append({
                    'id': template_id,
                    'file': filename,
                    'path': os.path.join(TEMPLATES_DIR, filename)
                })
        templates.sort(key=lambda x: x['id'])
        logger.info(f"Найдено {len(templates)} шаблонов")
    except Exception as e:
        logger.error(f"Ошибка при загрузке шаблонов: {e}")
    return templates

def generate_emoji_with_username(template_path: str, username: str, output_path: str) -> bool:
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            animation_dict = json.load(f)
        animation = objects.Animation.from_dict(animation_dict)
        text_replaced = False
        for layer in animation.layers:
            if layer.type == 5:   # Текстовый слой
                if hasattr(layer, 'text') and layer.text:
                    if hasattr(layer.text, 'document') and layer.text.document:
                        layer.text.document.text = username
                        text_replaced = True
                        break
         if not text_replaced:
            logger.warning(f"Не найден текстовый слой в шаблоне {template_path}")
        with gzip.open(output_path, 'wb', compresslevel=9) as f_out:
            json_str = json.dumps(animation.to_dict(), ensure_ascii=False, separators=(',', ':'))
            f_out.write(json_str.encode('utf-8'))
        return True
    except Exception as e:
        logger.error(f"Ошибка генерации эмодзи: {e}")
        return False

def get_templates_keyboard(page: int, selected_ids: List[int], free_mode: bool = False) -> types.InlineKeyboardMarkup:
    templates = get_templates_list()
    total_pages = (len(templates) + TEMPLATES_PER_PAGE - 1) // TEMPLATES_PER_PAGE
    start_idx = (page - 1) * TEMPLATES_PER_PAGE
    end_idx = min(start_idx + TEMPLATES_PER_PAGE, len(templates))
    page_templates = templates[start_idx:end_idx]

    kb = types.InlineKeyboardMarkup(row_width=4)
    # Кнопки шаблонов
    row = []
    for tmpl in page_templates:
        tmpl_id = tmpl['id']
        prefix = "✅ " if tmpl_id in selected_ids else ""
        button = types.InlineKeyboardButton(
            text=f"{prefix}{tmpl_id}",
            callback_data=tmpl_cb.new(id=tmpl_id)
        )
        row.append(button)
        if len(row) == 4:
            kb.row(*row)
            row = []
    if row:
        kb.row(*row)

    # Навигация
    nav_row = []
    if page > 1:
        nav_row.append(types.InlineKeyboardButton("◀️ Назад", callback_data=page_cb.new(num=page-1)))
    if page < total_pages:
        nav_row.append(types.InlineKeyboardButton("Вперед ▶️", callback_data=page_cb.new(num=page+1)))
    if nav_row:
        kb.row(*nav_row)

    # Кнопки управления
    kb.row(
        types.InlineKeyboardButton("✅ Выбрать все", callback_data=select_all_cb.new()),
        types.InlineKeyboardButton("👁 Предпросмотр", callback_data=preview_cb.new())
    )
    if selected_ids:
        if free_mode:
            kb.row(types.InlineKeyboardButton(
                f"🎁 Создать бесплатно ({len(selected_ids)} эмодзи)",
                callback_data=checkout_cb.new()
            ))
        else:
            kb.row(types.InlineKeyboardButton(
                f"⭐ Оплатить {len(selected_ids)} эмодзи",
                callback_data=checkout_cb.new()
            ))
    return kb

def get_main_menu_keyboard(user_id: int) -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    if is_admin(user_id):
        kb.row(types.InlineKeyboardButton("👑 Админ-панель", callback_data="admin_panel"))
    kb.row(
        types.InlineKeyboardButton("🎨 Новый набор", callback_data=page_cb.new(num=1)),
        types.InlineKeyboardButton("📚 Мои наборы", callback_data=my_sets_cb.new())
    )
    kb.row(
        types.InlineKeyboardButton("⭐ Пополнить", callback_data=topup_cb.new()),
        types.InlineKeyboardButton("👥 Рефералы", callback_data=referrals_cb.new())
    )
    return kb

def get_admin_panel_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.row(types.InlineKeyboardButton("🎁 Бесплатная генерация", callback_data=admin_free_cb.new()))
    kb.row(types.InlineKeyboardButton("🔙 Назад", callback_data=back_cb.new()))
    return kb

# --- Обработчики команд ---
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"📊 Твой профиль:\n"
        f"ID: {user_id}\n"
        f"Username: @{message.from_user.username or 'не указан'}\n"
        f"⭐ Баланс: 0\n\n"
        f"Я помогу тебе создать анимированные эмодзи с твоим ником!\n"
        f"Выбери шаблоны в каталоге и оплати звездами."
    )
    await message.answer(text, reply_markup=get_main_menu_keyboard(user_id))
[11.03.2026 16:38] лив.: @dp.message_handler(commands=['litovskiypressf'])
async def cmd_admin_panel(message: types.Message):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("⛔ У вас нет прав доступа.")
        return
    await message.answer(
        "👑 Админ-панель\n\nВыберите действие:",
        reply_markup=get_admin_panel_keyboard()
    )

# --- Обработчики колбэков ---
@dp.callback_query_handler(lambda c: c.data == 'admin_panel')
async def process_admin_panel(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    await callback.message.edit_text(
        "👑 Админ-панель\n\nВыберите действие:",
        reply_markup=get_admin_panel_keyboard()
    )
    await callback.answer()

@dp.callback_query_handler(admin_free_cb.filter())
async def process_admin_free(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer("⛔ Доступ запрещён", show_alert=True)
        return
    # Включаем бесплатный режим
    user_free_mode[user_id] = True
    # Переходим в каталог (страница 1)
    user_page[user_id] = 1
    selected = user_selections.get(user_id, [])
    await callback.message.edit_text(
        f"🎨 Бесплатный режим\nВыбери шаблоны для эмодзи\n"
        f"✅ Выбрано: {len(selected)}\nСтраница 1",
        reply_markup=get_templates_keyboard(1, selected, free_mode=True)
    )
    await callback.answer()

@dp.callback_query_handler(page_cb.filter())
async def process_page(callback: types.CallbackQuery, callback_data: dict):
    user_id = callback.from_user.id
    page = int(callback_data['num'])
    user_page[user_id] = page
    selected = user_selections.get(user_id, [])
    free_mode = user_free_mode.get(user_id, False)
    templates = get_templates_list()
    total_pages = (len(templates) + TEMPLATES_PER_PAGE - 1) // TEMPLATES_PER_PAGE
    mode_text = "🎁 Бесплатный режим\n" if free_mode else ""
    text = (
        f"{mode_text}🎨 Выбери шаблоны для эмодзи\n"
        f"✅ Выбрано: {len(selected)}\n"
        f"💫 Цена: {len(selected) * PRICE_PER_EMOJI} ⭐\n"
        f"Страница {page}/{total_pages}"
    )
    await callback.message.edit_text(text, reply_markup=get_templates_keyboard(page, selected, free_mode))
    await callback.answer()

@dp.callback_query_handler(tmpl_cb.filter())
async def process_template_select(callback: types.CallbackQuery, callback_data: dict):
    user_id = callback.from_user.id
    tmpl_id = int(callback_data['id'])
    selected = user_selections.get(user_id, [])
    if tmpl_id in selected:
        selected.remove(tmpl_id)
    else:
        selected.append(tmpl_id)
    user_selections[user_id] = selected
    page = user_page.get(user_id, 1)
    free_mode = user_free_mode.get(user_id, False)
    templates = get_templates_list()
    total_pages = (len(templates) + TEMPLATES_PER_PAGE - 1) // TEMPLATES_PER_PAGE
    mode_text = "🎁 Бесплатный режим\n" if free_mode else ""
    text = (
        f"{mode_text}🎨 Выбери шаблоны для эмодзи\n"
        f"✅ Выбрано: {len(selected)}\n"
        f"💫 Цена: {len(selected) * PRICE_PER_EMOJI} ⭐\n"
        f"Страница {page}/{total_pages}"
    )
    try:
        await callback.message.edit_text(text, reply_markup=get_templates_keyboard(page, selected, free_mode))
    except MessageNotModified:
        pass
    await callback.answer()

@dp.callback_query_handler(select_all_cb.filter())
async def process_select_all(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    templates = get_templates_list()
    all_ids = [t['id'] for t in templates]
    user_selections[user_id] = all_ids
    page = user_page.get(user_id, 1)
    free_mode = user_free_mode.get(user_id, False)
[11.03.2026 16:38] лив.: templates = get_templates_list()
    total_pages = (len(templates) + TEMPLATES_PER_PAGE - 1) // TEMPLATES_PER_PAGE
    mode_text = "🎁 Бесплатный режим\n" if free_mode else ""
    text = (
        f"{mode_text}🎨 Выбери шаблоны для эмодзи\n"
        f"✅ Выбрано: {len(all_ids)}\n"
        f"💫 Цена: {len(all_ids) * PRICE_PER_EMOJI} ⭐\n"
        f"Страница {page}/{total_pages}"
    )
    await callback.message.edit_text(text, reply_markup=get_templates_keyboard(page, all_ids, free_mode))
    await callback.answer("✅ Выбраны все шаблоны", show_alert=False)

@dp.callback_query_handler(preview_cb.filter())
async def process_preview(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    selected = user_selections.get(user_id, [])
    if not selected:
        await callback.answer("Сначала выбери шаблоны!", show_alert=True)
        return
    templates = get_templates_list()
    template_map = {t['id']: t for t in templates}
    first_id = selected[0]
    if first_id not in template_map:
        await callback.answer("Шаблон не найден", show_alert=True)
        return
    # Для превью используем username из Telegram (как заглушку)
    username = callback.from_user.username or f"user_{user_id}"
    template_path = template_map[first_id]['path']
    preview_path = os.path.join(GENERATED_DIR, f"preview_{user_id}.tgs")
    if generate_emoji_with_username(template_path, f"@{username}", preview_path):
        with open(preview_path, 'rb') as f:
            await callback.message.answer_document(
                types.InputFile(f, filename="preview.tgs"),
                caption=f"👁 Предпросмотр для шаблона {first_id}\nВсего выбрано: {len(selected)}\n(Использован твой текущий ник @{username})"
            )
    else:
        await callback.answer("Ошибка генерации превью", show_alert=True)
    await callback.answer()

@dp.callback_query_handler(checkout_cb.filter())
async def process_checkout(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    selected = user_selections.get(user_id, [])
    if not selected:
        await callback.answer("Сначала выбери шаблоны!", show_alert=True)
        return
    free_mode = user_free_mode.get(user_id, False)
    # Переходим в состояние ожидания ника
    await Form.waiting_for_nick.set()
    async with state.proxy() as data:
        data['selected'] = selected
        data['free_mode'] = free_mode
    if free_mode:
        await callback.message.answer(
            f"✏️ Отправь ник (или любой текст), который будет на эмодзи.\n"
            f"Ты в бесплатном режиме, оплата не потребуется.\n"
            f"Количество эмодзи: {len(selected)}"
        )
    else:
        await callback.message.answer(
            f"✏️ Отправь ник (или любой текст), который будет на эмодзи.\n"
            f"Например: @durov, Durov, или просто твоё имя.\n"
            f"Текст будет подставлен в каждый выбранный шаблон.\n\n"
            f"Количество эмодзи: {len(selected)}\n"
            f"Цена: {len(selected) * PRICE_PER_EMOJI} ⭐"
        )
    await callback.answer()

@dp.message_handler(state=Form.waiting_for_nick)
async def process_nick(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    nick = message.text.strip()
    if not nick:
        await message.answer("❌ Ник не может быть пустым. Попробуй ещё раз.")
        return
    async with state.proxy() as data:
        selected = data.get('selected', user_selections.get(user_id, []))
        free_mode = data.get('free_mode', False)
    if not selected:
        await message.answer("❌ Что-то пошло не так. Начни заново.")
        await state.finish()
        return
    # Сохраняем ник
    user_nick[user_id] = nick
    if free_mode:
        # Бесплатная генерация сразу
        await generate_and_send_pack(message, user_id, selected, nick)
[11.03.2026 16:38] лив.: await state.finish()
        return
    # Обычный платёж
    total_stars = len(selected) * PRICE_PER_EMOJI
    payload = f"emoji_pack_{user_id}_{datetime.now().timestamp()}"
    user_context[user_id] = payload
    try:
        await bot.send_invoice(
            chat_id=user_id,
            title="Создание набора эмодзи",
            description=f"Набор из {len(selected)} анимированных эмодзи с ником: {nick}",
            payload=payload,
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label="Эмодзи", amount=total_stars)],
            start_parameter="create_emoji_pack"
        )
    except Exception as e:
        logger.error(f"Ошибка создания инвойса: {e}")
        await message.answer("❌ Ошибка при создании платежа")
    await state.finish()

@dp.pre_checkout_query_handler(lambda query: True)
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

async def generate_and_send_pack(original_message: types.Message, user_id: int, selected: List[int], nick: str):
    """Генерирует и отправляет набор эмодзи (используется после оплаты или в бесплатном режиме)."""
    await original_message.answer(
        f"✅ Начинаю генерацию {len(selected)} эмодзи с ником «{nick}»...\n"
        f"Это займет несколько секунд."
    )
    templates = get_templates_list()
    template_map = {t['id']: t for t in templates}
    generated_files = []
    for idx, tmpl_id in enumerate(selected):
        if tmpl_id not in template_map:
            continue
        template_path = template_map[tmpl_id]['path']
        output_filename = f"{user_id}_{tmpl_id}_{int(datetime.now().timestamp())}.tgs"
        output_path = os.path.join(GENERATED_DIR, output_filename)
        if idx % 5 == 0 and idx > 0:
            await original_message.answer(f"⏳ Прогресс: {idx}/{len(selected)}")
        if generate_emoji_with_username(template_path, nick, output_path):
            generated_files.append(output_path)
        else:
            await original_message.answer(f"⚠️ Ошибка при генерации шаблона {tmpl_id}")
    if not generated_files:
        await original_message.answer("❌ Не удалось сгенерировать ни одного эмодзи")
        return
    await original_message.answer(
        f"✅ Готово! Сгенерировано {len(generated_files)} эмодзи.\n\n"
        f"📌 Чтобы создать набор:\n"
        f"1. Отправь команду @Stickers /newemojipack\n"
        f"2. Выбери тип 'Animated emoji'\n"
        f"3. Придумай название\n"
        f"4. Загружай файлы в том порядке, в котором они отправлены ниже"
    )
    for file_path in generated_files:
        try:
            with open(file_path, 'rb') as f:
                await original_message.answer_document(
                    types.InputFile(f, filename=os.path.basename(file_path))
                )
            os.remove(file_path)
        except Exception as e:
            logger.error(f"Ошибка при отправке файла {file_path}: {e}")
    # Очищаем временные данные
    if user_id in user_selections:
        del user_selections[user_id]
    if user_id in user_context:
        del user_context[user_id]
    if user_id in user_nick:
        del user_nick[user_id]
    if user_id in user_free_mode:
        del user_free_mode[user_id]

@dp.message_handler(content_types=ContentType.SUCCESSFUL_PAYMENT)
async def process_successful_payment(message: types.Message):
    user_id = message.from_user.id
    selected = user_selections.get(user_id, [])
    if not selected:
        await message.answer("❌ Ошибка: не найдены выбранные шаблоны")
        return
    nick = user_nick.get(user_id)
    if not nick:
        await message.answer("❌ Не найден ник для генерации. Пожалуйста, обратись в поддержку.")
        return
    await generate_and_send_pack(message, user_id, selected, nick)
[11.03.2026 16:38] лив.: @dp.callback_query_handler(lambda c: c.data in ['my_sets', 'topup', 'referrals', 'back'])
async def process_other_callbacks(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if callback.data == 'my_sets':
        await callback.message.answer("📚 У тебя пока нет сохранённых наборов. Сначала создай новый!")
    elif callback.data == 'topup':
        await callback.message.answer("⭐ Пополнение баланса через Stars происходит автоматически при оплате.")
    elif callback.data == 'referrals':
        await callback.message.answer("👥 Реферальная система пока в разработке.")
    elif callback.data == 'back':
        # Возврат в главное меню
        await cmd_start(callback.message)
    await callback.answer()

@dp.message_handler(commands=['cancel'], state='*')
async def cancel_handler(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        return
    await state.finish()
    await message.answer("❌ Действие отменено. Возвращаюсь в меню.", reply_markup=get_main_menu_keyboard(message.from_user.id))

# --- Запуск ---
async def on_startup(dp):
    await bot.delete_webhook()
    os.makedirs(TEMPLATES_DIR, exist_ok=True)
    os.makedirs(GENERATED_DIR, exist_ok=True)
    templates = get_templates_list()
    if not templates:
        logger.warning(f"В папке {TEMPLATES_DIR} нет JSON-шаблонов!")
    logger.info("Бот запущен и готов к работе!")

if name == "main":
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)




