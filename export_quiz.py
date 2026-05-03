import asyncio
import json
import aiohttp  # pip install aiohttp
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPoll


API_ID = 32599427          # my.telegram.org dan olingan
API_HASH = "4c94a696dc744d619b19789b93ed4709"  # my.telegram.org dan olingan
#KANAL = -1001234567890     # private kanal ID (-100 bilan boshlanadi)
KANAL = "@argos_testlarim" 
# ↓↓↓ SHU YERGA RAILWAY URL INI QO'YING ↓↓↓
API_URL = "https://argos-bot-production.up.railway.app/api/add_questions"  # API endpoint URL

async def main():
    client = TelegramClient("session", API_ID, API_HASH)
    await client.start()

    # Kanal mavjudligini tekshirish
    try:
        entity = await client.get_entity(KANAL)
        print(f"✅ Kanal topildi: {entity.title}")
    except Exception as e:
        print(f"❌ Kanal topilmadi: {e}")
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
            "explanation": ""
        })
        print(f"✅ {len(questions)}-savol: {question_text[:60]}...")

    if not questions:
        print("❌ Hech qanday quiz topilmadi.")
        await client.disconnect()
        return

    # API orqali yuborish (dublikat tekshiruvi bilan)
    async with aiohttp.ClientSession() as session:
        async with session.post(API_URL, json=questions) as resp:
            text = await resp.text()
            print(f"\nServer javobi: {text}")
            try:
                result = json.loads(text)
                print(f"\n✅ Qo'shildi: {result['added']} ta")
                print(f"⏭️  O'tkazib yuborildi (dublikat): {result['skipped']} ta")
                print(f"📦 Jami savollar: {result['total']} ta")
            except Exception as e:
                print(f"❌ Xato: {e}")

    await client.disconnect()

asyncio.run(main())