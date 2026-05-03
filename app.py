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


def get_conn():
    return sqlite3.connect(DB)


def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT UNIQUE,
            options TEXT,
            correct INTEGER,
            explanation TEXT DEFAULT ''
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            role TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            question_id INTEGER,
            is_correct BOOLEAN,
            answered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    if os.path.exists("questions.json"):
        with open("questions.json", "r", encoding="utf-8") as f:
            qs = json.load(f)
        imported = 0
        for q in qs:
            try:
                c.execute(
                    "INSERT OR IGNORE INTO questions (question, options, correct, explanation) VALUES (?, ?, ?, ?)",
                    (q["question"], json.dumps(q["options"], ensure_ascii=False), q["correct"], q.get("explanation", ""))
                )
                if c.rowcount > 0:
                    imported += 1
            except Exception:
                pass
        conn.commit()
        if imported > 0:
            print(f"questions.json dan {imported} ta savol import qilindi")

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


@app.post("/api/register")
def register(data: UserRole):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO users (user_id, role) VALUES (?, ?)",
        (data.user_id, data.role)
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


@app.get("/api/questions")
def get_questions(user_id: int, bolim: str = "", count: int = 40):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, question, options, explanation FROM questions"
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
            "explanation": r[3] or ""
        }
        for r in selected
    ]


@app.post("/api/answer")
def submit_answer(data: Answer):
    conn = get_conn()
    row = conn.execute(
        "SELECT correct, explanation FROM questions WHERE id=?",
        (data.question_id,)
    ).fetchone()
    if not row:
        conn.close()
        return {"error": "Savol topilmadi"}
    correct_idx, explanation = row
    is_correct = data.selected == correct_idx
    conn.execute(
        "INSERT INTO results (user_id, question_id, is_correct) VALUES (?, ?, ?)",
        (data.user_id, data.question_id, is_correct)
    )
    conn.commit()
    conn.close()
    return {
        "is_correct": is_correct,
        "correct_index": correct_idx,
        "explanation": explanation or ""
    }


@app.get("/api/stats")
def get_stats(user_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*), SUM(is_correct) FROM results WHERE user_id=?",
        (user_id,)
    ).fetchone()
    conn.close()
    total, correct = row
    correct = correct or 0
    return {
        "total": total or 0,
        "correct": correct,
        "wrong": (total or 0) - correct,
        "percent": round(correct / total * 100) if total else 0
    }


@app.get("/api/mistakes")
def get_mistakes(user_id: int):
    conn = get_conn()
    wrong_ids = [r[0] for r in conn.execute(
        "SELECT DISTINCT question_id FROM results WHERE user_id=? AND is_correct=0",
        (user_id,)
    ).fetchall()]
    if not wrong_ids:
        conn.close()
        return []
    placeholders = ",".join("?" * len(wrong_ids))
    rows = conn.execute(
        f"SELECT id, question, options, correct, explanation FROM questions WHERE id IN ({placeholders})",
        wrong_ids
    ).fetchall()
    conn.close()
    return [
        {
            "id": r[0],
            "question": r[1],
            "options": json.loads(r[2]),
            "correct": r[3],
            "explanation": r[4] or ""
        }
        for r in rows
    ]


@app.post("/api/add_questions")
async def add_questions(new_questions: List[Dict[str, Any]]):
    conn = get_conn()
    added = 0
    skipped = 0
    for q in new_questions:
        text = q.get("question", "").strip()
        if not text:
            skipped += 1
            continue
        try:
            conn.execute(
                "INSERT OR IGNORE INTO questions (question, options, correct, explanation) VALUES (?, ?, ?, ?)",
                (text, json.dumps(q.get("options", []), ensure_ascii=False), q.get("correct", 0), q.get("explanation", ""))
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
def total_questions():
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
    conn.close()
    return {"total": total}