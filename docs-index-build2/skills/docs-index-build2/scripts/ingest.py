#!/usr/bin/env python3
"""
ingest.py — docs-index-build2 scanner

문서 폴더를 스캔하여 청킹과 라우팅 메타데이터를 JSON으로 출력한다.
closet/AGENTS.md 작성은 AI가 담당한다.
"""

import fnmatch
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
MAX_FILE_SIZE = 5 * 1024 * 1024

STATE_FILE = ".doc-palace-state.json"
WORK_FILE = "_palace_work.json"

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "when", "where",
    "what", "how", "why", "which", "then", "than", "into", "onto", "will", "shall",
    "have", "has", "had", "using", "used", "use", "user", "users", "your", "their",
    "there", "here", "also", "only", "more", "most", "many", "much", "each", "other",
    "into", "does", "doesnt", "dont", "should", "must", "can", "could", "would",
    "문서", "설명", "사용", "구성", "정의", "처리", "생성", "수행", "대한", "관련",
    "에서", "하기", "하는", "한다", "위한", "또는", "그리고", "파일", "폴더", "섹션",
}

COMMON_TOPICS = {
    "overview", "introduction", "general", "notes", "guide", "docs", "doc", "readme",
    "example", "examples", "reference", "misc", "common", "default",
}

QTYPE_PATTERNS = {
    "setup": [r"\binstall\b", r"\bsetup\b", r"\bprerequisite\b", r"\brequirements?\b"],
    "config": [r"\bconfig\b", r"\bconfiguration\b", r"\benv\b", r"\boption\b", r"\bsettings?\b"],
    "api_contract": [r"\bapi\b", r"\bendpoint\b", r"\brequest\b", r"\bresponse\b", r"\bschema\b"],
    "error_policy": [r"\berror\b", r"\bexception\b", r"\bfail\b", r"\b401\b", r"\b403\b", r"\b5\d\d\b"],
    "decision_log": [r"\bdecid\w*\b", r"\btrade-?off\b", r"\brather than\b", r"\binstead of\b", r"\bchosen\b"],
    "architecture": [r"\barchitecture\b", r"\bcomponent\b", r"\bflow\b", r"\bdiagram\b", r"\binvariant\b"],
    "workflow": [r"\bworkflow\b", r"\bprocess\b", r"\bstep\b", r"\bpipeline\b"],
    "troubleshooting": [r"\btroubleshoot\b", r"\bdebug\b", r"\broot cause\b", r"\bworkaround\b"],
    "security": [r"\bauth\b", r"\bauthoriz\w*\b", r"\btoken\b", r"\bpermission\b", r"\bsecurity\b"],
    "reference": [r"\breference\b", r"\btable\b", r"\bmatrix\b", r"\blookup\b"],
}

HALL_PATTERNS = {
    "decisions": [r"\bdecid\w*\b", r"\btrade-?off\b", r"\bchosen\b", r"\brather than\b", r"\binstead of\b"],
    "problems": [r"\berror\b", r"\bfail\b", r"\bissue\b", r"\bbug\b", r"\bworkaround\b", r"\broot cause\b"],
    "milestones": [r"\bshipped\b", r"\bimplemented\b", r"\bcompleted\b", r"\blaunched\b", r"\bdeployed\b"],
    "technical": [r"\bapi\b", r"\bconfig\b", r"\bschema\b", r"\bdatabase\b", r"\bclass\b", r"\bfunction\b", r"\btoken\b"],
}


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
            if line:
                rules.append({"pattern": line, "anchored": anchored, "dir_only": dir_only, "negated": negated})
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


def chunk_text(content: str) -> List[str]:
    content = content.strip()
    if not content:
        return []
    chunks = []
    start = 0
    while start < len(content):
        end = min(start + CHUNK_SIZE, len(content))
        if end < len(content):
            split = content.rfind("\n\n", start, end)
            if split <= start + CHUNK_SIZE // 2:
                split = content.rfind("\n", start, end)
            if split > start + CHUNK_SIZE // 2:
                end = split
        chunk = content[start:end].strip()
        if len(chunk) >= MIN_CHUNK_SIZE:
            chunks.append(chunk)
        start = end - CHUNK_OVERLAP if end < len(content) else end
    return chunks


def normalize_token(token: str) -> str:
    token = token.strip().lower().replace("-", "_")
    token = re.sub(r"[^a-z0-9_]+", "", token)
    if len(token) < 3:
        return ""
    if token in STOPWORDS or token in COMMON_TOPICS:
        return ""
    return token


def tokenize(content: str) -> List[str]:
    raw = re.findall(r"[A-Za-z][A-Za-z0-9_\-/]{2,}", content)
    tokens = []
    for item in raw:
        for part in re.split(r"[\-_/]", item):
            norm = normalize_token(part)
            if norm:
                tokens.append(norm)
    return tokens


def extract_headings(content: str) -> List[str]:
    headings = []
    for line in content.splitlines():
        text = line.strip()
        if re.match(r"^#{1,6}\s+", text):
            headings.append(re.sub(r"^#{1,6}\s+", "", text).strip())
        elif re.match(r"^[A-Z][A-Za-z0-9 /:_-]{3,80}$", text) and not text.endswith((":", ";")):
            headings.append(text)
    return headings[:12]


def extract_entities(content: str) -> List[str]:
    counts = Counter(re.findall(r"\b[A-Z][A-Z0-9]{1,4}\b", content))
    entities = []
    for token, count in counts.most_common():
        if count < 2:
            continue
        if token in {"THE", "AND"}:
            continue
        entities.append(token)
        if len(entities) >= 8:
            break
    return entities


def infer_qtypes(content: str) -> List[str]:
    lowered = content.lower()
    scored = []
    for qtype, patterns in QTYPE_PATTERNS.items():
        score = sum(1 for pattern in patterns if re.search(pattern, lowered))
        if score:
            scored.append((score, qtype))
    return [name for _, name in sorted(scored, reverse=True)[:5]]


def classify_chunk(text: str) -> str:
    lowered = text.lower()
    scores = {hall: sum(1 for pattern in patterns if re.search(pattern, lowered)) for hall, patterns in HALL_PATTERNS.items()}
    if re.search(r"^#{1,6}\s+", text, re.MULTILINE):
        scores["technical"] += 1
    if re.search(r"\b(step|workflow|procedure|pipeline)\b", lowered):
        scores["technical"] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "reference"


def dominant_hall_from_content(content: str, chunks: List[dict]) -> str:
    counts = Counter(chunk["hall"] for chunk in chunks)
    headings = " ".join(extract_headings(content)).lower()
    if re.search(r"\bdecision|trade-?off|chosen\b", headings):
        counts["decisions"] += 2
    if re.search(r"\berror|troubleshoot|debug|incident\b", headings):
        counts["problems"] += 2
    if re.search(r"\breference|matrix|lookup\b", headings):
        counts["reference"] += 2
    return counts.most_common(1)[0][0] if counts else "reference"


def detect_wing(filepath: Path, folder_root: Path) -> str:
    try:
        parts = filepath.relative_to(folder_root).parts
    except ValueError:
        return folder_root.name
    return parts[0] if len(parts) >= 2 else folder_root.name


def detect_room(filepath: Path, folder_root: Path) -> str:
    try:
        relative = filepath.relative_to(folder_root)
    except ValueError:
        return filepath.stem
    parts = list(relative.parts)
    parts[-1] = Path(parts[-1]).stem
    slug = "-".join(p.lower().replace(" ", "-").replace("_", "-") for p in parts)
    slug = re.sub(r"[^a-z0-9\-]", "", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "general"


def build_sections(content: str, keywords: List[str]) -> List[dict]:
    headings = extract_headings(content)
    sections = []
    for idx, heading in enumerate(headings[:6], start=1):
        section_keywords = [token for token in tokenize(heading)[:3]]
        if not section_keywords:
            section_keywords = keywords[:3]
        sections.append({"id": f"S{idx}", "label": heading[:80], "keywords": section_keywords[:4]})
    if not sections:
        slices = ["core", "details", "exceptions"]
        for idx, label in enumerate(slices[: max(1, min(3, len(keywords) // 2 + 1))], start=1):
            start = max(0, (idx - 1) * 2)
            sections.append({"id": f"S{idx}", "label": label, "keywords": keywords[start:start + 3]})
    return sections[:8]


def summarize_about(content: str) -> List[str]:
    heading_tokens = []
    for heading in extract_headings(content):
        heading_tokens.extend(tokenize(heading))
    body_tokens = tokenize(content)
    counter = Counter(heading_tokens * 3 + body_tokens)
    return [token for token, _ in counter.most_common(8)]


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


def scan_folder(folder: Path, state: dict) -> Tuple[List[dict], List[str], List[str]]:
    matchers_stack = []
    root_matcher = GitignoreMatcher.from_dir(folder)
    if root_matcher:
        matchers_stack.append(root_matcher)

    found_files = []
    to_process = []

    for dirpath, dirnames, filenames in os.walk(folder):
        current_dir = Path(dirpath)
        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in SKIP_DIRS and not d.endswith(".egg-info") and not is_gitignored(current_dir / d, matchers_stack, is_dir=True)
        ]

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
            found_files.append(rel_path)

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

        if local_matcher:
            matchers_stack.pop()

    removed = [p for p in state["files"] if p not in set(found_files)]
    return to_process, removed, found_files


def analyze_file(filepath: Path, meta: dict) -> dict:
    try:
        content = filepath.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {**meta, "error": str(exc), "chunks": []}

    raw_chunks = chunk_text(content)
    chunks = []
    for idx, chunk in enumerate(raw_chunks):
        chunks.append({"index": idx, "hall": classify_chunk(chunk), "text": chunk})

    about = summarize_about(content)
    entities = extract_entities(content)
    qtypes = infer_qtypes(content)
    sections = build_sections(content, about)

    return {
        **meta,
        "dominant_hall": dominant_hall_from_content(content, chunks),
        "chunk_count": len(chunks),
        "chunks": chunks,
        "content_preview": content[:200].replace("\n", " "),
        "headings": extract_headings(content),
        "about": about[:6],
        "not_about": [],
        "qtypes": qtypes,
        "entities": entities[:6],
        "sections": sections,
    }


def build_room_index(documents: List[dict]) -> List[dict]:
    room_map: Dict[Tuple[str, str], List[dict]] = defaultdict(list)
    for doc in documents:
        room_map[(doc["wing"], doc["room"])].append(doc)

    room_index = []
    for (wing, room), docs in room_map.items():
        about_counter = Counter()
        entity_counter = Counter()
        qtype_counter = Counter()
        sections = []
        hall_counter = Counter()
        for doc in docs:
            about_counter.update(doc.get("about", []))
            entity_counter.update(doc.get("entities", []))
            qtype_counter.update(doc.get("qtypes", []))
            hall_counter.update([doc.get("dominant_hall", "reference")])
            sections.extend(doc.get("sections", []))
        room_index.append({
            "wing": wing,
            "room": room,
            "doc_count": len(docs),
            "dominant_hall": hall_counter.most_common(1)[0][0] if hall_counter else "reference",
            "about": [token for token, _ in about_counter.most_common(6)],
            "entities": [token for token, _ in entity_counter.most_common(6)],
            "qtypes": [token for token, _ in qtype_counter.most_common(5)],
            "sections": sections[:8],
            "paths": [doc["path"] for doc in docs],
        })

    by_wing: Dict[str, List[dict]] = defaultdict(list)
    for room in room_index:
        by_wing[room["wing"]].append(room)

    for wing_rooms in by_wing.values():
        for room in wing_rooms:
            current = set(room["about"])
            similar = []
            for other in wing_rooms:
                if other["room"] == room["room"]:
                    continue
                overlap = len(current & set(other["about"]))
                if overlap:
                    similar.append((overlap, other))
            similar.sort(reverse=True, key=lambda item: item[0])
            exclusion = []
            for _, other in similar[:2]:
                for token in other["about"]:
                    if token not in current and token not in exclusion:
                        exclusion.append(token)
                    if len(exclusion) >= 6:
                        break
                if len(exclusion) >= 6:
                    break
            room["not_about"] = exclusion

    return sorted(room_index, key=lambda item: (item["wing"], item["room"]))


def build_tunnels(room_index: List[dict]) -> List[dict]:
    tunnels = []
    for idx, room in enumerate(room_index):
        for other in room_index[idx + 1:]:
            shared_entities = sorted(set(room["entities"]) & set(other["entities"]))
            shared_qtypes = sorted(set(room["qtypes"]) & set(other["qtypes"]))
            shared_about = sorted(set(room["about"]) & set(other["about"]))
            label = None
            if shared_entities:
                label = f"shared_entity:{shared_entities[0]}"
            elif shared_qtypes:
                label = f"shared_qtype:{shared_qtypes[0]}"
            elif len(shared_about) >= 2:
                label = f"shared_topic:{shared_about[0]}"
            if label:
                tunnels.append({
                    "room_a": room["room"],
                    "room_b": other["room"],
                    "label": label,
                })
    return tunnels[:40]


def rebuild_documents(folder: Path, analyzed: List[dict], state: dict, removed: List[str]) -> List[dict]:
    changed = {doc["path"]: doc for doc in analyzed if "error" not in doc}
    documents = list(changed.values())
    for path, info in state["files"].items():
        if path in changed or path in removed:
            continue
        documents.append({
            "path": path,
            "mtime": info.get("mtime"),
            "is_new": False,
            "wing": info.get("wing", folder.name),
            "room": info.get("room", "general"),
            "dominant_hall": info.get("dominant_hall", "reference"),
            "chunk_count": info.get("chunk_count", 0),
            "chunks": [],
            "content_preview": info.get("content_preview", ""),
            "headings": info.get("headings", []),
            "about": info.get("about", []),
            "not_about": info.get("not_about", []),
            "qtypes": info.get("qtypes", []),
            "entities": info.get("entities", []),
            "sections": info.get("sections", []),
        })
    return sorted(documents, key=lambda item: item["path"])


def run_scan(folder_path: str):
    folder = Path(folder_path).expanduser().resolve()
    if not folder.is_dir():
        print(json.dumps({"error": f"폴더를 찾을 수 없음: {folder_path}"}))
        sys.exit(1)

    state = load_state(folder)
    to_process, removed, _ = scan_folder(folder, state)

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

    analyzed = [analyze_file(folder / meta["path"], meta) for meta in to_process]
    all_documents = rebuild_documents(folder, analyzed, state, removed)
    room_index = build_room_index(all_documents)

    room_not_about = {(room["wing"], room["room"]): room.get("not_about", []) for room in room_index}
    for doc in analyzed:
        doc["not_about"] = room_not_about.get((doc["wing"], doc["room"]), [])

    result = {
        "status": "needs_update",
        "folder": str(folder),
        "folder_name": folder.name,
        "scan_time": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "new_files": sum(1 for doc in analyzed if doc.get("is_new")),
            "changed_files": sum(1 for doc in analyzed if not doc.get("is_new")),
            "removed_files": len(removed),
            "total_chunks": sum(doc.get("chunk_count", 0) for doc in analyzed),
        },
        "new_and_changed": analyzed,
        "removed": removed,
        "all_documents": all_documents,
        "room_index": room_index,
        "tunnels": build_tunnels(room_index),
    }

    work_path = folder / WORK_FILE
    work_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"\n# 작업 파일 저장됨: {work_path}", file=sys.stderr)


def run_finalize(folder_path: str):
    folder = Path(folder_path).expanduser().resolve()
    work_path = folder / WORK_FILE
    if not work_path.exists():
        print(json.dumps({"error": "_palace_work.json 없음. ingest.py를 먼저 실행하세요."}))
        sys.exit(1)

    work = json.loads(work_path.read_text(encoding="utf-8"))
    state = load_state(folder)
    for item in work.get("new_and_changed", []):
        if "error" in item:
            continue
        state["files"][item["path"]] = {
            "mtime": item["mtime"],
            "wing": item["wing"],
            "room": item["room"],
            "dominant_hall": item.get("dominant_hall", "reference"),
            "chunk_count": item.get("chunk_count", 0),
            "content_preview": item.get("content_preview", ""),
            "headings": item.get("headings", []),
            "about": item.get("about", []),
            "not_about": item.get("not_about", []),
            "qtypes": item.get("qtypes", []),
            "entities": item.get("entities", []),
            "sections": item.get("sections", []),
        }
    for path in work.get("removed", []):
        state["files"].pop(path, None)

    save_state(folder, state)
    work_path.unlink(missing_ok=True)

    result = {
        "status": "finalized",
        "folder": str(folder),
        "tracked_files": len(state["files"]),
        "generated_at": state["generated_at"],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def run_status(folder_path: str):
    folder = Path(folder_path).expanduser().resolve()
    state = load_state(folder)
    agents_md = folder / "AGENTS.md"
    closets_dir = folder / "_closets"
    closet_count = len(list(closets_dir.glob("*.aaak.md"))) if closets_dir.exists() else 0

    wings = sorted({info.get("wing", folder.name) for info in state["files"].values()})
    rooms = sorted({info.get("room", "general") for info in state["files"].values()})
    qtypes = sorted({q for info in state["files"].values() for q in info.get("qtypes", [])})

    result = {
        "folder": str(folder),
        "has_agents_md": agents_md.exists(),
        "tracked_files": len(state["files"]),
        "wings": wings,
        "rooms": rooms,
        "qtypes": qtypes,
        "closet_files": closet_count,
        "last_ingest": state.get("generated_at"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


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
