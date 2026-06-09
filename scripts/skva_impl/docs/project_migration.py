#!/usr/bin/env python3
"""
SKVA Project Migration Module — Safe project copying, archiving,
import/export, and integrity validation.
"""
import os
import sys
import shutil
import tarfile
import zipfile
import logging
from pathlib import Path
from typing import List, Optional
import tempfile

# Configure basic logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(levelname)s] %(message)s',
)
log = logging.getLogger("skva.migration")

# Constants
HERMES_HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes"))
SKVA_DIR = ".skva"
SUPPORTED_ARCHIVE_TYPES = ("zip", "tar", "tar.gz", "tgz")

# Auto-import skva_impl components (for compatibility)
try:
    from skva_impl.checkpoint_system import CheckpointSystem
except ImportError:
    CheckpointSystem = None
try:
    from skva_impl.git_sync import GitSync
except ImportError:
    GitSync = None
try:
    from skva_impl.auto_mode import AutoMode
except ImportError:
    AutoMode = None
try:
    from skva_impl.dashboard import Dashboard
except ImportError:
    Dashboard = None
try:
    from skva_impl.gate_notifications import NotificationGateway
except ImportError:
    NotificationGateway = None
try:
    from skva_impl.agent_registry import AgentRegistry
except ImportError:
    AgentRegistry = None
try:
    from skva_impl.feedback_loop import FeedbackLoop
except ImportError:
    FeedbackLoop = None


def log_info(msg: str):
    log.info(msg)


def log_error(msg: str):
    log.error(msg)


def log_warning(msg: str):
    log.warning(msg)


def validate_project(project_dir: str) -> List[str]:
    """
    Validate the integrity of an SKVA project.

    Checks:
    - Presence of .skva/ directory
    - Required subdirectories (checkpoints, logs, state, artifacts)
    - Permissions and accessibility
    - Optional: Git repo status (if GitSync is available)

    Returns:
        List of error messages. Empty list means valid.
    """
    errors: List[str] = []
    proj_path = Path(project_dir).resolve()

    if not proj_path.exists():
        errors.append(f"Project directory does not exist: {proj_path}")
        return errors

    skva_path = proj_path / SKVA_DIR
    if not skva_path.exists():
        errors.append(f"Missing SKVA directory: {skva_path}")
    else:
        required_dirs = ["checkpoints", "logs", "state", "artifacts"]
        for dname in required_dirs:
            dpath = skva_path / dname
            if not dpath.exists():
                errors.append(f"Missing required directory: {dpath}")
            elif not dpath.is_dir():
                errors.append(f"Required path is not a directory: {dpath}")

        # Check write permissions
        if not os.access(skva_path, os.W_OK):
            errors.append(f"SKVA directory is not writable: {skva_path}")

    # Optional Git validation
    if GitSync and (proj_path / ".git").exists():
        try:
            # Simple check: ensure git dir is accessible
            git_head = proj_path / ".git" / "HEAD"
            if not git_head.exists():
                log_warning(f"Git repository appears corrupted: {git_head}")
        except Exception as e:
            errors.append(f"Git validation error: {e}")

    return errors


def migrate_project(src_dir: str, dst_dir: str) -> bool:
    """
    Migrate an SKVA project from src_dir to dst_dir.

    Copies:
    - The entire project tree
    - The .skva/ metadata and artifact directory

    Preserves permissions and handles conflicts.

    Returns:
        True on success, False on failure.
    """
    src = Path(src_dir).resolve()
    dst = Path(dst_dir).resolve()

    if not src.exists():
        log_error(f"Source directory does not exist: {src}")
        return False

    if dst.exists() and not dst.is_dir():
        log_error(f"Destination path exists and is not a directory: {dst}")
        return False

    if dst.exists() and any(dst.iterdir()):
        log_error(f"Destination directory is not empty: {dst}")
        return False

    try:
        # Ensure parent of dst exists
        dst.parent.mkdir(parents=True, exist_ok=True)

        # Use shutil.copytree for full copy
        shutil.copytree(
            src, dst,
            symlinks=False,
            ignore=None,
            copy_function=shutil.copy2,  # Preserve metadata
            dirs_exist_ok=False
        )
        log_info(f"Project migrated successfully: {src} → {dst}")
        return True

    except Exception as e:
        log_error(f"Failed to migrate project: {e}")
        if dst.exists():
            try:
                shutil.rmtree(dst)
                log_info(f"Cleaned up incomplete destination: {dst}")
            except:
                pass
        return False


def export_project(project_dir: str, output_path: str) -> str:
    """
    Export the SKVA project into a compressed archive.

    Supports formats:
      - .zip
      - .tar
      - .tar.gz or .tgz

    Returns:
        Absolute path to the created archive.
    Raises:
        Exception on failure.
    """
    proj_path = Path(project_dir).resolve()
    out_path = Path(output_path).resolve()

    if not proj_path.exists():
        raise FileNotFoundError(f"Project directory not found: {proj_path}")

    if not validate_project(project_dir):
        log_warning("Project has validation issues — proceeding anyway...")

    # Detect archive format
    if out_path.suffix == ".zip":
        archive_format = "zip"
    elif out_path.suffix == ".tar":
        archive_format = "tar"
    elif out_path.suffix in (".gz", ".tgz") and out_path.suffixes[0] == ".tar":
        archive_format = "tar.gz"
    else:
        raise ValueError(
            f"Unsupported archive format. Use one of: {SUPPORTED_ARCHIVE_TYPES}"
        )

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)

        if archive_format == "zip":
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
                _archive_directory(proj_path, proj_path, zf)
        else:  # tar variants
            mode = "w:gz" if archive_format == "tar.gz" else "w"
            with tarfile.open(out_path, mode) as tf:
                tf.add(proj_path, arcname=proj_path.name)

        log_info(f"Project exported to: {out_path}")
        return str(out_path.absolute())

    except Exception as e:
        log_error(f"Export failed: {e}")
        if out_path.exists():
            out_path.unlink()
        raise


def _archive_directory(root_path: Path, current_path: Path, archive):
    """Helper to recursively add files to zip archive."""
    for item in current_path.iterdir():
        if item.is_dir():
            _archive_directory(root_path, item, archive)
        else:
            # Use relative path inside archive
            arcname = item.relative_to(root_path)
            if hasattr(archive, 'write'):
                archive.write(item, arcname)
            else:
                # For zip
                archive.write(item, arcname)


def import_project(archive_path: str, target_dir: str) -> bool:
    """
    Import an SKVA project from an archive.

    Supports .zip, .tar, .tar.gz, .tgz

    Extracts into target_dir, then validates.

    Returns:
        True on success, False on failure.
    """
    archive = Path(archive_path).resolve()
    target = Path(target_dir).resolve()

    if not archive.exists():
        log_error(f"Archive not found: {archive}")
        return False

    if target.exists() and any(target.iterdir()):
        log_error(f"Target directory is not empty: {target}")
        return False

    # Determine archive type
    if archive.suffix == ".zip":
        return _extract_zip(archive, target)
    elif archive.suffix == ".tar" or (archive.suffixes and ".tar" in archive.suffixes):
        return _extract_tar(archive, target)
    else:
        log_error(f"Unsupported archive format: {archive}")
        return False


def _extract_zip(archive: Path, target: Path) -> bool:
    """Extract ZIP archive."""
    try:
        target.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, "r") as zf:
            zf.extractall(target)
        log_info(f"Extracted ZIP archive to: {target}")
    except Exception as e:
        log_error(f"Failed to extract ZIP {archive}: {e}")
        return False

    return _finalize_import(target)


def _extract_tar(archive: Path, target: Path) -> bool:
    """Extract TAR/TAR.GZ archive."""
    try:
        target.mkdir(parents=True, exist_ok=True)
        mode = "r:gz" if ".gz" in archive.suffixes else "r"
        with tarfile.open(archive, mode) as tf:
            tf.extractall(target, filter='data')  # Safer extraction
        log_info(f"Extracted TAR archive to: {target}")
    except Exception as e:
        log_error(f"Failed to extract TAR {archive}: {e}")
        return False

    return _finalize_import(target)


def _finalize_import(target: Path) -> bool:
    """Finalize import: validate and fix permissions if needed."""
    errors = validate_project(str(target))
    if errors:
        log_error("Imported project failed validation:")
        for err in errors:
            log_error(f"  - {err}")
        return False

    log_info("Project imported and validated successfully.")
    return True


# ═══════════════════════════════════════════════════
# CLI INTERFACE (for direct execution)
# ═══════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="SKVA Project Migration Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python skva_migration.py migrate /path/to/src /path/to/dst
  python skva_migration.py export ./myproject ./backup/project.zip
  python skva_migration.py import ./backup/project.zip ./restored
  python skva_migration.py validate ./myproject
        """
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Migrate
    p_migrate = subparsers.add_parser("migrate", help="Copy project from src to dst")
    p_migrate.add_argument("src", help="Source project directory")
    p_migrate.add_argument("dst", help="Destination directory")

    # Export
    p_export = subparsers.add_parser("export", help="Export project to archive")
    p_export.add_argument("project", help="Project directory to export")
    p_export.add_argument("output", help="Output archive path (.zip, .tar, .tar.gz)")

    # Import
    p_import = subparsers.add_parser("import", help="Import project from archive")
    p_import.add_argument("archive", help="Path to archive file")
    p_import.add_argument("target", help="Target directory for extraction")

    # Validate
    p_validate = subparsers.add_parser("validate", help="Validate project structure")
    p_validate.add_argument("project", help="Project directory to validate")

    args = parser.parse_args()

    if args.command == "migrate":
        success = migrate_project(args.src, args.dst)
        sys.exit(0 if success else 1)
    elif args.command == "export":
        try:
            path = export_project(args.project, args.output)
            log_info(f"Export successful: {path}")
            sys.exit(0)
        except Exception as e:
            log_error(f"Export failed: {e}")
            sys.exit(1)
    elif args.command == "import":
        success = import_project(args.archive, args.target)
        sys.exit(0 if success else 1)
    elif args.command == "validate":
        errors = validate_project(args.project)
        if errors:
            log_error("Validation FAILED:")
            for err in errors:
                log_error(f"  - {err}")
            sys.exit(1)
        else:
            log_info("Validation PASSED: Project is intact.")
            sys.exit(0)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
