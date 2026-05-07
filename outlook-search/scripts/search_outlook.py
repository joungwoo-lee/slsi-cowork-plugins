"""Search and read emails in local Microsoft Outlook desktop via COM (Windows only).

Requires: pywin32 (`pip install pywin32`) and Outlook desktop installed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, time

try:
    import win32com.client
    import pywintypes
except ImportError:
    sys.stderr.write(
        "ERROR: pywin32 not installed. Run: pip install pywin32\n"
        "Also: this script must run on Windows with Outlook desktop installed.\n"
    )
    sys.exit(2)


OL_FOLDER_INBOX = 6


def get_namespace():
    app = win32com.client.Dispatch("Outlook.Application")
    return app.GetNamespace("MAPI")


def resolve_folder(ns, account: str | None, folder_path: str | None):
    """Return a Folder object given an account name and a slash-separated folder path.

    If folder_path is None, returns default Inbox of the chosen account (or the
    overall default if account is None).
    """
    if account is None and folder_path is None:
        return ns.GetDefaultFolder(OL_FOLDER_INBOX)

    # Pick the root: account's root folder, or default store root
    root = None
    if account:
        for store in ns.Stores:
            if store.DisplayName == account:
                root = store.GetRootFolder()
                break
        if root is None:
            raise RuntimeError(f"Account not found: {account!r}")
    else:
        # No account specified but folder_path given → use default store root
        root = ns.DefaultStore.GetRootFolder()

    if not folder_path:
        # Account specified, folder not → that account's Inbox
        for f in root.Folders:
            if f.Name.lower() in ("inbox", "받은 편지함"):
                return f
        return root

    # Walk the path
    current = root
    for part in [p for p in folder_path.split("/") if p]:
        found = None
        for f in current.Folders:
            if f.Name == part:
                found = f
                break
        if found is None:
            raise RuntimeError(
                f"Folder segment {part!r} not found under {current.Name!r}"
            )
        current = found
    return current


def to_dt(value) -> datetime | None:
    if value is None:
        return None
    try:
        # pywintypes.datetime is tz-aware; strip tzinfo for naive comparison
        return datetime(
            value.year, value.month, value.day,
            value.hour, value.minute, value.second,
        )
    except Exception:
        return None


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def get_snippet(item, length: int = 300) -> str:
    body = ""
    try:
        body = item.Body or ""
    except Exception:
        body = ""
    if not body:
        try:
            html = item.HTMLBody or ""
            body = _HTML_TAG_RE.sub(" ", html)
        except Exception:
            body = ""
    body = _WS_RE.sub(" ", body).strip()
    return body[:length]


def get_full_body(item) -> str:
    try:
        body = item.Body or ""
    except Exception:
        body = ""
    if body.strip():
        return body
    try:
        html = item.HTMLBody or ""
        return _HTML_TAG_RE.sub(" ", html)
    except Exception:
        return ""


def get_sender(item) -> tuple[str, str]:
    name = ""
    email = ""
    try:
        name = item.SenderName or ""
    except Exception:
        pass
    try:
        email = item.SenderEmailAddress or ""
    except Exception:
        pass
    # Exchange senders often expose X.500 instead of SMTP; try resolving
    if email and email.startswith("/"):
        try:
            sender = item.Sender
            if sender is not None:
                exch = sender.GetExchangeUser()
                if exch is not None:
                    email = exch.PrimarySmtpAddress or email
        except Exception:
            pass
    return name, email


def item_matches(
    item,
    query: str | None,
    subject_q: str | None,
    body_q: str | None,
    from_q: str | None,
    since: datetime | None,
    until: datetime | None,
    unread_only: bool,
    has_attachment: bool,
) -> bool:
    # Date filters
    received = to_dt(getattr(item, "ReceivedTime", None))
    if since and (received is None or received < since):
        return False
    if until and (received is None or received > until):
        return False

    # Unread / attachment
    if unread_only:
        try:
            if not item.UnRead:
                return False
        except Exception:
            return False
    if has_attachment:
        try:
            if item.Attachments.Count == 0:
                return False
        except Exception:
            return False

    # Sender filter
    if from_q:
        name, email = get_sender(item)
        hay = f"{name} {email}".lower()
        if from_q.lower() not in hay:
            return False

    # Text filters (case-insensitive substring)
    subject = ""
    try:
        subject = (item.Subject or "")
    except Exception:
        pass

    if subject_q and subject_q.lower() not in subject.lower():
        return False

    if body_q:
        body = get_snippet(item, length=10_000).lower()
        if body_q.lower() not in body:
            return False

    if query:
        ql = query.lower()
        if ql not in subject.lower():
            body = get_snippet(item, length=10_000).lower()
            if ql not in body:
                return False

    return True


def serialize_item(item, folder_name: str, full_body: bool) -> dict:
    name, email = get_sender(item)
    received = to_dt(getattr(item, "ReceivedTime", None))
    try:
        unread = bool(item.UnRead)
    except Exception:
        unread = False
    try:
        has_att = item.Attachments.Count > 0
    except Exception:
        has_att = False
    try:
        subject = item.Subject or ""
    except Exception:
        subject = ""
    try:
        entry_id = item.EntryID
    except Exception:
        entry_id = ""

    out = {
        "entry_id": entry_id,
        "received": received.isoformat() if received else None,
        "from_name": name,
        "from_email": email,
        "subject": subject,
        "unread": unread,
        "has_attachments": has_att,
        "folder": folder_name,
    }
    if full_body:
        out["body"] = get_full_body(item)
        attachments = []
        try:
            for i in range(1, item.Attachments.Count + 1):
                att = item.Attachments.Item(i)
                attachments.append(att.FileName)
        except Exception:
            pass
        out["attachments"] = attachments
    else:
        out["snippet"] = get_snippet(item, length=300)
    return out


def search(
    ns,
    account: str | None,
    folder_path: str | None,
    query: str | None,
    subject_q: str | None,
    body_q: str | None,
    from_q: str | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
    full_body: bool,
    unread_only: bool,
    has_attachment: bool,
) -> list[dict]:
    folder = resolve_folder(ns, account, folder_path)
    items = folder.Items
    try:
        items.Sort("[ReceivedTime]", True)  # newest first
    except Exception:
        pass

    results: list[dict] = []
    # Iterate; rely on date sort + early termination when 'since' boundary crossed
    item = items.GetFirst()
    while item is not None:
        try:
            if item.Class != 43:  # 43 = olMail; skip non-mail
                item = items.GetNext()
                continue
        except Exception:
            item = items.GetNext()
            continue

        # Early exit: if sorted newest first and received < since, stop
        received = to_dt(getattr(item, "ReceivedTime", None))
        if since and received is not None and received < since:
            break

        try:
            if item_matches(
                item, query, subject_q, body_q, from_q,
                since, until, unread_only, has_attachment,
            ):
                results.append(serialize_item(item, folder.Name, full_body))
                if len(results) >= limit:
                    break
        except pywintypes.com_error:
            pass

        item = items.GetNext()

    return results


def read_by_entry_id(ns, entry_id: str) -> dict:
    item = ns.GetItemFromID(entry_id)
    folder_name = ""
    try:
        folder_name = item.Parent.Name
    except Exception:
        pass
    return serialize_item(item, folder_name, full_body=True)


def parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def main():
    p = argparse.ArgumentParser(description="Search local Outlook desktop emails.")
    p.add_argument("--query")
    p.add_argument("--subject")
    p.add_argument("--body")
    p.add_argument("--from", dest="from_", help="sender email or name substring")
    p.add_argument("--since", help="YYYY-MM-DD")
    p.add_argument("--until", help="YYYY-MM-DD")
    p.add_argument("--folder", help="slash-separated folder path")
    p.add_argument("--account", help="store/account display name")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--full-body", action="store_true")
    p.add_argument("--unread-only", action="store_true")
    p.add_argument("--has-attachment", action="store_true")
    p.add_argument("--read-entry-id", help="fetch one mail by EntryID and exit")
    args = p.parse_args()

    ns = get_namespace()

    if args.read_entry_id:
        result = read_by_entry_id(ns, args.read_entry_id)
        sys.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
        sys.stdout.write("\n")
        return

    since = parse_date(args.since) if args.since else None
    until = (
        datetime.combine(parse_date(args.until).date(), time(23, 59, 59))
        if args.until else None
    )

    results = search(
        ns,
        account=args.account,
        folder_path=args.folder,
        query=args.query,
        subject_q=args.subject,
        body_q=args.body,
        from_q=args.from_,
        since=since,
        until=until,
        limit=args.limit,
        full_body=args.full_body,
        unread_only=args.unread_only,
        has_attachment=args.has_attachment,
    )
    sys.stdout.write(json.dumps(results, ensure_ascii=False, indent=2))
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
