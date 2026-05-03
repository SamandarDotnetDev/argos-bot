import asyncio
import json
from telethon import TelegramClient
from telethon.tl.types import MessageMediaPoll

API_ID = 32599427          # my.telegram.org dan olingan
API_HASH = "4c94a696dc744d619b19789b93ed4709"  # my.telegram.org dan olingan
KANAL = -1001234567890     # private kanal ID (-100 bilan boshlanadi)

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
    q_id = 1

    async for msg in client.iter_messages(entity, limit=5000):
        # Faqat quiz (poll) xabarlarni olish
        if not msg.media or not isinstance(msg.media, MessageMediaPoll):
            continue

        poll = msg.media.poll
        results = msg.media.results

        # Savol matni
        try:
            question_text = poll.question.text
        except AttributeError:
            question_text = str(poll.question)

        # Variantlar
        options = []
        for ans in poll.answers:
            try:
                options.append(ans.text.text)
            except AttributeError:
                options.append(str(ans.text))

        # To'g'ri javob indeksi
        correct = 0
        if results and results.results:
            for i, r in enumerate(results.results):
                if getattr(r, "correct", False):
                    correct = i
                    break

        questions.append({
            "id": q_id,
            "question": question_text,
            "options": options,
            "correct": correct,
            "explanation": ""
        })

        print(f"✅ {q_id}-savol: {question_text[:60]}...")
        q_id += 1

    if not questions:
        print("❌ Hech qanday quiz savoli topilmadi.")
        await client.disconnect()
        return

    # questions.json ga saqlash
    with open("questions.json", "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)

    print(f"\n🎉 Jami {len(questions)} ta savol saqlandi → questions.json")
    await client.disconnect()

asyncio.run(main())