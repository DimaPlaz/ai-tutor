"""Текущая задача ученика в FSM (Redis). Срок хранения задаётся в RedisStorage."""

from datetime import timedelta

from aiogram.fsm.context import FSMContext

from tutor_bot.services.tasks import TaskContext

TASK_TTL = timedelta(hours=24)
_TASK_KEY = "task"


async def load_task(state: FSMContext) -> TaskContext | None:
    raw = (await state.get_data()).get(_TASK_KEY)
    return TaskContext.model_validate(raw) if raw else None


async def start_task(state: FSMContext, task: TaskContext) -> None:
    await state.set_state(None)
    await state.set_data({_TASK_KEY: task.model_dump()})


async def save_task(state: FSMContext, task: TaskContext) -> None:
    await state.update_data({_TASK_KEY: task.model_dump()})


async def clear_task(state: FSMContext) -> None:
    await state.clear()
