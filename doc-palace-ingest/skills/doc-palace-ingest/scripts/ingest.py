#!/usr/bin/env python3
"""
ingest.py — doc-palace-ingest 스캐너

문서 폴더를 스캔하여 청킹 + 패턴 추출 결과를 JSON으로 출력한다.
LLM 요약과 파일 쓰기는 AI(Claude)가 담당한다.

Usage:
    python3 ingest.py <folder_path>              # 스캔 + 분석 → JSON 출력
    python3 ingest.py <folder_path> --finalize   # state.json 업데이트 (AI가 파일 쓰기 완료 후 호출)
    python3 ingest.py <folder_path> --status     # 현재 상태 확인

Source:
    GitignoreMatcher, chunk_text: MemPalace/mempalace/miner.py (MIT)
    extract_memories: MemPalace/mempalace/general_extractor.py (MIT)
"""

import json
import os
import re
import sys
import fnmatch
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict
from typing import List, Dict, Optional, Tuple

# =============================================================================
# CONSTANTS  (from MemPalace/mempalace/miner.py)
# =============================================================================

READABLE_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx",
    ".json", ".yaml", ".yml", ".html", ".css", ".java",
    ".go", ".rs", ".rb", ".sh", ".csv", ".sql", ".toml",
    ".rst", ".adoc", ".xml", ".conf", ".ini", ".env.example",
}

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "env",
    "dist", "build", ".next", "coverage", ".mempalace", ".ruff_cache",
    ".mypy_cache", ".pytest_cache", ".cache", ".tox", ".idea", ".vscode",
    ".ipynb_checkpoints", ".eggs", "htmlcov", "target", "_closets",
}

SKIP_FILENAMES = {
    "package-lock.json", "yarn.lock", "uv.lock", "bun.lock",
    ".gitignore", ".gitattributes", ".editorconfig",
    "_palace_work.json", ".doc-palace-state.json",
}

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
MIN_CHUNK_SIZE = 50
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

STATE_FILE = ".doc-palace-state.json"
WORK_FILE = "_palace_work.json"

# =============================================================================
# GITIGNORE MATCHER  (from MemPalace/mempalace/miner.py, MIT)
# =============================================================================

class GitignoreMatcher:
    def __init__(self, base_dir: Path, rules: list):
        self.base_dir = base_dir
        self.rules = rules

    @classmethod
    def from_dir(cls, dir_path: Path):
        gitignore_path = dir_path / ".gitignore"
        if not gitignore_path.is_file():
            return None
        try:
            lines = gitignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return None
        rules = []
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            negated = line.startswith("!")
            if negated:
                line = line[1:]
            anchored = line.startswith("/")
            if anchored:
                line = line.lstrip("/")
            dir_only = line.endswith("/")
            if dir_only:
                line = line.rstrip("/")
            if not line:
                continue
            rules.append({"pattern": line, "anchored": anchored,
                          "dir_only": dir_only, "negated": negated})
        return cls(dir_path, rules) if rules else None

    def matches(self, path: Path, is_dir: bool = None) -> Optional[bool]:
        try:
            relative = path.relative_to(self.base_dir).as_posix().strip("/")
        except ValueError:
            return None
        if not relative:
            return None
        if is_dir is None:
            is_dir = path.is_dir()
        ignored = None
        for rule in self.rules:
            if self._rule_matches(rule, relative, is_dir):
                ignored = not rule["negated"]
        return ignored

    def _rule_matches(self, rule: dict, relative: str, is_dir: bool) -> bool:
        pattern = rule["pattern"]
        parts = relative.split("/")
        pattern_parts = pattern.split("/")
        if rule["dir_only"]:
            target_parts = parts if is_dir else parts[:-1]
            if not target_parts:
                return False
            if rule["anchored"] or len(pattern_parts) > 1:
                return self._match_from_root(target_parts, pattern_parts)
            return any(fnmatch.fnmatch(part, pattern) for part in target_parts)
        if rule["anchored"] or len(pattern_parts) > 1:
            return self._match_from_root(parts, pattern_parts)
        return any(fnmatch.fnmatch(part, pattern) for part in parts)

    def _match_from_root(self, target_parts: list, pattern_parts: list) -> bool:
        def matches(pi: int, gi: int) -> bool:
            if gi == len(pattern_parts):
                return True
            if pi == len(target_parts):
                return all(p == "**" for p in pattern_parts[gi:])
            if pattern_parts[gi] == "**":
                return matches(pi, gi + 1) or matches(pi + 1, gi)
            if not fnmatch.fnmatch(target_parts[pi], pattern_parts[gi]):
                return False
            return matches(pi + 1, gi + 1)
        return matches(0, 0)


def is_gitignored(path: Path, matchers: list, is_dir: bool = False) -> bool:
    ignored = False
    for matcher in matchers:
        decision = matcher.matches(path, is_dir=is_dir)
        if decision is not None:
            ignored = decision
    return ignored

# =============================================================================
# CHUNKING  (from MemPalace/mempalace/miner.py, MIT)
# =============================================================================

def chunk_text(content: str) -> List[str]:
    content = content.strip()
    if not content:
        return []
    chunks = []
    start = 0
    while start < len(content):
        end = min(start + CHUNK_SIZE, len(content))
        if end < len(content):
            newline_pos = content.rfind("\n\n", start, end)
            if newline_pos > start + CHUNK_SIZE // 2:
                end = newline_pos
            else:
                newline_pos = content.rfind("\n", start, end)
                if newline_pos > start + CHUNK_SIZE // 2:
                    end = newline_pos
        chunk = content[start:end].strip()
        if len(chunk) >= MIN_CHUNK_SIZE:
            chunks.append(chunk)
        start = end - CHUNK_OVERLAP if end < len(content) else end
    return chunks

# =============================================================================
# PATTERN EXTRACTION  (from MemPalace/mempalace/general_extractor.py, MIT)
# =============================================================================

_DECISION_RE = [
    r"\blet'?s (use|go with|try|pick|choose|switch to)\b",
    r"\bwe (should|decided|chose|went with|picked|settled on)\b",
    r"\binstead of\b", r"\brather than\b", r"\btrade-?off\b",
    r"\barchitecture\b", r"\bapproach\b", r"\bstrategy\b",
    r"\bframework\b", r"\binfrastructure\b", r"\bconfigure\b",
]
_PROBLEM_RE = [
    r"\b(bug|error|crash|fail|broke|broken|issue|problem)\b",
    r"\bdoesn'?t work\b", r"\bnot working\b",
    r"\broot cause\b", r"\bthe fix (is|was)\b", r"\bworkaround\b",
]
_MILESTONE_RE = [
    r"\bit works\b", r"\bfixed\b", r"\bsolved\b", r"\bfinally\b",
    r"\bimplemented\b", r"\bshipped\b", r"\blaunched\b", r"\bdeployed\b",
]
_TECHNICAL_RE = [
    r"\bapi\b", r"\bendpoint\b", r"\bfunction\b", r"\bclass\b",
    r"\binterface\b", r"\bschema\b", r"\bdatabase\b", r"\bconfig\b",
    r"\binstall\b", r"\bsetup\b", r"\bdeploy\b", r"\bdocker\b",
    r"\bhttp\b", r"\brest\b", r"\bgraphql\b", r"\bsql\b",
]

def _score(text: str, patterns: List[str]) -> int:
    t = text.lower()
    return sum(1 for p in patterns if re.search(p, t))

def classify_chunk(text: str) -> str:
    """
    청크의 주된 성격을 Hall 이름으로 반환.
    decision > problem > milestone > technical > reference
    """
    scores = {
        "decisions":  _score(text, _DECISION_RE),
        "problems":   _score(text, _PROBLEM_RE),
        "milestones": _score(text, _MILESTONE_RE),
        "technical":  _score(text, _TECHNICAL_RE),
    }
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "reference"

# =============================================================================
# ROOM / WING DETECTION  (경로 기반)
# =============================================================================

def detect_wing(filepath: Path, folder_root: Path) -> str:
    """
    최상위 서브디렉토리를 Wing으로 사용.
    파일이 루트에 있으면 폴더명을 Wing으로.
    """
    try:
        parts = filepath.relative_to(folder_root).parts
    except ValueError:
        return folder_root.name
    if len(parts) >= 2:
        return parts[0]
    return folder_root.name

def detect_room(filepath: Path, folder_root: Path) -> str:
    """
    파일명(확장자 제외)을 Room 슬러그로 사용.
    경로 구분자를 하이픈으로 변환하여 계층 표현.
    예: auth/jwt-design.md → auth-jwt-design
    """
    try:
        relative = filepath.relative_to(folder_root)
    except ValueError:
        return filepath.stem
    parts = list(relative.parts)
    # 마지막이 파일명이면 stem으로
    parts[-1] = Path(parts[-1]).stem
    slug = "-".join(p.lower().replace(" ", "-").replace("_", "-") for p in parts)
    # 특수문자 제거
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "general"

# =============================================================================
# STATE MANAGEMENT
# =============================================================================

def load_state(folder: Path) -> dict:
    state_path = folder / STATE_FILE
    if state_path.exists():
        try:
            return json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"generated_at": None, "files": {}}

def save_state(folder: Path, state: dict):
    state_path = folder / STATE_FILE
    state["generated_at"] = datetime.now(timezone.utc).isoformat()
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")

# =============================================================================
# FOLDER SCAN
# =============================================================================

def scan_folder(folder: Path, state: dict) -> Tuple[List[dict], List[str]]:
    """
    폴더를 재귀 스캔하여 처리할 파일 목록 반환.
    Returns:
        to_process: 신규/변경 파일 정보 리스트
        removed:    삭제된 파일 경로 리스트
    """
    gitignore_cache = {}
    matchers_stack = []

    root_matcher = GitignoreMatcher.from_dir(folder)
    if root_matcher:
        matchers_stack.append(root_matcher)

    found_files = set()
    to_process = []

    for dirpath, dirnames, filenames in os.walk(folder):
        current_dir = Path(dirpath)

        # 스킵 디렉토리 필터
        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in SKIP_DIRS
            and not d.endswith(".egg-info")
            and not is_gitignored(current_dir / d, matchers_stack, is_dir=True)
        ]

        # 현재 디렉토리 .gitignore 로드
        local_matcher = GitignoreMatcher.from_dir(current_dir)
        if local_matcher:
            matchers_stack.append(local_matcher)

        for filename in sorted(filenames):
            if filename in SKIP_FILENAMES:
                continue
            filepath = current_dir / filename
            if is_gitignored(filepath, matchers_stack):
                continue
            if filepath.suffix.lower() not in READABLE_EXTENSIONS:
                continue
            if filepath.stat().st_size > MAX_FILE_SIZE:
                continue

            rel_path = str(filepath.relative_to(folder))
            found_files.add(rel_path)

            current_mtime = filepath.stat().st_mtime
            stored = state["files"].get(rel_path, {})
            stored_mtime = stored.get("mtime")

            is_new = stored_mtime is None
            is_changed = not is_new and abs(float(stored_mtime) - current_mtime) > 0.001

            if is_new or is_changed:
                to_process.append({
                    "path": rel_path,
                    "mtime": current_mtime,
                    "is_new": is_new,
                    "wing": detect_wing(filepath, folder),
                    "room": detect_room(filepath, folder),
                })

        # matchers_stack 팝 (하위 탐색 완료 후)
        if local_matcher:
            matchers_stack.pop()

    # 삭제된 파일
    removed = [p for p in state["files"] if p not in found_files]

    return to_process, removed

# =============================================================================
# MAIN ANALYSIS
# =============================================================================

def analyze_file(filepath: Path, meta: dict) -> dict:
    """파일을 읽어 청킹 + Hall 분류 수행."""
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {**meta, "error": str(e), "chunks": []}

    raw_chunks = chunk_text(content)
    analyzed_chunks = []
    hall_counts = defaultdict(int)

    for i, chunk in enumerate(raw_chunks):
        hall = classify_chunk(chunk)
        hall_counts[hall] += 1
        analyzed_chunks.append({
            "index": i,
            "hall": hall,
            "text": chunk,
        })

    # 파일 전체 대표 Hall (가장 많은 것)
    dominant_hall = max(hall_counts, key=hall_counts.get) if hall_counts else "reference"

    return {
        **meta,
        "dominant_hall": dominant_hall,
        "hall_counts": dict(hall_counts),
        "chunk_count": len(analyzed_chunks),
        "chunks": analyzed_chunks,
        "content_preview": content[:200].replace("\n", " "),
    }

def run_scan(folder_path: str):
    """메인 스캔 실행 → _palace_work.json 출력."""
    folder = Path(folder_path).expanduser().resolve()
    if not folder.is_dir():
        print(json.dumps({"error": f"폴더를 찾을 수 없음: {folder_path}"}))
        sys.exit(1)

    state = load_state(folder)
    to_process, removed = scan_folder(folder, state)

    # 변경/신규 없고 removed도 없으면 완전 최신
    if not to_process and not removed:
        result = {
            "status": "up_to_date",
            "folder": str(folder),
            "folder_name": folder.name,
            "message": "변경된 파일 없음. AGENTS.md가 최신 상태입니다.",
            "total_tracked": len(state["files"]),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    # 분석 수행
    analyzed = []
    for meta in to_process:
        filepath = folder / meta["path"]
        analyzed.append(analyze_file(filepath, meta))

    # Wing/Room 구조 빌드
    wings: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for item in analyzed:
        if "error" not in item:
            wings[item["wing"]][item["room"]].append(item["path"])

    # 기존 state에서 변경 없는 파일도 구조에 포함
    existing_wings: Dict[str, Dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for path, info in state["files"].items():
        if path not in {a["path"] for a in analyzed} and path not in removed:
            w = info.get("wing", folder.name)
            r = info.get("room", "general")
            existing_wings[w][r].append(path)

    # Tunnel 감지: 같은 room이 여러 wing에 등장
    all_room_wings: Dict[str, set] = defaultdict(set)
    for w, rooms in {**existing_wings, **wings}.items():
        for r in rooms:
            all_room_wings[r].add(w)
    tunnels = [
        {"room": r, "wings": sorted(ws)}
        for r, ws in all_room_wings.items()
        if len(ws) >= 2
    ]

    result = {
        "status": "needs_update",
        "folder": str(folder),
        "folder_name": folder.name,
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "new_files": sum(1 for a in analyzed if a.get("is_new")),
            "changed_files": sum(1 for a in analyzed if not a.get("is_new")),
            "removed_files": len(removed),
            "total_chunks": sum(a.get("chunk_count", 0) for a in analyzed),
        },
        "new_and_changed": analyzed,
        "removed": removed,
        "existing_structure": {w: dict(rooms) for w, rooms in existing_wings.items()},
        "tunnels": tunnels,
    }

    # _palace_work.json 저장
    work_path = folder / WORK_FILE
    work_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n# 작업 파일 저장됨: {work_path}", file=sys.stderr)

def run_finalize(folder_path: str):
    """AI가 파일 쓰기를 완료한 후 state.json 업데이트."""
    folder = Path(folder_path).expanduser().resolve()
    work_path = folder / WORK_FILE

    if not work_path.exists():
        print(json.dumps({"error": "_palace_work.json 없음. ingest.py를 먼저 실행하세요."}))
        sys.exit(1)

    work = json.loads(work_path.read_text(encoding="utf-8"))
    state = load_state(folder)

    # 신규/변경 파일 state 업데이트
    for item in work.get("new_and_changed", []):
        if "error" not in item:
            state["files"][item["path"]] = {
                "mtime": item["mtime"],
                "wing": item["wing"],
                "room": item["room"],
            }

    # 삭제 파일 제거
    for path in work.get("removed", []):
        state["files"].pop(path, None)

    save_state(folder, state)

    # 작업 파일 정리
    work_path.unlink(missing_ok=True)

    result = {
        "status": "finalized",
        "folder": str(folder),
        "tracked_files": len(state["files"]),
        "generated_at": state["generated_at"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

def run_status(folder_path: str):
    """현재 상태 확인."""
    folder = Path(folder_path).expanduser().resolve()
    state = load_state(folder)
    agents_md = folder / "AGENTS.md"
    closets_dir = folder / "_closets"

    closet_count = len(list(closets_dir.glob("*.aaak.md"))) if closets_dir.exists() else 0

    rooms = set()
    wings = set()
    for info in state["files"].values():
        rooms.add(info.get("room", "general"))
        wings.add(info.get("wing", folder.name))

    result = {
        "folder": str(folder),
        "has_agents_md": agents_md.exists(),
        "tracked_files": len(state["files"]),
        "wings": sorted(wings),
        "rooms": sorted(rooms),
        "closet_files": closet_count,
        "last_ingest": state.get("generated_at"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python3 ingest.py <folder>             # 스캔 및 분석")
        print("  python3 ingest.py <folder> --finalize  # state 업데이트")
        print("  python3 ingest.py <folder> --status    # 현재 상태 확인")
        sys.exit(1)

    folder_arg = sys.argv[1]
    mode = sys.argv[2] if len(sys.argv) > 2 else ""

    if mode == "--finalize":
        run_finalize(folder_arg)
    elif mode == "--status":
        run_status(folder_arg)
    else:
        run_scan(folder_arg)
