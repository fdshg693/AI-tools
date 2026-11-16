import fs from 'node:fs';
import path from 'node:path';

import { assertAllowedCommand, runCli, type CliLauncher, type RunOptions } from './passthrough.js';
import { errorText, firstFencedBlock, parseOutput } from './parse.js';

/**
 * 回収スクリプト。
 *
 * 委譲の開始時に `recording-start`、終了時に `recording-stop --json` を張り、`.result` から回収する。
 * **モデルの行動ログからスクリプトを組み立てない。** 記録は playwright-cli 側で意味的ロケータへ
 * 正規化されていて ref を含まないが、モデルに書かせると壊れやすいロケータが混じる
 * （[script-cli-roundtrip.md] 2 節「なぜ回収は記録一本なのか」）。
 *
 * 回収物は**現在地から始める 1 チャンク**で、初期化（`goto` + 状態リセット）は含めない。
 * 通し実行用の init チャンクは呼び出し側の責務（同 3 節）。
 *
 * 記録は**排他**で、止めずに覗く手段が無い（`recording-start` の二重撃ちは
 * `Error: Recording is already in progress.`）。呼び出し側が既に張っていた場合、
 * pwdo は**記録に一切触らない**（勝手に止めると呼び出し側のチャンクが切れる）。
 */

export interface RecoveredScript {
  /** cwd からの相対パス */
  path: string;
  lines: number;
  /** `await page.…` の行数 */
  actions: number;
}

/** 記録の状態。`owned` が false なら pwdo は `recording-stop` を撃たない。 */
export interface Recording {
  owned: boolean;
  runDir: string;
  runId: string;
  /** 記録を張れなかった／触らないことにした理由。返却物にそのまま 1 行で載る */
  note?: string;
}

export interface Recovery {
  script?: RecoveredScript;
  /** 回収の経緯。呼び出し側の分岐材料ではなく説明（分岐は status で行う） */
  note?: string;
}

export interface ChunkMeta {
  runId: string;
  session: string;
  instruction: string;
  model: string;
  status: string;
  steps: number;
  /** 再実行コマンドに載せる、cwd からの相対パス */
  scriptPath: string;
}

/** ヘッダーへ入れる 1 行。改行とコメント終端を潰し、長さで切る。 */
function oneLine(text: string, max = 160): string {
  const one = text.replace(/\s+/g, ' ').trim();
  return one.length > max ? one.slice(0, max) + '…' : one;
}

/**
 * 次の `<store>/<session>/run-NNNN/`。既存の最大値 + 1 を取る。
 *
 * **ディレクトリはここでは作らない。** 回収物が出ないまま終わる経路（呼び出し側が既に記録中 /
 * 記録が空）があり、先に作ると空ディレクトリだけが積む。実際に書く直前に作る。
 */
export function allocateRunDir(storeRoot: string, session: string): { dir: string; id: string } {
  const base = path.join(storeRoot, session);
  let max = 0;
  let names: string[] = [];
  try {
    names = fs.readdirSync(base);
  } catch {
    // まだ 1 度も回収していないセッション
  }
  for (const name of names) {
    const m = name.match(/^run-(\d{4})$/);
    if (m)
      max = Math.max(max, Number(m[1]));
  }
  const id = `run-${String(max + 1).padStart(4, '0')}`;
  return { dir: path.join(base, id), id };
}

/**
 * 回収したコードを `run-code` にそのまま載る形へ整形する。
 *
 * `run-code` はファイルの中身を `(...)` で包んで評価する（単一の関数式であること・
 * import/require 不可）。**先頭のコメント行は `(` の直後に来ても行末で閉じるので通る**
 * ——実測で確認済み。ヘッダーを付けるのは、後日ファイルだけを見た人（や別セッションの
 * エージェント）が「どのセッションの・何の指示で・どこまで進んだ区間か」を復元できるようにするため。
 */
export function formatChunk(code: string, meta: ChunkMeta): string {
  const body = code.trimEnd().split('\n').map(line => (line.trim() ? '  ' + line : '')).join('\n');
  return [
    `// pwdo ${meta.runId} — session=${meta.session} / model=${meta.model} / status=${meta.status} / steps=${meta.steps}`,
    `// ${new Date().toISOString()}`,
    `// 指示: ${oneLine(meta.instruction)}`,
    '//',
    '// 現在地から始める 1 区間です。初期化（goto + 状態リセット）は含みません。',
    '// 通しで再実行するなら init チャンクを別に用意してください。',
    `// 再実行: playwright-cli -s=${meta.session} run-code --filename=${meta.scriptPath}`,
    'async page => {',
    body,
    // ok は名乗らない。委譲が budget-exceeded / blocked で終わった区間もそのまま回収するので、
    // 「通った = 目的を達した」ではない。判断材料として status と現在地だけ返す。
    `  return { pwdo: '${meta.runId}', status: '${meta.status}', url: page.url() };`,
    '}',
    '',
  ].join('\n');
}

/**
 * 記録を開始する。
 *
 * 既に記録中なら **開始も停止もしない**。呼び出し側が張った記録の途中で pwdo が
 * `recording-stop` を撃つと、呼び出し側のチャンクがそこで切れて回収物が二重になる。
 * その場合この区間の操作は呼び出し側の記録に続けて入る（記録は操作の出所を問わない）ので、
 * 失われるものは無い。何が起きたかは `note` で 1 行返す。
 */
export async function startRecording(
  launcher: CliLauncher, session: string, runDir: string, runId: string, run: RunOptions
): Promise<Recording> {
  const args = [`-s=${session}`, 'recording-start'];
  assertAllowedCommand(args);

  let result;
  try {
    result = await runCli(launcher, args, run);
  } catch (err) {
    return { owned: false, runDir, runId, note: `recording-start を実行できず、回収はありません: ${oneLine(String(err))}` };
  }

  // 失敗は終了コードにも `### Error` にも出うる。両方見る（アクション系と同じ理由）。
  const error = errorText(parseOutput(result.stdout));
  if (error && /already in progress/i.test(error)) {
    return {
      owned: false, runDir, runId,
      note: '呼び出し側が既に recording-start を張っていたため、pwdo は記録に触れていません（停止もしていません）。'
        + 'この区間の操作は呼び出し側の記録に続けて入ります。',
    };
  }
  if (error || result.code !== 0)
    return { owned: false, runDir, runId, note: `recording-start に失敗し、回収はありません: ${oneLine(error ?? result.stderr ?? '')}` };

  return { owned: true, runDir, runId };
}

/**
 * 記録を止めて回収する。**成功時だけでなく失敗・中断時も呼ぶ**（呼び出し側の `finally`）。
 * 途中までのスクリプトは「どこまで進んだか」の最も正確な記録で、復帰の材料になる。
 *
 * ここだけは `--json` を付ける。アクション系と違って recording-stop は結果そのものが欲しく、
 * `.result` に ```js フェンス入りの文字列が入る（実測 2026-09-15）。
 */
export async function finishRecording(
  launcher: CliLauncher, recording: Recording, meta: Omit<ChunkMeta, 'runId' | 'scriptPath'>,
  cwd: string, run: RunOptions
): Promise<Recovery> {
  if (!recording.owned)
    return { note: recording.note };

  const args = [`-s=${meta.session}`, '--json', 'recording-stop'];
  assertAllowedCommand(args);

  let stdout: string;
  try {
    stdout = (await runCli(launcher, args, run)).stdout;
  } catch (err) {
    return { note: `recording-stop に失敗し、回収できませんでした: ${oneLine(String(err))}` };
  }

  let payload: { result?: string };
  try {
    payload = JSON.parse(stdout);
  } catch {
    return { note: 'recording-stop の出力を解釈できず、回収できませんでした。' };
  }
  const code = payload.result ? firstFencedBlock(payload.result) : undefined;
  if (!code || !code.trim())
    return { note: '記録が空でした（状態を変える操作が 1 つもありませんでした）。observe / find は記録に入りません。' };

  const file = path.join(recording.runDir, 'chunk.js');
  const scriptPath = path.relative(cwd, file).replace(/\\/g, '/');
  const text = formatChunk(code, { ...meta, runId: recording.runId, scriptPath });
  try {
    fs.mkdirSync(recording.runDir, { recursive: true });
    fs.writeFileSync(file, text, 'utf-8');
  } catch (err) {
    return { note: `回収物を書き出せませんでした: ${oneLine(String(err))}` };
  }

  const script: RecoveredScript = {
    path: scriptPath,
    lines: text.trimEnd().split('\n').length,
    actions: code.split('\n').filter(l => /^\s*await\s/.test(l)).length,
  };
  // 記録経由なら ref は混入しないはずだが、混じっていたら回収物は次のセッションで壊れる。
  // 落とさず 1 行で知らせる（[script-cli-roundtrip.md] 7 節の 6 と同じ確認）。
  const leaked = code.match(/\b(?:f\d+)?e\d+\b/);
  return leaked
    ? { script, note: `回収物に ref らしき文字列が混じっています（${leaked[0]}）。再実行前に確認してください。` }
    : { script };
}
