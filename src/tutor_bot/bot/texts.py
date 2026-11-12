TEXTS: dict[str, dict[str, str]] = {
    "start": {
        "ru": (
            "Привет! Я помогу с домашкой 📚\n\n"
            "Пришли фото задачи или напиши её текстом — я решу её по шагам "
            "и объясню каждый шаг.\n\n"
            "Предметы: математика, физика, химия, русский и английский язык."
        ),
        "en": (
            "Hi! I'll help you with your homework 📚\n\n"
            "Send a photo of a problem or type it in — I'll solve it step by step "
            "and explain every step.\n\n"
            "Subjects: math, physics, chemistry, Russian and English."
        ),
    },
    "solution_problem": {"ru": "📝 Условие", "en": "📝 Problem"},
    "solution_steps": {"ru": "🧩 Решение", "en": "🧩 Solution"},
    "solution_answer": {"ru": "✅ Ответ:", "en": "✅ Answer:"},
    "unreadable": {
        "ru": (
            "Не получилось разобрать фото 😕 Сфотографируй задачу ещё раз: "
            "ровно, при хорошем свете и чтобы условие было целиком в кадре."
        ),
        "en": (
            "I couldn't read the photo 😕 Please take it again: straight on, "
            "in good light, with the whole problem in the frame."
        ),
    },
    "not_a_problem": {
        "ru": (
            "Не вижу здесь школьной задачи 🤔 Пришли фото или текст задачи "
            "по математике, физике, химии, русскому или английскому."
        ),
        "en": (
            "I don't see a school problem here 🤔 Send a photo or the text of a problem "
            "in math, physics, chemistry, Russian or English."
        ),
    },
    "llm_refused": {
        "ru": "Не могу помочь с этим запросом. Попробуй прислать другую задачу.",
        "en": "I can't help with this request. Please try another problem.",
    },
    "llm_truncated": {
        "ru": (
            "Решение получилось слишком длинным 😅 Пришли задачу частями или одну задачу за раз."
        ),
        "en": "The solution got too long 😅 Please send one problem at a time or split it up.",
    },
    "llm_unavailable": {
        "ru": "Что-то пошло не так, не смог решить задачу. Попробуй ещё раз через минуту 🙏",
        "en": "Something went wrong and I couldn't solve it. Please try again in a minute 🙏",
    },
    "btn_simpler": {"ru": "🤔 Не понял, объясни проще", "en": "🤔 I don't get it, explain simpler"},
    "btn_check": {"ru": "✍️ Проверь мой ответ", "en": "✍️ Check my answer"},
    "btn_new": {"ru": "📸 Новая задача", "en": "📸 New problem"},
    "ask_answer": {
        "ru": "Напиши свой ответ, я проверю 👇",
        "en": "Type your answer and I'll check it 👇",
    },
    "verdict_correct": {"ru": "✅ Верно!", "en": "✅ Correct!"},
    "verdict_partial": {"ru": "🟡 Почти верно", "en": "🟡 Almost there"},
    "verdict_incorrect": {"ru": "❌ Пока неверно", "en": "❌ Not quite yet"},
    "followups_over": {
        "ru": (
            "По этой задаче я уже ответил на 5 уточнений — это максимум. Пришли новую задачу 📸"
        ),
        "en": (
            "I've already answered 5 follow-ups on this problem — that's the maximum. "
            "Send a new problem 📸"
        ),
    },
    "task_closed": {
        "ru": "Эта задача уже закрыта. Пришли новую 🙂",
        "en": "This problem is already closed. Send a new one 🙂",
    },
    "new_task_prompt": {
        "ru": "Жду новую задачу: пришли фото или напиши её текстом 📸",
        "en": "Ready for a new problem: send a photo or type it in 📸",
    },
    "lang_choose": {"ru": "Выбери язык:", "en": "Choose a language:"},
    "lang_set": {
        "ru": "Готово, теперь отвечаю по-русски 🇷🇺",
        "en": "Done, I'll answer in English now 🇬🇧",
    },
    "cmd_start": {"ru": "Начать", "en": "Start"},
    "cmd_lang": {"ru": "Язык / Language", "en": "Language / Язык"},
}


def t(key: str, lang: str) -> str:
    return TEXTS[key][lang]
