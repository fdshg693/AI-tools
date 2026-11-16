# mslearn: クエリの具体性を上げるコツ

`mslearn search` / `code-search` の結果が弱い、またはノイズで埋まるときに読む。

- ❌ `"Azure Functions"` → ✅ `"Azure Functions Python v2 programming model timeout"`
  のように、製品名だけでなく機能名・バージョン・具体的な症状まで含める
- ただし **ARM/Bicep のリソース型名まで入れると逆効果**。
  ❌ `"Bicep Microsoft.Search searchServices Microsoft.CognitiveServices accounts"`
  は、API バージョン違いの自動生成 ARM スキーマ参照ページ（ほぼ同一のボイラープレート）
  で結果が埋まる。デプロイ手順やクイックスタートが欲しいなら
  ✅ `"Azure AI Search Bicep quickstart"` のようにチュートリアル語彙で引く
- 日本語クエリも通るが、製品名・API 名・エラーメッセージは英語の方が一致率が高い。
  日本語で結果が弱ければ英語で再実行する
- `code-search` は `--language` を付けると精度が上がる(対応言語: csharp javascript
  typescript python powershell azurecli al sql java kusto cpp go rust ruby php)
- URL が未知で、手順の全体像やトラブルシューティングの詳細が必要なら、search の後に
  fetch で該当ページの全文を取る(`mslearn tools` の出力にある "Follow-up Pattern" の
  説明どおり)
