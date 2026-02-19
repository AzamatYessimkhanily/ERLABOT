import logging
import sys
import re
import gspread
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 💎 FUNDAMENTA BOT — КОНФИГУРАЦИЯ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BOT_TOKEN = '7780440391:AAEYlDcEq9egFWa8s_dq6v4-DZQVKXTy21E'
MASTER_SHEET_ID = '1DCUghK3I2108lyMbpM_1n_XTDw9HxhhaBhmAmOt9rXo'
CREDENTIALS_FILE = 'sheetsapi-443912-7487420df9cd.json'
YOUTUBE_LESSON_URL = "https://youtube.com/"

VIDEO_1_INTRO = "DQACAgIAAxkBAAICCmmUgJ-9aD1_vuMco8tXcv9AC0RpAAJ4jQACTpWoSF_997AbFDQaOgQ"
VIDEO_2_SEBES = "DQACAgIAAxkBAAICDGmUgJ_G4WYKwxkKYvtXuD1sohMKAAKHjQACTpWoSJoKnlDD7qDtOgQ"
VIDEO_3_OPER  = "DQACAgIAAxkBAAICC2mUgJ-IPpL8vGPfC6Giib0e1U7ZAAKDjQACTpWoSLnsjGLdJkKcOgQ"
VIDEO_4_DOP   = "DQACAgIAAxkBAAICDWmUgJ8ybwsukX88otT2SVMs5GR-AAKNjQACTpWoSGlethuhDPdpOgQ"

FUND_VIDEOS = {1: VIDEO_2_SEBES, 2: VIDEO_3_OPER, 3: VIDEO_4_DOP}
# Круг 1 (VIDEO_1_INTRO) отправляется в /start
# Круг 2 (VIDEO_2_SEBES) объясняет себестоимость → с Шагом 1
# Круг 3 (VIDEO_3_OPER) объясняет операционные → с Шагом 2
# Круг 4 (VIDEO_4_DOP) объясняет дополнительные → с Шагом 3
# После финала — без видео, только результат + YouTube

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📝 ЛОГИРОВАНИЕ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('fundamenta_bot.log', encoding='utf-8'),
    ]
)
log = logging.getLogger("FUND")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📊 GOOGLE SHEETS — ПОДКЛЮЧЕНИЕ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

log.info("🔌 Подключаемся к Google Sheets...")
try:
    gc = gspread.service_account(filename=CREDENTIALS_FILE)
    master_sh = gc.open_by_key(MASTER_SHEET_ID)
    try:
        ws_users = master_sh.worksheet("👥 Пользователи")
    except gspread.exceptions.WorksheetNotFound:
        ws_users = master_sh.add_worksheet(title="👥 Пользователи", rows=1000, cols=5)
        ws_users.append_row(["user_id", "username", "Имя", "sheet_id", "Дата регистрации"])
    log.info("✅ Мастер-таблица готова!")
except Exception as e:
    log.critical(f"❌ SHEETS: {e}", exc_info=True)
    sys.exit(1)

user_cache = {}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 👤 МНОГОПОЛЬЗОВАТЕЛЬСКАЯ СИСТЕМА
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def find_user_sheet_id(user_id):
    try:
        rows = ws_users.get_all_values()
        for row in rows[1:]:
            if len(row) >= 4 and str(row[0]) == str(user_id):
                return row[3]
    except Exception as e:
        log.error(f"❌ find_user: {e}", exc_info=True)
    return None


def create_user_sheet(user_id, username, first_name):
    log.info(f"🆕 Создаём таблицу для {first_name} (@{username})...")
    title = f"FUNDAMENTA — {first_name} (@{username or user_id})"
    try:
        new_sh = gc.create(title)
    except Exception as e:
        if "quota" in str(e).lower() or "storage" in str(e).lower():
            log.error(f"❌ Google Drive переполнен! {e}")
            return None
        raise e
    sheet_id = new_sh.id
    new_sh.share('', perm_type='anyone', role='reader')

    ws = new_sh.sheet1
    ws.update_title("⚙️ Настройки")
    new_sh.add_worksheet("🏗 Фонд 1 Себестоимость", rows=100, cols=6)
    new_sh.add_worksheet("💻 Фонд 2 Операционные", rows=100, cols=6)
    new_sh.add_worksheet("☕ Фонд 3 Дополнительные", rows=100, cols=6)
    new_sh.add_worksheet("💰 Баланс", rows=20, cols=6)
    new_sh.add_worksheet("📜 История", rows=5000, cols=7)

    ws_hist = new_sh.worksheet("📜 История")
    ws_hist.append_row(["Дата", "Тип", "Сумма ₸", "Фонд", "Карман", "Комментарий", "Пользователь"])

    ws_users.append_row([
        str(user_id), username or "", first_name,
        sheet_id, datetime.now().strftime("%Y-%m-%d %H:%M")
    ])
    log.info(f"   ✅ Таблица создана: {sheet_id}")
    return sheet_id


def get_user_ws(user_id, username="", first_name=""):
    uid = str(user_id)
    if uid in user_cache:
        return user_cache[uid]
    sheet_id = find_user_sheet_id(user_id)
    if not sheet_id:
        sheet_id = create_user_sheet(user_id, username, first_name)
    if not sheet_id:
        log.error(f"❌ Не удалось создать таблицу для {user_id}")
        return None
    try:
        sh = gc.open_by_key(sheet_id)
        data = {
            'sheet_id': sheet_id, 'sh': sh,
            'config': sh.worksheet("⚙️ Настройки"),
            'fund1': sh.worksheet("🏗 Фонд 1 Себестоимость"),
            'fund2': sh.worksheet("💻 Фонд 2 Операционные"),
            'fund3': sh.worksheet("☕ Фонд 3 Дополнительные"),
            'balance': sh.worksheet("💰 Баланс"),
            'history': sh.worksheet("📜 История"),
        }
        user_cache[uid] = data
        return data
    except Exception as e:
        log.error(f"❌ get_user_ws: {e}", exc_info=True)
        return None


def get_fund_ws(uw, fn):
    return uw[f'fund{fn}']

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🤖 БОТ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

class Form(StatesGroup):
    brief_items = State()
    income_amount = State()
    expense_amount = State()
    expense_fund = State()
    expense_pocket = State()
    expense_comment = State()
    add_pocket_fund = State()
    add_pocket_items = State()

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🏷 КОНСТАНТЫ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

FUND_NAMES = {
    1: "🏗 Себестоимость",
    2: "💻 Операционные расходы",
    3: "☕️ Дополнительные расходы",
}

FUND_BRIEF_MSG = {
    1: (
        "📝 *ШАГ 1 из 3 — Себестоимость*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Напиши, что входит в *себестоимость* твоего "
        "продукта с указанием суммы в месяц.\n\n"
        "💡 *Себестоимость* — это то, из чего состоит "
        "твой продукт и без чего продукт "
        "*НЕ МОЖЕТ* существовать.\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "*Пример:* в школе балета в себестоимость входит:\n\n"
        "`Аренда помещения - 1200000`\n"
        "`Зарплата педагогов - 1400000`\n"
        "`Налоги педагогов - 400000`\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "✏️ Напиши аналогичным образом с указанием\n"
        "суммы ежемесячного платежа.\n\n"
        "Формат: `Название - сумма`\n"
        "Каждый расход — *с новой строки*.\n"
        "Можно *сразу все* одним сообщением!\n\n"
        "👆 Посмотри видео-подсказку выше!"
    ),
    2: (
        "📝 *ШАГ 2 из 3 — Операционные расходы*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Спасибо, круто! 👍\n\n"
        "Далее, аналогичным образом, напиши что входит "
        "в твою *операционную деятельность*.\n\n"
        "💡 *Операционная деятельность* — это то, без чего "
        "твоему продукту будет *ОЧЕНЬ ТЯЖЕЛО*.\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "*Пример:* в школе балета операционные расходы:\n\n"
        "`Расходы на таргет - 400000`\n"
        "`СММ, Таргетолог - 300000`\n"
        "`Администраторы - 300000`\n"
        "`CRM система - 50000`\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "⚠️ *ВАЖНО!* Обязательно добавь строку\n"
        "со своей зарплатой:\n\n"
        "`Моя зарплата (доход собственника) - СУММА`\n\n"
        "Это зарплата, которую ты *реально хочешь*\n"
        "получать как собственник бизнеса.\n"
        "Не мечта, а *текущий достижимый уровень*.\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "✏️ *РАСПИШИ ВСЕ ЗАТРАТЫ* не упустив ничего!\n"
        "Формат: `Название - сумма`\n"
        "Каждый — с новой строки.\n\n"
        "👆 Посмотри видео-подсказку!"
    ),
    3: (
        "📝 *ШАГ 3 из 3 — Дополнительные расходы*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Супер! Остался *последний шаг*! 🏁\n\n"
        "Таким же образом распиши, что входит "
        "в твой *фонд дополнительных расходов*.\n\n"
        "💡 *Дополнительные расходы* — это то, что "
        "делает твой бизнес *ЛУЧШЕ*.\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "*Пример:* в школе балета доп. расходы:\n\n"
        "`Стаканчики для воды - 6000`\n"
        "`Вода в кулере - 4500`\n"
        "`Охрана - 12000`\n"
        "`Хоз товары - 15000`\n"
        "`Представительские расходы - 10000`\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "✏️ Формат: `Название - сумма`\n"
        "Каждый — с новой строки.\n\n"
        "👆 Посмотри видео-подсказку!"
    ),
}

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🛠 ХЕЛПЕРЫ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def fmt(n):
    try: return '{:,}'.format(int(float(n))).replace(',', ' ')
    except: return str(n)

def bar(cur, tot, l=10):
    if tot <= 0: return "░" * l + " 0%"
    r = min(max(cur / tot, 0), 1.0)
    f = int(r * l)
    return "█" * f + "░" * (l - f) + f" {int(r*100)}%"

def emo(cur, tot):
    if tot <= 0: return "⬜"
    p = cur / tot
    if p >= 1.0: return "✅"
    if p >= 0.5: return "🟡"
    if p >= 0.2: return "🟠"
    return "🔴"

def sf(v):
    try: return float(str(v).replace(',','.').replace(' ','').replace('\xa0','').replace('%',''))
    except: return 0.0

def si(v): return int(sf(v))

def parse_items(text):
    items = []
    for line in text.strip().split('\n'):
        line = line.strip()
        if not line: continue
        line = re.sub(r'^[\d]+[\.\)\-\s]+', '', line).strip()
        line = re.sub(r'^[-–—•]\s*', '', line).strip()
        if not line: continue
        parts = None
        for sep in [' - ', ' — ', ' – ', ': ', ' -', '- ', '— ']:
            if sep in line:
                idx = line.rfind(sep)
                parts = (line[:idx].strip(), line[idx+len(sep):].strip())
                break
        if not parts:
            m = re.match(r'^(.+?)\s+([\d\s\xa0]+)$', line)
            if m: parts = (m.group(1).strip(), m.group(2).strip())
        if parts:
            name = parts[0]
            amt = re.sub(r'[^\d]', '', parts[1])
            if name and amt and amt.isdigit() and int(amt) > 0:
                items.append({'name': name, 'amount': int(amt)})
                log.info(f"   📝 «{name}» = {amt}")
            else:
                log.warning(f"   ⚠️ «{line}»")
        else:
            log.warning(f"   ⚠️ «{line}»")
    return items

async def thinking(cid, text="⏳ Считаю..."):
    try:
        await bot.send_chat_action(cid, types.ChatActions.TYPING)
        return await bot.send_message(cid, text)
    except: return None

async def del_msg(m):
    try:
        if m: await m.delete()
    except: pass

def parse_fund(text):
    if "Себестоимость" in text: return 1
    if "Операционн" in text: return 2
    if "Дополнительн" in text or "Доп" in text: return 3
    return 0

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📊 SHEETS — ОПЕРАЦИИ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def get_pockets(uw, fn):
    ws = get_fund_ws(uw, fn)
    try: rows = ws.get_all_values()
    except Exception as e:
        log.error(f"❌ get_pockets({fn}): {e}"); return []
    pockets = []
    for i, row in enumerate(rows):
        if i == 0: continue
        if len(row) >= 5 and row[1] and not row[1].startswith("📊") and not row[1].startswith("═"):
            pockets.append({
                'row': i+1, 'name': row[1],
                'planned': sf(row[2]), 'pct': sf(row[3]),
                'balance': sf(row[4]),
            })
    return pockets


def get_balance(uw):
    try:
        rows = uw['balance'].get_all_values()
        f1=f2=f3=0
        for row in rows:
            if len(row)>=2:
                if "Себестоимость" in row[0]: f1=si(row[1])
                elif "Операционн" in row[0]: f2=si(row[1])
                elif "Дополнительн" in row[0]: f3=si(row[1])
        return [f1,f2,f3,f1+f2+f3]
    except Exception as e:
        log.error(f"❌ get_balance: {e}"); return [0,0,0,0]


def get_config(uw):
    try:
        rows = uw['config'].get_all_values()
        cfg = {}
        for row in rows:
            if len(row)<2: continue
            k=row[0].strip().lower(); v=sf(row[1])
            if "безубыточности" in k: cfg['tb']=v
            elif "сумма фонд 1" in k: cfg['sum1']=v
            elif "сумма фонд 2" in k: cfg['sum2']=v
            elif "сумма фонд 3" in k: cfg['sum3']=v
            elif "маржа" in k: cfg['margin']=v
            elif "остаток" in k and "дополнит" not in k: cfg['remainder']=v
            elif "себестоимость" in k and "%" in row[0]: cfg['pf1']=v
            elif "операционн" in k and "%" in row[0]: cfg['pf2']=v
            elif "дополнит" in k and "%" in row[0]: cfg['pf3']=v
        if 'tb' not in cfg or cfg['tb']==0: return None
        s1=cfg.get('sum1',0); s2=cfg.get('sum2',0)
        if 'margin' not in cfg: cfg['margin']=cfg['tb']-s1
        if 'remainder' not in cfg: cfg['remainder']=cfg['margin']-s2
        return cfg
    except Exception as e:
        log.error(f"❌ get_config: {e}"); return None


def write_balance(uw, bal, cfg):
    try:
        tb=cfg.get('tb',0); s1=cfg.get('sum1',0); s2=cfg.get('sum2',0); s3=cfg.get('sum3',0)
        total=bal[3]; runway=round(total/tb,1) if tb>0 else 0; gap=max(0,tb-total)
        data = [
            ["═══ FUNDAMENTA — БАЛАНС ═══","","","",""],
            ["","","","",""],
            ["Фонд","В фонде ₸","План ₸/мес","Заполнено","Статус"],
            ["🏗 Себестоимость",bal[0],int(s1),f"{int(bal[0]/s1*100)}%" if s1>0 else "0%",emo(bal[0],s1)],
            ["💻 Операционные",bal[1],int(s2),f"{int(bal[1]/s2*100)}%" if s2>0 else "0%",emo(bal[1],s2)],
            ["☕ Дополнительные",bal[2],int(s3),f"{int(bal[2]/s3*100)}%" if s3>0 else "0%",emo(bal[2],s3)],
            ["","","","",""],
            ["💰 ИТОГО",total,int(tb),"",""],
            ["","","","",""],
            ["═══ ПОКАЗАТЕЛИ ═══","","","",""],
            ["🎯 Точка безубыточности",int(tb),"₸/мес","",""],
            ["📉 Не хватает до ТБ",int(gap),"₸","",""],
            ["⏳ Запас хода",runway,"мес.","",""],
        ]
        uw['balance'].clear()
        uw['balance'].update(values=data, range_name='A1:E13')
    except Exception as e:
        log.error(f"❌ write_balance: {e}")


def save_brief(uw, f1, f2, f3):
    s1=sum(i['amount'] for i in f1); s2=sum(i['amount'] for i in f2); s3=sum(i['amount'] for i in f3)
    tb=s1+s2+s3
    if tb==0: return None
    margin=tb-s1; remainder=margin-s2
    pf1=round(s1/tb*100,1); pf2=round(s2/margin*100,1) if margin>0 else 0; pf3=round(s3/remainder*100,1) if remainder>0 else 0

    cfg_data=[
        ["═══ FUNDAMENTA — НАСТРОЙКИ ═══",""],["",""],
        ["🎯 Точка безубыточности",tb],["",""],
        ["🏗 Сумма Фонд 1",s1],["   % Себестоимость от ТБ",f"{pf1}%"],["",""],
        ["💻 Сумма Фонд 2",s2],["   Маржа",margin],["   % Операционные от Маржи",f"{pf2}%"],["",""],
        ["☕ Сумма Фонд 3",s3],["   Остаток",remainder],["   % Дополнительные от Остатка",f"{pf3}%"],["",""],
        ["Дата",datetime.now().strftime("%Y-%m-%d %H:%M")],
    ]
    uw['config'].clear()
    uw['config'].update(values=cfg_data, range_name='A1:B16')

    bases={1:('ТБ',tb),2:('маржи',margin),3:('остатка',remainder)}
    labels={1:'Себестоимость',2:'Операционные',3:'Дополнительные'}
    funds={1:f1,2:f2,3:f3}
    for fn in [1,2,3]:
        ws=get_fund_ws(uw,fn); items=funds[fn]; bl,bv=bases[fn]; ws.clear()
        data=[["№","Карман (статья расхода)","План ₸/мес",f"% от {bl}","Баланс ₸","Статус"]]
        for i,it in enumerate(items,1):
            pct=round(it['amount']/bv*100,1) if bv>0 else 0
            data.append([i,it['name'],it['amount'],f"{pct}%",0,"⬜"])
        data.append(["","","","","",""])
        data.append(["",f"📊 ИТОГО {labels[fn]}",sum(i['amount'] for i in items),"—",0,""])
        ws.update(values=data, range_name=f'A1:F{len(data)}')

    cfg={'tb':tb,'sum1':s1,'sum2':s2,'sum3':s3,'margin':margin,'remainder':remainder,'pf1':pf1,'pf2':pf2,'pf3':pf3}
    write_balance(uw,[0,0,0,0],cfg)
    log.info(f"✅ Бриф: ТБ={tb}")
    return cfg


def add_pockets_to_fund(uw, fund_num, new_items):
    all_f={}
    for fn in [1,2,3]:
        pockets=get_pockets(uw,fn)
        all_f[fn]=[{'name':p['name'],'amount':int(p['planned']),'balance':int(p['balance'])} for p in pockets]
    for it in new_items:
        all_f[fund_num].append({'name':it['name'],'amount':it['amount'],'balance':0})

    s1=sum(i['amount'] for i in all_f[1]); s2=sum(i['amount'] for i in all_f[2]); s3=sum(i['amount'] for i in all_f[3])
    tb=s1+s2+s3
    if tb==0: return None
    margin=tb-s1; remainder=margin-s2
    pf1=round(s1/tb*100,1); pf2=round(s2/margin*100,1) if margin>0 else 0; pf3=round(s3/remainder*100,1) if remainder>0 else 0

    cfg_data=[
        ["═══ FUNDAMENTA — НАСТРОЙКИ ═══",""],["",""],
        ["🎯 Точка безубыточности",tb],["",""],
        ["🏗 Сумма Фонд 1",s1],["   % Себестоимость от ТБ",f"{pf1}%"],["",""],
        ["💻 Сумма Фонд 2",s2],["   Маржа",margin],["   % Операционные от Маржи",f"{pf2}%"],["",""],
        ["☕ Сумма Фонд 3",s3],["   Остаток",remainder],["   % Дополнительные от Остатка",f"{pf3}%"],["",""],
        ["Дата",datetime.now().strftime("%Y-%m-%d %H:%M")],
    ]
    uw['config'].clear()
    uw['config'].update(values=cfg_data, range_name='A1:B16')

    bases={1:('ТБ',tb),2:('маржи',margin),3:('остатка',remainder)}; labels={1:'Себестоимость',2:'Операционные',3:'Дополнительные'}
    for fn in [1,2,3]:
        ws=get_fund_ws(uw,fn); items=all_f[fn]; bl,bv=bases[fn]; ws.clear()
        data=[["№","Карман","План ₸/мес",f"% от {bl}","Баланс ₸","Статус"]]
        for i,it in enumerate(items,1):
            pct=round(it['amount']/bv*100,1) if bv>0 else 0; b=it.get('balance',0)
            data.append([i,it['name'],it['amount'],f"{pct}%",b,emo(b,it['amount'])])
        tp=sum(i['amount'] for i in items); tb2=sum(i.get('balance',0) for i in items)
        data.append(["","","","","",""]); data.append(["",f"📊 ИТОГО {labels[fn]}",tp,"—",tb2,""])
        ws.update(values=data, range_name=f'A1:F{len(data)}')

    bal=get_balance(uw)
    cfg={'tb':tb,'sum1':s1,'sum2':s2,'sum3':s3,'margin':margin,'remainder':remainder,'pf1':pf1,'pf2':pf2,'pf3':pf3}
    write_balance(uw,bal,cfg)
    return cfg

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⌨️ КЛАВИАТУРЫ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def kb_main():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("💰 Внести доход","💸 Списать расход")
    kb.add("📊 Баланс","📋 Подробно по фондам")
    kb.add("⚙️ Настройки","🔗 Таблица")
    return kb

def kb_cancel():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True); kb.add("🔙 Отмена"); return kb

def kb_brief_act():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("➕ Добавить ещё","✅ Готово, следующий шаг"); kb.add("🔙 Отмена"); return kb

def kb_funds():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add("🏗 Себестоимость","💻 Операционные расходы","☕️ Дополнительные расходы","🔙 Отмена"); return kb

def kb_pockets(pockets):
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    for p in pockets: kb.add(f"{p['name']} [{fmt(p['balance'])} ₸]")
    kb.add("🔙 Назад"); return kb

def kb_settings():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add("➕ Добавить карман в фонд","🔄 Заполнить заново","📋 Текущие настройки","🔙 Главное меню"); return kb

def kb_save():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add("➕ Добавить ещё","✅ Сохранить"); kb.add("🔙 Отмена"); return kb

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🚀 /start
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dp.message_handler(commands=['start'], state="*")
async def cmd_start(msg: types.Message, state: FSMContext):
    log.info(f"👤 /start @{msg.from_user.username} id={msg.from_user.id}")
    await state.finish()

    st = await thinking(msg.chat.id, "⏳ Загружаю твои данные...")
    uw = get_user_ws(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name)
    await del_msg(st)

    if not uw:
        return await msg.answer(
            "❌ *Ошибка создания таблицы!*\n\n"
            "Скорее всего переполнен Google Drive.\n"
            "Напиши администратору для решения.",
            parse_mode="Markdown"
        )

    cfg = get_config(uw)

    if cfg and cfg['tb'] > 0:
        await msg.answer(
            "💎 *FUNDAMENTA*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"С возвращением, *{msg.from_user.first_name}*! ✨\n\n"
            f"🎯 Точка безубыточности: *{fmt(cfg['tb'])} ₸/мес*\n\n"
            "Система настроена и работает.\n"
            "Выбери действие 👇",
            parse_mode="Markdown", reply_markup=kb_main()
        )
    else:
        try: await bot.send_video_note(msg.chat.id, VIDEO_1_INTRO)
        except: pass

        await msg.answer(
            "💎 *FUNDAMENTA*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"Привет, *{msg.from_user.first_name}*! 👋\n\n"
            "Это Fundamenta — помощник, который поможет\n"
            "тебе наладить порядок в твоём бизнесе.\n\n"
            "Следуй инструкциям и обязательно\n"
            "смотри видео-подсказки! 🎬\n\n"
            "Мы пройдём *3 простых шага*:\n\n"
            "1️⃣ Запишем расходы на *себестоимость*\n"
            "    _(без чего продукт не может существовать)_\n"
            "2️⃣ Запишем *операционные* расходы\n"
            "    _(+ твоя зарплата как собственника)_\n"
            "3️⃣ Запишем *дополнительные* расходы\n"
            "    _(что делает бизнес лучше)_\n\n"
            "После этого система рассчитает\n"
            "точку безубыточности и начнёт\n"
            "автоматически распределять доходы! 🚀\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Готов? Начинаем!",
            parse_mode="Markdown"
        )
        await start_brief(msg, state, 1)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📝 БРИФ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def start_brief(msg, state, fn):
    log.info(f"📝 Бриф: Фонд {fn}")
    async with state.proxy() as d:
        d['bf'] = fn
        if fn == 1: d['f1']=[]; d['f2']=[]; d['f3']=[]
    vid = FUND_VIDEOS.get(fn)
    if vid:
        try: await bot.send_video_note(msg.chat.id, vid)
        except: pass
    await msg.answer(FUND_BRIEF_MSG[fn], parse_mode="Markdown", reply_markup=kb_cancel())
    await Form.brief_items.set()


@dp.message_handler(state=Form.brief_items)
async def brief_handler(msg: types.Message, state: FSMContext):
    if msg.text == "🔙 Отмена":
        await state.finish()
        return await msg.answer(
            "❌ Бриф отменён.\n\n"
            "Чтобы начать заново — нажми /start",
            reply_markup=types.ReplyKeyboardRemove()
        )
    if msg.text == "✅ Готово, следующий шаг":
        return await brief_done(msg, state)
    if msg.text == "➕ Добавить ещё":
        return await msg.answer(
            "✏️ Напиши ещё расходы.\n\n"
            "Формат: `Название - сумма`\n"
            "Каждый — с новой строки.\n"
            "Можно сразу несколько!",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )

    new = parse_items(msg.text)
    if not new:
        return await msg.answer(
            "⚠️ Не удалось распознать расходы.\n\n"
            "Пожалуйста, используй формат:\n"
            "`Название - сумма`\n\n"
            "Каждый расход — с новой строки.\n\n"
            "*Пример:*\n"
            "`Аренда помещения - 1200000`\n"
            "`Зарплата педагогов - 1400000`\n"
            "`Налоги - 400000`",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )

    async with state.proxy() as d:
        fn=d['bf']; key=f'f{fn}'
        lst=d.get(key,[]); lst.extend(new); d[key]=lst

    txt = ""
    for i,it in enumerate(lst,1):
        txt += f"  {i}. {it['name']} — {fmt(it['amount'])} ₸\n"
    total = sum(it['amount'] for it in lst)
    n = len(new)
    w = "карман" if n==1 else ("кармана" if n<5 else "карманов")

    await msg.answer(
        f"✅ Добавлено: {n} {w}!\n\n"
        f"📂 *{FUND_NAMES[fn]}:*\n\n{txt}\n"
        f"💰 *Итого по фонду: {fmt(total)} ₸/мес*\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Что дальше?\n\n"
        "➕ *Добавить ещё* — если есть ещё расходы\n"
        "✅ *Готово, следующий шаг* — переходим дальше",
        parse_mode="Markdown", reply_markup=kb_brief_act()
    )


async def brief_done(msg, state):
    async with state.proxy() as d:
        fn=d['bf']; items=d.get(f'f{fn}',[])
    if not items:
        return await msg.answer(
            "⚠️ Ты ещё ничего не добавил!\n\n"
            "Напиши хотя бы одну статью расхода.\n"
            "Формат: `Название - сумма`",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )
    total=sum(i['amount'] for i in items)
    if fn < 3:
        await msg.answer(
            f"👍 *{FUND_NAMES[fn]}* — заполнен!\n"
            f"Итого: *{fmt(total)} ₸/мес*\n\n"
            "Переходим к следующему шагу... ⏩",
            parse_mode="Markdown"
        )
        await start_brief(msg, state, fn+1)
    else:
        await finish_brief(msg, state)


async def finish_brief(msg, state):
    log.info("🏁 Завершаем бриф...")
    async with state.proxy() as d:
        f1=d.get('f1',[]); f2=d.get('f2',[]); f3=d.get('f3',[])

    st = await thinking(msg.chat.id, "⏳ Рассчитываю точку безубыточности\nи сохраняю настройки...")
    uw = get_user_ws(msg.from_user.id, msg.from_user.username or "", msg.from_user.first_name)
    cfg = save_brief(uw, f1, f2, f3)
    await del_msg(st)

    if not cfg:
        await state.finish()
        return await msg.answer("❌ Ошибка: сумма = 0.\nНачни заново: /start")

    tb=cfg['tb']; m=cfg['margin']; r=cfg['remainder']
    def pb(items, base):
        return "".join(
            f"    • {i['name']} — {fmt(i['amount'])} ₸ "
            f"({round(i['amount']/base*100,1) if base>0 else 0}%)\n"
            for i in items
        )

    text = (
        "━━━━━━━━━━━━━━━━━━\n"
        "🎉 *ВСЁ ГОТОВО!*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 *Точка безубыточности:*\n"
        f"    *{fmt(tb)} ₸/мес*\n\n"
        "Это минимум, который нужно зарабатывать,\n"
        "чтобы бизнес не уходил в минус.\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "*Как будет распределяться каждое поступление:*\n\n"
        f"🏗 *Себестоимость — {cfg['pf1']}% от ТБ*\n"
        f"    (= {fmt(cfg['sum1'])} ₸/мес)\n"
        f"{pb(f1, tb)}\n"
        f"💻 *Операционные — {cfg['pf2']}% от Маржи*\n"
        f"    (= {fmt(cfg['sum2'])} ₸/мес, маржа = {fmt(m)} ₸)\n"
        f"{pb(f2, m)}\n"
        f"☕️ *Дополнительные — {cfg['pf3']}% от Остатка*\n"
        f"    (= {fmt(cfg['sum3'])} ₸/мес, остаток = {fmt(r)} ₸)\n"
        f"{pb(f3, r)}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Теперь каждый доход автоматически\n"
        "распределяется по фондам и карманам! 🚀\n\n"
        "💡 *Не забывай каждый день вносить суммы*\n"
        "*своих продаж* — любые денежные средства,\n"
        "которые приходят на счёт твоего бизнеса!\n\n"
        "🎬 *Посмотри полноценный урок по финансам:*"
    )
    ilk = types.InlineKeyboardMarkup()
    ilk.add(types.InlineKeyboardButton("🎬 Смотреть урок по финансам", url=YOUTUBE_LESSON_URL))
    await state.finish()
    await msg.answer(text, parse_mode="Markdown", reply_markup=ilk)
    await msg.answer("Выбери действие 👇", reply_markup=kb_main())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 💰 ДОХОД
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dp.message_handler(lambda m: m.text == "💰 Внести доход")
async def income_start(msg: types.Message):
    uw=get_user_ws(msg.from_user.id); cfg=get_config(uw) if uw else None
    if not cfg:
        return await msg.answer("⚠️ Сначала заполни бриф: /start", reply_markup=kb_main())
    await msg.answer(
        "💰 *НОВЫЙ ДОХОД*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Введи сумму, которая пришла\n"
        "на счёт твоего бизнеса.\n\n"
        "Это любые денежные средства:\n"
        "оплата клиента, перевод, наличные.\n\n"
        "Только цифры, например: `500000`",
        parse_mode="Markdown", reply_markup=kb_cancel()
    )
    await Form.income_amount.set()


@dp.message_handler(state=Form.income_amount)
async def income_process(msg: types.Message, state: FSMContext):
    if msg.text == "🔙 Отмена":
        await state.finish()
        return await msg.answer("❌ Действие отменено.", reply_markup=kb_main())

    clean=re.sub(r'[^\d]','',msg.text)
    if not clean or int(clean)<=0:
        return await msg.answer(
            "⚠️ Введи только цифры!\n"
            "Например: `500000`",
            parse_mode="Markdown"
        )

    amount=int(clean)
    st=await thinking(msg.chat.id, "⏳ Распределяю по фондам и карманам...")
    uw=get_user_ws(msg.from_user.id); cfg=get_config(uw) if uw else None
    if not cfg:
        await del_msg(st); await state.finish()
        return await msg.answer("❌ Ошибка чтения настроек.\nПопробуй /start", reply_markup=kb_main())

    tb=cfg['tb']; s1=cfg.get('sum1',0); s2=cfg.get('sum2',0); s3=cfg.get('sum3',0)
    margin=cfg.get('margin',tb-s1)

    add1=int(amount*s1/tb) if tb>0 else 0
    rest1=amount-add1
    add2=int(rest1*s2/margin) if margin>0 else 0
    add3=amount-add1-add2

    bal=get_balance(uw)
    bal[0]+=add1; bal[1]+=add2; bal[2]+=add3; bal[3]=bal[0]+bal[1]+bal[2]

    for fn,add_a,fs in [(1,add1,s1),(2,add2,s2),(3,add3,s3)]:
        if add_a<=0: continue
        pockets=get_pockets(uw,fn)
        if not pockets: continue
        dist=0
        for i,p in enumerate(pockets):
            sh=p['planned']/fs if fs>0 else 1.0/len(pockets)
            pa=add_a-dist if i==len(pockets)-1 else int(add_a*sh)
            dist+=pa; nb=int(p['balance'])+pa
            ws=get_fund_ws(uw,fn); ws.update_cell(p['row'],5,nb); ws.update_cell(p['row'],6,emo(nb,p['planned']))

    write_balance(uw,bal,cfg)
    uw['history'].append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M"),"ДОХОД",amount,
        "ВСЕ ФОНДЫ","Автораспределение","",msg.from_user.username or str(msg.from_user.id)
    ])
    await del_msg(st)

    gap=max(0,tb-bal[3])
    text = (
        "✅ *ДОХОД ПОЛУЧЕН И РАСПРЕДЕЛЁН!*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💵 *Поступление:* +{fmt(amount)} ₸\n\n"
        "*Распределено по фондам:*\n\n"
        f"🏗 Себестоимость: +{fmt(add1)} ₸\n"
        f"💻 Операционные: +{fmt(add2)} ₸\n"
        f"☕️ Дополнительные: +{fmt(add3)} ₸\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "*Остаток по фондам:*\n\n"
        f"🏗 Себестоимость: *{fmt(bal[0])} ₸*\n"
        f"💻 Операционные: *{fmt(bal[1])} ₸*\n"
        f"☕️ Дополнительные: *{fmt(bal[2])} ₸*\n\n"
        f"💰 *Всего в кассе: {fmt(bal[3])} ₸*\n"
    )
    if gap>0:
        text += f"\n📉 *До точки безубыточности не хватает:* {fmt(gap)} ₸"
    await state.finish()
    await msg.answer(text, parse_mode="Markdown", reply_markup=kb_main())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 💸 РАСХОД
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dp.message_handler(lambda m: m.text == "💸 Списать расход")
async def expense_start(msg: types.Message):
    uw=get_user_ws(msg.from_user.id); cfg=get_config(uw) if uw else None
    if not cfg:
        return await msg.answer("⚠️ Сначала заполни бриф: /start", reply_markup=kb_main())
    await msg.answer(
        "💸 *РАСХОДНАЯ ОПЕРАЦИЯ*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Укажите сумму расхода.\n\n"
        "Только цифры, например: `120000`",
        parse_mode="Markdown", reply_markup=kb_cancel()
    )
    await Form.expense_amount.set()


@dp.message_handler(state=Form.expense_amount)
async def expense_amt(msg: types.Message, state: FSMContext):
    if msg.text == "🔙 Отмена":
        await state.finish()
        return await msg.answer("❌ Действие отменено.", reply_markup=kb_main())
    clean=re.sub(r'[^\d]','',msg.text)
    if not clean or int(clean)<=0:
        return await msg.answer("⚠️ Введи только цифры!\nНапример: `120000`", parse_mode="Markdown")

    async with state.proxy() as d: d['exp_amt']=int(clean)
    uw=get_user_ws(msg.from_user.id); bal=get_balance(uw)

    await msg.answer(
        f"💸 *Сумма расхода:* {fmt(int(clean))} ₸\n\n"
        "*Остатки в фондах:*\n\n"
        f"🏗 Себестоимость: {fmt(bal[0])} ₸\n"
        f"💻 Операционные: {fmt(bal[1])} ₸\n"
        f"☕️ Дополнительные: {fmt(bal[2])} ₸\n\n"
        "Из какого фонда списываем? 👇",
        parse_mode="Markdown", reply_markup=kb_funds()
    )
    await Form.expense_fund.set()


@dp.message_handler(state=Form.expense_fund)
async def expense_fund_h(msg: types.Message, state: FSMContext):
    if msg.text == "🔙 Отмена":
        await state.finish()
        return await msg.answer("❌ Действие отменено.", reply_markup=kb_main())
    fn=parse_fund(msg.text)
    if not fn:
        return await msg.answer("⚠️ Выбери фонд из кнопок ниже 👇", reply_markup=kb_funds())

    await bot.send_chat_action(msg.chat.id, types.ChatActions.TYPING)
    uw=get_user_ws(msg.from_user.id); pockets=get_pockets(uw,fn)
    if not pockets:
        await state.finish()
        return await msg.answer(
            "⚠️ В этом фонде ещё нет карманов.\n"
            "Заполни бриф: /start",
            reply_markup=kb_main()
        )
    async with state.proxy() as d: d['exp_fn']=fn

    await msg.answer(
        f"📂 *{FUND_NAMES[fn]}*\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        "Выберите из какого кармана Вы хотите\n"
        "провести расходную операцию?\n\n"
        "В скобках — текущий остаток в кармане.\n\n"
        "👇 Нажмите на нужный карман:",
        parse_mode="Markdown", reply_markup=kb_pockets(pockets)
    )
    await Form.expense_pocket.set()


@dp.message_handler(state=Form.expense_pocket)
async def expense_pocket_h(msg: types.Message, state: FSMContext):
    if msg.text == "🔙 Назад":
        uw=get_user_ws(msg.from_user.id); bal=get_balance(uw)
        await msg.answer(
            "*Остатки в фондах:*\n\n"
            f"🏗 Себестоимость: {fmt(bal[0])} ₸\n"
            f"💻 Операционные: {fmt(bal[1])} ₸\n"
            f"☕️ Дополнительные: {fmt(bal[2])} ₸\n\n"
            "Из какого фонда списываем? 👇",
            parse_mode="Markdown", reply_markup=kb_funds()
        )
        await Form.expense_fund.set()
        return
    if msg.text == "🔙 Отмена":
        await state.finish()
        return await msg.answer("❌ Действие отменено.", reply_markup=kb_main())

    async with state.proxy() as d: fn=d['exp_fn']; amt=d['exp_amt']
    uw=get_user_ws(msg.from_user.id); pockets=get_pockets(uw,fn)
    sel=None
    for p in pockets:
        if msg.text.startswith(p['name']): sel=p; break
    if not sel:
        return await msg.answer(
            "⚠️ Выбери карман из кнопок ниже 👇",
            reply_markup=kb_pockets(pockets)
        )

    pb=int(sel['balance'])
    if amt > pb:
        nm = msg.from_user.first_name
        await state.finish()
        return await msg.answer(
            f"⛔️ *{nm}*, в данном кармане не хватает\n"
            f"денежных средств для Вашей расходной\n"
            f"операции.\n\n"
            f"*Карман:* {sel['name']}\n"
            f"*В кармане:* {fmt(pb)} ₸\n"
            f"*Нужно:* {fmt(amt)} ₸\n"
            f"*Не хватает:* {fmt(amt - pb)} ₸\n\n"
            "Пожалуйста, дождитесь пополнения кармана\n"
            "и после совершите расходную операцию,\n"
            "иначе есть риск попасть в *кассовый разрыв*.\n\n"
            "Будьте аккуратны! ⚠️",
            parse_mode="Markdown", reply_markup=kb_main()
        )
    async with state.proxy() as d: d['exp_pocket']=sel
    await msg.answer(
        "📝 Напиши коротко — *на что тратим?*\n\n"
        "Например: `Оплата аренды за март`\n"
        "или `Зарплата администратору`",
        parse_mode="Markdown", reply_markup=kb_cancel()
    )
    await Form.expense_comment.set()


@dp.message_handler(state=Form.expense_comment)
async def expense_final(msg: types.Message, state: FSMContext):
    if msg.text == "🔙 Отмена":
        await state.finish()
        return await msg.answer("❌ Действие отменено.", reply_markup=kb_main())

    comment=msg.text
    async with state.proxy() as d:
        pocket=d['exp_pocket']; fn=d['exp_fn']; amt=d['exp_amt']

    st=await thinking(msg.chat.id, "⏳ Списываю расход...")
    uw=get_user_ws(msg.from_user.id)
    nb=int(pocket['balance'])-amt
    ws=get_fund_ws(uw,fn); ws.update_cell(pocket['row'],5,nb); ws.update_cell(pocket['row'],6,emo(nb,pocket['planned']))
    bal=get_balance(uw); bal[fn-1]-=amt; bal[3]=bal[0]+bal[1]+bal[2]
    cfg=get_config(uw)
    if cfg: write_balance(uw,bal,cfg)
    uw['history'].append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M"),"РАСХОД",-amt,
        FUND_NAMES[fn],pocket['name'],comment,msg.from_user.username or str(msg.from_user.id)
    ])
    await del_msg(st)

    await state.finish()
    await msg.answer(
        "✅ *РАСХОД СПИСАН!*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💸 *Сумма:* -{fmt(amt)} ₸\n"
        f"📂 *Фонд:* {FUND_NAMES[fn]}\n"
        f"👛 *Карман:* {pocket['name']}\n"
        f"💬 *Цель:* {comment}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "*Остатки в фондах:*\n\n"
        f"🏗 Себестоимость: *{fmt(bal[0])} ₸*\n"
        f"💻 Операционные: *{fmt(bal[1])} ₸*\n"
        f"☕️ Дополнительные: *{fmt(bal[2])} ₸*\n\n"
        f"💰 *Всего в кассе: {fmt(bal[3])} ₸*",
        parse_mode="Markdown", reply_markup=kb_main()
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📊 БАЛАНС
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dp.message_handler(lambda m: m.text == "📊 Баланс")
async def show_balance_h(msg: types.Message):
    await bot.send_chat_action(msg.chat.id, types.ChatActions.TYPING)
    uw=get_user_ws(msg.from_user.id); cfg=get_config(uw) if uw else None
    if not cfg:
        return await msg.answer("⚠️ Сначала заполни бриф: /start", reply_markup=kb_main())

    bal=get_balance(uw); tb=cfg['tb']; total=bal[3]
    t1=int(cfg.get('sum1',0)); t2=int(cfg.get('sum2',0)); t3=int(cfg.get('sum3',0))
    runway=round(total/tb,1) if tb>0 else 0; gap=max(0,tb-total)
    h="🟢" if runway>=3 else "🟡" if runway>=1 else "🔴"

    text = (
        "📊 *БАЛАНС ФОНДОВ*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🏗 *Себестоимость*\n"
        f"   {fmt(bal[0])} ₸ из {fmt(t1)} ₸\n"
        f"   {bar(bal[0],t1)}\n\n"
        f"💻 *Операционные расходы*\n"
        f"   {fmt(bal[1])} ₸ из {fmt(t2)} ₸\n"
        f"   {bar(bal[1],t2)}\n\n"
        f"☕️ *Дополнительные расходы*\n"
        f"   {fmt(bal[2])} ₸ из {fmt(t3)} ₸\n"
        f"   {bar(bal[2],t3)}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"💰 *ВСЕГО В КАССЕ:* {fmt(total)} ₸\n\n"
        f"🎯 *Точка безубыточности:* {fmt(tb)} ₸/мес\n"
    )
    if gap > 0:
        text += f"📉 *Не хватает до ТБ:* {fmt(gap)} ₸\n"
    text += (
        f"\n{h} *Запас хода:* {runway} мес.\n"
        f"   _(сколько проживёт бизнес\n"
        f"   без новых поступлений)_\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "💡 Нажми «📋 Подробно по фондам»\n"
        "чтобы увидеть все карманы."
    )
    await msg.answer(text, parse_mode="Markdown", reply_markup=kb_main())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 📋 ПОДРОБНО ПО ФОНДАМ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dp.message_handler(lambda m: m.text == "📋 Подробно по фондам")
async def show_detail(msg: types.Message):
    await bot.send_chat_action(msg.chat.id, types.ChatActions.TYPING)
    uw=get_user_ws(msg.from_user.id); cfg=get_config(uw) if uw else None
    if not cfg:
        return await msg.answer("⚠️ Сначала заполни бриф: /start", reply_markup=kb_main())
    bal=get_balance(uw); tb=cfg['tb']

    for fn in [1,2,3]:
        fsum=int(cfg.get(f'sum{fn}',0)); fbal=bal[fn-1]; gap=max(0,fsum-fbal)
        pockets=get_pockets(uw,fn)
        text = (
            f"{FUND_NAMES[fn]}\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 *В фонде:* {fmt(fbal)} ₸\n"
            f"📋 *План на месяц:* {fmt(fsum)} ₸\n"
        )
        if gap > 0:
            text += f"📉 *Не хватает:* {fmt(gap)} ₸\n"
        text += f"   {bar(fbal, fsum)}\n\n"

        if pockets:
            text += "*Карманы (статьи расходов):*\n\n"
            for p in pockets:
                pb=int(p['balance']); pp=int(p['planned']); pg=max(0,pp-pb)
                st = emo(pb,pp)
                text += f"  {st} *{p['name']}*\n"
                text += f"     {fmt(pb)} ₸ из {fmt(pp)} ₸"
                if pg > 0:
                    text += f" _(не хватает {fmt(pg)} ₸)_"
                text += f"\n     {bar(pb, pp)}\n\n"
        else:
            text += "  Нет карманов\n\n"

        await msg.answer(text, parse_mode="Markdown", reply_markup=kb_main())

    total=bal[3]; gap=max(0,tb-total)
    text = (
        "━━━━━━━━━━━━━━━━━━\n"
        f"💰 *ИТОГО ВО ВСЕХ ФОНДАХ:* {fmt(total)} ₸\n"
        f"🎯 *Точка безубыточности:* {fmt(tb)} ₸/мес\n"
    )
    if gap > 0:
        text += f"\n📉 *До безубыточности не хватает:* {fmt(gap)} ₸"
    await msg.answer(text, parse_mode="Markdown", reply_markup=kb_main())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ⚙️ НАСТРОЙКИ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dp.message_handler(lambda m: m.text == "⚙️ Настройки")
async def settings(msg: types.Message):
    await msg.answer(
        "⚙️ *НАСТРОЙКИ*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Выбери действие 👇",
        parse_mode="Markdown", reply_markup=kb_settings()
    )

@dp.message_handler(lambda m: m.text == "📋 Текущие настройки")
async def show_cfg(msg: types.Message):
    await bot.send_chat_action(msg.chat.id, types.ChatActions.TYPING)
    uw=get_user_ws(msg.from_user.id); cfg=get_config(uw) if uw else None
    if not cfg:
        return await msg.answer("⚠️ Настройки не найдены.\nЗаполни бриф: /start", reply_markup=kb_settings())

    m=cfg.get('margin',cfg['tb']-cfg.get('sum1',0))
    r=cfg.get('remainder',m-cfg.get('sum2',0))

    text = (
        "📋 *ТЕКУЩИЕ НАСТРОЙКИ*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 *Точка безубыточности:*\n"
        f"   {fmt(cfg['tb'])} ₸/мес\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "*Распределение доходов:*\n\n"
        f"🏗 *Себестоимость:* {cfg.get('pf1',0)}% от ТБ\n"
        f"   План: {fmt(cfg.get('sum1',0))} ₸/мес\n\n"
        f"💻 *Операционные:* {cfg.get('pf2',0)}% от маржи\n"
        f"   План: {fmt(cfg.get('sum2',0))} ₸/мес\n"
        f"   Маржа = {fmt(m)} ₸\n\n"
        f"☕️ *Дополнительные:* {cfg.get('pf3',0)}% от остатка\n"
        f"   План: {fmt(cfg.get('sum3',0))} ₸/мес\n"
        f"   Остаток = {fmt(r)} ₸\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
    )
    for fn in [1,2,3]:
        pockets=get_pockets(uw,fn)
        if pockets:
            text += f"*Карманы {FUND_NAMES[fn]}:*\n"
            for p in pockets:
                text += f"  • {p['name']} — {fmt(p['planned'])} ₸ ({round(p['pct'],1)}%)\n"
            text += "\n"
    text += "💡 Чтобы изменить — нажми «Заполнить заново»"
    await msg.answer(text, parse_mode="Markdown", reply_markup=kb_settings())

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ➕ ДОБАВИТЬ КАРМАН
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dp.message_handler(lambda m: m.text == "➕ Добавить карман в фонд")
async def add_pocket_start(msg: types.Message):
    await bot.send_chat_action(msg.chat.id, types.ChatActions.TYPING)
    uw=get_user_ws(msg.from_user.id); cfg=get_config(uw) if uw else None
    if not cfg:
        return await msg.answer("⚠️ Сначала заполни бриф: /start", reply_markup=kb_settings())

    text = (
        "➕ *ДОБАВИТЬ КАРМАН В ФОНД*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Сейчас в твоих фондах:\n\n"
    )
    for fn in [1,2,3]:
        pockets=get_pockets(uw,fn)
        text += f"*{FUND_NAMES[fn]}:*\n"
        if pockets:
            for p in pockets:
                text += f"  • {p['name']} — {fmt(p['planned'])} ₸\n"
        else:
            text += "  (пусто)\n"
        text += "\n"
    text += "В какой фонд добавить новый карман? 👇"
    await msg.answer(text, parse_mode="Markdown", reply_markup=kb_funds())
    await Form.add_pocket_fund.set()


@dp.message_handler(state=Form.add_pocket_fund)
async def add_pocket_fund_h(msg: types.Message, state: FSMContext):
    if msg.text == "🔙 Отмена":
        await state.finish()
        return await msg.answer("❌ Действие отменено.", reply_markup=kb_settings())
    fn=parse_fund(msg.text)
    if not fn:
        return await msg.answer("⚠️ Выбери фонд из кнопок ниже 👇", reply_markup=kb_funds())

    async with state.proxy() as d: d['add_fn']=fn; d['add_items']=[]

    uw=get_user_ws(msg.from_user.id); pockets=get_pockets(uw,fn)
    existing = ""
    if pockets:
        existing = "*Уже есть:*\n"
        for p in pockets:
            existing += f"  • {p['name']} — {fmt(p['planned'])} ₸\n"
        existing += "\n"

    await msg.answer(
        f"📂 *{FUND_NAMES[fn]}*\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"{existing}"
        "✏️ Напиши новые карманы:\n"
        "`Название - сумма`\n\n"
        "Каждый — с новой строки.\n"
        "Старые карманы останутся на месте!",
        parse_mode="Markdown", reply_markup=kb_cancel()
    )
    await Form.add_pocket_items.set()


@dp.message_handler(state=Form.add_pocket_items)
async def add_pocket_items_h(msg: types.Message, state: FSMContext):
    if msg.text == "🔙 Отмена":
        await state.finish()
        return await msg.answer("❌ Действие отменено.", reply_markup=kb_settings())

    if msg.text == "✅ Сохранить":
        async with state.proxy() as d: fn=d['add_fn']; items=d.get('add_items',[])
        if not items:
            return await msg.answer(
                "⚠️ Ты ещё ничего не добавил!\n"
                "Напиши карманы в формате: `Название - сумма`",
                parse_mode="Markdown", reply_markup=kb_cancel()
            )
        st=await thinking(msg.chat.id, "⏳ Пересчитываю проценты и сохраняю...")
        uw=get_user_ws(msg.from_user.id); cfg=add_pockets_to_fund(uw,fn,items)
        await del_msg(st)
        if not cfg:
            await state.finish()
            return await msg.answer("❌ Ошибка сохранения.\nПопробуй /start", reply_markup=kb_main())
        txt=""
        for it in items:
            txt += f"  • {it['name']} — {fmt(it['amount'])} ₸\n"
        await state.finish()
        return await msg.answer(
            "✅ *КАРМАНЫ ДОБАВЛЕНЫ!*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"📂 *{FUND_NAMES[fn]}*\n\n"
            f"Новые карманы:\n{txt}\n"
            f"🎯 *Новая точка безубыточности:* {fmt(cfg['tb'])} ₸/мес\n\n"
            "Все проценты пересчитаны.\n"
            "Балансы существующих карманов сохранены! 👍",
            parse_mode="Markdown", reply_markup=kb_main()
        )

    if msg.text == "➕ Добавить ещё":
        return await msg.answer(
            "✏️ Напиши ещё карманы:\n"
            "`Название - сумма`\n\n"
            "Каждый — с новой строки.",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )

    new=parse_items(msg.text)
    if not new:
        return await msg.answer(
            "⚠️ Не удалось распознать.\n\n"
            "Формат: `Название - сумма`\n\n"
            "*Пример:*\n"
            "`Новый сотрудник - 250000`\n"
            "`Доп. реклама - 100000`",
            parse_mode="Markdown", reply_markup=kb_cancel()
        )
    async with state.proxy() as d:
        fn=d['add_fn']; lst=d.get('add_items',[]); lst.extend(new); d['add_items']=lst
    txt=""
    for i,it in enumerate(lst,1):
        txt += f"  {i}. {it['name']} — {fmt(it['amount'])} ₸\n"
    n=len(new); w="карман" if n==1 else ("кармана" if n<5 else "карманов")
    await msg.answer(
        f"✅ Добавлено: {n} {w}!\n\n"
        f"Новые карманы для *{FUND_NAMES[fn]}:*\n\n{txt}\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "➕ *Добавить ещё* — если есть ещё карманы\n"
        "✅ *Сохранить* — пересчитать проценты и сохранить",
        parse_mode="Markdown", reply_markup=kb_save()
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🔄 ЗАПОЛНИТЬ ЗАНОВО / МЕНЮ / ТАБЛИЦА
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dp.message_handler(lambda m: m.text == "🔄 Заполнить заново")
async def reset(msg: types.Message, state: FSMContext):
    log.info(f"🔄 Сброс: {msg.from_user.id}")
    uw=get_user_ws(msg.from_user.id); cfg=get_config(uw) if uw else None
    tb_str=fmt(cfg['tb']) if cfg else "Не задано"
    await msg.answer(
        "⚠️ *ВНИМАНИЕ!*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"Текущая ТБ: *{tb_str} ₸*\n\n"
        "*Что произойдёт:*\n"
        "🔄 Все статьи будут записаны заново\n"
        "🔄 Балансы обнулятся\n"
        "🔄 Новые поступления пойдут по новым %\n\n"
        "Начинаем заполнение заново...",
        parse_mode="Markdown"
    )
    await start_brief(msg, state, 1)


@dp.message_handler(lambda m: m.text == "🔙 Главное меню")
async def back(msg: types.Message):
    await msg.answer("Главное меню 👇", reply_markup=kb_main())


@dp.message_handler(lambda m: m.text == "🔗 Таблица")
async def sheet_link(msg: types.Message):
    uw = get_user_ws(msg.from_user.id)
    if not uw:
        return await msg.answer("⚠️ Сначала заполни бриф: /start")
    url = f"https://docs.google.com/spreadsheets/d/{uw['sheet_id']}"
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📂 Открыть мою Google Таблицу", url=url))
    await msg.answer(
        "📊 *ТВОЯ ПЕРСОНАЛЬНАЯ ТАБЛИЦА*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "У тебя *своя личная* таблица!\n"
        "Все данные хранятся в Google Sheets.\n"
        "Каждый фонд — на отдельном листе.\n\n"
        "*Листы в таблице:*\n\n"
        "  ⚙️ Настройки — ТБ, маржа, проценты\n"
        "  🏗 Фонд 1 — карманы себестоимости\n"
        "  💻 Фонд 2 — операционные карманы\n"
        "  ☕ Фонд 3 — дополнительные карманы\n"
        "  💰 Баланс — общий обзор фондов\n"
        "  📜 История — все операции\n\n"
        "👇 Нажми чтобы открыть:",
        parse_mode="Markdown", reply_markup=kb
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🔙 ОТМЕНА / ❓ НЕИЗВЕСТНОЕ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dp.message_handler(lambda m: m.text in ["🔙 Отмена","🔙 Назад"], state="*")
async def cancel(msg: types.Message, state: FSMContext):
    if await state.get_state(): await state.finish()
    await msg.answer("❌ Действие отменено.", reply_markup=kb_main())


@dp.message_handler()
async def unknown(msg: types.Message):
    await msg.answer(
        "🤔 Не понял команду.\n\n"
        "Используй кнопки меню 👇\n"
        "Или напиши /start чтобы начать.",
        reply_markup=kb_main()
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 🚀 ЗАПУСК
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == '__main__':
    log.info("━━━━━━━━━━━━━━━━━━")
    log.info("💎 FUNDAMENTA BOT")
    log.info("🚀 Запуск...")
    log.info("━━━━━━━━━━━━━━━━━━")
    executor.start_polling(dp, skip_updates=True)