#!/usr/bin/env python3
"""
SKVA v5 — Система Колективної Взаємодії Агентів
FULL CLI: Integrates all SKVA components including AutoMode, Checkpoints, Dashboard, GitSync, Notifications, and E2E tests.
"""
import sys
import os
import argparse
from pathlib import Path
from typing import Optional, List

# Add project root to path
SCRIPT_DIR = Path(__file__).parent
SKVA_IMPL_DIR = SCRIPT_DIR / "skva_impl"
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SKVA_IMPL_DIR))

# Global dashboard for progress output
_dashboard = None


def get_dashboard(project_dir: str):
    global _dashboard
    if _dashboard is None:
        try:
            from skva_impl.dashboard import Dashboard
            _dashboard = Dashboard(project_dir)
        except Exception as e:
            print(f"⚠️  Не вдалося ініціалізувати Dashboard: {e}")
    return _dashboard


# Lazy imports with fallback handling
def import_component(name: str, module_path: str, class_name: str = None):
    try:
        if class_name:
            module = __import__(module_path, fromlist=[class_name])
            return getattr(module, class_name)
        else:
            return __import__(module_path)
    except Exception as e:
        print(f"❌ Не вдалося завантажити компонент {name}: {e}")
        return None


AutoMode = import_component("AutoMode", "skva_impl.auto_mode", "AutoMode")
CheckpointSystem = import_component("CheckpointSystem", "skva_impl.checkpoint_system", "CheckpointSystem")
Dashboard = import_component("Dashboard", "skva_impl.dashboard", "Dashboard")
GitSync = import_component("GitSync", "skva_impl.git_sync", "GitSync")
NotificationGateway = import_component("NotificationGateway", "skva_impl.gate_notifications", "NotificationGateway")
# E2E tests are functions, not classes
e2e_test_functions = []
if import_component("test_e2e", "skva_impl.test_e2e"):
    from skva_impl.test_e2e import (
        test_state_transitions,
        test_error_recovery,
        test_resource_balancing,
        test_isolation,
        test_dag_execution,
        test_checkpoint_rollback,
        test_notification_flow,
    )
    e2e_test_functions = [
        test_state_transitions,
        test_error_recovery,
        test_resource_balancing,
        test_isolation,
        test_dag_execution,
        test_checkpoint_rollback,
        test_notification_flow,
    ]


def ensure_project_dir(project_dir: str) -> Path:
    path = Path(project_dir).resolve()
    if not path.exists():
        print(f"❌ Каталог проекту не існує: {path}")
        sys.exit(1)
    return path


def cmd_auto(request: str, project_dir: str = "."):
    """Запуск одного циклу автоматичного режиму."""
    project_path = ensure_project_dir(project_dir)
    auto_mode = AutoMode(project_dir=str(project_path))
    if auto_mode is None:
        return False
    try:
        result = auto_mode.run_cycle(request.strip())
        dash = get_dashboard(project_dir)
        if dash:
            dash.show_summary()
        return result
    except Exception as e:
        print(f"❌ Помилка в auto режимі: {e}")
        return False


def cmd_watch(project_dir: str = "."):
    """Запуск безперервного режиму спостереження за змінами."""
    project_path = ensure_project_dir(project_dir)
    auto_mode = AutoMode(project_dir=str(project_path))
    if auto_mode is None:
        return False
    try:
        print(f"👀 Спостереження за змінами у {project_path}... (натисніть Ctrl+C для зупинки)")
        auto_mode.watch()
    except KeyboardInterrupt:
        print("\n🛑 Спостереження зупинено.")
    except Exception as e:
        print(f"❌ Помилка в режимі watch: {e}")
        return False
    return True


def cmd_checkout(phase: str, project_dir: str = "."):
    """Відкат до певної фази через систему чекпоінтів."""
    project_path = ensure_project_dir(project_dir)
    cp_system = CheckpointSystem(project_dir=str(project_path))
    if cp_system is None:
        return False
    try:
        success = cp_system.rollback(phase)
        dash = get_dashboard(project_dir)
        if dash:
            dash.show_phase(phase)
        if success:
            print(f"✅ Відкат до фази '{phase}' виконано.")
        else:
            print(f"❌ Не вдалося відкатитися до фази '{phase}'.")
        return success
    except Exception as e:
        print(f"❌ Помилка при відкаті: {e}")
        return False


def cmd_checkpoints(project_dir: str = "."):
    """Показати всі доступні чекпоінти."""
    project_path = ensure_project_dir(project_dir)
    cp_system = CheckpointSystem(project_dir=str(project_path))
    if cp_system is None:
        return False
    try:
        checkpoints = cp_system.list_checkpoints()
        if not checkpoints:
            print("📭 Немає збережених чекпоінтів.")
            return True
        print(f"💾 Збережені чекпоінти ({len(checkpoints)}):")
        for cp in sorted(checkpoints, key=lambda x: x.get('timestamp', 0), reverse=True):
            phase = cp.get('phase', 'unknown')
            timestamp = cp.get('timestamp', 0)
            timestr = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
            print(f"  🔹 {phase} @ {timestr}")
        return True
    except Exception as e:
        print(f"❌ Помилка при отриманні списку чекпоінтів: {e}")
        return False


def cmd_dashboard(project_dir: str = "."):
    """Показати інформацію через Dashboard."""
    project_path = ensure_project_dir(project_dir)
    dash = get_dashboard(project_dir)
    if not dash:
        return False
    try:
        print("📊 Статус системи (Dashboard):")
        dash.show_summary()
        return True
    except Exception as e:
        print(f"❌ Помилка при відображенні Dashboard: {e}")
        return False


def cmd_notify(message: str, project_dir: str = "."):
    """Надіслати повідомлення через NotificationGateway."""
    project_path = ensure_project_dir(project_dir)
    notifier = NotificationGateway(project_dir=str(project_path))
    if notifier is None:
        return False
    try:
        # Optional: add metadata
        metadata = {
            "sender": "skva-cli",
            "project": str(project_path.name),
            "timestamp": time.time()
        }
        notifier.notify(message, level="info", metadata=metadata)
        print(f"📨 Повідомлення надіслано: {message}")
        return True
    except Exception as e:
        print(f"❌ Не вдалося надіслати повідомлення: {e}")
        return False


def cmd_e2e():
    """Запустити end-to-end тести."""
    print("🧪 Запуск end-to-end тестів SKVA v5...")
    if not e2e_test_functions:
        print("❌ Неможливо запустити E2E тести: модуль test_e2e не завантажено.")
        return False

    passed = 0
    total = len(e2e_test_functions)

    for i, test_func in enumerate(e2e_test_functions, 1):
        test_name = test_func.__name__
        print(f"\n[{i}/{total}] Виконання: {test_name}...")
        try:
            result = test_func()
            if result:
                print(f"✅ {test_name} — успішно")
                passed += 1
            else:
                print(f"❌ {test_name} — провалено")
        except Exception as e:
            print(f"❌ {test_name} — виняток: {e}")

    print(f"\n✅ Пройдено: {passed}/{total}")
    if passed == total:
        print("🎉 Всі E2E тести успішні!")
        return True
    else:
        print("⚠️  Деякі тести провалені.")
        return False


def cmd_git_pull(project_dir: str = "."):
    """Виконати git pull для синхронізації."""
    project_path = ensure_project_dir(project_dir)
    git_sync = GitSync(project_dir=str(project_path))
    if git_sync is None:
        return False
    try:
        success = git_sync.pull()
        if success:
            print("📥 Git: Оновлення з віддаленого репозиторію — успішно")
        else:
            print("❌ Git: Не вдалося виконати pull")
        return success
    except Exception as e:
        print(f"❌ Git pull помилка: {e}")
        return False


def cmd_git_push(project_dir: str = "."):
    """Виконати git push для синхронізації."""
    project_path = ensure_project_dir(project_dir)
    git_sync = GitSync(project_dir=str(project_path))
    if git_sync is None:
        return False
    try:
        success = git_sync.push()
        if success:
            print("📤 Git: Відправка у віддалений репозиторій — успішно")
        else:
            print("❌ Git: Не вдалося виконати push")
        return success
    except Exception as e:
        print(f"❌ Git push помилка: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="SKVA v5 — Повнофункціональний CLI з усіма компонентами"
    )
    subparsers = parser.add_subparsers(dest="command", help="Доступні команди")

    # auto <request> [dir]
    p_auto = subparsers.add_parser("auto", help="Запустити один цикл автоматичного режиму")
    p_auto.add_argument("request", help="Технічне завдання або запит")
    p_auto.add_argument("dir", nargs="?", default=".", help="Каталог проекту (за замовчуванням: .)")

    # watch [dir]
    p_watch = subparsers.add_parser("watch", help="Запустити режим спостереження за змінами")
    p_watch.add_argument("dir", nargs="?", default=".", help="Каталог проекту")

    # checkout <phase> [dir]
    p_checkout = subparsers.add_parser("checkout", help="Відкатитися до певної фази")
    p_checkout.add_argument("phase", help="Назва фази для відкату")
    p_checkout.add_argument("dir", nargs="?", default=".", help="Каталог проекту")

    # checkpoints [dir]
    p_checkpoints = subparsers.add_parser("checkpoints", help="Показати всі чекпоінти")
    p_checkpoints.add_argument("dir", nargs="?", default=".", help="Каталог проекту")

    # dashboard [dir]
    p_dashboard = subparsers.add_parser("dashboard", help="Показати стан системи")
    p_dashboard.add_argument("dir", nargs="?", default=".", help="Каталог проекту")

    # notify <msg>
    p_notify = subparsers.add_parser("notify", help="Надіслати повідомлення")
    p_notify.add_argument("msg", help="Текст повідомлення")
    p_notify.add_argument("--dir", default=".", help="Каталог проекту")

    # e2e
    subparsers.add_parser("e2e", help="Запустити end-to-end тести")

    # git pull
    p_pull = subparsers.add_parser("git-pull", help="Виконати git pull")
    p_pull.add_argument("dir", nargs="?", default=".", help="Каталог проекту")

    # git push
    p_push = subparsers.add_parser("git-push", help="Виконати git push")
    p_push.add_argument("dir", nargs="?", default=".", help="Каталог проекту")

    # Parse args
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    args = parser.parse_args()

    # Route commands
    try:
        if args.command == "auto":
            success = cmd_auto(args.request, args.dir)
        elif args.command == "watch":
            success = cmd_watch(args.dir)
        elif args.command == "checkout":
            success = cmd_checkout(args.phase, args.dir)
        elif args.command == "checkpoints":
            success = cmd_checkpoints(args.dir)
        elif args.command == "dashboard":
            success = cmd_dashboard(args.dir)
        elif args.command == "notify":
            success = cmd_notify(args.msg, args.dir)
        elif args.command == "e2e":
            success = cmd_e2e()
        elif args.command == "git-pull":
            success = cmd_git_pull(args.dir)
        elif args.command == "git-push":
            success = cmd_git_push(args.dir)
        else:
            print(f"❌ Невідома команда: {args.command}")
            parser.print_help()
            sys.exit(1)

        sys.exit(0 if success else 1)

    except Exception as e:
        print(f"🚨 Невідома помилка: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
