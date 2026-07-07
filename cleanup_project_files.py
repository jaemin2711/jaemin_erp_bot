from __future__ import annotations

import argparse
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent

KEEP_EXACT = {
    ".env", ".env.example", ".gitignore", "README.md", "README_RUN.md", "requirements.txt",
    "telegram_bot.py", "ai_parser.py", "date_utils.py", "group_chat_filter.py",
    "force_register_mode.py", "ocr_product_memory.py", "image_parser.py",
    "inventory_engine.py", "multi_plan.py", "plan_product_change.py",
    "production_memory.py", "purchase_order.py", "purchase_order_form.py",
    "summary_commands.py",
}

KEEP_DIRS = {".git", ".venv", "venv", "data", "logs", "backups", "improvements"}
MOVE_TO_LOGS = {"usage_log.csv", "register_users.csv"}
PATCH_OR_TEMP_PREFIXES = ("apply_", "fix_", "repair_")
PATCH_OR_TEMP_EXACT = {
    "check_syntax.py", "create_sample_excel.py", "test_api.py",
    "install_and_patch.bat", "fix_runtime_event_loop.bat", "run_bot.bat",
    "FIX_README.txt", "CHANGELOG_IMPROVEMENTS.md", "README_PATCH_DETAIL.md",
    "README_RUNTIME_FIX.md",
}
PATCH_DOC_PREFIXES = ("README_",)
PATCH_DOC_KEEP = {"README.md", "README_RUN.md", "README_CLEANUP.md"}
BACKUP_OR_TEMP_PATTERNS = (".bak_", "_error.py", "_old.py", "_backup.py")
CACHE_DIR_NAMES = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}


def make_archive_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = ROOT / f"_archive_cleanup_{stamp}"
    archive.mkdir(exist_ok=False)
    return archive


def should_archive_file(path: Path) -> tuple[bool, str]:
    name = path.name

    if name in KEEP_EXACT:
        return False, "keep exact"

    if name in MOVE_TO_LOGS:
        return False, "move to logs"

    if any(token in name for token in BACKUP_OR_TEMP_PATTERNS):
        return True, "backup/temp file"

    if name.endswith((".zip", ".7z", ".rar")):
        return True, "downloaded archive"

    if name.endswith((".log", ".tmp", ".temp")):
        return True, "runtime temp/log"

    if name.startswith(PATCH_OR_TEMP_PREFIXES):
        return True, "patch helper script"

    if name in PATCH_OR_TEMP_EXACT:
        return True, "patch helper/doc"

    if name.startswith(PATCH_DOC_PREFIXES) and name not in PATCH_DOC_KEEP:
        return True, "patch readme"

    return False, "not matched"


def iter_targets() -> list[tuple[Path, str, str]]:
    targets: list[tuple[Path, str, str]] = []

    for path in ROOT.iterdir():
        name = path.name

        if name.startswith("_archive_cleanup_"):
            continue

        if path.is_dir():
            if name in KEEP_DIRS:
                continue

            if name in CACHE_DIR_NAMES:
                targets.append((path, "archive", "cache directory"))
                continue

            if (
                name.endswith("_patch")
                or name.endswith("-improved")
                or name.startswith("telegram-excel-bot-improved")
                or name.startswith("project_cleanup_tools")
                or name.startswith("shortage_usage")
                or name.startswith("ocr_")
                or name.startswith("force_")
                or name.startswith("group_")
                or name.startswith("plans_")
            ):
                targets.append((path, "archive", "patch extracted directory"))
                continue

            continue

        if not path.is_file():
            continue

        if name in MOVE_TO_LOGS:
            targets.append((path, "move_logs", "root log csv"))
            continue

        archive, reason = should_archive_file(path)

        if archive:
            targets.append((path, "archive", reason))

    return targets


def move_path(src: Path, dst_root: Path) -> Path:
    dst = dst_root / src.name

    if dst.exists():
        stem = src.stem
        suffix = src.suffix
        i = 2
        while True:
            candidate = dst_root / f"{stem}_{i}{suffix}"
            if not candidate.exists():
                dst = candidate
                break
            i += 1

    shutil.move(str(src), str(dst))
    return dst


def move_logs(src: Path) -> Path:
    logs_dir = ROOT / "logs"
    logs_dir.mkdir(exist_ok=True)
    return move_path(src, logs_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="telegram-excel-bot 불필요 파일 정리 도구")
    parser.add_argument("--apply", action="store_true", help="실제로 파일을 이동합니다. 없으면 미리보기만 합니다.")
    parser.add_argument("--hard-delete-cache", action="store_true", help="캐시 폴더를 아카이브가 아니라 실제 삭제합니다.")
    args = parser.parse_args()

    targets = iter_targets()

    if not targets:
        print("정리할 불필요 파일을 찾지 못했습니다.")
        return

    print("[정리 대상]")
    for path, action, reason in targets:
        print(f"- {action:9s} | {path.name} | {reason}")

    if not args.apply:
        print("")
        print("아직 실제로 이동하지 않았습니다.")
        print("실행하려면 아래 명령을 사용하세요.")
        print("python cleanup_project_files.py --apply")
        return

    archive = make_archive_dir()
    moved_count = 0
    log_moved_count = 0
    deleted_count = 0

    for path, action, reason in targets:
        if not path.exists():
            continue

        if action == "move_logs":
            dst = move_logs(path)
            print(f"logs 이동: {path.name} -> {dst.relative_to(ROOT)}")
            log_moved_count += 1
            continue

        if args.hard_delete_cache and path.is_dir() and path.name in CACHE_DIR_NAMES:
            shutil.rmtree(path)
            print(f"캐시 삭제: {path.name}")
            deleted_count += 1
            continue

        dst = move_path(path, archive)
        print(f"아카이브 이동: {path.name} -> {dst.relative_to(ROOT)}")
        moved_count += 1

    print("")
    print("✅ 정리 완료")
    print(f"- 아카이브 이동: {moved_count}개")
    print(f"- logs 이동: {log_moved_count}개")
    print(f"- 캐시 삭제: {deleted_count}개")
    print(f"- 아카이브 폴더: {archive.name}")
    print("")
    print("봇 실행 확인 후 며칠 뒤 아카이브 폴더를 삭제해도 됩니다.")


if __name__ == "__main__":
    main()
