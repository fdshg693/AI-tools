#!/usr/bin/env python3
"""ISSUEごとの試行記録をSQLiteで管理し、1 ISSUE = 1回までの自動試行に制限する。

`poller.py`はコンテナ起動**前**に`AttemptStore.record_attempt_start()`を呼ぶ。
既に記録済み（=試行済み）なら`False`が返るため、その場合は処理をスキップする。
記録を先に書き、コンテナ実行後に`record_attempt_result()`で結果を上書きする
2段階更新にしているのは、ワーカープロセスがコンテナ起動後・記録前にクラッシュ
した場合の二重処理を防ぐため。

「1回まで」の意味は成功/失敗を問わず一度試行を開始したISSUEは二度と自動処理
しない、という決定に基づく。一時的なインフラ障害等で誤って打ち切られた
ISSUEを人手で再試行させたい場合は、本ファイルをCLIとして実行する:

    python state.py --reset <issue_number>
"""

import argparse
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ORCHESTRATOR_DIR = Path(__file__).resolve().parent
DEFAULT_DB_PATH = "data/state.db"


def resolve_db_path(raw_path: str) -> Path:
    path = Path(raw_path)
    return path if path.is_absolute() else ORCHESTRATOR_DIR / path


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AttemptStore:
    """ISSUE番号ごとの試行記録を保持するSQLiteストア。"""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS attempts (
                issue_number INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                success INTEGER,
                detail TEXT
            )
            """
        )
        # `CREATE TABLE IF NOT EXISTS`は既存テーブルへカラムを追加しないため、
        # 稼働中の既存state.dbに対しては`ALTER TABLE`で後方互換に追加する。
        # 既にカラムが存在する場合はOperationalErrorを握りつぶしてスキップする。
        try:
            self._conn.execute("ALTER TABLE attempts ADD COLUMN log_file TEXT")
        except sqlite3.OperationalError:
            pass
        self._conn.commit()

    def record_attempt_start(self, issue_number: int) -> bool:
        """試行開始を記録する。未試行だった場合はTrue、既に試行済みならFalse。"""
        cursor = self._conn.execute(
            "INSERT OR IGNORE INTO attempts (issue_number, started_at) VALUES (?, ?)",
            (issue_number, _now_iso()),
        )
        self._conn.commit()
        return cursor.rowcount > 0

    def record_attempt_result(
        self, issue_number: int, success: bool, detail: str, log_file: str | None = None
    ) -> None:
        self._conn.execute(
            "UPDATE attempts SET finished_at = ?, success = ?, detail = ?, log_file = ? WHERE issue_number = ?",
            (_now_iso(), 1 if success else 0, detail, log_file, issue_number),
        )
        self._conn.commit()

    def reset(self, issue_number: int) -> bool:
        """指定ISSUEの試行記録を削除し、次回ポーリングで再試行可能にする。削除した場合True。"""
        cursor = self._conn.execute("DELETE FROM attempts WHERE issue_number = ?", (issue_number,))
        self._conn.commit()
        return cursor.rowcount > 0

    def get_attempt(self, issue_number: int) -> dict | None:
        """指定ISSUEの試行記録を1件取得する（`--show`CLI用）。見つからなければNone。"""
        cursor = self._conn.execute(
            "SELECT issue_number, started_at, finished_at, success, detail, log_file "
            "FROM attempts WHERE issue_number = ?",
            (issue_number,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        columns = [column[0] for column in cursor.description]
        return dict(zip(columns, row))


def main() -> None:
    parser = argparse.ArgumentParser(description="ISSUE試行記録ストアの手動操作CLI")
    parser.add_argument(
        "--db-path",
        default=os.environ.get("SANDBOX_STATE_DB_PATH", DEFAULT_DB_PATH),
        help="SQLiteファイルパス（既定: 環境変数SANDBOX_STATE_DB_PATH、未設定なら%(default)s）",
    )
    parser.add_argument(
        "--reset",
        type=int,
        metavar="ISSUE_NUMBER",
        default=None,
        help="指定したISSUE番号の試行記録を削除し、再試行可能にする",
    )
    parser.add_argument(
        "--show",
        type=int,
        metavar="ISSUE_NUMBER",
        default=None,
        help="指定したISSUE番号の試行記録を表示する（log_fileパス含む、読み取り専用）",
    )
    args = parser.parse_args()
    if args.reset is None and args.show is None:
        parser.error("--reset または --show のいずれかを指定してください")

    store = AttemptStore(resolve_db_path(args.db_path))

    if args.show is not None:
        attempt = store.get_attempt(args.show)
        if attempt is None:
            print(f"issue #{args.show}: 試行記録は見つかりませんでした")
        else:
            for key, value in attempt.items():
                print(f"{key}: {value}")

    if args.reset is not None:
        if store.reset(args.reset):
            print(f"issue #{args.reset}: 試行記録を削除しました（次回ポーリングで再試行されます）")
        else:
            print(f"issue #{args.reset}: 試行記録は見つかりませんでした")


if __name__ == "__main__":
    main()
