from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from tutor_bot.bot.texts import t


class TaskAction(CallbackData, prefix="task"):
    # task_id нужен, чтобы кнопки под старой задачей не срабатывали на новую
    action: str
    task_id: str


class LangChoice(CallbackData, prefix="lang"):
    lang: str


SIMPLER = "simpler"
CHECK = "check"
NEW = "new"


def task_keyboard(task_id: str, lang: str, followups_left: int) -> InlineKeyboardMarkup:
    new_button = InlineKeyboardButton(
        text=t("btn_new", lang), callback_data=TaskAction(action=NEW, task_id=task_id).pack()
    )
    if followups_left == 0:
        return InlineKeyboardMarkup(inline_keyboard=[[new_button]])
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("btn_simpler", lang),
                    callback_data=TaskAction(action=SIMPLER, task_id=task_id).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=t("btn_check", lang),
                    callback_data=TaskAction(action=CHECK, task_id=task_id).pack(),
                )
            ],
            [new_button],
        ]
    )


def lang_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data=LangChoice(lang="ru").pack()),
                InlineKeyboardButton(text="🇬🇧 English", callback_data=LangChoice(lang="en").pack()),
            ]
        ]
    )
