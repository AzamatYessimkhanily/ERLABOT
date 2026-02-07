import logging
import sys
import gspread
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
# --- КОНФИГУРАЦИЯ ---
BOT_TOKEN = '7780440391:AAEYlDcEq9egFWa8s_dq6v4-DZQVKXTy21E'
SHEET_ID = '1DCUghK3I2108lyMbpM_1n_XTDw9HxhhaBhmAmOt9rXo'
CREDENTIALS_FILE = 'sheetsapi-443912-7487420df9cd.json'

# --- НАСТРОЙКА ЛОГИРОВАНИЯ ---
logging.basicConfig(level=logging.INFO)

# --- ПОДКЛЮЧЕНИЕ К GOOGLE SHEETS ---
try:
    gc = gspread.service_account(filename=CREDENTIALS_FILE)
    sheet = gc.open_by_key(SHEET_ID)
    
    try:
        ws_balance = sheet.worksheet("Баланс")
    except:
        ws_balance = sheet.add_worksheet(title="Баланс", rows=10, cols=5)
        ws_balance.append_row(["Фонд 1 (Себестоимость)", "Фонд 2 (Операционка)", "Фонд 3 (Доп/Прибыль)", "ВСЕГО"])
        ws_balance.append_row([0, 0, 0, 0])

    try:
        ws_config = sheet.worksheet("Настройки")
    except:
        ws_config = sheet.add_worksheet(title="Настройки", rows=10, cols=5)
        ws_config.append_row(["% Фонд 1", "% Фонд 2", "% Фонд 3", "Точка Безубыточности"])
    
    try:
        ws_trans = sheet.worksheet("История")
    except:
        ws_trans = sheet.add_worksheet(title="История", rows=1000, cols=6)
        ws_trans.append_row(["Дата", "Тип", "Сумма", "Фонд", "Коммент", "Пользователь"])

    print("✅ Успешное подключение к таблице!")

except Exception as e:
    print(f"❌ КРИТИЧЕСКАЯ ОШИБКА ПОДКЛЮЧЕНИЯ: {e}")
    sys.exit()

# --- ИНИЦИАЛИЗАЦИЯ БОТА ---
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# --- МАШИНА СОСТОЯНИЙ ---
class Form(StatesGroup):
    setup_cost = State()
    setup_opex = State()
    setup_addex = State()
    
    income_amount = State()
    
    expense_amount = State()
    expense_fund = State()
    expense_comment = State()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def format_number(num):
    """Форматирование числа с пробелами (1 000 000)"""
    return '{:,}'.format(int(num)).replace(',', ' ')

def get_progress_bar(current, total, length=10):
    """Создает красивый прогресс-бар"""
    if total == 0:
        return "░" * length
    
    filled = int((current / total) * length)
    bar = "█" * filled + "░" * (length - filled)
    percentage = int((current / total) * 100)
    return f"{bar} {percentage}%"

def get_health_emoji(percentage):
    """Возвращает эмодзи в зависимости от процента заполнения"""
    if percentage >= 80:
        return "🟢"
    elif percentage >= 50:
        return "🟡"
    elif percentage >= 20:
        return "🟠"
    else:
        return "🔴"

# --- КЛАВИАТУРЫ ---

def get_main_keyboard():
    """Главное меню с красивыми кнопками"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    keyboard.add(
        types.KeyboardButton("💰 Доход"),
        types.KeyboardButton("💸 Расход")
    )
    keyboard.add(
        types.KeyboardButton("📊 Баланс"),
        types.KeyboardButton("📈 Аналитика")
    )
    # 👇 ДОБАВИЛ НОВЫЙ РЯД КНОПОК
    keyboard.add(
        types.KeyboardButton("⚙️ Настройки"),
        types.KeyboardButton("🔗 Таблица")
    )
    return keyboard

def get_fund_keyboard():
    """Меню выбора фонда"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    keyboard.add("🏗 Себестоимость")
    keyboard.add("💻 Операционка")
    keyboard.add("☕️ Доп. расходы")
    keyboard.add("🔙 Отмена")
    return keyboard

def get_settings_keyboard():
    """Меню настроек"""
    keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    keyboard.add("🔄 Пересчитать расходы")
    keyboard.add("📋 Показать настройки")
    keyboard.add("🔙 Главное меню")
    return keyboard

# --- ПРИВЕТСТВЕННОЕ СООБЩЕНИЕ ---

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    settings = ws_config.row_values(2)
    
    if not settings:
        welcome_text = (
            "💎 *FUNDAMENTA BOT*\n"
            "━━━━━━━━━━━━━━\n\n"
            f"Привет, {message.from_user.first_name}! 👋\n\n"
            "Я помогу навести порядок в твоих финансах.\n\n"
            "Система работает по принципу 3-х фондов:\n\n"
            "🏗 *Фонд 1* — Себестоимость\n"
            "💻 *Фонд 2* — Операционка\n"
            "☕️ *Фонд 3* — Дополнительные расходы\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "Для начала работы мне нужно задать несколько вопросов.\n\n"
            "*Вопрос 1 из 3* 📝\n\n"
            "Сколько денег в месяц уходит на *обязательные* расходы?\n"
            "_(Себестоимость продукта/услуги)_\n\n"
            "Введи сумму цифрами, например: `1500000`"
        )
        await message.answer(welcome_text, parse_mode="Markdown")
        await Form.setup_cost.set()
    else:
        welcome_back = (
            "💎 *FUNDAMENTA BOT*\n"
            "━━━━━━━━━━━━━━\n\n"
            f"С возвращением, {message.from_user.first_name}! ✨\n\n"
            "Система настроена и готова к работе.\n"
            "Выбери нужное действие:"
        )
        await message.answer(welcome_back, parse_mode="Markdown", reply_markup=get_main_keyboard())

# --- БЛОК НАСТРОЙКИ ---

@dp.message_handler(state=Form.setup_cost)
async def process_setup_cost(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Пожалуйста, введи только цифры.\n\nНапример: `1500000`", parse_mode="Markdown")
    
    async with state.proxy() as data:
        data['cost'] = int(message.text)
    
    progress = (
        "━━━━━━━━━━━━━━\n"
        "Прогресс: ████░░ 33%\n"
        "━━━━━━━━━━━━━━\n\n"
        "*Вопрос 2 из 3* 📝\n\n"
        "Введи сумму *операционных* расходов:\n"
        "_(Зарплаты менеджеров, реклама, маркетинг)_\n\n"
        "Например: `800000`"
    )
    await message.answer(progress, parse_mode="Markdown")
    await Form.setup_opex.set()

@dp.message_handler(state=Form.setup_opex)
async def process_setup_opex(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Только цифры, пожалуйста!")
    
    async with state.proxy() as data:
        data['opex'] = int(message.text)
    
    progress = (
        "━━━━━━━━━━━━━━\n"
        "Прогресс: ████████░░ 66%\n"
        "━━━━━━━━━━━━━━\n\n"
        "*Вопрос 3 из 3* 📝\n\n"
        "Сколько закладываем на *дополнительные* расходы?\n"
        "_(Офис, вода, канцелярия и прочее)_\n\n"
        "Например: `200000`"
    )
    await message.answer(progress, parse_mode="Markdown")
    await Form.setup_addex.set()

@dp.message_handler(state=Form.setup_addex)
async def process_setup_addex(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Только цифры!")
    
    addex = int(message.text)
    async with state.proxy() as data:
        cost = data['cost']
        opex = data['opex']
    
    tb = cost + opex + addex
    
    if tb == 0:
        return await message.answer("❌ Сумма расходов не может быть 0.\nНачни заново: /start")

    p_cost = cost / tb
    p_opex = opex / tb
    p_addex = addex / tb
    
    ws_config.clear()
    ws_config.append_row(["% Фонд 1", "% Фонд 2", "% Фонд 3", "Точка Безубыточности"])
    ws_config.append_row([p_cost, p_opex, p_addex, tb])
    
    result_text = (
        "━━━━━━━━━━━━━━\n"
        "Прогресс: ██████████ 100%\n"
        "━━━━━━━━━━━━━━\n\n"
        "✅ *НАСТРОЙКА ЗАВЕРШЕНА!*\n\n"
        f"🎯 *Точка безубыточности*\n"
        f"   {format_number(tb)} ₸/мес\n\n"
        "*Распределение доходов:*\n\n"
        f"🏗 Себестоимость: *{round(p_cost*100, 1)}%*\n"
        f"💻 Операционка: *{round(p_opex*100, 1)}%*\n"
        f"☕️ Доп. расходы: *{round(p_addex*100, 1)}%*\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "💡 Теперь все поступления будут автоматически распределяться по этим процентам!"
    )
    
    await state.finish()
    await message.answer(result_text, parse_mode="Markdown", reply_markup=get_main_keyboard())

# --- БЛОК ДОХОДА ---

@dp.message_handler(lambda message: message.text == "💰 Доход")
async def income_start(message: types.Message):
    prompt = (
        "💰 *НОВЫЙ ДОХОД*\n"
        "━━━━━━━━━━━━━━\n\n"
        "Введи сумму поступления:\n"
        "_(только цифры)_\n\n"
        "Пример: `500000`"
    )
    await message.answer(prompt, parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
    await Form.income_amount.set()

@dp.message_handler(state=Form.income_amount)
async def income_process(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Напиши просто число, например: 500000")
    
    amount = int(message.text)
    
    try:
        settings = ws_config.row_values(2)
        if not settings:
            raise ValueError("Пустая строка настроек")
            
        p_cost = float(str(settings[0]).replace(',', '.'))
        p_opex = float(str(settings[1]).replace(',', '.'))
        p_addex = float(str(settings[2]).replace(',', '.'))
        
    except Exception as e:
        print(f"Ошибка чтения настроек: {e}")
        await state.finish()
        return await message.answer(
            "❌ Ошибка чтения настроек!\n\n"
            "Попробуй заново: /start",
            reply_markup=get_main_keyboard()
        )
    
    add_f1 = int(amount * p_cost)
    add_f2 = int(amount * p_opex)
    add_f3 = amount - add_f1 - add_f2
    
    current_balance = ws_balance.row_values(2)
    if not current_balance: 
        current_balance = [0, 0, 0, 0]
    else:
        current_balance = [0 if x == '' else int(str(x).replace(' ', '')) for x in current_balance]
        while len(current_balance) < 4:
            current_balance.append(0)
    
    new_f1 = int(current_balance[0]) + add_f1
    new_f2 = int(current_balance[1]) + add_f2
    new_f3 = int(current_balance[2]) + add_f3
    total = new_f1 + new_f2 + new_f3
    
    ws_balance.update(values=[[new_f1, new_f2, new_f3, total]], range_name='A2:D2')
    
    from datetime import datetime
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
    ws_trans.append_row([date_now, "ДОХОД", amount, "РАСПРЕДЕЛЕНИЕ", "Автоматически", message.from_user.username])
    
    result = (
        "✅ *ДОХОД ПОЛУЧЕН*\n"
        "━━━━━━━━━━━━━━\n\n"
        f"*Поступление:* {format_number(amount)} ₸\n\n"
        "*Распределено:*\n\n"
        f"🏗 Себестоимость\n"
        f"   +{format_number(add_f1)} ₸ ({round(p_cost*100, 1)}%)\n\n"
        f"💻 Операционка\n"
        f"   +{format_number(add_f2)} ₸ ({round(p_opex*100, 1)}%)\n\n"
        f"☕️ Доп. расходы\n"
        f"   +{format_number(add_f3)} ₸ ({round(p_addex*100, 1)}%)\n\n"
        "━━━━━━━━━━━━━━\n"
        f"💰 *Новый баланс:* {format_number(total)} ₸"
    )
    
    await state.finish()
    await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())

# --- БЛОК РАСХОДА ---

@dp.message_handler(lambda message: message.text == "💸 Расход")
async def expense_start(message: types.Message):
    prompt = (
        "💸 *НОВЫЙ РАСХОД*\n"
        "━━━━━━━━━━━━━━\n\n"
        "Введи сумму расхода:\n"
        "_(только цифры)_\n\n"
        "Пример: `50000`"
    )
    await message.answer(prompt, parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
    await Form.expense_amount.set()

@dp.message_handler(state=Form.expense_amount)
async def expense_amount_step(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        return await message.answer("⚠️ Напиши просто число.")
    
    async with state.proxy() as data:
        data['amount'] = int(message.text)
        
    prompt = (
        "Из какого фонда списываем?\n\n"
        "Выбери один из вариантов ниже:"
    )
    await message.answer(prompt, reply_markup=get_fund_keyboard())
    await Form.expense_fund.set()

@dp.message_handler(state=Form.expense_fund)
async def expense_fund_step(message: types.Message, state: FSMContext):
    choice = message.text
    if choice == "🔙 Отмена":
        await state.finish()
        return await message.answer("❌ Операция отменена", reply_markup=get_main_keyboard())

    fund_index = -1
    fund_name = ""
    
    if "Себестоимость" in choice:
        fund_index = 0
        fund_name = "Себестоимость"
    elif "Операционка" in choice:
        fund_index = 1
        fund_name = "Операционка"
    elif "Доп. расходы" in choice:
        fund_index = 2
        fund_name = "Доп. расходы"
    else:
        return await message.answer("⚠️ Выбери кнопку из меню.")

    async with state.proxy() as data:
        amount = data['amount']

    current_vals = ws_balance.row_values(2)
    if not current_vals: 
        current_vals = [0, 0, 0, 0]
    else:
        current_vals = [0 if x == '' else int(str(x).replace(' ', '')) for x in current_vals]
        while len(current_vals) < 4:
            current_vals.append(0)
    
    current_fund_money = int(current_vals[fund_index])
    
    if current_fund_money < amount:
        deficit = amount - current_fund_money
        warning = (
            "⛔️ *НЕДОСТАТОЧНО СРЕДСТВ*\n"
            "━━━━━━━━━━━━━━\n\n"
            f"*Фонд:* {fund_name}\n"
            f"*Доступно:* {format_number(current_fund_money)} ₸\n"
            f"*Требуется:* {format_number(amount)} ₸\n\n"
            f"🔴 *Не хватает:* {format_number(deficit)} ₸\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "💡 *Правило FUNDAMENTA:*\n"
            "Нельзя брать деньги из других фондов.\n"
            "Дождись новых поступлений или пересмотри расходы."
        )
        await state.finish()
        return await message.answer(warning, parse_mode="Markdown", reply_markup=get_main_keyboard())

    new_val = current_fund_money - amount
    ws_balance.update_cell(2, fund_index + 1, new_val)
    
    total = int(current_vals[3]) - amount
    ws_balance.update_cell(2, 4, total)
    
    async with state.proxy() as data:
        data['fund_name'] = fund_name
    
    await message.answer(
        "📝 Последний шаг!\n\n"
        "Напиши комментарий:\n"
        "*(На что тратим деньги?)*\n\n"
        "Например: `Оплата за рекламу`",
        parse_mode="Markdown"
    )
    await Form.expense_comment.set()

@dp.message_handler(state=Form.expense_comment)
async def expense_final(message: types.Message, state: FSMContext):
    comment = message.text
    async with state.proxy() as data:
        amount = data['amount']
        fund_name = data['fund_name']
        
    from datetime import datetime
    date_now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    ws_trans.append_row([date_now, "РАСХОД", -amount, fund_name, comment, message.from_user.username])
    
    # Получаем обновленные остатки
    vals = ws_balance.row_values(2)
    if not vals: 
        vals = [0, 0, 0, 0]
    
    result = (
        "✅ *РАСХОД СПИСАН*\n"
        "━━━━━━━━━━━━━━\n\n"
        f"*Сумма:* -{format_number(amount)} ₸\n"
        f"*Фонд:* {fund_name}\n"
        f"*Цель:* {comment}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "*Остатки в фондах:*\n\n"
        f"🏗 Себестоимость: {format_number(vals[0])} ₸\n"
        f"💻 Операционка: {format_number(vals[1])} ₸\n"
        f"☕️ Доп. расходы: {format_number(vals[2])} ₸\n\n"
        f"💰 Всего: {format_number(vals[3])} ₸"
    )
    
    await state.finish()
    await message.answer(result, parse_mode="Markdown", reply_markup=get_main_keyboard())

# --- БЛОК БАЛАНСА ---

@dp.message_handler(lambda message: message.text == "📊 Баланс")
async def show_balance(message: types.Message):
    vals = ws_balance.row_values(2)
    if not vals: 
        vals = [0, 0, 0, 0]
    else:
        vals = [0 if x == '' else int(str(x).replace(' ', '')) for x in vals]
        while len(vals) < 4:
            vals.append(0)
    
    try:
        settings = ws_config.row_values(2)
        tb = float(str(settings[3]).replace(',', '.'))
        p_cost = float(str(settings[0]).replace(',', '.'))
        p_opex = float(str(settings[1]).replace(',', '.'))
        p_addex = float(str(settings[2]).replace(',', '.'))
    except:
        tb = 0
        p_cost = p_opex = p_addex = 0

    total_money = int(vals[3])
    runway = round(total_money / tb, 1) if tb > 0 else 0
    
    # Прогресс-бары для каждого фонда
    target_f1 = int(tb * p_cost) if tb > 0 else 1
    target_f2 = int(tb * p_opex) if tb > 0 else 1
    target_f3 = int(tb * p_addex) if tb > 0 else 1
    
    bar1 = get_progress_bar(vals[0], target_f1)
    bar2 = get_progress_bar(vals[1], target_f2)
    bar3 = get_progress_bar(vals[2], target_f3)
    
    # Эмодзи здоровья
    health_emoji = "🟢" if runway >= 3 else "🟡" if runway >= 1 else "🔴"
    
    text = (
        "📊 *БАЛАНС ФОНДОВ*\n"
        "━━━━━━━━━━━━━━\n\n"
        f"🏗 *Себестоимость*\n"
        f"   {format_number(vals[0])} ₸\n"
        f"   {bar1}\n\n"
        f"💻 *Операционка*\n"
        f"   {format_number(vals[1])} ₸\n"
        f"   {bar2}\n\n"
        f"☕️ *Доп. расходы*\n"
        f"   {format_number(vals[2])} ₸\n"
        f"   {bar3}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"💰 *ВСЕГО В КАССЕ*\n"
        f"   {format_number(total_money)} ₸\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"{health_emoji} *Запас хода:* {runway} мес.\n"
        f"   _(Сколько проживет бизнес\n"
        f"   без новых поступлений)_\n\n"
        f"🎯 *Точка безубыточности:*\n   {format_number(tb)} ₸/мес"
    )
    
    await message.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard())

# --- БЛОК АНАЛИТИКИ ---

@dp.message_handler(lambda message: message.text == "📈 Аналитика")
async def show_analytics(message: types.Message):
    # Получаем последние 10 транзакций
    try:
        all_trans = ws_trans.get_all_values()
        if len(all_trans) <= 1:
            return await message.answer(
                "📊 *Транзакций пока нет*\n\n"
                "Начни добавлять доходы и расходы!",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard()
            )
        
        recent = all_trans[-11:]  # Последние 10 + заголовок
        recent.reverse()  # Новые сверху
        
        text = "📈 *ПОСЛЕДНИЕ ОПЕРАЦИИ*\n\n"
        
        count = 0
        for row in recent:
            if len(row) < 3 or row[0] == "Дата":  # Пропускаем заголовок
                continue
            
            count += 1
            if count > 10:  # Максимум 10 операций
                break
                
            date = row[0][:10] if len(row[0]) > 10 else row[0]
            op_type = row[1]
            amount = row[2]
            comment = row[4] if len(row) > 4 else ""
            
            emoji = "💰" if op_type == "ДОХОД" else "💸"
            
            text += f"{emoji} *{date}*\n"
            text += f"   {format_number(abs(float(amount)))} ₸\n"
            if comment and comment != "Автоматически":
                text += f"   _{comment}_\n"
            text += "\n"
        
        text += "━━━━━━━━━━━━━━\n"
        text += "💡 Полная история в Google Таблице"
        
        await message.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard())
        
    except Exception as e:
        await message.answer(
            f"❌ Ошибка загрузки аналитики\n\n`{str(e)}`",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard()
        )

# --- БЛОК НАСТРОЕК ---

@dp.message_handler(lambda message: message.text == "⚙️ Настройки")
async def settings_menu(message: types.Message):
    text = (
        "⚙️ *НАСТРОЙКИ*\n"
        "━━━━━━━━━━━━━━\n\n"
        "Выбери действие:"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=get_settings_keyboard())

@dp.message_handler(lambda message: message.text == "📋 Показать настройки")
async def show_settings(message: types.Message):
    try:
        settings = ws_config.row_values(2)
        tb = float(str(settings[3]).replace(',', '.'))
        p_cost = float(str(settings[0]).replace(',', '.'))
        p_opex = float(str(settings[1]).replace(',', '.'))
        p_addex = float(str(settings[2]).replace(',', '.'))
        
        text = (
            "📋 *ТЕКУЩИЕ НАСТРОЙКИ*\n"
            "━━━━━━━━━━━━━━\n\n"
            f"🎯 *Точка безубыточности:*\n"
            f"   {format_number(tb)} ₸/мес\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "*Распределение доходов:*\n\n"
            f"🏗 Себестоимость: *{round(p_cost*100, 1)}%*\n"
            f"💻 Операционка: *{round(p_opex*100, 1)}%*\n"
            f"☕️ Доп. расходы: *{round(p_addex*100, 1)}%*\n\n"
            "━━━━━━━━━━━━━━\n\n"
            "💡 Для изменения используй\n"
            "   кнопку «Пересчитать расходы»"
        )
        
        await message.answer(text, parse_mode="Markdown", reply_markup=get_settings_keyboard())
        
    except:
        await message.answer("❌ Ошибка чтения настроек", reply_markup=get_settings_keyboard())

@dp.message_handler(lambda message: message.text == "🔄 Пересчитать расходы")
async def reset_settings(message: types.Message):
    try:
        settings = ws_config.row_values(2)
        current_tb = format_number(float(str(settings[3]).replace(',', '.'))) if len(settings) > 3 else "Не задано"
    except:
        current_tb = "Ошибка"

    warning = (
        "⚠️ *ВНИМАНИЕ!*\n"
        "━━━━━━━━━━━━━━\n\n"
        f"Текущая ТБ: *{current_tb} ₸*\n\n"
        "Вы изменяете финансовую модель.\n\n"
        "*Что произойдет:*\n"
        "✅ Деньги в фондах останутся на месте\n"
        "🔄 Новые поступления будут делиться по новым %\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "*Вопрос 1 из 3* 📝\n\n"
        "Введи новую сумму *обязательных* расходов:\n"
        "_(Себестоимость)_\n\n"
        "Например: `1500000`"
    )
    
    await message.answer(warning, parse_mode="Markdown", reply_markup=types.ReplyKeyboardRemove())
    await Form.setup_cost.set()

@dp.message_handler(lambda message: message.text == "🔙 Главное меню")
async def back_to_main(message: types.Message):
    await message.answer("Главное меню:", reply_markup=get_main_keyboard())
# --- БЛОК ССЫЛКИ НА ТАБЛИЦУ ---

@dp.message_handler(lambda message: message.text == "🔗 Таблица")
async def send_sheet_link(message: types.Message):
    # Формируем ссылку на твою таблицу
    sheet_url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}"
    
    # Создаем кнопку-ссылку (Inline)
    keyboard = types.InlineKeyboardMarkup()
    url_button = types.InlineKeyboardButton(text="📂 Открыть Google Таблицу", url=sheet_url)
    keyboard.add(url_button)
    
    text = (
        "📊 *ВАША ТАБЛИЦА УЧЕТА*\n"
        "━━━━━━━━━━━━━━\n\n"
        "Все данные хранятся в облаке Google.\n"
        "Вы можете зайти и отредактировать их вручную в любой момент.\n\n"
        "👇 *Нажмите на кнопку ниже, чтобы открыть:* "
    )
    
    await message.answer(text, parse_mode="Markdown", reply_markup=keyboard)
# --- ЗАПУСК БОТА ---

if __name__ == '__main__':
    print("━━━━━━━━━━━━━━")
    print("💎 FUNDAMENTA BOT")
    print("✅ Бот запущен!")
    print("━━━━━━━━━━━━━━")
    executor.start_polling(dp, skip_updates=True)