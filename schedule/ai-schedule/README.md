# スケジューラー

ローカルではWindows環境のタスクスケジューラに登録して、定期実行を行う。
クラウドでは、VMやワーカーに定期実行を設定する。

ローカル向けに、設定ファイル(YAML)をもとにWindowsタスクスケジューラへ登録済みPowerShellスクリプトの
定期実行を同期する `ai-schedule` CLIパッケージを用意している。設定を有効・無効にするには
`config/jobs.yaml` を編集した上で `ai-schedule sync` を実行する。詳細は [AGENTS.md](AGENTS.md) を参照。
