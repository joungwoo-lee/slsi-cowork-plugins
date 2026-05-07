---
name: outlook-search
description: Search and read emails stored in the local Microsoft Outlook desktop app (Windows) via COM automation. Use when the user wants to find emails by sender, subject keyword, date range, or folder in their already-installed Outlook (not Microsoft 365 cloud / Graph API). Triggers on phrases like "아웃룩에서 찾아줘", "Outlook 메일 검색", "받은편지함에서 OOO", "지난주 OOO한테 온 메일", "outlook search". Requires Windows + Outlook desktop running + pywin32. Does NOT work on macOS, Linux, or WSL.
---

# Outlook Search Skill (Windows desktop, COM)

Searches and reads emails from the **local Outlook desktop client** using `pywin32` COM automation. The mail must already be downloaded into Outlook (PST/OST). No cloud/Graph API.

## When to use
- User wants to find emails in Outlook desktop by keyword, sender, date, or folder.
- User wants to read the full body of a specific email by EntryID.
- User wants to list available mail folders / accounts.

## When NOT to use
- Mailbox is on Microsoft 365 cloud and Outlook desktop is not installed → use Graph API (python-o365) instead.
- Running on macOS / Linux / WSL → COM unavailable; tell the user.

## Prerequisites
- Windows 10/11
- Microsoft Outlook desktop installed and configured with at least one account
- Outlook should be running (or the script will start it)
- Python 3.x on Windows (not WSL Python)
- `pip install pywin32`

## Files
- Main script: `scripts/search_outlook.py`
- Folder lister: `scripts/list_folders.py`

## Commands

### 1. List accounts and folders (run first to discover folder paths)
```bash
python "%USERPROFILE%\.claude\skills\outlook-search\scripts\list_folders.py"
```
Returns JSON tree of every store (account) and folder. Use the `path` field for `--folder`.

### 2. Search emails
```bash
python "%USERPROFILE%\.claude\skills\outlook-search\scripts\search_outlook.py" ^
  --query "키워드" ^
  --from "alice@example.com" ^
  --since 2026-04-01 ^
  --until 2026-05-07 ^
  --folder "받은 편지함" ^
  --limit 20
```

All filters are optional and ANDed. If none provided, returns the most recent N items in Inbox.

#### Flags
- `--query TEXT` — substring match against subject AND body (case-insensitive)
- `--subject TEXT` — substring match against subject only
- `--body TEXT` — substring match against body only
- `--from TEXT` — sender email or display name substring
- `--since YYYY-MM-DD` — received on/after this date
- `--until YYYY-MM-DD` — received on/before this date (inclusive)
- `--folder PATH` — folder path like `받은 편지함` or `받은 편지함/프로젝트A`. Default: default Inbox.
- `--account NAME` — store/account display name. Default: default store.
- `--limit N` — max results (default 20)
- `--full-body` — include full body in output (default: 300-char snippet)
- `--unread-only` — only unread items
- `--has-attachment` — only items with attachments

#### Output
JSON array of:
```json
{
  "entry_id": "0000000...",
  "received": "2026-05-01T09:30:00",
  "from_name": "Alice",
  "from_email": "alice@example.com",
  "subject": "...",
  "snippet": "first 300 chars of body...",
  "unread": false,
  "has_attachments": true,
  "folder": "받은 편지함"
}
```

### 3. Read one email in full by EntryID
```bash
python "%USERPROFILE%\.claude\skills\outlook-search\scripts\search_outlook.py" ^
  --read-entry-id "0000000..."
```
Returns full body, headers, and attachment filenames.

## Search strategy
The script uses **manual iteration with `Items.Sort("[ReceivedTime]", True)`** rather than DASL `Restrict`, because:
- Body LIKE queries via DASL are unreliable on large mailboxes.
- Korean text in DASL filters has quoting edge cases.
- Manual iteration with early-exit on date range is fast enough for typical inboxes (< 50k items).

For very large folders, narrow with `--since` first.

## Known issues
- **Outlook security prompt**: First run may show "A program is trying to access email addresses…". Click Allow. To suppress permanently, use Trust Center → Programmatic Access settings, or run Outlook as the same user.
- **Outlook must be installed for the same user** running the script.
- **HTML body**: `snippet` is from plain `Body`. If empty, falls back to stripped `HTMLBody`.
- **Attachments**: filenames only; this skill does not save attachment content.
