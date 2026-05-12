import asyncio
import json
import os
import aiohttp  # pip install aiohttp
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPoll

# === Maxfiy ma'lumotlar — environment variables orqali yuklanadi ===
# my.telegram.org dan olinadi.
# Lokalda .env faylidan (gitignore'ga qo'shilgan), Railwayda Variables bo'limidan o'qiladi.
API_ID = int(os.environ.get("API_ID", "0") or "0")
API_HASH = os.environ.get("API_HASH", "").strip()
KANAL = os.environ.get("KANAL", "@argos_testlarim").strip()
API_URL = os.environ.get(
    "API_URL",
    "https://argos-bot-production.up.railway.app/api/add_questions",
).strip()

if not API_ID or not API_HASH:
    raise RuntimeError(
        "API_ID va API_HASH environment variables o'rnatilmagan. "
        "my.telegram.org dan olib, Railway > Variables bo'limiga qo'shing."
    )


async def main():
    client = TelegramClient("session", API_ID, API_HASH)
    await client.start()

    try:
        entity = await client.get_entity(KANAL)
        print(f"Kanal topildi: {entity.title}")
    except Exception as e:
        print(f"Kanal topilmadi: {e}")
        print("Kanal ID ni tekshiring yoki kanalga a'zo ekanligingizni tasdiqlang.")
        await client.disconnect()
        return

    print("Savollar o'qilmoqda...\n")
    questions = []

    async for msg in client.iter_messages(entity, limit=5000):
        if not msg.media or not isinstance(msg.media, MessageMediaPoll):
            continue

        poll = msg.media.poll
        results = msg.media.results

        try:
            question_text = poll.question.text
        except AttributeError:
            question_text = str(poll.question)

        options = []
        for ans in poll.answers:
            try:
                options.append(ans.text.text)
            except AttributeError:
                options.append(str(ans.text))

        correct = 0
        if results and results.results:
            for i, r in enumerate(results.results):
                if getattr(r, "correct", False):
                    correct = i
                    break

        questions.append({
            "question": question_text,
            "options": options,
            "correct": correct,
            "explanation": "",
        })
        print(f"{len(questions)}-savol: {question_text[:60]}...")

    if not questions:
        print("Hech qanday quiz topilmadi.")
        await client.disconnect()
        return

    async with aiohttp.ClientSession() as session:
        async with session.post(API_URL, json=questions) as resp:
            text = await resp.text()
            print(f"\nServer javobi: {text}")
            try:
                result = json.loads(text)
                print(f"\nQo'shildi: {result['added']} ta")
                print(f"O'tkazib yuborildi (dublikat): {result['skipped']} ta")
                print(f"Jami savollar: {result['total']} ta")
            except Exception as e:
                print(f"Xato: {e}")

    await client.disconnect()


asyncio.run(main())
