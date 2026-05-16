"""
ARGOS Test bot — backend (FastAPI).
Imkoniyatlar:
  - Test (50 ta tasodifiy savol, mavzu/modul bo'yicha)
  - Xato savollar va Spaced Repetition (SRS) qayta takrorlash
  - Vizual savollar (image_url maydoni)
  - Pulli obuna (har modul uchun 50 000 so'm/oy)
  - Click karta orqali to'lov + admin tasdig'i
  - Admin panel API (to'lov cheklari, foydalanuvchilar)
"""
from fastapi import FastAPI, HTTPException, Header, UploadFile, File, Form, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse, JSONResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import sqlite3
import json
import random
import os
import time
import base64
from datetime import datetime, timedelta

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================================
# KONFIG (Env variables)
# ============================================================
DB = os.environ.get("DB_PATH", "/app/data/argos.db")
RECEIPTS_DIR = os.environ.get("RECEIPTS_DIR", "/app/data/receipts")
ADMIN_TG_IDS = [
    int(x.strip())
    for x in os.environ.get("ADMIN_TG_IDS", "").split(",")
    if x.strip().isdigit()
]
CLICK_CARD = os.environ.get("CLICK_CARD", "8600 1234 5678 9012")
CLICK_HOLDER = os.environ.get("CLICK_HOLDER", "ARGOS BOT")
PRICE_PER_MODULE = int(os.environ.get("PRICE_PER_MODULE", "50000"))
SUBSCRIPTION_DAYS = int(os.environ.get("SUBSCRIPTION_DAYS", "30"))
RATE_LIMIT_PER_MIN = int(os.environ.get("RATE_LIMIT_PER_MIN", "120"))

ROLE_FILES = {
    "shifokor_1": "1_modul_questions_doc.json",
    "hamshira_2": "2_modul_question_med.json",
}

os.makedirs(RECEIPTS_DIR, exist_ok=True)
os.makedirs(os.path.dirname(DB), exist_ok=True)


# ============================================================
# DB
# ============================================================
def get_conn():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def column_exists(c, table, column):
    c.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in c.fetchall())


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # questions
    c.execute(
        "CREATE TABLE IF NOT EXISTS questions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "question TEXT UNIQUE,"
        "options TEXT,"
        "correct INTEGER,"
        "explanation TEXT DEFAULT '',"
        "role TEXT DEFAULT 'shifokor_1',"
        "image_url TEXT DEFAULT ''"
        ")"
    )
    if not column_exists(c, "questions", "role"):
        c.execute("ALTER TABLE questions ADD COLUMN role TEXT DEFAULT 'shifokor_1'")
    if not column_exists(c, "questions", "image_url"):
        c.execute("ALTER TABLE questions ADD COLUMN image_url TEXT DEFAULT ''")

    c.execute("CREATE INDEX IF NOT EXISTS idx_questions_role ON questions(role)")

    # users
    c.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "user_id INTEGER PRIMARY KEY,"
        "role TEXT,"
        "name TEXT DEFAULT '',"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    if not column_exists(c, "users", "name"):
        c.execute("ALTER TABLE users ADD COLUMN name TEXT DEFAULT ''")

    # results
    c.execute(
        "CREATE TABLE IF NOT EXISTS results ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER,"
        "question_id INTEGER,"
        "is_correct BOOLEAN,"
        "answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_results_user ON results(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_results_q ON results(question_id)")

    # subscriptions (har user-modul uchun bitta faol obuna)
    c.execute(
        "CREATE TABLE IF NOT EXISTS subscriptions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER NOT NULL,"
        "role_module TEXT NOT NULL,"
        "started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "expires_at TIMESTAMP NOT NULL,"
        "status TEXT DEFAULT 'active',"
        "payment_id INTEGER"
        ")"
    )
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_subs_user ON subscriptions(user_id, role_module)"
    )

    # payments
    c.execute(
        "CREATE TABLE IF NOT EXISTS payments ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER NOT NULL,"
        "user_name TEXT DEFAULT '',"
        "role_module TEXT NOT NULL,"
        "amount INTEGER DEFAULT 50000,"
        "receipt_path TEXT DEFAULT '',"
        "comment TEXT DEFAULT '',"
        "status TEXT DEFAULT 'pending',"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
        "decided_at TIMESTAMP,"
        "admin_note TEXT DEFAULT ''"
        ")"
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_pay_status ON payments(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_pay_user ON payments(user_id)")

    # SRS schedule (Spaced Repetition)
    c.execute(
        "CREATE TABLE IF NOT EXISTS srs ("
        "user_id INTEGER NOT NULL,"
        "question_id INTEGER NOT NULL,"
        "next_review TIMESTAMP NOT NULL,"
        "interval_days INTEGER DEFAULT 1,"
        "repetitions INTEGER DEFAULT 0,"
        "ease REAL DEFAULT 2.5,"
        "PRIMARY KEY (user_id, question_id)"
        ")"
    )
    c.execute("CREATE INDEX IF NOT EXISTS idx_srs_due ON srs(user_id, next_review)")

    conn.commit()

    # Eski yozuvlar tozalash + role normalize
    c.execute("DELETE FROM questions WHERE role IS NULL OR role = ''")
    c.execute("UPDATE questions SET role = 'shifokor_1' WHERE role = 'shifokor'")
    c.execute("UPDATE questions SET role = 'hamshira_2' WHERE role = 'hamshira'")
    conn.commit()

    # JSON fayllardan import
    for role, fname in ROLE_FILES.items():
        if not os.path.exists(fname):
            continue
        try:
            with open(fname, "r", encoding="utf-8") as f:
                qs = json.load(f)
        except Exception as e:
            print(f"{fname} xato: {e}")
            continue
        imported = 0
        for q in qs:
            text = (q.get("question") or "").strip()
            if not text:
                continue
            try:
                c.execute(
                    "INSERT OR IGNORE INTO questions (question, options, correct, explanation, role, image_url) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        text,
                        json.dumps(q.get("options", []), ensure_ascii=False),
                        q.get("correct", 0),
                        q.get("explanation", ""),
                        role,
                        q.get("image_url", ""),
                    ),
                )
                if c.rowcount > 0:
                    imported += 1
            except Exception:
                pass
        conn.commit()
        if imported > 0:
            print(f"{fname} dan {imported} ta '{role}' savoli import")
    conn.close()


init_db()

# Static files
static_dir = "static"
if not os.path.exists(static_dir):
    os.makedirs(static_dir)
app.mount("/static", StaticFiles(directory=static_dir), name="static")
# Receipts (admin uchun ko'rish)
app.mount("/receipts", StaticFiles(directory=RECEIPTS_DIR), name="receipts")


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


# ============================================================
# YORDAMCHI FUNKSIYALAR
# ============================================================
def _normalize_role(bolim: str) -> str:
    if not bolim:
        return "shifokor_1"
    b = bolim.strip().lower()
    parts = b.replace("-", "_").split("_")
    base = parts[0]
    modul = parts[1] if len(parts) > 1 and parts[1].isdigit() else None
    if base in ("shifokor", "shifokorlar", "doctor", "doctors"):
        base = "shifokor"
    elif base in ("hamshira", "hamshiralar", "nurse", "nurses"):
        base = "hamshira"
    if modul:
        return f"{base}_{modul}"
    return f"{base}_1" if base == "shifokor" else f"{base}_2"


def has_active_subscription(user_id: int, role_module: str) -> bool:
    """Foydalanuvchining shu modulga faol obunasi bormi?"""
    if not user_id or not role_module:
        return False
    # Admin doim ruxsatli
    if user_id in ADMIN_TG_IDS:
        return True
    conn = get_conn()
    row = conn.execute(
        "SELECT id, expires_at FROM subscriptions "
        "WHERE user_id = ? AND role_module = ? AND status = 'active' "
        "ORDER BY expires_at DESC LIMIT 1",
        (user_id, role_module),
    ).fetchone()
    conn.close()
    if not row:
        return False
    try:
        exp = datetime.fromisoformat(row[1])
    except Exception:
        return False
    return exp > datetime.utcnow()


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_TG_IDS


# ============================================================
# RATE LIMITING (oddiy in-memory)
# ============================================================
_rate_buckets: Dict[str, List[float]] = {}


@app.middleware("http")
async def rate_limit_mw(request: Request, call_next):
    # Faqat /api/* ga qo'llanadi
    if request.url.path.startswith("/api/"):
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        bucket = _rate_buckets.setdefault(ip, [])
        bucket[:] = [t for t in bucket if now - t < 60]
        if len(bucket) >= RATE_LIMIT_PER_MIN:
            return JSONResponse(
                {"error": "Juda ko'p so'rov. Bir oz kuting."}, status_code=429
            )
        bucket.append(now)
    return await call_next(request)


# ============================================================
# MODELS
# ============================================================
class UserRole(BaseModel):
    user_id: int
    role: str
    name: Optional[str] = ""


class Answer(BaseModel):
    user_id: int
    question_id: int
    selected: int


class PaymentSubmit(BaseModel):
    user_id: int
    user_name: Optional[str] = ""
    role_module: str
    receipt_b64: str  # base64 encoded image (data:image/png;base64,...)
    comment: Optional[str] = ""


class AdminAction(BaseModel):
    payment_id: int
    admin_user_id: int
    note: Optional[str] = ""


# ============================================================
# REGISTER
# ============================================================
@app.post("/api/register")
def register(data: UserRole):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO users (user_id, role, name) VALUES (?, ?, ?)",
        (data.user_id, data.role, data.name or ""),
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


# ============================================================
# QUESTIONS
# ============================================================
@app.get("/api/questions")
def get_questions(user_id: int, bolim: str = "shifokor_1", count: int = 50):
    role = _normalize_role(bolim)
    if not has_active_subscription(user_id, role):
        return JSONResponse(
            {
                "error": "subscription_required",
                "message": f"Bu modulga obuna kerak ({PRICE_PER_MODULE:,} so'm/oy)",
                "role_module": role,
                "price": PRICE_PER_MODULE,
            },
            status_code=402,
        )
    if count < 1:
        count = 50
    if count > 200:
        count = 200
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, question, options, explanation, image_url FROM questions WHERE role = ?",
        (role,),
    ).fetchall()
    conn.close()
    if not rows:
        return []
    selected = random.sample(rows, min(count, len(rows)))
    return [
        {
            "id": r[0],
            "question": r[1],
            "options": json.loads(r[2]),
            "explanation": r[3] or "",
            "image_url": r[4] or "",
        }
        for r in selected
    ]


@app.post("/api/answer")
def submit_answer(data: Answer):
    conn = get_conn()
    row = conn.execute(
        "SELECT correct, explanation, role FROM questions WHERE id=?",
        (data.question_id,),
    ).fetchone()
    if not row:
        conn.close()
        return {"error": "Savol topilmadi"}
    correct_idx, explanation, role = row
    is_correct = data.selected == correct_idx
    conn.execute(
        "INSERT INTO results (user_id, question_id, is_correct) VALUES (?, ?, ?)",
        (data.user_id, data.question_id, is_correct),
    )
    # SRS yangilash
    _update_srs(conn, data.user_id, data.question_id, is_correct)
    conn.commit()
    conn.close()
    return {
        "is_correct": is_correct,
        "correct_index": correct_idx,
        "explanation": explanation or "",
    }


# ============================================================
# STATISTIKA
# ============================================================
@app.get("/api/stats")
def get_stats(user_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*), SUM(is_correct) FROM results WHERE user_id=?",
        (user_id,),
    ).fetchone()
    # Modul bo'yicha alohida statistika
    by_role = conn.execute(
        "SELECT q.role, COUNT(*), SUM(r.is_correct) "
        "FROM results r JOIN questions q ON r.question_id = q.id "
        "WHERE r.user_id = ? GROUP BY q.role",
        (user_id,),
    ).fetchall()
    conn.close()
    total, correct = row
    correct = correct or 0
    return {
        "total": total or 0,
        "correct": correct,
        "wrong": (total or 0) - correct,
        "percent": round(correct / total * 100) if total else 0,
        "by_module": [
            {
                "role_module": r[0],
                "total": r[1],
                "correct": r[2] or 0,
                "percent": round((r[2] or 0) / r[1] * 100) if r[1] else 0,
            }
            for r in by_role
        ],
    }


# ============================================================
# XATOLAR
# ============================================================
@app.get("/api/mistakes")
def get_mistakes(user_id: int, bolim: str = "shifokor_1", count: int = 50):
    role = _normalize_role(bolim)
    if not has_active_subscription(user_id, role):
        return []
    if count < 1:
        count = 50
    if count > 200:
        count = 200
    conn = get_conn()
    wrong_ids = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT question_id FROM results WHERE user_id=? AND is_correct=0",
            (user_id,),
        ).fetchall()
    ]
    if not wrong_ids:
        conn.close()
        return []
    placeholders = ",".join("?" * len(wrong_ids))
    rows = conn.execute(
        "SELECT id, question, options, correct, explanation, image_url FROM questions "
        f"WHERE id IN ({placeholders}) AND role = ?",
        wrong_ids + [role],
    ).fetchall()
    conn.close()
    if not rows:
        return []
    if len(rows) > count:
        rows = random.sample(rows, count)
    return [
        {
            "id": r[0],
            "question": r[1],
            "options": json.loads(r[2]),
            "correct": r[3],
            "explanation": r[4] or "",
            "image_url": r[5] or "",
        }
        for r in rows
    ]


# ============================================================
# SPACED REPETITION (SRS) — Anki uslubidagi soddalashtirilgan
# ============================================================
def _update_srs(conn, user_id: int, question_id: int, is_correct: bool):
    row = conn.execute(
        "SELECT interval_days, repetitions, ease FROM srs WHERE user_id=? AND question_id=?",
        (user_id, question_id),
    ).fetchone()
    now = datetime.utcnow()
    if row is None:
        # Birinchi marta
        if is_correct:
            interval = 1
            reps = 1
            ease = 2.5
        else:
            interval = 1
            reps = 0
            ease = 2.5
    else:
        interval, reps, ease = row
        if is_correct:
            reps = (reps or 0) + 1
            if reps == 1:
                interval = 1
            elif reps == 2:
                interval = 3
            elif reps == 3:
                interval = 7
            else:
                interval = min(int((interval or 1) * (ease or 2.5)), 90)
            ease = max(1.3, (ease or 2.5) + 0.1)
        else:
            reps = 0
            interval = 1
            ease = max(1.3, (ease or 2.5) - 0.2)
    next_review = now + timedelta(days=interval)
    conn.execute(
        "INSERT OR REPLACE INTO srs (user_id, question_id, next_review, interval_days, repetitions, ease) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, question_id, next_review.isoformat(), interval, reps, ease),
    )


@app.get("/api/srs/due")
def srs_due(user_id: int, bolim: str = "shifokor_1", count: int = 50):
    """Bugun (yoki o'tgan) takror qilish kerak bo'lgan savollarni qaytaradi."""
    role = _normalize_role(bolim)
    if not has_active_subscription(user_id, role):
        return {"due": [], "count": 0}
    now = datetime.utcnow().isoformat()
    if count < 1:
        count = 50
    if count > 200:
        count = 200
    conn = get_conn()
    rows = conn.execute(
        "SELECT q.id, q.question, q.options, q.correct, q.explanation, q.image_url "
        "FROM srs s JOIN questions q ON q.id = s.question_id "
        "WHERE s.user_id = ? AND s.next_review <= ? AND q.role = ? "
        "ORDER BY s.next_review ASC LIMIT ?",
        (user_id, now, role, count),
    ).fetchall()
    # Umumiy due soni
    total_due = conn.execute(
        "SELECT COUNT(*) FROM srs s JOIN questions q ON q.id = s.question_id "
        "WHERE s.user_id = ? AND s.next_review <= ? AND q.role = ?",
        (user_id, now, role),
    ).fetchone()[0]
    conn.close()
    return {
        "count": total_due,
        "due": [
            {
                "id": r[0],
                "question": r[1],
                "options": json.loads(r[2]),
                "correct": r[3],
                "explanation": r[4] or "",
                "image_url": r[5] or "",
            }
            for r in rows
        ],
    }


# ============================================================
# OBUNA (SUBSCRIPTION) STATUS
# ============================================================
@app.get("/api/subscription/status")
def subscription_status(user_id: int):
    conn = get_conn()
    rows = conn.execute(
        "SELECT role_module, started_at, expires_at, status FROM subscriptions "
        "WHERE user_id = ? AND status = 'active' AND datetime(expires_at) > datetime('now')",
        (user_id,),
    ).fetchall()
    # Pending (kutilayotgan) to'lovlar
    pending = conn.execute(
        "SELECT id, role_module, created_at FROM payments "
        "WHERE user_id = ? AND status = 'pending' ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    conn.close()
    return {
        "active": [
            {
                "role_module": r[0],
                "started_at": r[1],
                "expires_at": r[2],
                "status": r[3],
            }
            for r in rows
        ],
        "pending_payments": [
            {"id": p[0], "role_module": p[1], "created_at": p[2]} for p in pending
        ],
        "is_admin": is_admin(user_id),
    }


@app.get("/api/payment/info")
def payment_info():
    """To'lov ma'lumotlari (karta raqami, narx)."""
    return {
        "card": CLICK_CARD,
        "holder": CLICK_HOLDER,
        "price": PRICE_PER_MODULE,
        "currency": "so'm",
        "duration_days": SUBSCRIPTION_DAYS,
    }


@app.post("/api/payment/submit")
def submit_payment(data: PaymentSubmit):
    """Foydalanuvchi to'lov chekini yuboradi (base64 rasm)."""
    role = _normalize_role(data.role_module)
    # Receipt'ni saqlash
    receipt_path = ""
    try:
        b64 = data.receipt_b64
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        raw = base64.b64decode(b64)
        if len(raw) > 5_000_000:  # 5MB chegara
            raise HTTPException(status_code=413, detail="Rasm juda katta (max 5MB)")
        ts = int(time.time())
        ext = "png"
        # Kichik content-type tekshiruv (oddiy)
        if raw[:3] == b"\xff\xd8\xff":
            ext = "jpg"
        elif raw[:8].startswith(b"\x89PNG"):
            ext = "png"
        fname = f"r_{data.user_id}_{ts}.{ext}"
        path = os.path.join(RECEIPTS_DIR, fname)
        with open(path, "wb") as fh:
            fh.write(raw)
        receipt_path = fname
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Rasm o'qilmadi: {e}")

    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO payments (user_id, user_name, role_module, amount, receipt_path, comment) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            data.user_id,
            data.user_name or "",
            role,
            PRICE_PER_MODULE,
            receipt_path,
            data.comment or "",
        ),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return {
        "status": "ok",
        "payment_id": pid,
        "message": "To'lov chegingiz qabul qilindi. Admin tasdiqlashi kutilmoqda.",
    }


# ============================================================
# ADMIN PANEL
# ============================================================
def _check_admin(admin_id: int):
    if not is_admin(admin_id):
        raise HTTPException(status_code=403, detail="Faqat admin uchun")


@app.get("/api/admin/payments")
def admin_payments(admin_user_id: int, status: str = "pending"):
    _check_admin(admin_user_id)
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, user_id, user_name, role_module, amount, receipt_path, comment, status, created_at, decided_at, admin_note "
        "FROM payments WHERE status = ? ORDER BY created_at DESC LIMIT 200",
        (status,),
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "user_id": r[1],
            "user_name": r[2] or "",
            "role_module": r[3],
            "amount": r[4],
            "receipt_url": f"/receipts/{r[5]}" if r[5] else "",
            "comment": r[6] or "",
            "status": r[7],
            "created_at": r[8],
            "decided_at": r[9],
            "admin_note": r[10] or "",
        }
        for r in rows
    ]


@app.post("/api/admin/payment/approve")
def admin_approve(data: AdminAction):
    _check_admin(data.admin_user_id)
    conn = get_conn()
    row = conn.execute(
        "SELECT user_id, role_module, status FROM payments WHERE id = ?",
        (data.payment_id,),
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="To'lov topilmadi")
    if row[2] != "pending":
        conn.close()
        raise HTTPException(status_code=400, detail="Allaqachon hal qilingan")
    user_id, role_module, _ = row
    # Obuna faollashtirish
    now = datetime.utcnow()
    expires = now + timedelta(days=SUBSCRIPTION_DAYS)
    conn.execute(
        "INSERT INTO subscriptions (user_id, role_module, started_at, expires_at, status, payment_id) "
        "VALUES (?, ?, ?, ?, 'active', ?)",
        (user_id, role_module, now.isoformat(), expires.isoformat(), data.payment_id),
    )
    # To'lovni belgilash
    conn.execute(
        "UPDATE payments SET status = 'approved', decided_at = ?, admin_note = ? WHERE id = ?",
        (now.isoformat(), data.note or "", data.payment_id),
    )
    conn.commit()
    conn.close()
    return {
        "status": "approved",
        "user_id": user_id,
        "role_module": role_module,
        "expires_at": expires.isoformat(),
    }


@app.post("/api/admin/payment/reject")
def admin_reject(data: AdminAction):
    _check_admin(data.admin_user_id)
    conn = get_conn()
    cur = conn.execute(
        "UPDATE payments SET status = 'rejected', decided_at = ?, admin_note = ? "
        "WHERE id = ? AND status = 'pending'",
        (datetime.utcnow().isoformat(), data.note or "", data.payment_id),
    )
    if cur.rowcount == 0:
        conn.close()
        raise HTTPException(status_code=400, detail="Allaqachon hal qilingan yoki topilmadi")
    conn.commit()
    conn.close()
    return {"status": "rejected"}


@app.get("/api/admin/users")
def admin_users(admin_user_id: int, limit: int = 100):
    _check_admin(admin_user_id)
    conn = get_conn()
    rows = conn.execute(
        "SELECT u.user_id, u.role, u.name, u.created_at, "
        "  (SELECT COUNT(*) FROM results WHERE user_id = u.user_id) as answered, "
        "  (SELECT COUNT(*) FROM subscriptions WHERE user_id = u.user_id AND status='active' AND datetime(expires_at) > datetime('now')) as active_subs "
        "FROM users u ORDER BY u.created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [
        {
            "user_id": r[0],
            "role": r[1] or "",
            "name": r[2] or "",
            "created_at": r[3],
            "answered": r[4],
            "active_subs": r[5],
        }
        for r in rows
    ]


@app.get("/api/admin/dashboard")
def admin_dashboard(admin_user_id: int):
    _check_admin(admin_user_id)
    conn = get_conn()
    counts = {
        "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        "questions": conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0],
        "answers": conn.execute("SELECT COUNT(*) FROM results").fetchone()[0],
        "active_subs": conn.execute(
            "SELECT COUNT(*) FROM subscriptions WHERE status='active' AND datetime(expires_at) > datetime('now')"
        ).fetchone()[0],
        "pending_payments": conn.execute(
            "SELECT COUNT(*) FROM payments WHERE status='pending'"
        ).fetchone()[0],
        "approved_payments": conn.execute(
            "SELECT COUNT(*) FROM payments WHERE status='approved'"
        ).fetchone()[0],
        "total_revenue": conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM payments WHERE status='approved'"
        ).fetchone()[0],
    }
    # Modul bo'yicha obuna
    by_module = conn.execute(
        "SELECT role_module, COUNT(*) FROM subscriptions "
        "WHERE status='active' AND datetime(expires_at) > datetime('now') GROUP BY role_module"
    ).fetchall()
    conn.close()
    counts["by_module"] = [{"role_module": r[0], "active": r[1]} for r in by_module]
    return counts


@app.post("/api/admin/grant")
def admin_grant_subscription(
    admin_user_id: int, target_user_id: int, role_module: str, days: int = 30
):
    """Admin foydalanuvchiga bepul obuna berishi mumkin (sinov, sovrin va h.k.)"""
    _check_admin(admin_user_id)
    role = _normalize_role(role_module)
    now = datetime.utcnow()
    expires = now + timedelta(days=days)
    conn = get_conn()
    conn.execute(
        "INSERT INTO subscriptions (user_id, role_module, started_at, expires_at, status) "
        "VALUES (?, ?, ?, ?, 'active')",
        (target_user_id, role, now.isoformat(), expires.isoformat()),
    )
    conn.commit()
    conn.close()
    return {"status": "granted", "expires_at": expires.isoformat()}


# ============================================================
# QO'SHIMCHA API
# ============================================================
@app.post("/api/add_questions")
async def add_questions(new_questions: List[Dict[str, Any]]):
    conn = get_conn()
    added = 0
    skipped = 0
    for q in new_questions:
        text = (q.get("question") or "").strip()
        if not text:
            skipped += 1
            continue
        role = _normalize_role(q.get("role", "shifokor"))
        try:
            conn.execute(
                "INSERT OR IGNORE INTO questions (question, options, correct, explanation, role, image_url) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    text,
                    json.dumps(q.get("options", []), ensure_ascii=False),
                    q.get("correct", 0),
                    q.get("explanation", ""),
                    role,
                    q.get("image_url", ""),
                ),
            )
            if conn.total_changes > 0:
                added += 1
            else:
                skipped += 1
        except Exception:
            skipped += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    return {"added": added, "skipped": skipped, "total": total}


@app.get("/api/total_questions")
def total_questions(bolim: str = ""):
    conn = get_conn()
    if bolim:
        role = _normalize_role(bolim)
        total = conn.execute(
            "SELECT COUNT(*) FROM questions WHERE role = ?", (role,)
        ).fetchone()[0]
    else:
        total = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    return {"total": total}
