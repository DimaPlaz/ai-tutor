import secrets

from pydantic import BaseModel

from tutor_bot.services.solver import Solution

MAX_FOLLOWUPS = 5


class FollowUpTurn(BaseModel):
    request: str
    reply: str


class TaskContext(BaseModel):
    """Текущая задача ученика: всё, что нужно Claude для ответа на уточнения."""

    task_id: str
    problem: str
    steps: list[str]
    answer: str
    history: list[FollowUpTurn] = []

    @classmethod
    def from_solution(cls, solution: Solution) -> TaskContext:
        return cls(
            task_id=secrets.token_hex(4),
            problem=solution.problem,
            steps=solution.steps,
            answer=solution.answer,
        )

    @property
    def followups_left(self) -> int:
        return max(MAX_FOLLOWUPS - len(self.history), 0)

    def with_turn(self, request: str, reply: str) -> TaskContext:
        turn = FollowUpTurn(request=request, reply=reply)
        return self.model_copy(update={"history": [*self.history, turn]})
