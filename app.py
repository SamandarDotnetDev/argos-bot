from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import sqlite3
import json
import random
import os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DB = "/app/data/argos.db"

ROLE_FILES = {
    # Format: "<role>_<modul>" -> JSON fayl
    "shifokor_1": "1_modul_questions_doc.json",
    # "shifokor_2": "2_modul_questions_doc.json",  # keyinroq
    # "shifokor_3": "3_modul_questions_doc.json",  # keyinroq
    # "shifokor_4": "4_modul_questions_doc.json",  # keyinroq
    "hamshira_2": "2_modul_question_med.json",   # hamshiralar 2-modul (faol)
    # "hamshira_3": "3_modul_question_med.json",  # hozircha bosh
    # "hamshira_4": "4_modul_question_med.json",  # hozircha bosh
}


def get_conn():
    conn = sqlite3.connect(DB)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def column_exists(c, table, column):
    c.execute(f"PRAGMA table_info({table})")
    return any(r[1] == column for r in c.fetchall())


def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS questions ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "question TEXT UNIQUE,"
        "options TEXT,"
        "correct INTEGER,"
        "explanation TEXT DEFAULT '',"
        "role TEXT DEFAULT 'shifokor'"
        ")"
    )
    if not column_exists(c, "questions", "role"):
        c.execute("ALTER TABLE questions ADD COLUMN role TEXT DEFAULT 'shifokor'")
    c.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        "user_id INTEGER PRIMARY KEY,"
        "role TEXT,"
        "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    c.execute(
        "CREATE TABLE IF NOT EXISTS results ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "user_id INTEGER,"
        "question_id INTEGER,"
        "is_correct BOOLEAN,"
        "answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    conn.commit()

    c.execute("DELETE FROM questions WHERE role IS NULL OR role = ''")
    # Eski yozuvlar 'shifokor' deb saqlangan bo'lishi mumkin -> 'shifokor_1' ga ko'chiramiz
    c.execute("UPDATE questions SET role = 'shifokor_1' WHERE role = 'shifokor'")
    c.execute("UPDATE questions SET role = 'hamshira_2' WHERE role = 'hamshira'")
    conn.commit()

    for role, fname in ROLE_FILES.items():
        if not os.path.exists(fname):
            continue
        try:
            with open(fname, "r", encoding="utf-8") as f:
                qs = json.load(f)
        except Exception as e:
            print(f"{fname} ni o'qishda xato: {e}")
            continue
        imported = 0
        for q in qs:
            text = (q.get("question") or "").strip()
            if not text:
                continue
            try:
                c.execute(
                    "INSERT OR IGNORE INTO questions (question, options, correct, explanation, role) VALUES (?, ?, ?, ?, ?)",
                    (
                        text,
                        json.dumps(q.get("options", []), ensure_ascii=False),
                        q.get("correct", 0),
                        q.get("explanation", ""),
                        role,
                    ),
                )
                if c.rowcount > 0:
                    imported += 1
            except Exception:
                pass
        conn.commit()
        if imported > 0:
            print(f"{fname} dan {imported} ta '{role}' savoli import qilindi")

    conn.close()


init_db()

static_dir = "static"
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def root():
    return RedirectResponse(url="/static/index.html")


class UserRole(BaseModel):
    user_id: int
    role: str


class Answer(BaseModel):
    user_id: int
    question_id: int
    selected: int


def _normalize_role(bolim: str) -> str:
    """bo'lim/role argumentini standartlashtirish.
    Qabul qiladi: 'shifokor_1', 'shifokor', 'doctor_1', 'hamshira_2', 'nurse_3' va h.k.
    Qaytaradi: '<role>_<modul>' (default '<role>_1') yoki shunchaki role.
    """
    if not bolim:
        return "shifokor_1"
    b = bolim.strip().lower()
    # Modul raqamini ajratish: "shifokor_1" -> ("shifokor", "1")
    parts = b.replace("-", "_").split("_")
    base = parts[0]
    modul = parts[1] if len(parts) > 1 and parts[1].isdigit() else None
    # Rolni tarjima qilish
    if base in ("shifokor", "shifokorlar", "doctor", "doctors"):
        base = "shifokor"
    elif base in ("hamshira", "hamshiralar", "nurse", "nurses"):
        base = "hamshira"
    if modul:
        return f"{base}_{modul}"
    # Default: shifokor uchun 1-modul, hamshira uchun 2-modul
    return f"{base}_1" if base == "shifokor" else f"{base}_2"


@app.post("/api/register")
def register(data: UserRole):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO users (user_id, role) VALUES (?, ?)",
        (data.user_id, data.role),
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/api/questions")
def get_questions(user_id: int, bolim: str = "shifokor_1", count: int = 50):
    role = _normalize_role(bolim)
    if count < 1:
        count = 50
    if count > 200:
        count = 200
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, question, options, explanation FROM questions WHERE role = ?",
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
        }
        for r in selected
    ]


@app.post("/api/answer")
def submit_answer(data: Answer):
    conn = get_conn()
    row = conn.execute(
        "SELECT correct, explanation FROM questions WHERE id=?",
        (data.question_id,),
    ).fetchone()
    if not row:
        conn.close()
        return {"error": "Savol topilmadi"}
    correct_idx, explanation = row
    is_correct = data.selected == correct_idx
    conn.execute(
        "INSERT INTO results (user_id, question_id, is_correct) VALUES (?, ?, ?)",
        (data.user_id, data.question_id, is_correct),
    )
    conn.commit()
    conn.close()
    return {
        "is_correct": is_correct,
        "correct_index": correct_idx,
        "explanation": explanation or "",
    }


@app.get("/api/stats")
def get_stats(user_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*), SUM(is_correct) FROM results WHERE user_id=?",
        (user_id,),
    ).fetchone()
    conn.close()
    total, correct = row
    correct = correct or 0
    return {
        "total": total or 0,
        "correct": correct,
        "wrong": (total or 0) - correct,
        "percent": round(correct / total * 100) if total else 0,
    }


@app.get("/api/mistakes")
def get_mistakes(user_id: int, bolim: str = "shifokor_1", count: int = 50):
    role = _normalize_role(bolim)
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
        "SELECT id, question, options, correct, explanation FROM questions "
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
        }
        for r in rows
    ]


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
                "INSERT OR IGNORE INTO questions (question, options, correct, explanation, role) VALUES (?, ?, ?, ?, ?)",
                (
                    text,
                    json.dumps(q.get("options", []), ensure_ascii=False),
                    q.get("correct", 0),
                    q.get("explanation", ""),
                    role,
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
