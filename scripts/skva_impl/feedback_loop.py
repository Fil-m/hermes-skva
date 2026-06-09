# SKVA FeedbackLoop
import sys,os,json,time
from pathlib import Path
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skva_core import log

class FeedbackLoop:
    def __init__(self, project_dir):
        self.project_dir = Path(project_dir)
        self.feedback_dir = self.project_dir / SKVA_DIR / "feedback"
        self.feedback_dir.mkdir(parents=True, exist_ok=True)
        self.log = getattr(sys.modules[__name__], 'log', print)

    def submit(self, phase: str, status: str, user_comment: str) -> str:
        from uuid import uuid4
        feedback_id = str(uuid4())
        timestamp = time.time()
        data = {
            "id": feedback_id,
            "phase": phase,
            "status": status,
            "user_comment": user_comment,
            "timestamp": timestamp,
            "resolved": False,
            "action": None
        }
        file_path = self.feedback_dir / f"{feedback_id}.json"
        try:
            file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            self.log(f"[Feedback] Submitted: {feedback_id} for phase '{phase}' with status '{status}'")
            return feedback_id
        except Exception as e:
            self.log(f"[Feedback] Failed to submit: {e}")
            return ""

    def list(self, phase=None, status=None) -> list:
        feedbacks = []
        try:
            for file in self.feedback_dir.glob("*.json"):
                try:
                    data = json.loads(file.read_text(encoding="utf-8"))
                    matches_phase = phase is None or data.get("phase") == phase
                    matches_status = status is None or data.get("status") == status
                    if matches_phase and matches_status:
                        feedbacks.append(data)
                except Exception as e:
                    self.log(f"[Feedback] Error reading {file}: {e}")
        except Exception as e:
            self.log(f"[Feedback] Error accessing feedback directory: {e}")
        return sorted(feedbacks, key=lambda x: x.get("timestamp", 0), reverse=True)

    def get(self, feedback_id) -> dict:
        file_path = self.feedback_dir / f"{feedback_id}.json"
        try:
            if file_path.exists():
                data = json.loads(file_path.read_text(encoding="utf-8"))
                return data
            else:
                self.log(f"[Feedback] Not found: {feedback_id}")
                return {}
        except Exception as e:
            self.log(f"[Feedback] Error loading {feedback_id}: {e}")
            return {}

    def react(self, feedback_id, action: str) -> bool:
        valid_actions = {"retry", "rollback", "skip", "restart"}
        if action not in valid_actions:
            self.log(f"[Feedback] Invalid action: {action}. Must be one of {valid_actions}")
            return False

        data = self.get(feedback_id)
        if not data:
            return False

        try:
            data["resolved"] = True
            data["action"] = action
            file_path = self.feedback_dir / f"{feedback_id}.json"
            file_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
            self.log(f"[Feedback] Action applied: {action} on {feedback_id}")
            return True
        except Exception as e:
            self.log(f"[Feedback] Failed to apply action {action}: {e}")
            return False

    def stats(self) -> dict:
        all_feedbacks = self.list()
        if not all_feedbacks:
            return {
                "total": 0,
                "success_rate": 0.0,
                "common_errors": {}
            }

        total = len(all_feedbacks)
        successes = sum(1 for f in all_feedbacks if f.get("status") == "success")
        errors = [f for f in all_feedbacks if f.get("status") != "success"]

        error_counts = {}
        for e in errors:
            phase = e.get("phase", "unknown")
            error_counts[phase] = error_counts.get(phase, 0) + 1

        success_rate = round(successes / total * 100, 2) if total > 0 else 0.0

        return {
            "total": total,
            "success_rate": success_rate,
            "common_errors": dict(sorted(error_counts.items(), key=lambda x: -x[1]))
        }
