"""tools/my-agents/skills/ 配下のスキル定義を読み込む。

スキルファイルは `{skill-name}_SKILL.md` の形式。同階層の別ファイルはスコープ外。
フロントマターの `description` をカタログ用に使い、スキルツールはフロントマターを
除いた本文を返す。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

# 実行時のカレントディレクトリに依存せず、常にこのパッケージが置かれた
# tools/my-agents/skills/ を参照する。
SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"
SKILL_SUFFIX = "_SKILL.md"


@dataclass(frozen=True)
class SkillInfo:
    name: str
    description: str
    path: Path


def _strip_frontmatter(text: str) -> tuple[dict, str]:
    """YAMLフロントマターをパースし、(data, body) を返す。無ければ ({}, text)。"""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    raw = text[3:end]
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        data = None
    if not isinstance(data, dict):
        data = {}
    body = text[end + 4 :]  # skip "\n---"
    if body.startswith("\n"):
        body = body[1:]
    return data, body


def _skill_name_from_path(path: Path) -> str | None:
    if not path.name.endswith(SKILL_SUFFIX):
        return None
    name = path.name[: -len(SKILL_SUFFIX)]
    return name or None


def list_skills(skills_dir: Path | None = None) -> list[SkillInfo]:
    """利用可能なスキルを名前昇順で返す。"""
    root = skills_dir if skills_dir is not None else SKILLS_DIR
    if not root.is_dir():
        return []

    skills: list[SkillInfo] = []
    for path in sorted(root.glob(f"*{SKILL_SUFFIX}")):
        name = _skill_name_from_path(path)
        if name is None:
            continue
        text = path.read_text(encoding="utf-8")
        data, _ = _strip_frontmatter(text)
        description = str(data.get("description") or "").strip()
        skills.append(SkillInfo(name=name, description=description, path=path))
    return skills


def load_skill_body(name: str, skills_dir: Path | None = None) -> str:
    """スキル名に対応する SKILL.md の本文(フロントマター除く)を返す。"""
    root = skills_dir if skills_dir is not None else SKILLS_DIR
    path = root / f"{name}{SKILL_SUFFIX}"
    if not path.is_file():
        available = ", ".join(s.name for s in list_skills(root)) or "(なし)"
        raise ValueError(f"未知のスキル名です: {name} (利用可能なスキル: {available})")
    text = path.read_text(encoding="utf-8")
    _, body = _strip_frontmatter(text)
    return body


def format_skills_catalog(skills: list[SkillInfo] | None = None) -> str:
    """システムプロンプトに追記するスキル一覧テキスト。スキルが無ければ空文字。"""
    items = list_skills() if skills is None else skills
    if not items:
        return ""
    lines = [
        "## Available skills",
        "",
        "関連するスキルがあれば `load_skill` ツールにスキル名を渡して本文を取得し、その指示に従うこと。",
        "",
    ]
    for skill in items:
        desc = skill.description or "(no description)"
        lines.append(f"- `{skill.name}`: {desc}")
    return "\n".join(lines)
