# Codex SDK 最小ラッパー

Python の公式 Codex SDK (`openai-codex`) を使い、ローカルの Codex エージェント
(`gpt-5.6-luna`) に1ターンだけ問い合わせる最小例です。

## セットアップ

```powershell
python -m pip install openai-codex
codex login
```

## 実行

リポジトリルートから実行します。

```powershell
python tools\codex-wrapper\main.py
python tools\codex-wrapper\main.py "1+1="
```

ファイル変更は行わない読み取り専用スレッドとして起動します。

## 関連ファイル

- `codex-plugins\meta\skills\codex-sdk-use\SKILL.md`
