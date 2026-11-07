"""
Standalone Instagram 1-Click Publisher Script.

Usage:
    python publish_instagram.py --id 36
    python publish_instagram.py --id 36 --caption "Check out this insane moment! #Shorts #Reels"
    python publish_instagram.py --url "https://.../video.mp4" --caption "Awesome clip"
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.database import DatabaseService
from src.services.instagram_publisher import InstagramPublisher, InstagramPublishError
from src.console import log_error, log_info, log_success, log_warning


def is_url_accessible(url: str, timeout: int = 5) -> bool:
    """Check if an HTTP/HTTPS URL is live and returns 200 OK."""
    if not url or not url.startswith("http") or "example.com" in url:
        return False
    try:
        r = requests.head(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return True
        if r.status_code in (403, 405):
            r = requests.get(url, stream=True, timeout=timeout)
            return r.status_code == 200
        return False
    except Exception:
        return False


def build_default_caption(hook_title: str, tags: Optional[str] = None) -> str:
    """Build an engaging, clean Instagram caption from title and tags."""
    title = hook_title.strip() if hook_title else "New Reel"
    # Basic hashtags for reels discovery
    base_tags = ["#reels", "#reelsinstagram", "#viral", "#trending", "#fyp"]
    if tags:
        extra_tags = [str(t).strip() for t in (tags if isinstance(tags, (list, tuple)) else str(tags).strip("[]").replace('"', "").replace("'", "").split(",")) if str(t).strip()]
        for t in extra_tags:
            tag_slug = "#" + "".join(c for c in t if c.isalnum())
            if tag_slug not in base_tags and len(tag_slug) > 2:
                base_tags.append(tag_slug)

    tag_str = " ".join(base_tags[:12])
    return f"{title}\n\n.\n.\n{tag_str}"


def publish_short_to_instagram(
    short_id: Optional[int] = None,
    video_url: Optional[str] = None,
    file_path: Optional[str] = None,
    caption: Optional[str] = None,
    title: Optional[str] = None,
) -> bool:
    """Publish a Short or video to Instagram Reels."""
    publisher = InstagramPublisher()

    profile = publisher.get_account_profile()
    if not profile.get("connected"):
        log_error("INSTAGRAM", f"Instagram account not connected: {profile.get('error')}")
        return False

    username = profile.get("username", "account")
    log_info("INSTAGRAM", f"Connected to Instagram Account: @{username} (ID: {profile.get('id')})")

    db_service = DatabaseService()
    resolved_video_source = ""
    hook_title = ""
    tags = ""

    # If short_id is given, resolve details from Supabase or local SQLite
    row = None
    if short_id:
        log_info("INSTAGRAM", f"Resolving Short #{short_id} metadata...")
        # Check Supabase first
        if db_service.client:
            try:
                res = db_service.client.table("shorts_metadata").select("*").eq("id", short_id).execute()
                if res.data:
                    row = res.data[0]
                    resolved_video_source = row.get("storage_url") or ""
                    hook_title = row.get("hook_title") or ""
                    tags = row.get("tags") or ""
            except Exception as e:
                log_warning("INSTAGRAM", f"Supabase lookup warning: {e}")

        # Verify cloud storage URL is accessible and not deleted/404 (e.g. from wiped storage)
        if resolved_video_source and resolved_video_source.startswith("http"):
            if not is_url_accessible(resolved_video_source):
                log_warning(
                    "INSTAGRAM",
                    f"Cloud storage URL is unreachable or deleted (404): {resolved_video_source}. Falling back to local disk...",
                )
                resolved_video_source = ""

        # Fallback to local SQLite if storage_url wasn't found or is placeholder/unreachable
        if not resolved_video_source or resolved_video_source.startswith("https://example.com"):
            conn = db_service._get_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    cursor.execute("SELECT hook_title, storage_url, local_path, tags FROM shorts_metadata WHERE id = ?", (short_id,))
                    lrow = cursor.fetchone()
                    if lrow:
                        hook_title = hook_title or lrow[0] or ""
                        st_url = lrow[1] or ""
                        loc_p = lrow[2] or ""
                        if st_url and not st_url.startswith("https://example.com") and is_url_accessible(st_url):
                            resolved_video_source = st_url
                        elif loc_p and Path(loc_p).exists():
                            resolved_video_source = loc_p
                        tags = tags or (lrow[3] or "")
                    conn.close()
                except Exception:
                    pass

        # Additional local file search if unresolved or local file path does not exist
        if not resolved_video_source or (not resolved_video_source.startswith("http") and not Path(resolved_video_source).exists()):
            item_dict = row or {"id": short_id, "hook_title": hook_title}
            found_local = db_service.find_local_video(item_dict)
            if found_local and found_local.exists():
                resolved_video_source = str(found_local)
                log_info("INSTAGRAM", f"Found local video file: {resolved_video_source}")

    # Direct URL or file path override
    if video_url:
        resolved_video_source = video_url
    elif file_path:
        resolved_video_source = file_path

    if not resolved_video_source:
        log_error("INSTAGRAM", f"No video source could be resolved for Short #{short_id}.")
        return False

    # Custom title override
    if title and title.strip():
        hook_title = title.strip()
        log_info("INSTAGRAM", f"Using custom title: [bold white]{hook_title}[/bold white]")
        if short_id:
            conn = db_service._get_connection()
            if conn:
                try:
                    conn.cursor().execute("UPDATE shorts_metadata SET hook_title = ? WHERE id = ?", (hook_title, short_id))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
            if db_service.client:
                try:
                    db_service.client.table("shorts_metadata").update({"hook_title": hook_title}).eq("id", short_id).execute()
                except Exception:
                    pass

    # Format caption
    final_caption = caption or build_default_caption(hook_title, tags)

    try:
        result = publisher.publish_reel(
            video_source=resolved_video_source,
            caption=final_caption,
            share_to_feed=True,
        )

        media_id = result.get("media_id")
        permalink = result.get("permalink", "")
        log_success("INSTAGRAM", f"Successfully published to Instagram @{username}!")
        log_success("INSTAGRAM", f"Instagram Permalink: {permalink}")

        # Update metadata in Supabase & SQLite if short_id is present
        if short_id:
            now_iso = datetime.now(timezone.utc).isoformat()
            new_storage_url = result.get("video_url")
            supabase_payload = {
                "instagram_id": media_id,
                "instagram_url": permalink,
                "instagram_published_at": now_iso,
            }
            if new_storage_url and str(new_storage_url).startswith("http") and not str(new_storage_url).startswith("https://example.com"):
                supabase_payload["storage_url"] = new_storage_url

            if db_service.client:
                try:
                    db_service.client.table("shorts_metadata").update(supabase_payload).eq("id", short_id).execute()
                except Exception:
                    pass

            conn = db_service._get_connection()
            if conn:
                try:
                    cursor = conn.cursor()
                    # Add columns if not already present
                    try:
                        cursor.execute("ALTER TABLE shorts_metadata ADD COLUMN instagram_id TEXT")
                    except Exception:
                        pass
                    try:
                        cursor.execute("ALTER TABLE shorts_metadata ADD COLUMN instagram_url TEXT")
                    except Exception:
                        pass
                    try:
                        cursor.execute("ALTER TABLE shorts_metadata ADD COLUMN instagram_published_at TEXT")
                    except Exception:
                        pass

                    if new_storage_url and str(new_storage_url).startswith("http"):
                        cursor.execute(
                            "UPDATE shorts_metadata SET instagram_id = ?, instagram_url = ?, instagram_published_at = ?, storage_url = ? WHERE id = ?",
                            (media_id, permalink, now_iso, new_storage_url, short_id),
                        )
                    else:
                        cursor.execute(
                            "UPDATE shorts_metadata SET instagram_id = ?, instagram_url = ?, instagram_published_at = ? WHERE id = ?",
                            (media_id, permalink, now_iso, short_id),
                        )
                    if cursor.rowcount == 0 and db_service.client:
                        sb_res = db_service.client.table("shorts_metadata").select("*").eq("id", short_id).execute()
                        if sb_res.data:
                            r = sb_res.data[0]
                            cols = [c[1] for c in cursor.execute("PRAGMA table_info(shorts_metadata)").fetchall()]
                            row_data = {k: (','.join(v) if isinstance(v, list) else v) for k, v in r.items() if k in cols}
                            row_data["instagram_id"] = media_id
                            row_data["instagram_url"] = permalink
                            row_data["instagram_published_at"] = now_iso
                            if new_storage_url and str(new_storage_url).startswith("http"):
                                row_data["storage_url"] = new_storage_url
                            keys = list(row_data.keys())
                            qmarks = ','.join(['?'] * len(keys))
                            cursor.execute(f"INSERT OR REPLACE INTO shorts_metadata ({','.join(keys)}) VALUES ({qmarks})", list(row_data.values()))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass

        return True

    except InstagramPublishError as e:
        log_error("INSTAGRAM", f"Publication failed: {e}")
        return False
    except Exception as e:
        log_error("INSTAGRAM", f"Unexpected error during publication: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="1-Click Instagram Reels Publisher")
    parser.add_argument("--id", type=int, default=None, help="Database ID of the short")
    parser.add_argument("--url", type=str, default=None, help="Direct video URL")
    parser.add_argument("--file", type=str, default=None, help="Direct local video file path")
    parser.add_argument("--caption", type=str, default=None, help="Custom caption")
    parser.add_argument("--title", type=str, default=None, help="Custom title for video/Reel")
    args = parser.parse_args()

    if not (args.id or args.url or args.file):
        parser.error("Must specify at least one of --id, --url, or --file")

    success = publish_short_to_instagram(
        short_id=args.id,
        video_url=args.url,
        file_path=args.file,
        caption=args.caption,
        title=args.title,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
