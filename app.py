from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import sqlite3, json, random

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static fayllar (index.html)
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Ma'lumotlar bazasi ---
def init_db():
    conn = sqlite3.connect("argos.db")
    c = conn.cursor()
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
    conn.close()

init_db()

# --- Savollarni yuklash ---
def load_questions():
    with open("questions.json", "r", encoding="utf-8") as f:
        return json.load(f)

# --- Modellar ---
class UserRole(BaseModel):
    user_id: int
    role: str  # "shifokor" yoki "hamshira"

class Answer(BaseModel):
    user_id: int
    question_id: int
    selected: int  # tanlangan variant indeksi

# --- Endpointlar ---

@app.post("/api/register")
def register(data: UserRole):
    conn = sqlite3.connect("argos.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, role) VALUES (?, ?)", (data.user_id, data.role))
    conn.commit()
    conn.close()
    return {"status": "ok"}

@app.get("/api/questions")
def get_questions(user_id: int, count: int = 10):
    questions = load_questions()
    selected = random.sample(questions, min(count, len(questions)))
    clean = []
    for q in selected:
        clean.append({
            "id": q["id"],
            "question": q["question"],
            "options": q["options"],
            "explanation": q.get("explanation", "")
        })
    return clean

@app.post("/api/add_questions")
def add_questions(new_questions: list[dict]):
    """Yangi savollarni qo'shadi, dublikatlarni o'tkazib yuboradi"""
    existing = load_questions()

    # Mavjud savollar matnini set ga olish (tez qidirish uchun)
    existing_texts = {q["question"].strip().lower() for q in existing}

    added = 0
    skipped = 0
    next_id = max((q["id"] for q in existing), default=0) + 1

    for q in new_questions:
        text = q.get("question", "").strip().lower()
        if not text or text in existing_texts:
            skipped += 1
            continue
        q["id"] = next_id
        existing.append(q)
        existing_texts.add(text)
        next_id += 1
        added += 1

    with open("questions.json", "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    return {"added": added, "skipped": skipped, "total": len(existing)}

@app.post("/api/answer")
def submit_answer(data: Answer):
    questions = load_questions()
    q = next((x for x in questions if x["id"] == data.question_id), None)
    if not q:
        return {"error": "Savol topilmadi"}
    is_correct = data.selected == q["correct"]
    conn = sqlite3.connect("argos.db")
    c = conn.cursor()
    c.execute(
        "INSERT INTO results (user_id, question_id, is_correct) VALUES (?, ?, ?)",
        (data.user_id, data.question_id, is_correct)
    )
    conn.commit()
    conn.close()
    return {
        "is_correct": is_correct,
        "correct_index": q["correct"],
        "explanation": q.get("explanation", "")
    }

@app.get("/api/stats")
def get_stats(user_id: int):
    conn = sqlite3.connect("argos.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*), SUM(is_correct) FROM results WHERE user_id=?", (user_id,))
    total, correct = c.fetchone()
    conn.close()
    correct = correct or 0
    return {
        "total": total or 0,
        "correct": correct,
        "wrong": (total or 0) - correct,
        "percent": round(correct / total * 100) if total else 0
    }

@app.get("/api/mistakes")
def get_mistakes(user_id: int):
    questions = load_questions()
    conn = sqlite3.connect("argos.db")
    c = conn.cursor()
    c.execute("""
        SELECT question_id FROM results
        WHERE user_id=? AND is_correct=0
        GROUP BY question_id
    """, (user_id,))
    wrong_ids = [row[0] for row in c.fetchall()]
    conn.close()
    mistakes = [q for q in questions if q["id"] in wrong_ids]
    return mistakes