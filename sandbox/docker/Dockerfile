# Debian bookworm を使う（Ubuntu 24.04系は避ける）。
# Ubuntu 24.04+ は既定のAppArmorポリシーでbubblewrapのユーザー名前空間作成を
# 制限しており、追加のホスト設定なしではClaude Code組み込みサンドボックスが
# 動かない可能性があるため。
FROM python:3.12-slim-bookworm

# git: リポジトリのclone/push用。
# bubblewrap/socat: Claude Code組み込みサンドボックス（sandbox.*）がLinux上で
# ファイルシステム/ネットワーク隔離を行うために必須の依存（Node.js製CLIではなく
# ネイティブ機能なので、これらのパッケージが無いとsandbox.failIfUnavailable=trueにより
# 起動自体が失敗する）。
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        bubblewrap \
        socat \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# claude-agent-sdk はホストOS向けのネイティブClaude Codeバイナリを同梱するため、
# Node.jsや @anthropic-ai/claude-code の別途インストールは不要
# （出典: 公式 secure-deployment ページ「Runtime dependencies」）。
# PyJWT[crypto]: GitHub App installation token取得（tools/sandbox/github_app/
# get_installation_token.py）のJWT(RS256)署名に使用。extraのcryptographyパッケージが
# RSA署名の実体を提供する。
RUN pip install --no-cache-dir claude-agent-sdk "PyJWT[crypto]"

# managed settings: sandboxのロックダウン設定（allowManagedDomainsOnly等）は
# managed settingsスコープでのみ有効。project設定やSDKオプション経由では無視されるため、
# このファイルパスへの焼き込みが必須（詳細: 01-research.md）。
RUN mkdir -p /etc/claude-code
COPY claude-settings/managed-settings.json /etc/claude-code/managed-settings.json

# project向けの非セキュリティ設定（filesystem.allowWrite等の利便性設定）。
# setting_sources=[] でSDKを呼ぶ想定のため、Claude Codeの通常のproject設定読み込みは
# 使わず、オーケストレーター（tools/sandbox/orchestrator/run_agent.py）がこのファイルを
# 読み込んで ClaudeAgentOptions(sandbox=...) に渡す。
COPY claude-settings/settings.json /opt/sandbox-agent/claude-settings/settings.json

# permission_mode="bypassPermissions" はサンドボックス未認識時にrootでの実行を拒否されるため、
# 非rootユーザーで実行する。
RUN useradd --create-home --shell /bin/bash sandbox-agent
USER sandbox-agent
WORKDIR /home/sandbox-agent

# リポジトリのclone・エージェント起動コマンドは、オーケストレーター側の
# `docker run` 実行時引数として渡す（このイメージ自体はエントリポイントを固定しない）。
CMD ["bash"]
