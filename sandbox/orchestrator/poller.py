#!/usr/bin/env python3
"""GitHub ISSUEの`@sandbox`メンションをポーリングし、対応コンテナを起動する常駐ワーカー。

一定間隔でGitHub Issues検索APIを叩き、`@sandbox`メンションを含むopen issueのうち
まだPRが作られていないものを見つけたら、`run_agent.run_container()`で
ISSUE専用の使い捨てDockerコンテナを起動する。成功したらPRを作成し、
失敗したらISSUEにエラーコメントを投稿する。

ISSUEへの自動対応は成功/失敗を問わず1回までに制限する。主判定は`state.py`の
`AttemptStore`（SQLite）で、コンテナ起動前に試行開始を記録し、既に記録済みの
ISSUEは二度と自動処理しない。GitHub側（そのISSUEのブランチ名をheadとする
PRの有無）による判定も、state.dbが消失・リセットされた場合の保険として
重複PR防止の副次チェックとして併用する。

さらに、`@sandbox`を実際に書いたユーザー（ISSUE本文またはコメントの投稿者）の
`author_association`が`SANDBOX_ALLOWED_AUTHOR_ASSOCIATIONS`（既定`OWNER,COLLABORATOR`）
に含まれない場合は処理をスキップする（`is_mention_authorized()`）。誰でもISSUEを
開けるリポジトリで、部外者のメンションだけで書き込み権限を持つエージェントが
起動しないようにするための認可ゲート。

使い方:
    python poller.py
    （必要な環境変数は同階層の`.env`またはプロセス環境。`.env.example`参照）
"""

import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import github_client
import logging_setup
import run_agent
import state

# get_installation_token.pyのJWT署名・token取得ロジックを再利用する
# （GitHub App認証の実装をgithub_app/とorchestrator/で重複させないため）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github_app"))
import get_installation_token  # noqa: E402


DEFAULT_OWNER = "fdshg693"
DEFAULT_REPO = "AI"
MENTION = "@sandbox"
DEFAULT_ALLOWED_AUTHOR_ASSOCIATIONS = "OWNER,COLLABORATOR"
ENV_PATH = Path(__file__).resolve().parent / ".env"

logger = logging.getLogger(__name__)


def load_dotenv(path: Path) -> None:
    """Load simple KEY=VALUE entries without overriding process environment."""

    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue

        key, value = (part.strip() for part in line.split("=", 1))
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ[key] = value


def missing_required_key_message(key: str, env_path: Path) -> str:
    env_state = "未設定" if key not in os.environ else "空で設定されている"
    if not env_path.is_file():
        file_state = f"想定した .env は {env_path} ですが、ファイルがありません。"
    else:
        file_state = f"{env_path} はありますが、{key} が無いか空です。"
    return f"{key} が解決できません。\n環境変数 {key} は{env_state}です。\n{file_state}"


@dataclass
class Config:
    github_app_id: str
    github_app_private_key_path: str
    github_app_installation_id: str
    anthropic_api_key: str
    image: str
    owner: str
    repo: str
    base_branch: str
    model: str
    max_turns: int
    poll_interval_seconds: int
    max_issues_per_cycle: int
    container_memory: str
    container_cpus: str
    container_pids_limit: int
    container_timeout_seconds: int
    state_db_path: str
    allowed_author_associations: frozenset[str]
    log_level: str
    log_dir: str
    log_retention_days: int

    @classmethod
    def from_env(cls) -> "Config":
        load_dotenv(ENV_PATH)

        def require(name: str) -> str:
            value = os.environ.get(name)
            if not value:
                sys.exit(missing_required_key_message(name, ENV_PATH))
            return value

        def default_env(name: str, default: str) -> str:
            """環境変数が未設定、または空文字・空白のみの場合もデフォルトへフォールバックする。

            ``os.environ.get(name, default)`` は変数が未設定のときのみデフォルトを返し、
            空文字列が設定されている場合は空文字列をそのまま返してしまう。本ヘルパは
            「未設定」と「空・空白のみ」を同列に扱い、いずれでもデフォルトへフォールバック
            させる（例: 数値系変数が空のまま ``int("")`` で ``ValueError`` を投げる問題の予防）。
            """
            value = os.environ.get(name)
            if value is None or not value.strip():
                return default
            return value

        allowed_raw = default_env(
            "SANDBOX_ALLOWED_AUTHOR_ASSOCIATIONS", DEFAULT_ALLOWED_AUTHOR_ASSOCIATIONS
        )
        allowed_author_associations = frozenset(
            part.strip().upper() for part in allowed_raw.split(",") if part.strip()
        )

        return cls(
            github_app_id=require("GITHUB_APP_ID"),
            github_app_private_key_path=require("GITHUB_APP_PRIVATE_KEY_PATH"),
            github_app_installation_id=require("GITHUB_APP_INSTALLATION_ID"),
            anthropic_api_key=require("ANTHROPIC_API_KEY"),
            image=require("SANDBOX_IMAGE"),
            owner=default_env("GITHUB_OWNER", DEFAULT_OWNER),
            repo=default_env("GITHUB_REPO", DEFAULT_REPO),
            base_branch=default_env("SANDBOX_BASE_BRANCH", "main"),
            model=default_env("SANDBOX_MODEL", "sonnet"),
            max_turns=int(default_env("SANDBOX_MAX_TURNS", "40")),
            poll_interval_seconds=int(default_env("SANDBOX_POLL_INTERVAL_SECONDS", "60")),
            max_issues_per_cycle=int(default_env("SANDBOX_MAX_ISSUES_PER_CYCLE", "1")),
            container_memory=default_env("SANDBOX_CONTAINER_MEMORY", "2g"),
            container_cpus=default_env("SANDBOX_CONTAINER_CPUS", "2"),
            container_pids_limit=int(default_env("SANDBOX_CONTAINER_PIDS_LIMIT", "512")),
            container_timeout_seconds=int(default_env("SANDBOX_CONTAINER_TIMEOUT_SECONDS", "1200")),
            state_db_path=default_env("SANDBOX_STATE_DB_PATH", state.DEFAULT_DB_PATH),
            allowed_author_associations=allowed_author_associations,
            log_level=default_env("SANDBOX_LOG_LEVEL", "INFO"),
            log_dir=default_env("SANDBOX_LOG_DIR", logging_setup.DEFAULT_LOG_DIR),
            log_retention_days=int(default_env("SANDBOX_LOG_RETENTION_DAYS", "14")),
        )


def fetch_fresh_token(config: Config) -> str:
    private_key_pem = get_installation_token.read_private_key(config.github_app_private_key_path)
    app_jwt = get_installation_token.build_app_jwt(config.github_app_id, private_key_pem)
    result = get_installation_token.fetch_installation_token(
        app_jwt, config.github_app_installation_id, [config.repo]
    )
    return result["token"]


def is_mention_authorized(token: str, config: Config, issue_number: int) -> bool:
    """`@sandbox`を実際に書いたユーザーが`allowed_author_associations`に該当するか判定する。

    ISSUE本文・全コメントそれぞれについて、`MENTION`を含み、かつ書いた人の
    `author_association`が許可リストに含まれる箇所が1つでもあればTrue。
    ISSUE作成者ではなく「メンションを書いた人」単位で見るのは、部外者が開いた
    ISSUEに対してオーナーが後から`@sandbox`とコメントして起動する運用を
    許可するため（ISSUE作成者だけで判定すると、このケースをブロックしてしまう）。
    """
    issue = github_client.get_issue(token, config.owner, config.repo, issue_number)
    if MENTION in (issue.get("body") or ""):
        if (
            issue.get("author_association") or "NONE"
        ).upper() in config.allowed_author_associations:
            return True

    comments = github_client.get_issue_comments(token, config.owner, config.repo, issue_number)
    for comment in comments:
        if MENTION not in (comment.get("body") or ""):
            continue
        if (
            comment.get("author_association") or "NONE"
        ).upper() in config.allowed_author_associations:
            return True

    return False


def poll_once(config: Config, store: state.AttemptStore) -> None:
    token = fetch_fresh_token(config)
    issues = github_client.search_mentioning_issues(token, config.owner, config.repo, MENTION)
    logger.info(f"found {len(issues)} issue(s) mentioning {MENTION}")

    processed = 0
    for issue in issues:
        if processed >= config.max_issues_per_cycle:
            logger.info(
                f"reached max_issues_per_cycle={config.max_issues_per_cycle}, deferring the rest to next poll"
            )
            break

        issue_number = issue["number"]
        with logging_setup.issue_context(issue_number):
            branch = f"sandbox/issue-{issue_number}"
            if github_client.has_existing_pr_for_branch(token, config.owner, config.repo, branch):
                continue

            if not is_mention_authorized(token, config, issue_number):
                logger.info(
                    f"{MENTION}を書いたユーザーが許可対象外のためスキップ"
                    f"（許可: {sorted(config.allowed_author_associations)}）"
                )
                continue

            if not store.record_attempt_start(issue_number):
                logger.info("試行済みのためスキップ（1 ISSUE = 1回までの制限）")
                continue

            result = run_agent.run_container(issue, token, config.anthropic_api_key, config)
            processed += 1

            # コンテナ実行に時間がかかっている間にtokenが失効している可能性があるため、
            # PR作成/コメント投稿の前に取り直す。
            token = fetch_fresh_token(config)

            store.record_attempt_result(
                issue_number, success=result.success, detail=result.detail, log_file=result.log_file
            )

            if result.success:
                pr = github_client.create_pull_request(
                    token,
                    config.owner,
                    config.repo,
                    result.branch,
                    config.base_branch,
                    title=f"[sandbox] {issue['title']} (#{issue_number})",
                    body=(
                        f"ISSUE #{issue_number} への対応として `{MENTION}` エージェントが自動生成しました。\n\n"
                        f"{result.detail}\n\nCloses #{issue_number}"
                    ),
                )
                logger.info(f"PR作成 {pr.get('html_url')}")
            else:
                github_client.create_issue_comment(
                    token,
                    config.owner,
                    config.repo,
                    issue_number,
                    body=f"`{MENTION}` エージェントの実行に失敗しました。\n\n詳細: {result.detail}",
                )
                logger.info(f"失敗、コメント投稿済み ({result.detail})")


def main() -> None:
    config = Config.from_env()
    logging_setup.setup_logging(
        level=config.log_level,
        log_dir=logging_setup.resolve_log_dir(config.log_dir),
        retention_days=config.log_retention_days,
    )
    store = state.AttemptStore(state.resolve_db_path(config.state_db_path))
    logger.info(
        f"polling {config.owner}/{config.repo} for {MENTION} every {config.poll_interval_seconds}s "
        f"(state db: {store.db_path})"
    )
    while True:
        try:
            poll_once(config, store)
        except Exception as exc:  # noqa: BLE001 -- 1周期の一時的な失敗でワーカー自体を落とさない
            logger.exception(f"poll cycle failed: {exc}")
        time.sleep(config.poll_interval_seconds)


if __name__ == "__main__":
    main()
