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
}


def t(key: str, lang: str) -> str:
    return TEXTS[key][lang]
