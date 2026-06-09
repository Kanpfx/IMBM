from copy import deepcopy


QUEUE_NAMES = ("economy_build", "production_tech", "combat")
WAITING = "waiting"
BLOCKED = "blocked"
DONE = "done"


class ActionQueueStore:
    def __init__(self):
        self.queues = {name: [] for name in QUEUE_NAMES}
        self.blocked_feedback = []

    def snapshot(self) -> dict:
        return deepcopy(self.queues)

    def feedback_snapshot(self) -> list:
        return deepcopy(self.blocked_feedback[-20:])

    def has_waiting_tasks(self) -> bool:
        return any(self.first_waiting(name) is not None for name in QUEUE_NAMES)

    def has_queue_pressure(self, max_tasks_per_queue: int = 5) -> bool:
        return any(len(self.queues.get(name, [])) > max_tasks_per_queue for name in QUEUE_NAMES)

    def first_waiting(self, queue_name: str) -> dict | None:
        for task in self.queues.get(queue_name, []):
            if task.get("status") == WAITING and task.get("task"):
                return deepcopy(task)
        return None

    def append_tasks(self, tasks: list) -> list:
        accepted = []
        for item in tasks:
            if not isinstance(item, dict):
                continue
            queue_name = item.get("queue")
            status = item.get("status")
            task_text = item.get("task")
            if queue_name not in QUEUE_NAMES:
                continue
            if status != WAITING:
                continue
            if not isinstance(task_text, str) or not task_text.strip():
                continue
            task = {
                "status": WAITING,
                "task": task_text.strip(),
                "retry_count": 0,
            }
            self.queues[queue_name].append(task)
            accepted.append({"queue": queue_name, **task})
        return accepted

    def mark_done(self, queue_name: str, task_text: str) -> None:
        for idx, task in enumerate(self.queues.get(queue_name, [])):
            if task.get("status") == WAITING and task.get("task") == task_text:
                self.queues[queue_name].pop(idx)
                return

    def mark_blocked(self, queue_name: str, task_text: str, reason: str, max_retries: int = 1) -> str:
        for idx, task in enumerate(self.queues.get(queue_name, [])):
            if task.get("status") == WAITING and task.get("task") == task_text:
                retry_count = int(task.get("retry_count", 0))
                if retry_count < max_retries:
                    task["retry_count"] = retry_count + 1
                    outcome = "retry"
                else:
                    self.queues[queue_name].pop(idx)
                    outcome = "dropped"
                break
        else:
            outcome = "missing"
        self.blocked_feedback.append(
            {
                "queue": queue_name,
                "task": task_text,
                "reason": reason,
                "outcome": outcome,
            }
        )
        return outcome
