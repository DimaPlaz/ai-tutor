"""Решения и уточнения с учётом лимитов: проверка доступа → вызов LLM → запись расходов."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from tutor_bot.db.models import User
from tutor_bot.llm.client import ImageInput, LLMError
from tutor_bot.services.limits import Limits
from tutor_bot.services.llm_json import LLMCall, call_from_usages
from tutor_bot.services.solver import Solution, SolutionStatus, Solver
from tutor_bot.services.tasks import TaskContext
from tutor_bot.services.throttle import Throttle
from tutor_bot.services.tutor import FollowUpReply, NewProblemDetected, Tutor


@dataclass(frozen=True, slots=True)
class SolveResult:
    solution: Solution
    task: TaskContext | None  # None, если задачи нет (нечитаемо / не задача)


class Assistant:
    def __init__(self, limits: Limits, solver: Solver, tutor: Tutor, throttle: Throttle) -> None:
        self._limits = limits
        self._solver = solver
        self._tutor = tutor
        self._throttle = throttle

    async def solve(self, user: User, text: str | None, image: ImageInput | None) -> SolveResult:
        await self._limits.check(user, new_solution=True)
        solution = await self._metered(
            user, "solve", None, lambda: self._solver.solve(user.language, text, image)
        )
        task = None
        if solution.status is SolutionStatus.OK:
            task = TaskContext.from_solution(solution)
        # Решение списываем только за успешный ответ с задачей
        await self._limits.record(
            user,
            "solve",
            solution.call,
            task_id=task.task_id if task else None,
            charged=task is not None,
        )
        return SolveResult(solution, task)

    async def explain_simpler(self, user: User, task: TaskContext) -> FollowUpReply:
        await self._check_followup(user)
        reply = await self._metered(
            user, "simpler", task, lambda: self._tutor.explain_simpler(user.language, task)
        )
        await self._record_followup(user, "simpler", task, reply.call)
        return reply

    async def check_answer(self, user: User, task: TaskContext, answer: str) -> FollowUpReply:
        await self._check_followup(user)
        reply = await self._metered(
            user, "check", task, lambda: self._tutor.check_answer(user.language, task, answer)
        )
        await self._record_followup(user, "check", task, reply.call)
        return reply

    async def answer_question(
        self, user: User, task: TaskContext, question: str
    ) -> FollowUpReply | NewProblemDetected:
        await self._check_followup(user)
        result = await self._metered(
            user,
            "question",
            task,
            lambda: self._tutor.answer_question(user.language, task, question),
        )
        await self._record_followup(user, "question", task, result.call)
        return result

    async def remaining_free_solutions(self, user: User) -> int | None:
        """None для подписчика: у него нет лимита по числу решений."""
        if self._limits.is_subscribed(user):
            return None
        return await self._limits.remaining_free_solutions(user)

    async def _check_followup(self, user: User) -> None:
        await self._limits.check(user, new_solution=False)

    async def _record_followup(
        self, user: User, kind: str, task: TaskContext, call: LLMCall
    ) -> None:
        await self._limits.record(user, kind, call, task_id=task.task_id, charged=False)

    async def _metered[T](
        self,
        user: User,
        kind: str,
        task: TaskContext | None,
        run: Callable[[], Awaitable[T]],
    ) -> T:
        """Вызов LLM под антиспамом; при ошибке оплаченные токены всё равно идут в бюджет."""
        try:
            async with self._throttle.slot(user.id):
                return await run()
        except LLMError as e:
            failed = call_from_usages(e.usages)
            if failed is not None:
                task_id = task.task_id if task else None
                await self._limits.record(user, kind, failed, task_id=task_id, charged=False)
            raise
