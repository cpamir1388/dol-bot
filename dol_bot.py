from balebale import Bot, Dispatcher, Types
from balebale.Filters import Command
import sqlite3
import random
from datetime import datetime, timedelta

API_TOKEN = "TOKEN_INJAST"

bot = Bot(API_TOKEN)
dp = Dispatcher(bot)

DEFAULT_TIME = '2000-01-01 00:00:00'
TIME_FMT = '%Y-%m-%d %H:%M:%S'
GROW_COOLDOWN = 24 * 3600
DAILY_COOLDOWN = 24 * 3600
STEAL_COOLDOWN = 12 * 3600
SEASON_LENGTH_DAYS = 30

# ──────────────────────────────────────────────
#  پایگاه داده
# ──────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect('dol.db')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute(f'''CREATE TABLE IF NOT EXISTS users (
        user_id TEXT,
        group_id TEXT,
        username TEXT,
        size INTEGER DEFAULT 10,
        last_grow TEXT DEFAULT '{DEFAULT_TIME}',
        coins INTEGER DEFAULT 0,
        last_daily TEXT DEFAULT '{DEFAULT_TIME}',
        last_steal TEXT DEFAULT '{DEFAULT_TIME}',
        pvp_wins INTEGER DEFAULT 0,
        pvp_losses INTEGER DEFAULT 0,
        win_streak INTEGER DEFAULT 0,
        pill_until TEXT DEFAULT '{DEFAULT_TIME}',
        insurance INTEGER DEFAULT 0,
        shield_until TEXT DEFAULT '{DEFAULT_TIME}',
        achievements TEXT DEFAULT '',
        history TEXT DEFAULT '',
        PRIMARY KEY (user_id, group_id)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS duels (
        duel_id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id TEXT,
        challenger_id TEXT,
        challenger_name TEXT,
        target_id TEXT,
        target_name TEXT,
        amount INTEGER,
        status TEXT DEFAULT 'pending',
        created_at TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS seasons (
        group_id TEXT PRIMARY KEY,
        season_number INTEGER DEFAULT 1,
        start_date TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS season_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_id TEXT,
        season_number INTEGER,
        winner_username TEXT,
        winner_size INTEGER,
        ended_at TEXT
    )''')

    conn.commit()
    conn.close()


def get_user(user_id, group_id, username):
    conn = get_conn()
    c = conn.cursor()
    c.execute('INSERT OR IGNORE INTO users (user_id, group_id, username) VALUES (?, ?, ?)',
              (user_id, group_id, username))
    c.execute('UPDATE users SET username=? WHERE user_id=? AND group_id=?',
              (username, user_id, group_id))
    conn.commit()
    c.execute('SELECT * FROM users WHERE user_id=? AND group_id=?', (user_id, group_id))
    user = c.fetchone()
    conn.close()
    return user


def get_user_by_username(group_id, username):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM users WHERE group_id=? AND username=? COLLATE NOCASE',
              (group_id, username))
    user = c.fetchone()
    conn.close()
    return user


def update_user(user_id, group_id, **kwargs):
    if not kwargs:
        return
    conn = get_conn()
    c = conn.cursor()
    fields = ', '.join(f'{k}=?' for k in kwargs)
    values = list(kwargs.values()) + [user_id, group_id]
    c.execute(f'UPDATE users SET {fields} WHERE user_id=? AND group_id=?', values)
    conn.commit()
    conn.close()


def get_top(group_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT username, size FROM users WHERE group_id=? ORDER BY size DESC LIMIT 10',
              (group_id,))
    top = c.fetchall()
    conn.close()
    return top


# ──────────────────────────────────────────────
#  ابزارهای نمایش
# ──────────────────────────────────────────────

TITLES = [
    (0, 5, "🍼 نوزاد"),
    (5, 15, "🌱 نهال"),
    (15, 30, "😎 معمولی"),
    (30, 50, "💪 باتجربه"),
    (50, 80, "🔥 حرفه‌ای"),
    (80, 120, "👑 استاد"),
    (120, 200, "🐉 افسانه"),
    (200, float('inf'), "🌌 خداگونه"),
]


def get_title(size):
    for lo, hi, title in TITLES:
        if lo <= size < hi:
            return title
    return TITLES[-1][2]


def progress_bar(elapsed_seconds, total_seconds, length=10):
    percent = max(0, min(100, int(100 * elapsed_seconds / total_seconds)))
    filled = max(0, min(length, int(length * percent / 100)))
    return '🟩' * filled + '⬜' * (length - filled) + f' {percent}٪'


def append_history(history_str, change):
    changes = history_str.split(',') if history_str else []
    changes.append(str(change))
    changes = changes[-10:]
    return ','.join(changes)


def history_bar(history_str):
    if not history_str:
        return "هنوز رشدی ثبت نشده 🤷"
    changes = [int(x) for x in history_str.split(',') if x != '']
    bar = ''
    for ch in changes:
        if ch > 0:
            bar += '🟢'
        elif ch < 0:
            bar += '🔴'
        else:
            bar += '⚪'
    return bar


def parse_amount(text, max_size):
    if text in ('all', 'All', 'ALL', 'همه'):
        return max(1, max_size - 1)
    try:
        val = int(text)
        if val <= 0:
            return None
        return val
    except ValueError:
        return None


# ──────────────────────────────────────────────
#  آیتم‌های فروشگاه
# ──────────────────────────────────────────────

SHOP_ITEMS = {
    'pill': {
        'name': '💊 قرص رشد',
        'price': 50,
        'desc': 'به مدت ۲۴ ساعت بازه رشد روزانه بهتر می‌شه',
    },
    'insurance': {
        'name': '🛡 بیمه شکست',
        'price': 80,
        'desc': 'ضرر شکست بعدی در /pvp نصف می‌شه',
    },
    'shield': {
        'name': '🔒 سپر ضد دزدی',
        'price': 60,
        'desc': 'به مدت ۲۴ ساعت در برابر /steal محافظت می‌کنی',
    },
}


# ──────────────────────────────────────────────
#  مدال‌ها / آچیومنت‌ها
# ──────────────────────────────────────────────

ACHIEVEMENTS = {
    'first_grow': ('🌱 اولین رشد', 'اولین بار /grow رو زدی'),
    'size_50': ('🏅 نیم‌متری', 'سایز به ۵۰ سانتی‌متر رسید'),
    'size_100': ('💯 متری', 'سایز به ۱۰۰ سانتی‌متر رسید'),
    'size_200': ('🐉 افسانه‌ای', 'سایز به ۲۰۰ سانتی‌متر رسید'),
    'first_win': ('⚔️ اولین برد', 'اولین برد رو در نبرد گرفتی'),
    'streak_5': ('🔥 رگبار برد', '۵ برد متوالی در نبرد'),
    'jackpot': ('🎰 جکپات‌باز', 'جکپات رو در /grow زدی'),
    'rich_100': ('💰 پولدار', 'به ۱۰۰ سکه رسیدی'),
    'rich_500': ('💎 میلیاردر', 'به ۵۰۰ سکه رسیدی'),
    'champion': ('🏆 قهرمان فصل', 'قهرمان یک فصل کامل شدی'),
}


def check_achievements(user):
    unlocked = set(user['achievements'].split(',')) if user['achievements'] else set()
    new = []

    checks = [
        ('first_grow', user['last_grow'] != DEFAULT_TIME),
        ('size_50', user['size'] >= 50),
        ('size_100', user['size'] >= 100),
        ('size_200', user['size'] >= 200),
        ('first_win', user['pvp_wins'] >= 1),
        ('streak_5', user['win_streak'] >= 5),
        ('rich_100', user['coins'] >= 100),
        ('rich_500', user['coins'] >= 500),
    ]

    for key, condition in checks:
        if condition and key not in unlocked:
            unlocked.add(key)
            new.append(key)

    if new:
        update_user(user['user_id'], user['group_id'], achievements=','.join(unlocked))

    return new


def achievement_announcement(new_ach):
    if not new_ach:
        return ""
    lines = ["", "━━━━━━━━━━━━━━━", "🎉 مدال جدید گرفتی! 🎉"]
    for key in new_ach:
        name, desc = ACHIEVEMENTS[key]
        lines.append(f"{name} — {desc}")
    return "\n".join(lines)


def unlock_special(user, key):
    unlocked = set(user['achievements'].split(',')) if user['achievements'] else set()
    if key not in unlocked:
        unlocked.add(key)
        update_user(user['user_id'], user['group_id'], achievements=','.join(unlocked))
        return True
    return False


# ──────────────────────────────────────────────
#  سیستم فصل (Season)
# ──────────────────────────────────────────────

def check_season(group_id):
    """اگر فصل وجود نداشته باشه می‌سازه. اگه زمانش تموم شده باشه ریست می‌کنه
    و (یوزرنیم قهرمان، سایز قهرمان) رو برمی‌گردونه. در غیر این صورت None."""
    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM seasons WHERE group_id=?', (group_id,))
    season = c.fetchone()
    now = datetime.now()

    if not season:
        c.execute('INSERT INTO seasons (group_id, season_number, start_date) VALUES (?, 1, ?)',
                  (group_id, now.strftime(TIME_FMT)))
        conn.commit()
        conn.close()
        return None

    start = datetime.strptime(season['start_date'], TIME_FMT)
    if now - start < timedelta(days=SEASON_LENGTH_DAYS):
        conn.close()
        return None

    c.execute('SELECT user_id, username, size, achievements FROM users WHERE group_id=? ORDER BY size DESC LIMIT 1',
              (group_id,))
    winner = c.fetchone()

    result = None
    if winner:
        c.execute('''INSERT INTO season_history
            (group_id, season_number, winner_username, winner_size, ended_at)
            VALUES (?, ?, ?, ?, ?)''',
                  (group_id, season['season_number'], winner['username'], winner['size'],
                   now.strftime(TIME_FMT)))

        ach = set(winner['achievements'].split(',')) if winner['achievements'] else set()
        ach.add('champion')
        c.execute('UPDATE users SET achievements=? WHERE user_id=? AND group_id=?',
                  (','.join(ach), winner['user_id'], group_id))

        result = (winner['username'], winner['size'])

    c.execute('UPDATE users SET size=10, history="" WHERE group_id=?', (group_id,))
    c.execute('UPDATE seasons SET season_number=season_number+1, start_date=? WHERE group_id=?',
              (now.strftime(TIME_FMT), group_id))

    conn.commit()
    conn.close()
    return result


# ──────────────────────────────────────────────
#  متن‌های رندوم
# ──────────────────────────────────────────────

GROW_POSITIVE_MSGS = [
    "محکم به جلو رفتی! 💪",
    "انگار ویتامین زده بودی! 😎",
    "رشد طبیعی و قشنگ ✨",
    "روز خوبیه برات! 🌞",
    "همینطوری ادامه بده! 🚀",
]

GROW_NEGATIVE_MSGS = [
    "اوه... بد روزی بود 😬",
    "یکم خستگی نشون داد 😴",
    "نگران نباش، فردا بهتره 🙏",
    "این یکی درد داشت... 😅",
    "گاهی همه چی کوچیک‌تر می‌شه 🥲",
]

GROW_ZERO_MSGS = [
    "امروز فرقی نکرد، عادیه 🤷",
    "ثابت موند... صبور باش 🧘",
    "نه برد نه باخت، یه روز آرام 🌫️",
]


# ──────────────────────────────────────────────
#  دستورات
# ──────────────────────────────────────────────

@dp.message(Command("start"))
def start(message):
    message.answer(
        "🍆 به DickGrower خوش اومدی! 🍆\n"
        "━━━━━━━━━━━━━━━\n"
        "هر روز با /grow رشد کن، با /pvp و /duel\n"
        "بجنگ، سکه جمع کن و مدال بگیر! 🏆\n\n"
        "📋 برای دیدن همه‌چی:\n"
        "👉 /help\n"
        "━━━━━━━━━━━━━━━\n"
        "👨‍💻 Dev: cpamir | @BreadpitB"
    )


@dp.message(Command("help"))
def help_cmd(message):
    message.answer(
        "📖 راهنمای کامل DickGrower 📖\n"
        "━━━━━━━━━━━━━━━\n"
        "🌱 /grow\n"
        "رشد روزانه (هر ۲۴ ساعت یه بار). یه عدد\n"
        "رندوم بین -۵ تا +۱۵ به سایزت اضافه می‌شه.\n"
        "۵٪ شانس هست که جکپات بخوره: یا سایزت\n"
        "۲ برابر می‌شه 🎰💚 یا صفر می‌شه 🎰💔\n"
        "━━━━━━━━━━━━━━━\n"
        "📊 /stats\n"
        "آمار کامل: سایز، عنوان، سکه‌ها، برد/باخت،\n"
        "رکورد برد، تعداد مدال‌ها و یه نمودار ساده\n"
        "از ۱۰ رشد آخرت (🟢 رشد / 🔴 کاهش / ⚪ بدون تغییر)\n"
        "━━━━━━━━━━━━━━━\n"
        "🏆 /top\n"
        "جدول ۱۰ نفر برتر گروه در فصل فعلی\n"
        "━━━━━━━━━━━━━━━\n"
        "🗓 /season\n"
        "اطلاعات فصل فعلی (هر فصل ۳۰ روزه) و\n"
        "لیست قهرمانان فصل‌های قبلی. در پایان هر\n"
        "فصل، نفر اول قهرمان می‌شه و همه سایزها\n"
        "ریست می‌شن!\n"
        "━━━━━━━━━━━━━━━\n"
        "🎁 /daily\n"
        "جایزه سکه‌ی روزانه (هر ۲۴ ساعت)، بین\n"
        "۱۰ تا ۴۰ سکه رندوم می‌گیری\n"
        "━━━━━━━━━━━━━━━\n"
        "⚔️ /pvp مقدار\n"
        "نبرد با شانس! یه عددی که می‌خوای شرط\n"
        "ببندی بفرست (یا به‌جای عدد بنویس all\n"
        "برای شرط کل سایزت منهای ۱). هرچی نسبت\n"
        "به سایزت بیشتر شرط ببندی، شانس بردت کمتره\n"
        "━━━━━━━━━━━━━━━\n"
        "🤺 /duel @یوزرنیم مقدار\n"
        "چالش مستقیم با یه نفر دیگه از گروه (باید\n"
        "قبلاً با ربات /start کرده باشه). طرف مقابل\n"
        "باید با /accept قبول یا با /decline رد کنه.\n"
        "شانس برد بر اساس سایز نسبی دو طرفه\n"
        "━━━━━━━━━━━━━━━\n"
        "✅ /accept — قبول کردن آخرین چالش\n"
        "❌ /decline — رد کردن آخرین چالش\n"
        "━━━━━━━━━━━━━━━\n"
        "🛒 /shop\n"
        "لیست آیتم‌های فروشگاه:\n"
        "💊 قرص رشد (۵۰ سکه) — ۲۴ ساعت رشد بهتر\n"
        "🛡 بیمه شکست (۸۰ سکه) — نصف کردن ضرر\n"
        "      شکست بعدی در /pvp\n"
        "🔒 سپر ضد دزدی (۶۰ سکه) — ۲۴ ساعت\n"
        "      محافظت در برابر /steal\n"
        "━━━━━━━━━━━━━━━\n"
        "🛍 /buy آیتم\n"
        "خرید آیتم با کلید آیتم (مثلاً /buy pill)\n"
        "━━━━━━━━━━━━━━━\n"
        "🎒 /inventory\n"
        "وضعیت آیتم‌های فعال خودت\n"
        "━━━━━━━━━━━━━━━\n"
        "🕵️ /steal @یوزرنیم\n"
        "دزدی سکه از یه کاربر دیگه (کول‌دان ۱۲\n"
        "ساعته). ۴۰٪ شانس موفقیت داری؛ اگه شکست\n"
        "بخوری خودت جریمه می‌شی. اگه طرف سپر\n"
        "داشته باشه دزدیت بی‌اثره\n"
        "━━━━━━━━━━━━━━━\n"
        "🎖 /achievements\n"
        "لیست همه مدال‌ها و اینکه کدوم‌ها رو\n"
        "گرفتی\n"
        "━━━━━━━━━━━━━━━\n"
        "🎗 عنوان‌ها بر اساس سایز:\n"
        "🍼 نوزاد < ۵ | 🌱 نهال ۵-۱۵ | 😎 معمولی ۱۵-۳۰\n"
        "💪 باتجربه ۳۰-۵۰ | 🔥 حرفه‌ای ۵۰-۸۰\n"
        "👑 استاد ۸۰-۱۲۰ | 🐉 افسانه ۱۲۰-۲۰۰\n"
        "🌌 خداگونه ۲۰۰+\n"
        "━━━━━━━━━━━━━━━\n"
        "👨‍💻 Dev: cpamir | @BreadpitB"
    )


@dp.message(Command("grow"))
def grow(message):
    user_id = str(message.user_id)
    group_id = str(message.chat_id)
    username = message.first_name or message.username or "کاربر"

    season_result = check_season(group_id)
    if season_result:
        message.answer(
            "🎉 پایان فصل! 🎉\n"
            "━━━━━━━━━━━━━━━\n"
            f"👑 قهرمان فصل قبل: {season_result[0]}\n"
            f"📏 با سایز: {season_result[1]} cm\n"
            "🔄 فصل جدید شروع شد، همه سایزها ریست شدن!\n"
            "━━━━━━━━━━━━━━━"
        )

    user = get_user(user_id, group_id, username)
    size = user['size']
    now = datetime.now()
    last = datetime.strptime(user['last_grow'], TIME_FMT)
    elapsed = (now - last).total_seconds()

    if elapsed < GROW_COOLDOWN:
        remaining = GROW_COOLDOWN - elapsed
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        message.answer(
            "⏳ هنوز وقتش نشده! ⏳\n"
            "━━━━━━━━━━━━━━━\n"
            f"⏰ {hours} ساعت و {minutes} دقیقه دیگه بیا\n"
            f"{progress_bar(elapsed, GROW_COOLDOWN)}\n"
            "━━━━━━━━━━━━━━━"
        )
        return

    pill_active = datetime.strptime(user['pill_until'], TIME_FMT) > now
    jackpot = random.random() < 0.05

    if jackpot:
        if random.random() < 0.5:
            new_size = size * 2
            jp_text = "🎰💚 جکپات طلایی! سایزت ۲ برابر شد!"
        else:
            new_size = 1
            jp_text = "🎰💔 جکپات شوم! سایزت صفر شد!"
        change = new_size - size
        unlock_special(user, 'jackpot')
    else:
        lo, hi = (-2, 20) if pill_active else (-5, 15)
        change = random.randint(lo, hi)
        new_size = max(1, size + change)

    new_history = append_history(user['history'], change)
    update_user(user_id, group_id, size=new_size, last_grow=now.strftime(TIME_FMT), history=new_history)

    updated = get_user(user_id, group_id, username)
    new_ach = check_achievements(updated)
    title = get_title(new_size)

    if jackpot:
        body = f"{jp_text}\n📏 سایز جدید: {new_size} cm\n🎗 عنوان: {title}"
    elif change > 0:
        body = (f"📈 {random.choice(GROW_POSITIVE_MSGS)}\n"
                f"🍆 +{change} cm\n📏 سایز: {new_size} cm\n🎗 عنوان: {title}")
    elif change < 0:
        body = (f"📉 {random.choice(GROW_NEGATIVE_MSGS)}\n"
                f"🍆 {change} cm\n📏 سایز: {new_size} cm\n🎗 عنوان: {title}")
    else:
        body = (f"😐 {random.choice(GROW_ZERO_MSGS)}\n"
                f"📏 سایز: {new_size} cm\n🎗 عنوان: {title}")

    if pill_active and not jackpot:
        body += "\n💊 (با بافت قرص رشد!)"

    text = f"🌱 رشد روزانه {username} 🌱\n━━━━━━━━━━━━━━━\n{body}"
    text += achievement_announcement(new_ach)
    text += "\n━━━━━━━━━━━━━━━"
    message.answer(text)


@dp.message(Command("stats"))
def stats(message):
    user_id = str(message.user_id)
    group_id = str(message.chat_id)
    username = message.first_name or message.username or "کاربر"
    user = get_user(user_id, group_id, username)

    now = datetime.now()
    title = get_title(user['size'])
    hist_bar = history_bar(user['history'])
    unlocked = set(user['achievements'].split(',')) if user['achievements'] else set()

    pill_active = datetime.strptime(user['pill_until'], TIME_FMT) > now
    shield_active = datetime.strptime(user['shield_until'], TIME_FMT) > now

    text = (
        f"📊 آمار {username} 📊\n"
        "━━━━━━━━━━━━━━━\n"
        f"🍆 سایز: {user['size']} cm\n"
        f"🎗 عنوان: {title}\n"
        f"💰 سکه: {user['coins']}\n"
        f"⚔️ برد/باخت: {user['pvp_wins']} / {user['pvp_losses']}\n"
        f"🔥 رکورد برد متوالی: {user['win_streak']}\n"
        f"🎖 مدال‌ها: {len(unlocked)}/{len(ACHIEVEMENTS)}\n"
        f"📈 روند رشد: {hist_bar}\n"
    )

    extras = []
    if pill_active:
        extras.append("💊 قرص رشد فعال!")
    if shield_active:
        extras.append("🔒 سپر ضد دزدی فعال!")
    if user['insurance']:
        extras.append("🛡 بیمه شکست فعال!")

    if extras:
        text += "\n" + "\n".join(extras) + "\n"

    text += "━━━━━━━━━━━━━━━"
    message.answer(text)


@dp.message(Command("top"))
def top(message):
    group_id = str(message.chat_id)
    check_season(group_id)

    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT season_number FROM seasons WHERE group_id=?', (group_id,))
    season = c.fetchone()
    conn.close()
    season_num = season['season_number'] if season else 1

    top_users = get_top(group_id)

    if not top_users:
        message.answer("😔 هنوز بازیکنی نیست! با /grow شروع کن")
        return

    medals = ["🥇", "🥈", "🥉"]
    text = f"🏆 برترین‌های فصل {season_num} 🏆\n━━━━━━━━━━━━━━━\n"

    for i, row in enumerate(top_users):
        medal = medals[i] if i < 3 else f"{i + 1}."
        title = get_title(row['size'])
        text += f"{medal} {row['username']} — {row['size']} cm {title}\n"

    text += "━━━━━━━━━━━━━━━"
    message.answer(text)


@dp.message(Command("season"))
def season_cmd(message):
    group_id = str(message.chat_id)
    check_season(group_id)

    conn = get_conn()
    c = conn.cursor()
    c.execute('SELECT * FROM seasons WHERE group_id=?', (group_id,))
    season = c.fetchone()

    now = datetime.now()
    start = datetime.strptime(season['start_date'], TIME_FMT)
    elapsed_days = (now - start).days
    remaining_days = max(0, SEASON_LENGTH_DAYS - elapsed_days)

    text = f"🗓 فصل {season['season_number']} 🗓\n━━━━━━━━━━━━━━━\n"
    text += f"📅 {remaining_days} روز تا پایان این فصل\n\n"

    c.execute('''SELECT season_number, winner_username, winner_size
                 FROM season_history WHERE group_id=?
                 ORDER BY season_number DESC LIMIT 5''', (group_id,))
    history = c.fetchall()
    conn.close()

    if history:
        text += "👑 قهرمانان قبلی:\n"
        for h in history:
            text += f"  فصل {h['season_number']}: {h['winner_username']} ({h['winner_size']} cm)\n"
    else:
        text += "📭 هنوز هیچ فصلی به پایان نرسیده"

    text += "\n━━━━━━━━━━━━━━━"
    message.answer(text)


@dp.message(Command("daily"))
def daily(message):
    user_id = str(message.user_id)
    group_id = str(message.chat_id)
    username = message.first_name or message.username or "کاربر"
    user = get_user(user_id, group_id, username)

    now = datetime.now()
    last = datetime.strptime(user['last_daily'], TIME_FMT)
    elapsed = (now - last).total_seconds()

    if elapsed < DAILY_COOLDOWN:
        remaining = DAILY_COOLDOWN - elapsed
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        message.answer(
            "🎁 جایزه روزانه 🎁\n"
            "━━━━━━━━━━━━━━━\n"
            f"⏰ {hours} ساعت و {minutes} دقیقه دیگه بیا\n"
            f"{progress_bar(elapsed, DAILY_COOLDOWN)}\n"
            "━━━━━━━━━━━━━━━"
        )
        return

    reward = random.randint(10, 40)
    new_coins = user['coins'] + reward
    update_user(user_id, group_id, coins=new_coins, last_daily=now.strftime(TIME_FMT))

    updated = get_user(user_id, group_id, username)
    new_ach = check_achievements(updated)

    text = (
        "🎁 جایزه روزانه گرفته شد! 🎁\n"
        "━━━━━━━━━━━━━━━\n"
        f"💰 +{reward} سکه\n"
        f"💳 موجودی: {new_coins} سکه"
    )
    text += achievement_announcement(new_ach)
    text += "\n━━━━━━━━━━━━━━━"
    message.answer(text)


@dp.message(Command("pvp"))
def pvp(message):
    args = message.text.split()
    if len(args) < 2:
        message.answer(
            "⚔️ نبرد ⚔️\n"
            "━━━━━━━━━━━━━━━\n"
            "فرمت: /pvp مقدار\n"
            "یا: /pvp all (شرط کل سایزت منهای ۱)\n"
            "━━━━━━━━━━━━━━━"
        )
        return

    user_id = str(message.user_id)
    group_id = str(message.chat_id)
    username = message.first_name or message.username or "کاربر"
    user = get_user(user_id, group_id, username)

    amount = parse_amount(args[1], user['size'])
    if amount is None:
        message.answer("❌ مقدار باید یه عدد مثبت یا all باشه!")
        return

    if user['size'] < amount:
        message.answer(
            "❌ سایزت کافی نیست! ❌\n"
            "━━━━━━━━━━━━━━━\n"
            f"🍆 سایزت: {user['size']} cm\n"
            "━━━━━━━━━━━━━━━"
        )
        return

    risk = amount / user['size']
    win_chance = max(0.2, min(0.6, 0.55 - risk * 0.25))
    win = random.random() < win_chance

    insurance_active = bool(user['insurance'])

    if win:
        new_size = user['size'] + amount
        update_user(user_id, group_id, size=new_size,
                     pvp_wins=user['pvp_wins'] + 1,
                     win_streak=user['win_streak'] + 1)
        text = (
            f"🎉 {username} بُرد! 🎉\n"
            "━━━━━━━━━━━━━━━\n"
            f"🍆 +{amount} cm\n"
            f"📏 سایز: {new_size} cm\n"
            f"🎲 شانس برد بود: {int(win_chance * 100)}٪"
        )
    else:
        loss = amount
        used_insurance = False
        if insurance_active:
            loss = max(1, amount // 2)
            used_insurance = True
            update_user(user_id, group_id, insurance=0)

        new_size = max(1, user['size'] - loss)
        update_user(user_id, group_id, size=new_size,
                     pvp_losses=user['pvp_losses'] + 1,
                     win_streak=0)

        text = (
            f"💀 {username} باخت! 💀\n"
            "━━━━━━━━━━━━━━━\n"
            f"🍆 -{loss} cm\n"
            f"📏 سایز: {new_size} cm\n"
            f"🎲 شانس برد بود: {int(win_chance * 100)}٪"
        )
        if used_insurance:
            text += "\n🛡 بیمه فعال شد و ضررت نصف شد!"

    updated = get_user(user_id, group_id, username)
    new_ach = check_achievements(updated)
    text += achievement_announcement(new_ach)
    text += "\n━━━━━━━━━━━━━━━"
    message.answer(text)


@dp.message(Command("duel"))
def duel(message):
    args = message.text.split()
    if len(args) < 3:
        message.answer(
            "🤺 چالش مستقیم 🤺\n"
            "━━━━━━━━━━━━━━━\n"
            "فرمت: /duel @یوزرنیم مقدار\n"
            "یا: /duel @یوزرنیم all\n"
            "━━━━━━━━━━━━━━━"
        )
        return

    user_id = str(message.user_id)
    group_id = str(message.chat_id)
    username = message.first_name or message.username or "کاربر"
    challenger = get_user(user_id, group_id, username)

    amount = parse_amount(args[2], challenger['size'])
    if amount is None:
        message.answer("❌ مقدار باید یه عدد مثبت یا all باشه!")
        return

    if challenger['size'] < amount:
        message.answer("❌ سایزت برای این شرط کافی نیست!")
        return

    target_username = args[1].lstrip('@')
    target = get_user_by_username(group_id, target_username)

    if not target:
        message.answer("❌ این کاربر پیدا نشد! باید قبلاً با /start ربات رو استارت کرده باشه.")
        return

    if target['user_id'] == user_id:
        message.answer("❌ نمی‌تونی خودتو به چالش بکشی!")
        return

    if target['size'] < amount:
        message.answer(f"❌ {target['username']} سایز کافی برای این شرط نداره!")
        return

    conn = get_conn()
    c = conn.cursor()
    c.execute('''INSERT INTO duels
        (group_id, challenger_id, challenger_name, target_id, target_name, amount, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)''',
              (group_id, user_id, username, target['user_id'], target['username'], amount,
               datetime.now().strftime(TIME_FMT)))
    conn.commit()
    conn.close()

    message.answer(
        "🤺 چالش جدید! 🤺\n"
        "━━━━━━━━━━━━━━━\n"
        f"🧑 {username} به {target['username']} چالش داد!\n"
        f"💰 مقدار شرط: {amount} cm\n\n"
        f"✅ {target['username']} با /accept قبول کن\n"
        f"❌ یا با /decline رد کن\n"
        "━━━━━━━━━━━━━━━"
    )


@dp.message(Command("accept"))
def accept_duel(message):
    user_id = str(message.user_id)
    group_id = str(message.chat_id)

    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT * FROM duels WHERE group_id=? AND target_id=? AND status='pending'
                 ORDER BY duel_id DESC LIMIT 1''', (group_id, user_id))
    duel_row = c.fetchone()

    if not duel_row:
        conn.close()
        message.answer("❌ چالشی برای قبول کردن نداری!")
        return

    c.execute("UPDATE duels SET status='done' WHERE duel_id=?", (duel_row['duel_id'],))
    conn.commit()
    conn.close()

    amount = duel_row['amount']
    challenger = get_user(duel_row['challenger_id'], group_id, duel_row['challenger_name'])
    target = get_user(duel_row['target_id'], group_id, duel_row['target_name'])

    if challenger['size'] < amount or target['size'] < amount:
        message.answer("❌ یکی از طرفین دیگه سایز کافی نداره، چالش لغو شد.")
        return

    total = challenger['size'] + target['size']
    challenger_chance = 0.5 + (challenger['size'] - target['size']) / (2 * total)
    challenger_wins = random.random() < challenger_chance

    if challenger_wins:
        winner, loser = challenger, target
    else:
        winner, loser = target, challenger

    update_user(winner['user_id'], group_id,
                 size=winner['size'] + amount,
                 pvp_wins=winner['pvp_wins'] + 1,
                 win_streak=winner['win_streak'] + 1)
    update_user(loser['user_id'], group_id,
                 size=max(1, loser['size'] - amount),
                 pvp_losses=loser['pvp_losses'] + 1,
                 win_streak=0)

    text = (
        "🤺 نتیجه چالش 🤺\n"
        "━━━━━━━━━━━━━━━\n"
        f"🏆 برنده: {winner['username']} (+{amount} cm)\n"
        f"💀 بازنده: {loser['username']} (-{amount} cm)\n"
    )

    for user_row in (winner, loser):
        updated = get_user(user_row['user_id'], group_id, user_row['username'])
        new_ach = check_achievements(updated)
        if new_ach:
            text += f"\n🎖 {user_row['username']}:"
            text += achievement_announcement(new_ach)

    text += "\n━━━━━━━━━━━━━━━"
    message.answer(text)


@dp.message(Command("decline"))
def decline_duel(message):
    user_id = str(message.user_id)
    group_id = str(message.chat_id)

    conn = get_conn()
    c = conn.cursor()
    c.execute('''SELECT * FROM duels WHERE group_id=? AND target_id=? AND status='pending'
                 ORDER BY duel_id DESC LIMIT 1''', (group_id, user_id))
    duel_row = c.fetchone()

    if not duel_row:
        conn.close()
        message.answer("❌ چالشی برای رد کردن نداری!")
        return

    c.execute("UPDATE duels SET status='declined' WHERE duel_id=?", (duel_row['duel_id'],))
    conn.commit()
    conn.close()

    message.answer(
        "🙅 چالش رد شد 🙅\n"
        "━━━━━━━━━━━━━━━\n"
        f"{duel_row['target_name']} چالش {duel_row['challenger_name']} رو رد کرد.\n"
        "━━━━━━━━━━━━━━━"
    )


@dp.message(Command("shop"))
def shop(message):
    text = "🛒 فروشگاه 🛒\n━━━━━━━━━━━━━━━\n"
    for key, item in SHOP_ITEMS.items():
        text += (
            f"{item['name']}\n"
            f"💰 قیمت: {item['price']} سکه\n"
            f"ℹ️ {item['desc']}\n"
            f"🔑 خرید: /buy {key}\n\n"
        )
    text += "━━━━━━━━━━━━━━━"
    message.answer(text)


@dp.message(Command("buy"))
def buy(message):
    args = message.text.split()
    if len(args) < 2 or args[1] not in SHOP_ITEMS:
        message.answer("❌ آیتم نامعتبره! با /shop لیست آیتم‌ها رو ببین.")
        return

    item_key = args[1]
    item = SHOP_ITEMS[item_key]

    user_id = str(message.user_id)
    group_id = str(message.chat_id)
    username = message.first_name or message.username or "کاربر"
    user = get_user(user_id, group_id, username)

    if user['coins'] < item['price']:
        message.answer(
            "❌ سکه کافی نداری! ❌\n"
            "━━━━━━━━━━━━━━━\n"
            f"💰 نیاز: {item['price']} سکه\n"
            f"💳 موجودی: {user['coins']} سکه\n"
            "━━━━━━━━━━━━━━━"
        )
        return

    new_coins = user['coins'] - item['price']
    now = datetime.now()

    if item_key == 'pill':
        until = (now + timedelta(hours=24)).strftime(TIME_FMT)
        update_user(user_id, group_id, coins=new_coins, pill_until=until)
    elif item_key == 'insurance':
        update_user(user_id, group_id, coins=new_coins, insurance=1)
    elif item_key == 'shield':
        until = (now + timedelta(hours=24)).strftime(TIME_FMT)
        update_user(user_id, group_id, coins=new_coins, shield_until=until)

    message.answer(
        "✅ خریداری شد! ✅\n"
        "━━━━━━━━━━━━━━━\n"
        f"{item['name']} فعال شد!\n"
        f"💳 موجودی: {new_coins} سکه\n"
        "━━━━━━━━━━━━━━━"
    )


@dp.message(Command("inventory"))
def inventory(message):
    user_id = str(message.user_id)
    group_id = str(message.chat_id)
    username = message.first_name or message.username or "کاربر"
    user = get_user(user_id, group_id, username)
    now = datetime.now()

    pill_active = datetime.strptime(user['pill_until'], TIME_FMT) > now
    shield_active = datetime.strptime(user['shield_until'], TIME_FMT) > now

    text = (
        "🎒 کیف آیتم‌ها 🎒\n"
        "━━━━━━━━━━━━━━━\n"
        f"💊 قرص رشد: {'فعال ✅' if pill_active else 'غیرفعال ❌'}\n"
        f"🛡 بیمه شکست: {'فعال ✅' if user['insurance'] else 'غیرفعال ❌'}\n"
        f"🔒 سپر ضد دزدی: {'فعال ✅' if shield_active else 'غیرفعال ❌'}\n"
        "━━━━━━━━━━━━━━━"
    )
    message.answer(text)


@dp.message(Command("steal"))
def steal(message):
    args = message.text.split()
    if len(args) < 2:
        message.answer(
            "🕵️ دزدی 🕵️\n"
            "━━━━━━━━━━━━━━━\n"
            "فرمت: /steal @یوزرنیم\n"
            "━━━━━━━━━━━━━━━"
        )
        return

    user_id = str(message.user_id)
    group_id = str(message.chat_id)
    username = message.first_name or message.username or "کاربر"
    user = get_user(user_id, group_id, username)

    now = datetime.now()
    last_steal = datetime.strptime(user['last_steal'], TIME_FMT)
    elapsed = (now - last_steal).total_seconds()

    if elapsed < STEAL_COOLDOWN:
        remaining = STEAL_COOLDOWN - elapsed
        hours = int(remaining // 3600)
        minutes = int((remaining % 3600) // 60)
        message.answer(
            "🕵️ هنوز نمی‌تونی دزدی کنی! 🕵️\n"
            "━━━━━━━━━━━━━━━\n"
            f"⏰ {hours} ساعت و {minutes} دقیقه دیگه\n"
            f"{progress_bar(elapsed, STEAL_COOLDOWN)}\n"
            "━━━━━━━━━━━━━━━"
        )
        return

    target_username = args[1].lstrip('@')
    target = get_user_by_username(group_id, target_username)

    if not target or target['user_id'] == user_id:
        message.answer("❌ این کاربر پیدا نشد یا نمی‌تونی از خودت بدزدی!")
        return

    update_user(user_id, group_id, last_steal=now.strftime(TIME_FMT))

    shield_active = datetime.strptime(target['shield_until'], TIME_FMT) > now
    if shield_active:
        message.answer(
            "🔒 دزدی نافرجام! 🔒\n"
            "━━━━━━━━━━━━━━━\n"
            f"{target['username']} سپر داره و دزدیت ناکام ماند 😅\n"
            "━━━━━━━━━━━━━━━"
        )
        return

    success = random.random() < 0.4
    if success and target['coins'] > 0:
        stolen = max(1, int(target['coins'] * random.uniform(0.1, 0.3)))
        update_user(user_id, group_id, coins=user['coins'] + stolen)
        update_user(target['user_id'], group_id, coins=max(0, target['coins'] - stolen))

        updated = get_user(user_id, group_id, username)
        new_ach = check_achievements(updated)

        text = (
            "🕵️ دزدی موفق! 🕵️\n"
            "━━━━━━━━━━━━━━━\n"
            f"💰 {stolen} سکه از {target['username']} دزدیدی!\n"
            f"💳 موجودی: {updated['coins']} سکه"
        )
        text += achievement_announcement(new_ach)
        text += "\n━━━━━━━━━━━━━━━"
        message.answer(text)
    else:
        penalty = random.randint(5, 15)
        new_coins = max(0, user['coins'] - penalty)
        update_user(user_id, group_id, coins=new_coins)
        message.answer(
            "🚨 دزدی شکست خورد! 🚨\n"
            "━━━━━━━━━━━━━━━\n"
            f"💸 {penalty} سکه جریمه شدی!\n"
            f"💳 موجودی: {new_coins} سکه\n"
            "━━━━━━━━━━━━━━━"
        )


@dp.message(Command("achievements"))
def achievements_cmd(message):
    user_id = str(message.user_id)
    group_id = str(message.chat_id)
    username = message.first_name or message.username or "کاربر"
    user = get_user(user_id, group_id, username)

    unlocked = set(user['achievements'].split(',')) if user['achievements'] else set()

    text = "🎖 مدال‌های من 🎖\n━━━━━━━━━━━━━━━\n"
    for key, (name, desc) in ACHIEVEMENTS.items():
        status = "✅" if key in unlocked else "🔒"
        text += f"{status} {name}\n     {desc}\n"

    text += f"━━━━━━━━━━━━━━━\n📊 {len(unlocked)}/{len(ACHIEVEMENTS)} مدال گرفتی"
    message.answer(text)


init_db()

if __name__ == "__main__":
    bot.start_polling(dp)
