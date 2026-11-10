@./README.md

## Behaviour

- CLI 仕様(サブコマンド・オプション・出力形式・終了コード)を変えたら、`claude-plugins/my-tools/skills/aws-docs/SKILL.md` の「サブコマンド」「出力形式」「終了コード」節も同じ変更で同期すること。
- サーバーの実測挙動(応答形状・エラーの返り方)が変わったのを見つけたら、`memo/01-knowledge-mcp-server.md` も更新すること。
- サーバー挙動の変化を見つけたら、`claude-plugins/my-tools-no-install/skills/web-lookup` の `aws` 系統（`scripts/backends.py` の AWS 判定と `aws.md`）も確認すること。
