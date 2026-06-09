# SKVA ProjectLayout
import sys,os
from pathlib import Path
sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skva_core import log

from pathlib import Path
import logging
from typing import List

logger = logging.getLogger(__name__)


class ProjectLayout:
    """
    Encapsulates the directory layout for a SKVA project.
    Ensures consistent use of Path objects and provides methods to access standard directories.
    Creates directories on demand via ensure_dirs().
    """

    def __init__(self, project_dir):
        """
        Initialize the project layout.

        :param project_dir: Path-like object (str or Path) pointing to the project root.
        """
        self.project_dir = Path(project_dir).resolve()
        self._skva_dir = None

    def skva_dir(self) -> Path:
        """
        Returns the path to the .skva directory inside the project directory.
        """
        if self._skva_dir is None:
            self._skva_dir = self.project_dir / ".skva"
        return self._skva_dir

    def gates_dir(self) -> Path:
        """
        Returns the path to the gates directory.
        """
        return self.skva_dir() / "gates"

    def checkpoints_dir(self) -> Path:
        """
        Returns the path to the checkpoints directory.
        """
        return self.skva_dir() / "checkpoints"

    def agents_dir(self) -> Path:
        """
        Returns the path to the agents directory.
        """
        return self.skva_dir() / "agents"

    def feedback_dir(self) -> Path:
        """
        Returns the path to the feedback directory.
        """
        return self.skva_dir() / "feedback"

    def logs_dir(self) -> Path:
        """
        Returns the path to the logs directory.
        """
        return self.skva_dir() / "logs"

    def skills_dir(self) -> Path:
        """
        Returns the path to the skills directory.
        """
        return self.skva_dir() / "skills"

    def improvements_dir(self) -> Path:
        """
        Returns the path to the improvements directory.
        """
        return self.skva_dir() / "improvements"

    def ensure_dirs(self) -> List[Path]:
        """
        Ensures all required directories exist. Creates them if they don't.
        Returns a list of directories that were created (i.e., didn't exist before).
        """
        dirs_to_create = [
            self.skva_dir(),
            self.gates_dir(),
            self.checkpoints_dir(),
            self.agents_dir(),
            self.feedback_dir(),
            self.logs_dir(),
            self.skills_dir(),
            self.improvements_dir(),
        ]

        created_dirs = []
        for directory in dirs_to_create:
            try:
                if not directory.exists():
                    directory.mkdir(parents=True, exist_ok=True)
                    created_dirs.append(directory)
                    logger.debug(f"Created directory: {directory}")
                else:
                    logger.debug(f"Directory already exists: {directory}")
            except Exception as e:
                logger.error(f"Failed to create directory {directory}: {e}")
                raise

        return created_dirs
