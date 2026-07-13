import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from threading import Lock


class RunLogger:
    """Write the small, fixed set of artifacts for one game run."""

    def __init__(self, log_path: str):
        self.root = Path(log_path)
        self.obs_dir = self.root / "obs"
        self.im_dir = self.root / "im"
        self.bm_dir = self.root / "bm"
        for directory in (self.root, self.obs_dir, self.im_dir, self.bm_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.overview_path = self.root / "overview.json"
        self._lock = Lock()
        self._overview = None

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _write_json(path: Path, payload) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.replace(temp_path, path)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def initialize_overview(self, config: dict) -> None:
        with self._lock:
            self._overview = {
                "config": config,
                "started_at": self._now(),
                "result": None,
                "counts": {
                    "im_decisions": 0,
                    "bm_tasks": 0,
                    "bm_published": 0,
                    "bm_errors": 0,
                },
            }
            self._write_json(self.overview_path, self._overview)

    def _update_overview(self, updater) -> None:
        with self._lock:
            if self._overview is None:
                self._overview = {
                    "config": {},
                    "started_at": self._now(),
                    "result": None,
                    "counts": {
                        "im_decisions": 0,
                        "bm_tasks": 0,
                        "bm_published": 0,
                        "bm_errors": 0,
                    },
                }
            updater(self._overview)
            self._write_json(self.overview_path, self._overview)

    def save_observation(self, tick: int, text: str) -> str:
        filename = f"{tick:06d}.txt"
        path = self.obs_dir / filename
        with self._lock:
            path.write_text(text, encoding="utf-8")
        return f"../obs/{filename}"

    def save_im(self, tick: int, payload: dict) -> None:
        self._write_json(self.im_dir / f"{tick:06d}.json", payload)

        def update(overview):
            overview["counts"]["im_decisions"] += 1

        self._update_overview(update)

    def save_bm(self, task_id: int, payload: dict) -> None:
        self._write_json(self.bm_dir / f"{task_id:04d}.json", payload)

        def update(overview):
            overview["counts"]["bm_tasks"] += 1
            status = payload.get("status")
            if status == "published":
                overview["counts"]["bm_published"] += 1
            elif status == "error":
                overview["counts"]["bm_errors"] += 1

        self._update_overview(update)

    def finalize(self, result: dict) -> None:
        def update(overview):
            overview["result"] = result

        self._update_overview(update)
