import logging
import sys
import re
import asyncio
import sqlite3
import hmac
import hashlib
import json
import gspread
from datetime import datetime, timezone, timedelta
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.utils import executor
from aiohttp import web

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 💎 FUNDAMENTA BOT v4 — КОНФИГУРАЦИЯ
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

BOT_TOKEN = '7780440391:AAEYlDcEq9egFWa8s_dq6v4-DZQVKXTy21E'
MASTER_SHEET_ID = '1DCUghK3I2108lyMbpM_1n_XTDw9HxhhaBhmAmOt9rXo'
CREDENTIALS_FILE = 'sheetsapi-443912-7487420df9cd.json'
YOUTUBE_LESSON_URL = "https://youtu.be/lDp0aICRlR0?si=vtO0xtpxA3uLBADf"
DB_FILE = 'fundamenta.db'
SYNC_INTERVAL = 300  # секунды

# ━━━ TRIBUTE ПОДПИСКА ━━━
TRIBUTE_API_KEY = ''           # API ключ из дашборда Tribute (Dashboard → Settings → API Keys)
TRIBUTE_PAYMENT_URL = ''       # Ссылка на подписку Tribute для этого бота
WEBHOOK_HOST = '0.0.0.0'
WEBHOOK_PORT = 8080
ADMIN_USER_ID = 870933779              # Telegram user_id администратора (для команды /activate)

# file_id видео-кружков (привязаны к боту 7780440391). Если круги не шлются — отправь круг боту, скопируй file_id из ответа.
VIDEO_1_INTRO = "DQACAgIAAxkBAAICCmmUgJ-9aD1_vuMco8tXcv9AC0RpAAJ4jQACTpWoSF_997AbFDQaOgQ"
VIDEO_2_SEBES = "DQACAgIAAxkBAAICC2mUgJ-IPpL8vGPfC6Giib0e1U7ZAAKDjQACTpWoSLnsjGLdJkKcOgQ"
VIDEO_3_OPER  = "DQACAgIAAxkBAAICDGmUgJ_G4WYKwxkKYvtXuD1sohMKAAKHjQACTpWoSJoKnlDD7qDtOgQ"
VIDEO_4_DOP   = "DQACAgIAAxkBAAICDWmUgJ8ybwsukX88otT2SVMs5GR-AAKNjQACTpWoSGlethuhDPdpOgQ"
VIDEO_5_FINAL = "DQACAgIAAxkBAAIJ4GmlU2CgkYEzueGN2QsVnqCiWaqbAAINkQAC1C3gSPJysJA2zyu6OgQ"


FUND_VIDEOS = {1: VIDEO_1_INTRO, 2: VIDEO_2_SEBES, 3: VIDEO_3_OPER}
ALMATY_TZ = timezone(timedelta(hours=5))

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)-7s | %(name)s | %(message)s',
    handlers=[logging.StreamHandler(sys.stdout), logging.FileHandler('fundamenta_bot.log', encoding='utf-8')])
log = logging.getLogger("FUND")

# ━━━ SQLITE ━━━
def db_connect():
    conn = sqlite3.connect(DB_FILE); conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL"); conn.execute("PRAGMA foreign_keys=ON"); return conn

def db_init():
    conn = db_connect()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (user_id INTEGER PRIMARY KEY, username TEXT DEFAULT '', first_name TEXT DEFAULT '', sheet_id TEXT DEFAULT '', needs_sync INTEGER DEFAULT 1, created_at TEXT);
        CREATE TABLE IF NOT EXISTS config (user_id INTEGER PRIMARY KEY, tb REAL DEFAULT 0, sum1 REAL DEFAULT 0, sum2 REAL DEFAULT 0, sum3 REAL DEFAULT 0, margin REAL DEFAULT 0, remainder REAL DEFAULT 0, pf1 REAL DEFAULT 0, pf2 REAL DEFAULT 0, pf3 REAL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS pockets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, fund_num INTEGER, name TEXT, planned REAL DEFAULT 0, pct REAL DEFAULT 0, balance REAL DEFAULT 0, position INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, date TEXT, type TEXT, amount REAL, fund TEXT DEFAULT '', pocket TEXT DEFAULT '', comment TEXT DEFAULT '', username TEXT DEFAULT '');
        CREATE TABLE IF NOT EXISTS subscriptions (user_id INTEGER PRIMARY KEY, status TEXT DEFAULT 'inactive', tribute_sub_id TEXT DEFAULT '', started_at TEXT DEFAULT '', expires_at TEXT DEFAULT '', updated_at TEXT DEFAULT '');
        CREATE INDEX IF NOT EXISTS idx_pockets_user ON pockets(user_id, fund_num);
        CREATE INDEX IF NOT EXISTS idx_history_user ON history(user_id);
    """)
    conn.commit(); conn.close(); log.info("🗄 SQLite OK")

def db_get_user(uid):
    c = db_connect(); r = c.execute("SELECT * FROM users WHERE user_id=?", (uid,)).fetchone(); c.close()
    return dict(r) if r else None

def db_create_user(uid, un, fn):
    c = db_connect(); c.execute("INSERT OR IGNORE INTO users (user_id,username,first_name,created_at) VALUES (?,?,?,?)", (uid,un,fn,datetime.now().strftime("%Y-%m-%d %H:%M"))); c.commit(); c.close()

def db_set_sheet_id(uid, sid):
    c = db_connect(); c.execute("UPDATE users SET sheet_id=?,needs_sync=1 WHERE user_id=?", (sid,uid)); c.commit(); c.close()

def db_mark_dirty(uid):
    c = db_connect(); c.execute("UPDATE users SET needs_sync=1 WHERE user_id=?", (uid,)); c.commit(); c.close()

def db_mark_clean(uid):
    c = db_connect(); c.execute("UPDATE users SET needs_sync=0 WHERE user_id=?", (uid,)); c.commit(); c.close()

def db_get_dirty_users():
    c = db_connect(); rows = c.execute("SELECT * FROM users WHERE needs_sync=1 AND sheet_id!=''").fetchall(); c.close()
    return [dict(r) for r in rows]

def db_get_all_users():
    c = db_connect(); rows = c.execute("SELECT * FROM users").fetchall(); c.close()
    return [dict(r) for r in rows]

def db_get_config(uid):
    c = db_connect(); r = c.execute("SELECT * FROM config WHERE user_id=?", (uid,)).fetchone(); c.close()
    if not r or r['tb'] == 0: return None
    return dict(r)

def db_save_config(uid, cfg):
    c = db_connect()
    c.execute("INSERT INTO config (user_id,tb,sum1,sum2,sum3,margin,remainder,pf1,pf2,pf3) VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET tb=excluded.tb,sum1=excluded.sum1,sum2=excluded.sum2,sum3=excluded.sum3,margin=excluded.margin,remainder=excluded.remainder,pf1=excluded.pf1,pf2=excluded.pf2,pf3=excluded.pf3",
        (uid, cfg['tb'], cfg['sum1'], cfg['sum2'], cfg['sum3'], cfg['margin'], cfg['remainder'], cfg['pf1'], cfg['pf2'], cfg['pf3']))
    c.commit(); c.close(); db_mark_dirty(uid)

def db_get_pockets(uid, fn):
    c = db_connect(); rows = c.execute("SELECT * FROM pockets WHERE user_id=? AND fund_num=? ORDER BY position", (uid,fn)).fetchall(); c.close()
    return [dict(r) for r in rows]

def db_save_pockets(uid, fn, items, keep_balances=False):
    c = db_connect()
    old = {}
    if keep_balances:
        for r in c.execute("SELECT name, balance FROM pockets WHERE user_id=? AND fund_num=?", (uid,fn)).fetchall():
            old[r['name']] = r['balance']
    c.execute("DELETE FROM pockets WHERE user_id=? AND fund_num=?", (uid,fn))
    for i, it in enumerate(items):
        bal = old.get(it['name'], it.get('balance', 0))
        c.execute("INSERT INTO pockets (user_id,fund_num,name,planned,pct,balance,position) VALUES (?,?,?,?,?,?,?)",
            (uid, fn, it['name'], it['amount'], it.get('pct',0), bal, i+1))
    c.commit(); c.close(); db_mark_dirty(uid)

def db_update_pocket_balance(pid, nb):
    c = db_connect(); c.execute("UPDATE pockets SET balance=? WHERE id=?", (nb,pid)); c.commit(); c.close()

def db_get_balance(uid):
    c = db_connect(); f = [0,0,0]
    for fn in [1,2,3]:
        r = c.execute("SELECT COALESCE(SUM(balance),0) as s FROM pockets WHERE user_id=? AND fund_num=?", (uid,fn)).fetchone()
        f[fn-1] = int(r['s'])
    c.close(); return [f[0],f[1],f[2],f[0]+f[1]+f[2]]

def db_add_history(uid, type_, amount, fund, pocket, comment, username):
    c = db_connect()
    c.execute("INSERT INTO history (user_id,date,type,amount,fund,pocket,comment,username) VALUES (?,?,?,?,?,?,?,?)",
        (uid, datetime.now().strftime("%Y-%m-%d %H:%M"), type_, amount, fund, pocket, comment, username))
    c.commit(); c.close(); db_mark_dirty(uid)

def db_get_debts(uid):
    c = db_connect()
    rows = c.execute("SELECT fund, SUM(ABS(amount)) as total FROM history WHERE user_id=? AND type='ДОЛГ' GROUP BY fund", (uid,)).fetchall()
    c.close(); return {r['fund']: int(r['total']) for r in rows}

def db_get_history(uid):
    c = db_connect(); rows = c.execute("SELECT * FROM history WHERE user_id=? ORDER BY id", (uid,)).fetchall(); c.close()
    return [dict(r) for r in rows]

# ━━━ ПОДПИСКИ ━━━
def db_get_sub(uid):
    c = db_connect(); r = c.execute("SELECT * FROM subscriptions WHERE user_id=?", (uid,)).fetchone(); c.close()
    return dict(r) if r else None

def db_has_active_sub(uid):
    c = db_connect()
    r = c.execute("SELECT 1 FROM subscriptions WHERE user_id=? AND status='active'", (uid,)).fetchone()
    c.close()
    return r is not None

def db_set_sub(uid, status, tribute_sub_id=''):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    c = db_connect()
    existing = c.execute("SELECT 1 FROM subscriptions WHERE user_id=?", (uid,)).fetchone()
    if existing:
        if status == 'active':
            c.execute("UPDATE subscriptions SET status=?, tribute_sub_id=?, updated_at=? WHERE user_id=?",
                (status, tribute_sub_id or '', now, uid))
        else:
            c.execute("UPDATE subscriptions SET status=?, updated_at=? WHERE user_id=?",
                (status, now, uid))
    else:
        c.execute("INSERT INTO subscriptions (user_id, status, tribute_sub_id, started_at, updated_at) VALUES (?,?,?,?,?)",
            (uid, status, tribute_sub_id or '', now, now))
    c.commit(); c.close()

def db_get_active_subscribers():
    c = db_connect()
    rows = c.execute("SELECT s.user_id, u.first_name FROM subscriptions s LEFT JOIN users u ON s.user_id=u.user_id WHERE s.status='active'").fetchall()
    c.close()
    return [dict(r) for r in rows]

# ━━━ GOOGLE SHEETS SYNC ━━━
log.info("🔌 Google Sheets...")
try:
    gc = gspread.service_account(filename=CREDENTIALS_FILE); log.info("✅ Sheets OK")
except Exception as e:
    log.warning(f"⚠️ Sheets: {e}"); gc = None

def emo(cur, tot):
    if tot <= 0: return "⬜"
    p = cur / tot
    if p >= 1.0: return "✅"
    if p >= 0.5: return "🟡"
    if p >= 0.2: return "🟠"
    return "🔴"

def sheets_create_for_user(uid, un, fn):
    if not gc: return None
    title = f"FUNDAMENTA — {fn} (@{un or uid})"
    try: new_sh = gc.create(title)
    except Exception as e:
        if "quota" in str(e).lower() or "storage" in str(e).lower(): log.error(f"❌ Drive full: {e}"); return None
        raise
    sid = new_sh.id; new_sh.share('', perm_type='anyone', role='reader')
    ws = new_sh.sheet1; ws.update_title("⚙️ Настройки")
    new_sh.add_worksheet("🏗 Фонд 1 Себестоимость", rows=100, cols=6)
    new_sh.add_worksheet("💻 Фонд 2 Операционные", rows=100, cols=6)
    new_sh.add_worksheet("☕ Фонд 3 Дополнительные", rows=100, cols=6)
    new_sh.add_worksheet("💰 Баланс", rows=20, cols=6)
    new_sh.add_worksheet("📜 История", rows=5000, cols=7)
    new_sh.worksheet("📜 История").append_row(["Дата","Тип","Сумма ₸","Фонд","Карман","Комментарий","Пользователь"])
    log.info(f"   ✅ Sheet: {sid}"); return sid

def sync_user_to_sheets(user):
    uid = user['user_id']; sid = user['sheet_id']
    if not sid or not gc: return False
    try: sh = gc.open_by_key(sid)
    except Exception as e: log.error(f"❌ sync open {uid}: {e}"); return False
    try:
        cfg = db_get_config(uid)
        if not cfg: db_mark_clean(uid); return True
        ws_cfg = sh.worksheet("⚙️ Настройки")
        cfg_data = [["═══ FUNDAMENTA — НАСТРОЙКИ ═══",""],["",""],["🎯 Точка безубыточности",cfg['tb']],["",""],
            ["🏗 Сумма Фонд 1",cfg['sum1']],["   % Себестоимость от ТБ",f"{cfg['pf1']}%"],["",""],
            ["💻 Сумма Фонд 2",cfg['sum2']],["   Маржа",cfg['margin']],["   % Операционные от Маржи",f"{cfg['pf2']}%"],["",""],
            ["☕ Сумма Фонд 3",cfg['sum3']],["   Остаток",cfg['remainder']],["   % Дополнительные от Остатка",f"{cfg['pf3']}%"],["",""],
            ["Дата",datetime.now().strftime("%Y-%m-%d %H:%M")]]
        ws_cfg.clear(); ws_cfg.update(values=cfg_data, range_name='A1:B16')
        fwn = {1:"🏗 Фонд 1 Себестоимость",2:"💻 Фонд 2 Операционные",3:"☕ Фонд 3 Дополнительные"}
        bases = {1:('ТБ',cfg['tb']),2:('маржи',cfg['margin']),3:('остатка',cfg['remainder'])}
        labels = {1:'Себестоимость',2:'Операционные',3:'Дополнительные'}
        for fn in [1,2,3]:
            ws = sh.worksheet(fwn[fn]); pockets = db_get_pockets(uid,fn); bl,bv = bases[fn]
            data = [["№","Карман","План ₸/мес",f"% от {bl}","Баланс ₸","Статус"]]
            for i,p in enumerate(pockets,1):
                pct = round(p['planned']/bv*100,1) if bv>0 else 0; b = int(p['balance'])
                data.append([i,p['name'],int(p['planned']),f"{pct}%",b,emo(b,p['planned'])])
            tp = sum(int(p['planned']) for p in pockets); tb2 = sum(int(p['balance']) for p in pockets)
            data.append(["","","","","",""]); data.append(["",f"📊 ИТОГО {labels[fn]}",tp,"—",tb2,""])
            ws.clear(); ws.update(values=data, range_name=f'A1:F{len(data)}')
        bal = db_get_balance(uid); tb=cfg['tb']; total=bal[3]; s1,s2,s3=cfg['sum1'],cfg['sum2'],cfg['sum3']
        runway=round(total/tb,1) if tb>0 else 0; gap=max(0,tb-total)
        bd = [["═══ FUNDAMENTA — БАЛАНС ═══","","","",""],["","","","",""],
            ["Фонд","В фонде ₸","План ₸/мес","Заполнено","Статус"],
            ["🏗 Себестоимость",bal[0],int(s1),f"{int(bal[0]/s1*100)}%" if s1>0 else "0%",emo(bal[0],s1)],
            ["💻 Операционные",bal[1],int(s2),f"{int(bal[1]/s2*100)}%" if s2>0 else "0%",emo(bal[1],s2)],
            ["☕ Дополнительные",bal[2],int(s3),f"{int(bal[2]/s3*100)}%" if s3>0 else "0%",emo(bal[2],s3)],
            ["","","","",""],["💰 ИТОГО",total,int(tb),"",""],["","","","",""],
            ["═══ ПОКАЗАТЕЛИ ═══","","","",""],["🎯 Точка безубыточности",int(tb),"₸/мес","",""],
            ["📉 Не хватает до ТБ",int(gap),"₸","",""],["⏳ Запас хода",runway,"мес.",""]]
        ws_bal = sh.worksheet("💰 Баланс"); ws_bal.clear(); ws_bal.update(values=bd, range_name='A1:E13')
        hist = db_get_history(uid); ws_h = sh.worksheet("📜 История"); ws_h.clear()
        hd = [["Дата","Тип","Сумма ₸","Фонд","Карман","Комментарий","Пользователь"]]
        for h in hist: hd.append([h['date'],h['type'],h['amount'],h['fund'],h['pocket'],h['comment'],h['username']])
        ws_h.update(values=hd, range_name=f'A1:G{len(hd)}')
        db_mark_clean(uid); log.info(f"   ✅ Synced: {user['first_name']} ({uid})"); return True
    except Exception as e:
        log.error(f"❌ sync {uid}: {e}"); return False

async def sync_loop():
    log.info(f"🔄 Sync loop started ({SYNC_INTERVAL}s)")
    while True:
        await asyncio.sleep(SYNC_INTERVAL)
        try:
            dirty = db_get_dirty_users()
            if dirty:
                log.info(f"🔄 Syncing {len(dirty)} users...")
                for u in dirty: sync_user_to_sheets(u); await asyncio.sleep(2)
        except Exception as e: log.error(f"❌ sync_loop: {e}")

# ━━━ БИЗНЕС-ЛОГИКА ━━━
def ensure_user(uid, un, fn):
    u = db_get_user(uid)
    if not u: db_create_user(uid, un, fn); u = db_get_user(uid)
    if not u.get('sheet_id') and gc:
        sid = sheets_create_for_user(uid, un, fn)
        if sid: db_set_sheet_id(uid, sid); u['sheet_id'] = sid
    return u

def save_brief(uid, f1, f2, f3):
    s1=sum(i['amount'] for i in f1); s2=sum(i['amount'] for i in f2); s3=sum(i['amount'] for i in f3)
    tb=s1+s2+s3
    if tb==0: return None
    margin=tb-s1; remainder=margin-s2
    pf1=round(s1/tb*100,1); pf2=round(s2/margin*100,1) if margin>0 else 0; pf3=round(s3/remainder*100,1) if remainder>0 else 0
    cfg={'tb':tb,'sum1':s1,'sum2':s2,'sum3':s3,'margin':margin,'remainder':remainder,'pf1':pf1,'pf2':pf2,'pf3':pf3}
    db_save_config(uid, cfg)
    bases={1:tb,2:margin,3:remainder}; funds={1:f1,2:f2,3:f3}
    for fn in [1,2,3]:
        bv=bases[fn]
        for it in funds[fn]: it['pct']=round(it['amount']/bv*100,1) if bv>0 else 0; it['balance']=0
        db_save_pockets(uid, fn, funds[fn])
    return cfg

def add_pockets_logic(uid, fund_num, new_items):
    all_f={}
    for fn in [1,2,3]:
        pockets=db_get_pockets(uid,fn)
        all_f[fn]=[{'name':p['name'],'amount':int(p['planned']),'balance':int(p['balance'])} for p in pockets]
    for it in new_items: all_f[fund_num].append({'name':it['name'],'amount':it['amount'],'balance':0})
    s1=sum(i['amount'] for i in all_f[1]); s2=sum(i['amount'] for i in all_f[2]); s3=sum(i['amount'] for i in all_f[3])
    tb=s1+s2+s3
    if tb==0: return None
    margin=tb-s1; remainder=margin-s2
    pf1=round(s1/tb*100,1); pf2=round(s2/margin*100,1) if margin>0 else 0; pf3=round(s3/remainder*100,1) if remainder>0 else 0
    cfg={'tb':tb,'sum1':s1,'sum2':s2,'sum3':s3,'margin':margin,'remainder':remainder,'pf1':pf1,'pf2':pf2,'pf3':pf3}
    db_save_config(uid, cfg)
    bases={1:tb,2:margin,3:remainder}
    for fn in [1,2,3]:
        bv=bases[fn]
        for it in all_f[fn]: it['pct']=round(it['amount']/bv*100,1) if bv>0 else 0
        db_save_pockets(uid, fn, all_f[fn], keep_balances=True)
    return cfg

def distribute_income(uid, amount):
    cfg=db_get_config(uid)
    if not cfg: return None
    tb=cfg['tb']; s1=cfg['sum1']; s2=cfg['sum2']; s3=cfg['sum3']; margin=cfg['margin']
    add1=int(amount*s1/tb) if tb>0 else 0; rest1=amount-add1
    add2=int(rest1*s2/margin) if margin>0 else 0; add3=amount-add1-add2
    for fn,add_a,fs in [(1,add1,s1),(2,add2,s2),(3,add3,s3)]:
        if add_a<=0: continue
        pockets=db_get_pockets(uid,fn)
        if not pockets: continue
        dist=0
        for i,p in enumerate(pockets):
            sh=p['planned']/fs if fs>0 else 1.0/len(pockets)
            pa=add_a-dist if i==len(pockets)-1 else int(add_a*sh)
            dist+=pa; db_update_pocket_balance(p['id'], int(p['balance'])+pa)
    db_mark_dirty(uid); return add1, add2, add3, db_get_balance(uid)

# ━━━ БОТ ━━━
bot = Bot(token=BOT_TOKEN); storage = MemoryStorage(); dp = Dispatcher(bot, storage=storage)

class Form(StatesGroup):
    brief_items = State(); income_amount = State()
    expense_amount = State(); expense_fund = State(); expense_pocket = State()
    expense_comment = State(); expense_insufficient = State()
    expense_borrow_fund = State(); expense_borrow_pocket = State()
    add_pocket_fund = State(); add_pocket_items = State()

FUND_NAMES = {1:"🏗 Себестоимость", 2:"💻 Операционные расходы", 3:"☕️ Дополнительные расходы"}

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

def fmt(n):
    try: return '{:,}'.format(int(float(n))).replace(',', ' ')
    except: return str(n)

def bar(cur, tot, l=10):
    if tot<=0: return "░"*l+" 0%"
    r=min(max(cur/tot,0),1.0); f=int(r*l); return "█"*f+"░"*(l-f)+f" {int(r*100)}%"

def parse_items(text):
    items=[]
    for line in text.strip().split('\n'):
        line=line.strip()
        if not line: continue
        line=re.sub(r'^[\d]+[\.\)\-\s]+','',line).strip(); line=re.sub(r'^[-–—•]\s*','',line).strip()
        if not line: continue
        parts=None
        for sep in [' - ',' — ',' – ',': ',' -','- ','— ']:
            if sep in line: idx=line.rfind(sep); parts=(line[:idx].strip(),line[idx+len(sep):].strip()); break
        if not parts:
            m=re.match(r'^(.+?)\s+([\d\s\xa0]+)$',line)
            if m: parts=(m.group(1).strip(),m.group(2).strip())
        if parts:
            name=parts[0]; amt=re.sub(r'[^\d]','',parts[1])
            if name and amt and amt.isdigit() and int(amt)>0: items.append({'name':name,'amount':int(amt)})
    return items

async def thinking(cid, text="⏳ Считаю..."):
    try: await bot.send_chat_action(cid, types.ChatActions.TYPING); return await bot.send_message(cid, text)
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

# ━━━ КЛАВИАТУРЫ ━━━
def kb_main():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=2)
    kb.add("💰 Внести доход","💸 Списать расход"); kb.add("📊 Баланс","📋 Подробно по фондам"); kb.add("⚙️ Настройки","🔗 Таблица"); return kb
def kb_cancel():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True); kb.add("🔙 Отмена"); return kb
def kb_brief_act():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=2); kb.add("➕ Добавить ещё","✅ Готово, следующий шаг"); kb.add("🔙 Отмена"); return kb
def kb_funds():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=1); kb.add("🏗 Себестоимость","💻 Операционные расходы","☕️ Дополнительные расходы","🔙 Отмена"); return kb
def kb_pockets(pockets):
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=1)
    for p in pockets: kb.add(f"{p['name']} [{fmt(p['balance'])} ₸]")
    kb.add("🔙 Назад"); return kb
def kb_settings():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=1); kb.add("➕ Добавить карман в фонд","🔄 Заполнить заново","📋 Текущие настройки","🔙 Главное меню"); return kb
def kb_save():
    kb=types.ReplyKeyboardMarkup(resize_keyboard=True,row_width=2); kb.add("➕ Добавить ещё","✅ Сохранить"); kb.add("🔙 Отмена"); return kb
def kb_insufficient(av, sh):
    kb=types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton(f"💳 Оплатить частично ({fmt(av)} ₸)",callback_data="exp_partial"),
           types.InlineKeyboardButton(f"🔄 Одолжить у другого фонда ({fmt(sh)} ₸)",callback_data="exp_borrow"),
           types.InlineKeyboardButton("⏳ Перенести платёж",callback_data="exp_postpone")); return kb

# ━━━ TRIBUTE WEBHOOK SERVER ━━━
def verify_tribute_signature(body: bytes, signature: str) -> bool:
    if not TRIBUTE_API_KEY:
        return False
    expected = hmac.new(TRIBUTE_API_KEY.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

async def tribute_webhook_handler(request: web.Request) -> web.Response:
    body = await request.read()
    signature = request.headers.get('trbt-signature', '')
    if TRIBUTE_API_KEY and not verify_tribute_signature(body, signature):
        log.warning("⚠️ Tribute webhook: неверная подпись")
        return web.Response(status=403, text="Invalid signature")
    try:
        data = json.loads(body)
    except Exception:
        return web.Response(status=400, text="Bad JSON")
    event = data.get('event', '')
    payload = data.get('payload', {})
    user_data = payload.get('user', {})
    tg_id = user_data.get('telegram_id') or payload.get('telegram_id')
    sub_id = str(payload.get('id', ''))
    if not tg_id:
        log.warning(f"⚠️ Tribute webhook без telegram_id: {event}")
        return web.Response(status=200, text="OK (no tg_id)")
    tg_id = int(tg_id)
    log.info(f"💳 Tribute event: {event} | user={tg_id} | sub_id={sub_id}")
    if event in ('newSubscription', 'renewedSubscription'):
        db_set_sub(tg_id, 'active', sub_id)
        try:
            await bot.send_message(tg_id,
                "✅ *ПОДПИСКА АКТИВИРОВАНА!*\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "Теперь тебе доступны все функции\n"
                "FUNDAMENTA! 💎\n\n"
                "  💰 Внесение доходов\n"
                "  💸 Списание расходов\n"
                "  📊 Баланс и аналитика\n"
                "  ⚙️ Настройки фондов\n\n"
                "Выбери действие 👇",
                parse_mode="Markdown", reply_markup=kb_main())
        except Exception as e:
            log.warning(f"⚠️ Не удалось отправить подтверждение подписки {tg_id}: {e}")
    elif event == 'cancelledSubscription':
        db_set_sub(tg_id, 'inactive', sub_id)
        try:
            await bot.send_message(tg_id,
                "⚠️ *Подписка отменена*\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "Доступ к функциям FUNDAMENTA\n"
                "приостановлен.\n\n"
                "Чтобы продолжить — оформи подписку\n"
                "заново: /subscribe",
                parse_mode="Markdown")
        except Exception as e:
            log.warning(f"⚠️ Не удалось отправить уведомление об отмене {tg_id}: {e}")
    return web.Response(status=200, text="OK")

async def start_webhook_server():
    app = web.Application()
    app.router.add_post('/webhook/tribute', tribute_webhook_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEBHOOK_HOST, WEBHOOK_PORT)
    await site.start()
    log.info(f"🌐 Tribute webhook server: http://{WEBHOOK_HOST}:{WEBHOOK_PORT}/webhook/tribute")

# ━━━ ПРОВЕРКА ПОДПИСКИ ━━━
def kb_subscribe():
    kb = types.InlineKeyboardMarkup(row_width=1)
    if TRIBUTE_PAYMENT_URL:
        kb.add(types.InlineKeyboardButton("💳 Оформить подписку", url=TRIBUTE_PAYMENT_URL))
    kb.add(types.InlineKeyboardButton("🔄 Я уже оплатил", callback_data="check_sub"))
    return kb

async def require_sub(msg: types.Message) -> bool:
    if db_has_active_sub(msg.from_user.id):
        return True
    await msg.answer(
        "🔒 *НУЖНА ПОДПИСКА*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Эта функция доступна только\n"
        "по подписке *FUNDAMENTA*.\n\n"
        "Стоимость: *6 999 ₸/мес*\n"
        "Автопродление каждый месяц.\n\n"
        "Оформи подписку и получи\n"
        "полный доступ ко всем функциям! 💎\n\n"
        "Нажми /subscribe для подробностей.",
        parse_mode="Markdown", reply_markup=kb_subscribe())
    return False

@dp.callback_query_handler(lambda c: c.data == "check_sub", state="*")
async def cb_check_sub(cb: types.CallbackQuery):
    await cb.answer()
    if db_has_active_sub(cb.from_user.id):
        await cb.message.answer(
            "✅ *Подписка активна!*\n\n"
            "Все функции доступны.\n"
            "Выбери действие 👇",
            parse_mode="Markdown", reply_markup=kb_main())
    else:
        await cb.message.answer(
            "⏳ Оплата ещё не поступила.\n\n"
            "Если ты только что оплатил — подожди\n"
            "1–2 минуты и нажми «Я уже оплатил» снова.\n\n"
            "Если проблема сохраняется — напиши\n"
            "администратору.",
            parse_mode="Markdown", reply_markup=kb_subscribe())

# ━━━ /start ━━━
@dp.message_handler(commands=['start'], state="*")
async def cmd_start(msg: types.Message, state: FSMContext):
    await state.finish(); uid=msg.from_user.id
    st=await thinking(msg.chat.id,"⏳ Загружаю твои данные..."); u=ensure_user(uid,msg.from_user.username or "",msg.from_user.first_name); await del_msg(st)
    if not u: return await msg.answer("❌ *Ошибка создания таблицы!*\n\nСкорее всего переполнен Google Drive.\nНапиши администратору для решения.",parse_mode="Markdown")
    cfg=db_get_config(uid)
    if cfg and cfg['tb']>0:
        await msg.answer("💎 *FUNDAMENTA*\n━━━━━━━━━━━━━━━━━━\n\n"+f"С возвращением, *{msg.from_user.first_name}*! ✨\n\n"+f"🎯 Точка безубыточности: *{fmt(cfg['tb'])} ₸/мес*\n\n"+"Система настроена и работает.\nВыбери действие 👇",parse_mode="Markdown",reply_markup=kb_main())
    else:
        await msg.answer("💎 *FUNDAMENTA*\n━━━━━━━━━━━━━━━━━━\n\n"+f"Привет, *{msg.from_user.first_name}*! 👋\n\n"+"Это Fundamenta — помощник, который поможет\nтебе наладить порядок в твоём бизнесе.\n\n"+"Следуй инструкциям и обязательно\nсмотри видео-подсказки! 🎬\n\n"+"Мы пройдём *3 простых шага*:\n\n"+"1️⃣ Запишем расходы на *себестоимость*\n    _(без чего продукт не может существовать)_\n"+"2️⃣ Запишем *операционные* расходы\n    _(+ твоя зарплата как собственника)_\n"+"3️⃣ Запишем *дополнительные* расходы\n    _(что делает бизнес лучше)_\n\n"+"После этого система рассчитает\nточку безубыточности и начнёт\nавтоматически распределять доходы! 🚀\n\n"+"━━━━━━━━━━━━━━━━━━\n"+"Готов? Начинаем!",parse_mode="Markdown")
        await start_brief(msg, state, 1)

# ━━━ /subscribe ━━━
@dp.message_handler(commands=['subscribe'], state="*")
async def cmd_subscribe(msg: types.Message, state: FSMContext):
    uid = msg.from_user.id
    sub = db_get_sub(uid)
    if sub and sub['status'] == 'active':
        await msg.answer(
            "✅ *ПОДПИСКА АКТИВНА*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"Статус: *Активна* ✅\n"
            f"С: {sub.get('started_at','—')}\n\n"
            "Все функции FUNDAMENTA доступны.\n"
            "Выбери действие 👇",
            parse_mode="Markdown", reply_markup=kb_main())
    else:
        await msg.answer(
            "💎 *ПОДПИСКА FUNDAMENTA*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Стоимость: *6 999 ₸/мес*\n"
            "Автопродление каждый месяц.\n\n"
            "*Что входит в подписку:*\n\n"
            "✅ Автоматическое распределение\n"
            "   доходов по фондам\n"
            "✅ Защита от кассовых разрывов\n"
            "✅ Контроль расходов в реальном времени\n"
            "✅ Запрет на «поедание» аренды,\n"
            "   налогов и зарплат\n"
            "✅ Прогноз наполнения фондов\n"
            "✅ Отслеживание долгов фондов\n"
            "✅ Индекс финансовой устойчивости\n"
            "✅ Сообщество предпринимателей\n"
            "   и ежемесячные воркшопы\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Оформи подписку 👇",
            parse_mode="Markdown", reply_markup=kb_subscribe())

# ━━━ /activate (admin) ━━━
@dp.message_handler(commands=['activate'], state="*")
async def cmd_activate(msg: types.Message, state: FSMContext):
    if msg.from_user.id != ADMIN_USER_ID:
        return await msg.answer("⛔ Команда доступна только администратору.")
    parts = msg.text.split()
    if len(parts) < 2:
        return await msg.answer("Использование: `/activate USER_ID`", parse_mode="Markdown")
    try:
        target_uid = int(parts[1])
    except ValueError:
        return await msg.answer("⚠️ USER_ID должен быть числом.")
    db_set_sub(target_uid, 'active', 'manual')
    await msg.answer(f"✅ Подписка активирована для user_id: {target_uid}")
    try:
        await bot.send_message(target_uid,
            "✅ *ПОДПИСКА АКТИВИРОВАНА!*\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "Администратор активировал тебе\n"
            "полный доступ к FUNDAMENTA! 💎\n\n"
            "Выбери действие 👇",
            parse_mode="Markdown", reply_markup=kb_main())
    except Exception:
        pass

# ━━━ /deactivate (admin) ━━━
@dp.message_handler(commands=['deactivate'], state="*")
async def cmd_deactivate(msg: types.Message, state: FSMContext):
    if msg.from_user.id != ADMIN_USER_ID:
        return await msg.answer("⛔ Команда доступна только администратору.")
    parts = msg.text.split()
    if len(parts) < 2:
        return await msg.answer("Использование: `/deactivate USER_ID`", parse_mode="Markdown")
    try:
        target_uid = int(parts[1])
    except ValueError:
        return await msg.answer("⚠️ USER_ID должен быть числом.")
    db_set_sub(target_uid, 'inactive')
    await msg.answer(f"❌ Подписка деактивирована для user_id: {target_uid}")

# ━━━ БРИФ ━━━
async def start_brief(msg, state, fn):
    async with state.proxy() as d:
        d['bf']=fn
        if fn==1: d['f1']=[]; d['f2']=[]; d['f3']=[]
    wait_text = "⏳ Подготавливаю первый шаг..." if fn == 1 else "⏳ Подготавливаю следующий шаг..."
    st = await thinking(msg.chat.id, wait_text)
    vid=FUND_VIDEOS.get(fn)
    if vid:
        try: await bot.send_video_note(msg.chat.id, vid)
        except Exception as e: log.warning(f"📹 Круг шаг {fn} не отправлен: {e}")
    await del_msg(st)
    await msg.answer(FUND_BRIEF_MSG[fn],parse_mode="Markdown",reply_markup=kb_cancel()); await Form.brief_items.set()

@dp.message_handler(state=Form.brief_items)
async def brief_handler(msg: types.Message, state: FSMContext):
    if msg.text=="🔙 Отмена": await state.finish(); return await msg.answer("❌ Бриф отменён.\n\nЧтобы начать заново — нажми /start",reply_markup=types.ReplyKeyboardRemove())
    if msg.text=="✅ Готово, следующий шаг": return await brief_done(msg, state)
    if msg.text=="➕ Добавить ещё": return await msg.answer("✏️ Напиши ещё расходы.\n\nФормат: `Название - сумма`\nКаждый — с новой строки.\nМожно сразу несколько!",parse_mode="Markdown",reply_markup=kb_cancel())
    new=parse_items(msg.text)
    if not new: return await msg.answer("⚠️ Не удалось распознать расходы.\n\nПожалуйста, используй формат:\n`Название - сумма`\n\nКаждый расход — с новой строки.\n\n*Пример:*\n`Аренда помещения - 1200000`\n`Зарплата педагогов - 1400000`\n`Налоги - 400000`",parse_mode="Markdown",reply_markup=kb_cancel())
    async with state.proxy() as d:
        fn=d['bf']; lst=d.get(f'f{fn}',[]); lst.extend(new); d[f'f{fn}']=lst
    txt="".join(f"  {i}. {it['name']} — {fmt(it['amount'])} ₸\n" for i,it in enumerate(lst,1))
    total=sum(it['amount'] for it in lst); n=len(new); w="карман" if n==1 else ("кармана" if n<5 else "карманов")
    await msg.answer(f"✅ Добавлено: {n} {w}!\n\n📂 *{FUND_NAMES[fn]}:*\n\n{txt}\n💰 *Итого по фонду: {fmt(total)} ₸/мес*\n\n━━━━━━━━━━━━━━━━━━\n\nЧто дальше?\n\n➕ *Добавить ещё* — если есть ещё расходы\n✅ *Готово, следующий шаг* — переходим дальше",parse_mode="Markdown",reply_markup=kb_brief_act())

async def brief_done(msg, state):
    async with state.proxy() as d: fn=d['bf']; items=d.get(f'f{fn}',[])
    if not items: return await msg.answer("⚠️ Ты ещё ничего не добавил!\n\nНапиши хотя бы одну статью расхода.\nФормат: `Название - сумма`",parse_mode="Markdown",reply_markup=kb_cancel())
    total=sum(i['amount'] for i in items)
    if fn<3:
        await msg.answer(f"👍 *{FUND_NAMES[fn]}* — заполнен!\n"+f"Итого: *{fmt(total)} ₸/мес*\n\n"+"Переходим к следующему шагу... ⏩",parse_mode="Markdown")
        await start_brief(msg, state, fn+1)
    else:
        await finish_brief(msg, state)

async def finish_brief(msg, state):
    async with state.proxy() as d: f1=d.get('f1',[]); f2=d.get('f2',[]); f3=d.get('f3',[])
    uid=msg.from_user.id
    st=await thinking(msg.chat.id,"⏳ Рассчитываю точку безубыточности\nи сохраняю настройки..."); ensure_user(uid,msg.from_user.username or "",msg.from_user.first_name)
    cfg=save_brief(uid,f1,f2,f3); await del_msg(st)
    if not cfg: await state.finish(); return await msg.answer("❌ Ошибка: сумма = 0.\nНачни заново: /start")
    try: await bot.send_video_note(msg.chat.id, VIDEO_5_FINAL)
    except Exception as e: log.warning(f"📹 Круг VIDEO_5_FINAL не отправлен: {e}")
    tb=cfg['tb']; m=cfg['margin']; r=cfg['remainder']
    def pb(items, base):
        return "".join(f"    • {i['name']} — {fmt(i['amount'])} ₸ ({round(i['amount']/base*100,1) if base>0 else 0}%)\n" for i in items)
    t1=(f"━━━━━━━━━━━━━━━━━━\n🎉 *Отлично!*\n━━━━━━━━━━━━━━━━━━\n\n*Фонды сформированы.*\n\n🎯 *Точка безубыточности:*\n    *{fmt(tb)} ₸/мес*\n\n"
        f"🏗 *Себестоимость — {cfg['pf1']}% от ТБ*\n    ({fmt(cfg['sum1'])} ₸/мес)\n{pb(f1,tb)}\n"
        f"💻 *Операционные — {cfg['pf2']}% от Маржи*\n    ({fmt(cfg['sum2'])} ₸/мес, маржа = {fmt(m)} ₸)\n{pb(f2,m)}\n"
        f"☕️ *Дополнительные — {cfg['pf3']}% от Остатка*\n    ({fmt(cfg['sum3'])} ₸/мес, остаток = {fmt(r)} ₸)\n{pb(f3,r)}")
    await msg.answer(t1,parse_mode="Markdown")
    t2=("Теперь каждое поступление денег будет\nавтоматически распределяться по фондам\nи карманам.\n\n"
        "Ты больше не работаешь\n*«из одного общего мешка»*.\n"
        "Каждая сумма имеет своё назначение.\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Теперь ты всегда видишь:\n\n"
        "  💰 сколько денег *реально доступно*\n"
        "  💸 сколько *можно потратить*\n"
        "  🛡 какие расходы *защищены*\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "*Пример:*\n\n"
        "Администратор просит аванс — 150 000 ₸.\n\n"
        "Ты открываешь карман «ЗП администраторов»\n"
        "и видишь — там 100 000 ₸.\n\n"
        "Значит:\n"
        "  ✅ ты можешь выплатить 100 000 ₸\n"
        "  ⏳ оставшиеся 50 000 ₸ — после\n"
        "     следующего поступления\n\n"
        "Ты *не трогаешь:*\n"
        "  🚫 фонд аренды\n"
        "  🚫 фонд налогов\n"
        "  🚫 фонд зарплат других сотрудников\n\n"
        "Именно так система *защищает бизнес*\n"
        "от кассовых разрывов.\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Теперь ты управляешь деньгами,\n"
        "а не реагируешь на давление расходов.\n\n"
        "*Добро пожаловать в систему\n"
        "финансового контроля.* 💎")
    await msg.answer(t2,parse_mode="Markdown")
    t3=("🔓 *АКТИВИРУЙ ПОЛНЫЙ ДОСТУП*\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Активируй систему финансового контроля\n"
        "всего за *6 999 ₸/мес* и получи\n"
        "полный доступ к FUNDAMENTA!\n\n"
        "*С полным доступом ты получишь:*\n\n"
        "✅ Автоматическое распределение каждого\n"
        "   поступления по фондам\n"
        "✅ Защиту от кассовых разрывов\n"
        "✅ Контроль расходов в реальном времени\n"
        "✅ Запрет на «поедание» аренды, налогов\n"
        "   и зарплат\n"
        "✅ Прогноз наполнения фондов на 30 дней\n"
        "✅ Отслеживание долгов фондов\n"
        "   в переходный период\n"
        "✅ Индекс финансовой устойчивости бизнеса\n\n"
        "И самое главное — *сообщество*\n"
        "*предпринимателей*, где раз в месяц\n"
        "проводятся воркшопы! 🤝\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "Ты всегда будешь видеть:\n\n"
        "  💰 сколько можно тратить\n"
        "  🛡 сколько уже защищено\n"
        "  📅 когда закроются обязательства\n"
        "  ⚠️ есть ли риск\n\n"
        "*FUNDAMENTA — это не учёт.*\n"
        "*Это система финансового контроля*\n"
        "*и предсказуемости.* 💎")
    await msg.answer(t3, parse_mode="Markdown", reply_markup=kb_subscribe())
    ilk=types.InlineKeyboardMarkup(); ilk.add(types.InlineKeyboardButton("🎬 Смотреть урок по финансам",url=YOUTUBE_LESSON_URL))
    await state.finish()
    await msg.answer("🎬 А пока — посмотри полноценный урок\nпо финансам бизнеса:",parse_mode="Markdown",reply_markup=ilk)
    try: await bot.send_video_note(msg.chat.id, VIDEO_4_DOP)
    except Exception as e: log.warning(f"📹 Круг VIDEO_4_DOP не отправлен: {e}")
    await msg.answer("Выбери действие 👇",reply_markup=kb_main())

# ━━━ ДОХОД ━━━
@dp.message_handler(lambda m: m.text=="💰 Внести доход")
async def income_start(msg: types.Message):
    if not await require_sub(msg): return
    if not db_get_config(msg.from_user.id): return await msg.answer("⚠️ Сначала заполни бриф: /start",reply_markup=kb_main())
    await msg.answer("💰 *НОВЫЙ ДОХОД*\n━━━━━━━━━━━━━━━━━━\n\nВведи сумму, которая пришла\nна счёт твоего бизнеса.\n\nЭто любые денежные средства:\nоплата клиента, перевод, наличные.\n\nТолько цифры, например: `500000`",parse_mode="Markdown",reply_markup=kb_cancel()); await Form.income_amount.set()

@dp.message_handler(state=Form.income_amount)
async def income_process(msg: types.Message, state: FSMContext):
    if msg.text=="🔙 Отмена": await state.finish(); return await msg.answer("❌ Действие отменено.",reply_markup=kb_main())
    clean=re.sub(r'[^\d]','',msg.text)
    if not clean or int(clean)<=0: return await msg.answer("⚠️ Только цифры! `500000`",parse_mode="Markdown")
    amount=int(clean); uid=msg.from_user.id
    st=await thinking(msg.chat.id,"⏳ Распределяю по фондам и карманам..."); result=distribute_income(uid,amount)
    if not result: await del_msg(st); await state.finish(); return await msg.answer("❌ Ошибка чтения настроек.\nПопробуй /start",reply_markup=kb_main())
    add1,add2,add3,bal=result
    db_add_history(uid,"ДОХОД",amount,"ВСЕ ФОНДЫ","Авто","",msg.from_user.username or str(uid))
    await del_msg(st); cfg=db_get_config(uid); tb=cfg['tb']; gap=max(0,tb-bal[3])
    text=(f"✅ *ДОХОД ПОЛУЧЕН И РАСПРЕДЕЛЁН!*\n━━━━━━━━━━━━━━━━━━\n\n"
        f"💵 *Поступление:* +{fmt(amount)} ₸\n\n"
        f"*Распределено по фондам:*\n\n"
        f"🏗 Себестоимость: +{fmt(add1)} ₸\n"
        f"💻 Операционные: +{fmt(add2)} ₸\n"
        f"☕️ Дополнительные: +{fmt(add3)} ₸\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n"
        f"*Остаток по фондам:*\n\n"
        f"🏗 Себестоимость: *{fmt(bal[0])} ₸*\n"
        f"💻 Операционные: *{fmt(bal[1])} ₸*\n"
        f"☕️ Дополнительные: *{fmt(bal[2])} ₸*\n\n"
        f"💰 *Всего в кассе: {fmt(bal[3])} ₸*\n")
    if gap>0: text+=f"\n📉 *До точки безубыточности не хватает:* {fmt(gap)} ₸"
    await state.finish(); await msg.answer(text,parse_mode="Markdown",reply_markup=kb_main())

# ━━━ РАСХОД ━━━
@dp.message_handler(lambda m: m.text=="💸 Списать расход")
async def expense_start(msg: types.Message):
    if not await require_sub(msg): return
    if not db_get_config(msg.from_user.id): return await msg.answer("⚠️ Сначала заполни бриф: /start",reply_markup=kb_main())
    await msg.answer("💸 *РАСХОДНАЯ ОПЕРАЦИЯ*\n━━━━━━━━━━━━━━━━━━\n\nУкажите сумму расхода.\nТолько цифры, например: `120000`",parse_mode="Markdown",reply_markup=kb_cancel()); await Form.expense_amount.set()

@dp.message_handler(state=Form.expense_amount)
async def expense_amt_h(msg: types.Message, state: FSMContext):
    if msg.text=="🔙 Отмена": await state.finish(); return await msg.answer("❌ Действие отменено.",reply_markup=kb_main())
    clean=re.sub(r'[^\d]','',msg.text)
    if not clean or int(clean)<=0: return await msg.answer("⚠️ Введи только цифры!\nНапример: `120000`",parse_mode="Markdown")
    async with state.proxy() as d: d['exp_amt']=int(clean)
    st=await thinking(msg.chat.id,"⏳ Загружаю остатки по фондам...")
    bal=db_get_balance(msg.from_user.id)
    await del_msg(st)
    await msg.answer(f"💸 *Сумма расхода:* {fmt(int(clean))} ₸\n\n*Остатки в фондах:*\n\n🏗 Себестоимость: {fmt(bal[0])} ₸\n💻 Операционные: {fmt(bal[1])} ₸\n☕️ Дополнительные: {fmt(bal[2])} ₸\n\nИз какого фонда списываем? 👇",parse_mode="Markdown",reply_markup=kb_funds()); await Form.expense_fund.set()

@dp.message_handler(state=Form.expense_fund)
async def expense_fund_h(msg: types.Message, state: FSMContext):
    if msg.text=="🔙 Отмена": await state.finish(); return await msg.answer("❌ Действие отменено.",reply_markup=kb_main())
    fn=parse_fund(msg.text)
    if not fn: return await msg.answer("⚠️ Выбери фонд из кнопок ниже 👇",reply_markup=kb_funds())
    st=await thinking(msg.chat.id,"⏳ Загружаю карманы...")
    pockets=db_get_pockets(msg.from_user.id,fn)
    if not pockets: await del_msg(st); await state.finish(); return await msg.answer("⚠️ В этом фонде нет карманов.\nЗаполни бриф: /start",reply_markup=kb_main())
    async with state.proxy() as d: d['exp_fn']=fn
    await del_msg(st)
    await msg.answer(f"📂 *{FUND_NAMES[fn]}*\n━━━━━━━━━━━━━━━━━━\n\nВыберите из какого кармана Вы хотите\nпровести расходную операцию?\n\nВ скобках — текущий остаток в кармане.\n\n👇 Нажмите на нужный карман:",parse_mode="Markdown",reply_markup=kb_pockets(pockets)); await Form.expense_pocket.set()

@dp.message_handler(state=Form.expense_pocket)
async def expense_pocket_h(msg: types.Message, state: FSMContext):
    uid=msg.from_user.id
    if msg.text=="🔙 Назад":
        st=await thinking(msg.chat.id,"⏳ Загружаю остатки...")
        bal=db_get_balance(uid)
        await del_msg(st)
        await msg.answer(f"*Остатки в фондах:*\n\n🏗 Себестоимость: {fmt(bal[0])} ₸\n💻 Операционные: {fmt(bal[1])} ₸\n☕️ Дополнительные: {fmt(bal[2])} ₸\n\nИз какого фонда списываем? 👇",parse_mode="Markdown",reply_markup=kb_funds()); return await Form.expense_fund.set()
    if msg.text=="🔙 Отмена": await state.finish(); return await msg.answer("❌ Действие отменено.",reply_markup=kb_main())
    async with state.proxy() as d: fn=d['exp_fn']
    pockets=db_get_pockets(uid,fn); sel=None
    for p in pockets:
        if msg.text.startswith(p['name']): sel=p; break
    if not sel: return await msg.answer("⚠️ Выбери карман из кнопок ниже 👇",reply_markup=kb_pockets(pockets))
    async with state.proxy() as d: d['exp_pocket']=sel
    await msg.answer("📝 Напиши коротко — *на что тратим?*\n\nНапример: `Оплата аренды за март`\nили `Зарплата администратору`",parse_mode="Markdown",reply_markup=kb_cancel()); await Form.expense_comment.set()

@dp.message_handler(state=Form.expense_comment)
async def expense_comment_h(msg: types.Message, state: FSMContext):
    if msg.text=="🔙 Отмена": await state.finish(); return await msg.answer("❌ Действие отменено.",reply_markup=kb_main())
    uid=msg.from_user.id; comment=msg.text
    async with state.proxy() as d: d['exp_comment']=comment; pocket=d['exp_pocket']; fn=d['exp_fn']; amt=d['exp_amt']
    pb=int(pocket['balance'])
    if amt<=pb:
        st=await thinking(msg.chat.id,"⏳ Списываю расход..."); nb=pb-amt
        db_update_pocket_balance(pocket['id'],nb); db_add_history(uid,"РАСХОД",-amt,FUND_NAMES[fn],pocket['name'],comment,msg.from_user.username or str(uid)); db_mark_dirty(uid)
        await del_msg(st); bal=db_get_balance(uid); await state.finish()
        return await msg.answer(f"✅ *РАСХОД СПИСАН!*\n━━━━━━━━━━━━━━━━━━\n\n💸 *Сумма:* -{fmt(amt)} ₸\n📂 *Фонд:* {FUND_NAMES[fn]}\n👛 *Карман:* {pocket['name']}\n💬 *Цель:* {comment}\n\n━━━━━━━━━━━━━━━━━━\n\n*Остатки в фондах:*\n\n🏗 Себестоимость: *{fmt(bal[0])} ₸*\n💻 Операционные: *{fmt(bal[1])} ₸*\n☕️ Дополнительные: *{fmt(bal[2])} ₸*\n\n💰 *Всего в кассе: {fmt(bal[3])} ₸*",parse_mode="Markdown",reply_markup=kb_main())
    shortage=amt-pb
    await msg.answer(f"⚠️ *{msg.from_user.first_name}, не хватает средств!*\n━━━━━━━━━━━━━━━━━━\n\n*Карман:* {pocket['name']}\n*Нужно:* {fmt(amt)} ₸\n*В кармане:* {fmt(pb)} ₸\n*Не хватает:* {fmt(shortage)} ₸\n\n━━━━━━━━━━━━━━━━━━\n\nВыбери что делать:",parse_mode="Markdown",reply_markup=kb_insufficient(pb,shortage)); await Form.expense_insufficient.set()

@dp.message_handler(state=Form.expense_insufficient)
async def expense_insuf_text(msg: types.Message, state: FSMContext):
    await msg.answer("👆 Пожалуйста, нажми одну из кнопок выше.")
@dp.message_handler(state=Form.expense_borrow_fund)
async def borrow_fund_text(msg: types.Message, state: FSMContext):
    await msg.answer("👆 Нажми кнопку с фондом, из которого хочешь одолжить.")
@dp.message_handler(state=Form.expense_borrow_pocket)
async def borrow_pocket_text(msg: types.Message, state: FSMContext):
    await msg.answer("👆 Нажми кнопку с карманом, из которого хочешь одолжить.")

@dp.callback_query_handler(lambda c: c.data=="exp_partial", state=Form.expense_insufficient)
async def cb_partial(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer(); uid=cb.from_user.id
    async with state.proxy() as d: pocket=d['exp_pocket']; fn=d['exp_fn']; amt=d['exp_amt']; comment=d['exp_comment']
    pb=int(pocket['balance'])
    if pb<=0: await state.finish(); return await cb.message.answer("⚠️ В кармане 0 ₸, нечего списывать.",reply_markup=kb_main())
    st=await thinking(cb.message.chat.id,"⏳ Списываю частично...")
    db_update_pocket_balance(pocket['id'],0); db_add_history(uid,"РАСХОД (частично)",-pb,FUND_NAMES[fn],pocket['name'],comment,cb.from_user.username or str(uid)); db_mark_dirty(uid)
    await del_msg(st); bal=db_get_balance(uid); rem=amt-pb; await state.finish()
    await cb.message.answer(f"✅ *ЧАСТИЧНАЯ ОПЛАТА!*\n━━━━━━━━━━━━━━━━━━\n\n💸 *Списано:* {fmt(pb)} ₸ из {fmt(amt)} ₸\n📂 *Фонд:* {FUND_NAMES[fn]}\n👛 *Карман:* {pocket['name']}\n💬 *Цель:* {comment}\n\n⏳ *Остаток к оплате:* {fmt(rem)} ₸\n   _(оплатишь после следующего поступления)_\n\n━━━━━━━━━━━━━━━━━━\n\n*Остатки в фондах:*\n\n🏗 Себестоимость: *{fmt(bal[0])} ₸*\n💻 Операционные: *{fmt(bal[1])} ₸*\n☕️ Дополнительные: *{fmt(bal[2])} ₸*\n\n💰 *Всего в кассе: {fmt(bal[3])} ₸*",parse_mode="Markdown",reply_markup=kb_main())

@dp.callback_query_handler(lambda c: c.data=="exp_borrow", state=[Form.expense_insufficient,Form.expense_borrow_pocket])
async def cb_borrow(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer(); uid=cb.from_user.id
    async with state.proxy() as d: fn=d['exp_fn']; pocket=d['exp_pocket']; amt=d['exp_amt']
    shortage=amt-int(pocket['balance'])
    kb=types.InlineKeyboardMarkup(row_width=1)
    for ofn in [1,2,3]:
        if ofn==fn: continue
        bf=db_get_balance(uid)[ofn-1]; kb.add(types.InlineKeyboardButton(f"{FUND_NAMES[ofn]} [{fmt(bf)} ₸]",callback_data=f"borrow_f{ofn}"))
    kb.add(types.InlineKeyboardButton("🔙 Отмена",callback_data="exp_postpone"))
    await cb.message.answer(f"🔄 *ОДОЛЖИТЬ У ДРУГОГО ФОНДА*\n━━━━━━━━━━━━━━━━━━\n\nНужно одолжить: *{fmt(shortage)} ₸*\n\nИз какого фонда возьмём деньги? 👇",parse_mode="Markdown",reply_markup=kb); await Form.expense_borrow_fund.set()

@dp.callback_query_handler(lambda c: c.data.startswith("borrow_f"), state=Form.expense_borrow_fund)
async def cb_borrow_fund(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer(); bfn=int(cb.data[-1])
    async with state.proxy() as d: d['borrow_fn']=bfn
    pockets=db_get_pockets(cb.from_user.id,bfn)
    if not pockets: return await cb.message.answer("⚠️ В этом фонде нет карманов.\nВыбери другой фонд.",parse_mode="Markdown")
    kb=types.InlineKeyboardMarkup(row_width=1)
    for p in pockets:
        if int(p['balance'])>0: kb.add(types.InlineKeyboardButton(f"{p['name']} [{fmt(p['balance'])} ₸]",callback_data=f"borrow_p{p['id']}"))
    kb.add(types.InlineKeyboardButton("🔙 Назад",callback_data="exp_borrow"))
    await cb.message.answer(f"📂 *{FUND_NAMES[bfn]}*\n━━━━━━━━━━━━━━━━━━\n\nИз какого кармана одолжить? 👇\n\n_(показаны только карманы с деньгами)_",parse_mode="Markdown",reply_markup=kb); await Form.expense_borrow_pocket.set()

@dp.callback_query_handler(lambda c: c.data.startswith("borrow_p"), state=Form.expense_borrow_pocket)
async def cb_borrow_pocket(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer(); bpid=int(cb.data.replace("borrow_p","")); uid=cb.from_user.id
    async with state.proxy() as d: bfn=d['borrow_fn']; fn=d['exp_fn']; amt=d['exp_amt']; pocket=d['exp_pocket']; comment=d['exp_comment']
    pockets=db_get_pockets(uid,bfn); bp=None
    for p in pockets:
        if p['id']==bpid: bp=p; break
    if not bp: return await cb.message.answer("⚠️ Карман не найден. Попробуй снова.")
    pbo=int(pocket['balance']); shortage=amt-pbo; bpb=int(bp['balance'])
    if bpb<shortage: return await cb.message.answer(f"⚠️ В кармане «{bp['name']}» только\n{fmt(bpb)} ₸, а нужно {fmt(shortage)} ₸.\n\nВыбери другой карман с бо́льшим остатком.",parse_mode="Markdown")
    st=await thinking(cb.message.chat.id,"⏳ Выполняю заимствование...")
    db_update_pocket_balance(pocket['id'],0); db_update_pocket_balance(bp['id'],bpb-shortage)
    us=cb.from_user.username or str(uid)
    db_add_history(uid,"РАСХОД",-amt,FUND_NAMES[fn],pocket['name'],comment,us)
    db_add_history(uid,"ДОЛГ",shortage,f"{FUND_NAMES[fn]} ← {FUND_NAMES[bfn]}",f"{pocket['name']} ← {bp['name']}",f"Заимствование: {comment}",us)
    db_mark_dirty(uid); await del_msg(st); bal=db_get_balance(uid); await state.finish()
    await cb.message.answer(f"✅ *РАСХОД СПИСАН С ЗАИМСТВОВАНИЕМ!*\n━━━━━━━━━━━━━━━━━━\n\n💸 *Сумма расхода:* {fmt(amt)} ₸\n💬 *Цель:* {comment}\n\n📂 Из кармана *«{pocket['name']}»*:\n   Списано {fmt(pbo)} ₸ (весь остаток)\n\n🔄 Одолжено у *«{bp['name']}»*\n   ({FUND_NAMES[bfn]}):\n   *{fmt(shortage)} ₸*\n\n━━━━━━━━━━━━━━━━━━\n\n💳 *ДОЛГ:* {FUND_NAMES[fn]} должен\n   {FUND_NAMES[bfn]} → *{fmt(shortage)} ₸*\n\n⚠️ Этот долг зафиксирован в истории.\nПри следующих поступлениях постарайся\nпокрыть его как можно скорее!\n\n━━━━━━━━━━━━━━━━━━\n\n*Остатки в фондах:*\n\n🏗 Себестоимость: *{fmt(bal[0])} ₸*\n💻 Операционные: *{fmt(bal[1])} ₸*\n☕️ Дополнительные: *{fmt(bal[2])} ₸*\n\n💰 *Всего в кассе: {fmt(bal[3])} ₸*",parse_mode="Markdown",reply_markup=kb_main())

@dp.callback_query_handler(lambda c: c.data=="exp_postpone", state=[Form.expense_insufficient,Form.expense_borrow_fund,Form.expense_borrow_pocket])
async def cb_postpone(cb: types.CallbackQuery, state: FSMContext):
    await cb.answer(); await state.finish()
    await cb.message.answer("⏳ *Платёж перенесён.*\n\nТы правильно делаешь — лучше подождать\nследующего поступления, чем залезать\nв другие фонды без необходимости.\n\nЭто и есть финансовый контроль! 💎",parse_mode="Markdown",reply_markup=kb_main())

# ━━━ БАЛАНС ━━━
@dp.message_handler(lambda m: m.text=="📊 Баланс")
async def show_bal(msg: types.Message):
    if not await require_sub(msg): return
    uid=msg.from_user.id; cfg=db_get_config(uid)
    if not cfg: return await msg.answer("⚠️ Сначала заполни бриф: /start",reply_markup=kb_main())
    st=await thinking(msg.chat.id,"⏳ Загружаю баланс...")
    bal=db_get_balance(uid); tb=cfg['tb']; total=bal[3]; t1,t2,t3=int(cfg['sum1']),int(cfg['sum2']),int(cfg['sum3'])
    rw=round(total/tb,1) if tb>0 else 0; gap=max(0,tb-total); h="🟢" if rw>=3 else "🟡" if rw>=1 else "🔴"
    text=(f"📊 *БАЛАНС ФОНДОВ*\n━━━━━━━━━━━━━━━━━━\n\n"
        f"🏗 *Себестоимость*\n   {fmt(bal[0])} ₸ из {fmt(t1)} ₸\n   {bar(bal[0],t1)}\n\n"
        f"💻 *Операционные расходы*\n   {fmt(bal[1])} ₸ из {fmt(t2)} ₸\n   {bar(bal[1],t2)}\n\n"
        f"☕️ *Дополнительные расходы*\n   {fmt(bal[2])} ₸ из {fmt(t3)} ₸\n   {bar(bal[2],t3)}\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n💰 *ВСЕГО В КАССЕ:* {fmt(total)} ₸\n\n🎯 *Точка безубыточности:* {fmt(tb)} ₸/мес\n")
    if gap>0: text+=f"📉 *Не хватает до ТБ:* {fmt(gap)} ₸\n"
    text+=f"\n{h} *Запас хода:* {rw} мес.\n   _(сколько проживёт бизнес\n   без новых поступлений)_\n"
    debts=db_get_debts(uid)
    if debts:
        text+="\n━━━━━━━━━━━━━━━━━━\n\n💳 *ДОЛГИ МЕЖДУ ФОНДАМИ:*\n\n"
        for k,v in debts.items(): text+=f"  🔄 {k}: *{fmt(v)} ₸*\n"
        text+="\n⚠️ Постарайся покрыть долги\nпри следующих поступлениях!"
    text+="\n\n━━━━━━━━━━━━━━━━━━\n💡 Нажми «📋 Подробно по фондам»\nчтобы увидеть все карманы."
    await del_msg(st)
    await msg.answer(text,parse_mode="Markdown",reply_markup=kb_main())

# ━━━ ПОДРОБНО ━━━
@dp.message_handler(lambda m: m.text=="📋 Подробно по фондам")
async def show_detail(msg: types.Message):
    if not await require_sub(msg): return
    uid=msg.from_user.id; cfg=db_get_config(uid)
    if not cfg: return await msg.answer("⚠️ Сначала заполни бриф: /start",reply_markup=kb_main())
    st=await thinking(msg.chat.id,"⏳ Загружаю данные по фондам...")
    bal=db_get_balance(uid); tb=cfg['tb']
    await del_msg(st)
    for fn in [1,2,3]:
        fs=int(cfg[f'sum{fn}']); fb=bal[fn-1]; gap=max(0,fs-fb)
        pockets=db_get_pockets(uid,fn)
        text=f"{FUND_NAMES[fn]}\n━━━━━━━━━━━━━━━━━━\n\n💰 *В фонде:* {fmt(fb)} ₸\n📋 *План на месяц:* {fmt(fs)} ₸\n"
        if gap>0: text+=f"📉 *Не хватает:* {fmt(gap)} ₸\n"
        text+=f"   {bar(fb,fs)}\n\n"
        if pockets:
            text+="*Карманы (статьи расходов):*\n\n"
            for p in pockets:
                pb_=int(p['balance']); pp_=int(p['planned']); pg_=max(0,pp_-pb_)
                text+=f"  {emo(pb_,pp_)} *{p['name']}*\n     {fmt(pb_)} ₸ из {fmt(pp_)} ₸"
                if pg_>0: text+=f" _(не хватает {fmt(pg_)} ₸)_"
                text+=f"\n     {bar(pb_,pp_)}\n\n"
        else:
            text+="  Нет карманов\n\n"
        await msg.answer(text,parse_mode="Markdown",reply_markup=kb_main())
    total=bal[3]; gap=max(0,tb-total)
    text=f"━━━━━━━━━━━━━━━━━━\n💰 *ИТОГО ВО ВСЕХ ФОНДАХ:* {fmt(total)} ₸\n🎯 *Точка безубыточности:* {fmt(tb)} ₸/мес\n"
    if gap>0: text+=f"\n📉 *До безубыточности не хватает:* {fmt(gap)} ₸"
    await msg.answer(text,parse_mode="Markdown",reply_markup=kb_main())

# ━━━ НАСТРОЙКИ ━━━
@dp.message_handler(lambda m: m.text=="⚙️ Настройки")
async def settings(msg: types.Message):
    if not await require_sub(msg): return
    await msg.answer("⚙️ *НАСТРОЙКИ*\n━━━━━━━━━━━━━━━━━━\n\nВыбери действие 👇",parse_mode="Markdown",reply_markup=kb_settings())

@dp.message_handler(lambda m: m.text=="📋 Текущие настройки")
async def show_cfg(msg: types.Message):
    if not await require_sub(msg): return
    uid=msg.from_user.id; cfg=db_get_config(uid)
    if not cfg: return await msg.answer("⚠️ Настройки не найдены.\nЗаполни бриф: /start",reply_markup=kb_settings())
    st=await thinking(msg.chat.id,"⏳ Загружаю настройки...")
    m_=cfg['margin']; r_=cfg['remainder']
    text=(f"📋 *ТЕКУЩИЕ НАСТРОЙКИ*\n━━━━━━━━━━━━━━━━━━\n\n🎯 *Точка безубыточности:*\n   {fmt(cfg['tb'])} ₸/мес\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n*Распределение доходов:*\n\n"
        f"🏗 *Себестоимость:* {cfg.get('pf1',0)}% от ТБ\n   План: {fmt(cfg.get('sum1',0))} ₸/мес\n\n"
        f"💻 *Операционные:* {cfg.get('pf2',0)}% от маржи\n   План: {fmt(cfg.get('sum2',0))} ₸/мес\n   Маржа = {fmt(m_)} ₸\n\n"
        f"☕️ *Дополнительные:* {cfg.get('pf3',0)}% от остатка\n   План: {fmt(cfg.get('sum3',0))} ₸/мес\n   Остаток = {fmt(r_)} ₸\n\n"
        f"━━━━━━━━━━━━━━━━━━\n\n")
    for fn in [1,2,3]:
        pockets=db_get_pockets(uid,fn)
        if pockets:
            text+=f"*Карманы {FUND_NAMES[fn]}:*\n"
            for p in pockets: text+=f"  • {p['name']} — {fmt(p['planned'])} ₸ ({round(p['pct'],1)}%)\n"
            text+="\n"
    text+="💡 Чтобы изменить — нажми «Заполнить заново»"
    await del_msg(st)
    await msg.answer(text,parse_mode="Markdown",reply_markup=kb_settings())

# ━━━ ДОБАВИТЬ КАРМАН ━━━
@dp.message_handler(lambda m: m.text=="➕ Добавить карман в фонд")
async def add_pocket_start(msg: types.Message):
    if not await require_sub(msg): return
    uid=msg.from_user.id; cfg=db_get_config(uid)
    if not cfg: return await msg.answer("⚠️ Сначала заполни бриф: /start",reply_markup=kb_settings())
    st=await thinking(msg.chat.id,"⏳ Загружаю список фондов...")
    text="➕ *ДОБАВИТЬ КАРМАН В ФОНД*\n━━━━━━━━━━━━━━━━━━\n\nСейчас в твоих фондах:\n\n"
    for fn in [1,2,3]:
        pockets=db_get_pockets(uid,fn); text+=f"*{FUND_NAMES[fn]}:*\n"
        if pockets:
            for p in pockets: text+=f"  • {p['name']} — {fmt(p['planned'])} ₸\n"
        else: text+="  (пусто)\n"
        text+="\n"
    text+="В какой фонд добавить новый карман? 👇"
    await del_msg(st)
    await msg.answer(text,parse_mode="Markdown",reply_markup=kb_funds()); await Form.add_pocket_fund.set()

@dp.message_handler(state=Form.add_pocket_fund)
async def add_pocket_fund_h(msg: types.Message, state: FSMContext):
    if msg.text=="🔙 Отмена": await state.finish(); return await msg.answer("❌ Действие отменено.",reply_markup=kb_settings())
    fn=parse_fund(msg.text)
    if not fn: return await msg.answer("⚠️ Выбери фонд из кнопок ниже 👇",reply_markup=kb_funds())
    async with state.proxy() as d: d['add_fn']=fn; d['add_items']=[]
    pockets=db_get_pockets(msg.from_user.id,fn)
    ex=""
    if pockets:
        ex="*Уже есть:*\n"
        for p in pockets: ex+=f"  • {p['name']} — {fmt(p['planned'])} ₸\n"
        ex+="\n"
    await msg.answer(f"📂 *{FUND_NAMES[fn]}*\n━━━━━━━━━━━━━━━━━━\n\n{ex}✏️ Напиши новые карманы:\n`Название - сумма`\n\nКаждый — с новой строки.\nСтарые карманы останутся на месте!",parse_mode="Markdown",reply_markup=kb_cancel()); await Form.add_pocket_items.set()

@dp.message_handler(state=Form.add_pocket_items)
async def add_pocket_items_h(msg: types.Message, state: FSMContext):
    uid=msg.from_user.id
    if msg.text=="🔙 Отмена": await state.finish(); return await msg.answer("❌ Действие отменено.",reply_markup=kb_settings())
    if msg.text=="✅ Сохранить":
        async with state.proxy() as d: fn=d['add_fn']; items=d.get('add_items',[])
        if not items: return await msg.answer("⚠️ Ты ещё ничего не добавил!\nНапиши: `Название - сумма`",parse_mode="Markdown")
        st=await thinking(msg.chat.id,"⏳ Пересчитываю проценты и сохраняю..."); cfg=add_pockets_logic(uid,fn,items); await del_msg(st)
        if not cfg: await state.finish(); return await msg.answer("❌ Ошибка сохранения.\nПопробуй /start",reply_markup=kb_main())
        txt="".join(f"  • {it['name']} — {fmt(it['amount'])} ₸\n" for it in items)
        await state.finish(); return await msg.answer(f"✅ *КАРМАНЫ ДОБАВЛЕНЫ!*\n━━━━━━━━━━━━━━━━━━\n\n📂 *{FUND_NAMES[fn]}*\n\nНовые карманы:\n{txt}\n🎯 *Новая точка безубыточности:* {fmt(cfg['tb'])} ₸/мес\n\nВсе проценты пересчитаны.\nБалансы существующих карманов сохранены! 👍",parse_mode="Markdown",reply_markup=kb_main())
    if msg.text=="➕ Добавить ещё": return await msg.answer("✏️ Напиши ещё карманы:\n`Название - сумма`",parse_mode="Markdown",reply_markup=kb_cancel())
    new=parse_items(msg.text)
    if not new: return await msg.answer("⚠️ Не удалось распознать.\n\nФормат: `Название - сумма`\n\n*Пример:*\n`Новый сотрудник - 250000`\n`Доп. реклама - 100000`",parse_mode="Markdown",reply_markup=kb_cancel())
    async with state.proxy() as d: fn=d['add_fn']; lst=d.get('add_items',[]); lst.extend(new); d['add_items']=lst
    txt="".join(f"  {i}. {it['name']} — {fmt(it['amount'])} ₸\n" for i,it in enumerate(lst,1))
    n=len(new); w="карман" if n==1 else ("кармана" if n<5 else "карманов")
    await msg.answer(f"✅ Добавлено: {n} {w}!\n\nНовые карманы для *{FUND_NAMES[fn]}:*\n\n{txt}\n━━━━━━━━━━━━━━━━━━\n\n➕ *Добавить ещё* — если есть ещё карманы\n✅ *Сохранить* — пересчитать проценты и сохранить",parse_mode="Markdown",reply_markup=kb_save())

# ━━━ ПРОЧЕЕ ━━━
@dp.message_handler(lambda m: m.text=="🔄 Заполнить заново")
async def reset(msg: types.Message, state: FSMContext):
    if not await require_sub(msg): return
    cfg=db_get_config(msg.from_user.id); tb_s=fmt(cfg['tb']) if cfg else "Не задано"
    await msg.answer("⚠️ *ВНИМАНИЕ!*\n━━━━━━━━━━━━━━━━━━\n\n"+f"Текущая ТБ: *{tb_s} ₸*\n\n"+"*Что произойдёт:*\n🔄 Все статьи будут записаны заново\n🔄 Балансы обнулятся\n🔄 Новые поступления пойдут по новым %\n\nНачинаем заполнение заново...",parse_mode="Markdown")
    await start_brief(msg, state, 1)

@dp.message_handler(lambda m: m.text=="🔙 Главное меню")
async def back(msg: types.Message):
    await msg.answer("Главное меню 👇",reply_markup=kb_main())

@dp.message_handler(lambda m: m.text=="🔗 Таблица")
async def sheet_link(msg: types.Message):
    if not await require_sub(msg): return
    u=db_get_user(msg.from_user.id)
    if not u or not u.get('sheet_id'): return await msg.answer("⚠️ Сначала заполни бриф: /start")
    url=f"https://docs.google.com/spreadsheets/d/{u['sheet_id']}"
    kb=types.InlineKeyboardMarkup(); kb.add(types.InlineKeyboardButton("📂 Открыть мою Google Таблицу",url=url))
    await msg.answer("📊 *ТВОЯ ПЕРСОНАЛЬНАЯ ТАБЛИЦА*\n━━━━━━━━━━━━━━━━━━\n\nУ тебя *своя личная* таблица!\nВсе данные хранятся в Google Sheets.\nКаждый фонд — на отдельном листе.\n\n*Листы в таблице:*\n\n  ⚙️ Настройки — ТБ, маржа, проценты\n  🏗 Фонд 1 — карманы себестоимости\n  💻 Фонд 2 — операционные карманы\n  ☕ Фонд 3 — дополнительные карманы\n  💰 Баланс — общий обзор фондов\n  📜 История — все операции\n\n👇 Нажми чтобы открыть:",parse_mode="Markdown",reply_markup=kb)

@dp.message_handler(lambda m: m.text in ["🔙 Отмена","🔙 Назад"], state="*")
async def cancel(msg: types.Message, state: FSMContext):
    if await state.get_state(): await state.finish()
    await msg.answer("❌ Действие отменено.",reply_markup=kb_main())

@dp.message_handler(content_types=['video_note'])
async def on_video_note(msg: types.Message):
    """Получить file_id круга для этого бота — отправь круг боту, скопируй ответ в main.py."""
    fid = msg.video_note.file_id
    await msg.answer(
        f"📹 *file_id* этого круга для *этого бота*:\n\n`{fid}`\n\n"
        "Скопируй и подставь в main.py в константу:\n"
        "VIDEO_1_INTRO / VIDEO_2_SEBES / VIDEO_3_OPER / VIDEO_4_DOP / VIDEO_5_FINAL",
        parse_mode="Markdown"
    )

@dp.message_handler()
async def unknown(msg: types.Message):
    await msg.answer("🤔 Не понял команду.\n\nИспользуй кнопки меню 👇\nИли напиши /start чтобы начать.",reply_markup=kb_main())

# ━━━ УВЕДОМЛЕНИЯ ━━━
async def send_morning():
    for u in db_get_active_subscribers():
        if not u['user_id']: continue
        name = u['first_name'] or 'Друг'
        try: await bot.send_message(u['user_id'],f"🌅 *Доброе утро, {name}!*\n━━━━━━━━━━━━━━━━━━\n\nУдели 10 секунд.\nЗакрой глаза и скажи себе:\n\n💭 _«Этот бизнес я делаю, чтобы\nделать свою жизнь и жизнь\nсвоих близких лучше и ярче.\n\nВсё в моих руках.\nУ меня всё получится!\nАминь!»_\n\n━━━━━━━━━━━━━━━━━━\n💪 Сегодня будет отличный день!",parse_mode="Markdown")
        except: pass
        await asyncio.sleep(0.1)

async def send_evening():
    for u in db_get_active_subscribers():
        if not u['user_id']: continue
        name = u['first_name'] or 'Друг'
        try: await bot.send_message(u['user_id'],f"🌙 *{name}, день подходит к концу!*\n━━━━━━━━━━━━━━━━━━\n\nНе забудь внести поступления\nза сегодня! 💰\n\nКаждое внесение — это шаг\nк наполнению твоих фондов\nи финансовой устойчивости бизнеса.\n\nНажми *«💰 Внести доход»* 👇",parse_mode="Markdown")
        except: pass
        await asyncio.sleep(0.1)

async def notif_scheduler():
    lm=None; le=None
    while True:
        try:
            now=datetime.now(ALMATY_TZ); today=now.date()
            if now.hour==9 and lm!=today: lm=today; await send_morning()
            if now.hour==21 and le!=today: le=today; await send_evening()
        except Exception as e: log.error(f"🔔 {e}")
        await asyncio.sleep(30)

async def on_startup(dp_instance):
    asyncio.create_task(sync_loop()); asyncio.create_task(notif_scheduler())
    if TRIBUTE_API_KEY:
        asyncio.create_task(start_webhook_server())
    else:
        log.warning("⚠️ TRIBUTE_API_KEY не задан — webhook-сервер не запущен")
    log.info("🔄 Sync + 🔔 Notifications active")

if __name__ == '__main__':
    db_init()
    log.info("━━━━━━━━━━━━━━━━━━")
    log.info("💎 FUNDAMENTA v4")
    log.info("🗄 SQLite + Sheets Sync")
    log.info("🚀 Starting...")
    log.info("━━━━━━━━━━━━━━━━━━")
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)