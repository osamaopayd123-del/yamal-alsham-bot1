import os, sqlite3, logging, secrets
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters

TOKEN = os.environ["BOT_TOKEN"]
CHANNEL = os.getenv("CHANNEL_USERNAME", "@YaMalAlShamExchange")
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()}
REFERRAL_REWARD_SYP = 5
DB = os.getenv("DB_PATH", "yam_alsham.sqlite3")
FOOTER = "\n\nأسامة أبو إسلام الحمداني\nيا مال الشام لتحويل العملات"

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("yamalsham")

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(
          user_id INTEGER PRIMARY KEY, phone TEXT UNIQUE, verified INTEGER DEFAULT 0,
          referrer INTEGER, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS balances(
          user_id INTEGER, currency TEXT, amount REAL NOT NULL DEFAULT 0,
          PRIMARY KEY(user_id,currency)
        );
        CREATE TABLE IF NOT EXISTS rates(
          base TEXT, quote TEXT, rate REAL NOT NULL, updated_by INTEGER, updated_at TEXT,
          PRIMARY KEY(base,quote)
        );
        CREATE TABLE IF NOT EXISTS transactions(
          id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, currency TEXT,
          gross REAL, fee REAL, net REAL, status TEXT, note TEXT, created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS referrals(
          invited_id INTEGER PRIMARY KEY, referrer_id INTEGER, reward REAL DEFAULT 0,
          status TEXT DEFAULT 'pending', created_at TEXT
        );
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
        """)
        for cur in ("SYP","USD","EUR","TRY","SYRIATEL","MTN"):
            c.execute("INSERT OR IGNORE INTO balances(user_id,currency,amount) VALUES(0,?,0)", (cur,))

def now():
    return datetime.now(timezone.utc).isoformat()

def is_admin(uid): return uid in ADMIN_IDS

async def subscribed(context, uid):
    try:
        m = await context.bot.get_chat_member(CHANNEL, uid)
        return m.status in ("member","administrator","creator")
    except Exception:
        return False

def main_keyboard():
    return InlineKeyboardMarkup([
      [InlineKeyboardButton("💱 تحويل العملات", callback_data="exchange"),
       InlineKeyboardButton("📊 أسعار الصرف", callback_data="rates")],
      [InlineKeyboardButton("💰 إيداع", callback_data="deposit"),
       InlineKeyboardButton("💸 سحب", callback_data="withdraw")],
      [InlineKeyboardButton("👛 رصيدي", callback_data="balance"),
       InlineKeyboardButton("📜 سجل العمليات", callback_data="history")],
      [InlineKeyboardButton("🎁 الإحالات", callback_data="referrals"),
       InlineKeyboardButton("☎️ الدعم", callback_data="support")]
    ])

async def gate(update, context):
    uid = update.effective_user.id
    if not await subscribed(context, uid):
        kb = InlineKeyboardMarkup([
          [InlineKeyboardButton("📢 الاشتراك بالقناة", url=f"https://t.me/{CHANNEL.lstrip('@')}")],
          [InlineKeyboardButton("✅ تحقق من الاشتراك", callback_data="checksub")]
        ])
        await update.effective_message.reply_text("أهلاً بك في يا مال الشام.\nيرجى الاشتراك بالقناة أولاً ثم الضغط على تحقق.", reply_markup=kb)
        return False
    return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ref = None
    if context.args and context.args[0].isdigit():
        candidate = int(context.args[0])
        if candidate != uid: ref = candidate
    with db() as c:
        c.execute("INSERT OR IGNORE INTO users(user_id,referrer,created_at) VALUES(?,?,?)", (uid,ref,now()))
        if ref:
            c.execute("INSERT OR IGNORE INTO referrals(invited_id,referrer_id,created_at) VALUES(?,?,?)", (uid,ref,now()))
    if not await gate(update, context): return
    await update.message.reply_text("أهلاً بك في *يا مال الشام لتحويل العملات* 💱\nاختر الخدمة المطلوبة:" + FOOTER, reply_markup=main_keyboard(), parse_mode="Markdown")

async def contact_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    contact = update.message.contact
    uid = update.effective_user.id
    if contact.user_id != uid:
        await update.message.reply_text("يرجى مشاركة رقم هاتفك أنت عبر زر مشاركة جهة الاتصال.")
        return
    phone = contact.phone_number.strip()
    try:
        with db() as c:
            c.execute("UPDATE users SET phone=?, verified=1 WHERE user_id=?", (phone,uid))
            row = c.execute("SELECT referrer FROM users WHERE user_id=?", (uid,)).fetchone()
            if row and row["referrer"]:
                c.execute("INSERT OR IGNORE INTO referrals(invited_id,referrer_id,created_at) VALUES(?,?,?)",(uid,row["referrer"],now()))
        await update.message.reply_text("تم توثيق رقمك بنجاح. ستُراجع الإحالة لمنع التكرار.")
    except sqlite3.IntegrityError:
        await update.message.reply_text("هذا الرقم موثق مسبقاً في حساب آخر. تواصل مع الدعم إذا كان هناك خطأ.")

async def button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = q.from_user.id
    if q.data == "checksub":
        if await subscribed(context,uid):
            await q.edit_message_text("تم التحقق من اشتراكك ✅\nأرسل /start لفتح القائمة.")
        else: await q.answer("لم يظهر اشتراكك بعد. اشترك ثم أعد المحاولة.", show_alert=True)
        return
    if not await subscribed(context,uid):
        await q.edit_message_text("يجب الاشتراك بالقناة أولاً. أرسل /start.")
        return
    if q.data == "balance":
        with db() as c:
            rows=c.execute("SELECT currency,amount FROM balances WHERE user_id=? ORDER BY currency",(uid,)).fetchall()
        text="👛 *أرصدتك الحالية*\n" + "\n".join(f"{r['currency']}: {r['amount']:,.2f}" for r in rows)
        await q.edit_message_text(text+FOOTER, parse_mode="Markdown", reply_markup=main_keyboard())
    elif q.data == "rates":
        with db() as c: rows=c.execute("SELECT base,quote,rate,updated_at FROM rates ORDER BY base,quote").fetchall()
        text="📊 *أسعار الصرف اليدوية*\n"
        text += "\n".join(f"1 {r['base']} = {r['rate']:,.4f} {r['quote']}" for r in rows) or "لم تُضف أسعار بعد."
        await q.edit_message_text(text+FOOTER, parse_mode="Markdown", reply_markup=main_keyboard())
    elif q.data in ("deposit","withdraw"):
        context.user_data["pending_kind"]=q.data
        await q.edit_message_text("أرسل المبلغ والعملة والطريقة في رسالة واحدة.\nمثال: 100 USD - شام كاش\nسيُسجل الطلب بانتظار مراجعة الإدارة، ولا يُضاف أي رصيد تلقائياً.")
    elif q.data == "exchange":
        await q.edit_message_text("التحويل متاح بعد إدخال أسعار الصرف واعتمادها من الإدارة. تواصل مع الدعم أو راجع الأسعار.", reply_markup=main_keyboard())
    elif q.data == "history":
        with db() as c: rows=c.execute("SELECT id,kind,currency,gross,fee,net,status,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT 15",(uid,)).fetchall()
        text="📜 *آخر العمليات*\n" + ("\n".join(f"#{r['id']} {r['kind']} {r['gross']} {r['currency']} | رسم {r['fee']} | {r['status']}" for r in rows) or "لا توجد عمليات.")
        await q.edit_message_text(text+FOOTER, parse_mode="Markdown", reply_markup=main_keyboard())
    elif q.data == "referrals":
        with db() as c:
            n=c.execute("SELECT COUNT(*) n FROM referrals WHERE referrer_id=?",(uid,)).fetchone()["n"]
            earned=c.execute("SELECT COALESCE(SUM(reward),0) n FROM referrals WHERE referrer_id=? AND status='paid'",(uid,)).fetchone()["n"]
        me=await context.bot.get_me()
        await q.edit_message_text(f"🎁 رابط دعوتك:\nhttps://t.me/{me.username}?start={uid}\nالإحالات المسجلة: {n}\nالمكافآت المصروفة: {earned} SYP\nالمكافأة 5 ليرات سورية بعد التحقق وموافقة الإدارة."+FOOTER, reply_markup=main_keyboard())
    elif q.data == "support":
        await q.edit_message_text("للدعم: أرسل رسالتك هنا وسيتم تحويلها للإدارة عند تفعيل وكلاء الدعم."+FOOTER, reply_markup=main_keyboard())

async def request_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kind=context.user_data.get("pending_kind")
    if not kind: return
    uid=update.effective_user.id
    raw=update.message.text.strip()
    import re
    m=re.match(r"^([0-9]+(?:[.,][0-9]+)?)\s+(SYP|USD|EUR|TRY|SYRIATEL|MTN)\s*[-،]?\s*(.*)$",raw,re.I)
    if not m:
        await update.message.reply_text("صيغة غير واضحة. مثال: 100 USD - شام كاش")
        return
    gross=float(m.group(1).replace(",",".")); cur=m.group(2).upper(); note=m.group(3)
    if gross<=0:
        await update.message.reply_text("المبلغ يجب أن يكون أكبر من صفر."); return
    fee=round(gross*0.02,8); net=round(gross-fee,8)
    with db() as c:
        curid=c.execute("INSERT INTO transactions(user_id,kind,currency,gross,fee,net,status,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
          (uid,kind,cur,gross,fee,net,"pending",note,now())).lastrowid
    context.user_data.pop("pending_kind",None)
    await update.message.reply_text(f"تم تسجيل طلبك رقم #{curid} بانتظار مراجعة الإدارة.\nالمبلغ: {gross:g} {cur}\nالعمولة 2%: {fee:g} {cur}\nالصافي المتوقع: {net:g} {cur}\nلا يعتبر الطلب منفذاً قبل تأكيد الإدارة."+FOOTER)
    for aid in ADMIN_IDS:
        try: await context.bot.send_message(aid,f"طلب {kind} جديد #{curid}\nالمستخدم: {uid}\nالمبلغ: {gross:g} {cur}\nالرسوم: {fee:g}\nالتفاصيل: {note}\nللمراجعة: /review {curid}")
        except Exception: pass

async def admin_setrate(update, context):
    if not is_admin(update.effective_user.id): return
    try:
        base,quote,rate=context.args[0].upper(),context.args[1].upper(),float(context.args[2])
        if rate<=0: raise ValueError()
        with db() as c: c.execute("INSERT INTO rates VALUES(?,?,?,?,?) ON CONFLICT(base,quote) DO UPDATE SET rate=excluded.rate,updated_by=excluded.updated_by,updated_at=excluded.updated_at",(base,quote,rate,update.effective_user.id,now()))
        await update.message.reply_text(f"تم تحديث السعر: 1 {base} = {rate} {quote}")
    except Exception:
        await update.message.reply_text("الاستخدام: /setrate USD SYP 15000")

async def review(update, context):
    if not is_admin(update.effective_user.id): return
    try:
        tid=int(context.args[0])
        with db() as c: r=c.execute("SELECT * FROM transactions WHERE id=?",(tid,)).fetchone()
        if not r: raise ValueError()
        await update.message.reply_text(f"الطلب #{tid}\nالمستخدم {r['user_id']}\n{r['kind']} {r['gross']} {r['currency']}\nالعمولة {r['fee']}، الصافي {r['net']}\nللاعتماد: /approve {tid}\nللرفض: /reject {tid}")
    except Exception: await update.message.reply_text("الاستخدام: /review رقم_الطلب")

async def approve(update, context):
    if not is_admin(update.effective_user.id): return
    try:
        tid=int(context.args[0])
        with db() as c:
            r=c.execute("SELECT * FROM transactions WHERE id=? AND status='pending'",(tid,)).fetchone()
            if not r: raise ValueError()
            # deposit credits net; withdrawal debits gross, with insufficient-balance check
            if r["kind"]=="deposit":
                c.execute("INSERT INTO balances(user_id,currency,amount) VALUES(?,?,?) ON CONFLICT(user_id,currency) DO UPDATE SET amount=amount+excluded.amount",(r["user_id"],r["currency"],r["net"]))
            else:
                b=c.execute("SELECT amount FROM balances WHERE user_id=? AND currency=?",(r["user_id"],r["currency"])).fetchone()
                if not b or b["amount"] < r["gross"]: raise ValueError("رصيد غير كافٍ")
                c.execute("UPDATE balances SET amount=amount-? WHERE user_id=? AND currency=?",(r["gross"],r["user_id"],r["currency"]))
            c.execute("UPDATE transactions SET status='approved' WHERE id=?",(tid,))
        await update.message.reply_text(f"تم اعتماد الطلب #{tid}.")
        await context.bot.send_message(r["user_id"],f"تم اعتماد طلبك #{tid}.\nالعملية: {r['kind']}\nالصافي: {r['net']} {r['currency']}"+FOOTER)
    except Exception as e: await update.message.reply_text(f"تعذر الاعتماد: {e}")

async def reject(update, context):
    if not is_admin(update.effective_user.id): return
    try:
        tid=int(context.args[0])
        with db() as c:
            r=c.execute("SELECT user_id FROM transactions WHERE id=? AND status='pending'",(tid,)).fetchone()
            if not r: raise ValueError()
            c.execute("UPDATE transactions SET status='rejected' WHERE id=?",(tid,))
        await update.message.reply_text(f"تم رفض الطلب #{tid}.")
        await context.bot.send_message(r["user_id"],f"تم رفض طلبك #{tid}."+FOOTER)
    except Exception: await update.message.reply_text("تعذر رفض الطلب. تحقق من رقم الطلب.")

async def admin_help(update, context):
    if is_admin(update.effective_user.id):
        await update.message.reply_text("أوامر الإدارة:\n/setrate USD SYP 15000\n/review رقم\n/approve رقم\n/reject رقم")

def main():
    init_db()
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("setrate",admin_setrate))
    app.add_handler(CommandHandler("review",review))
    app.add_handler(CommandHandler("approve",approve))
    app.add_handler(CommandHandler("reject",reject))
    app.add_handler(CommandHandler("admin",admin_help))
    app.add_handler(CallbackQueryHandler(button))
    app.add_handler(MessageHandler(filters.CONTACT,contact_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,request_text))
    app.run_polling()

if __name__=="__main__": main()
