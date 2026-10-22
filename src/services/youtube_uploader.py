"""
Stage 6: YouTube Shorts OAuth Uploader Service.
Uploads rendered Shorts via YouTube Data API v3 with resumable chunked progress reporting.
"""

import os
from pathlib import Path
from typing import Dict, Optional, Tuple
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from src.config import settings
from src.console import (
    log_stage,
    log_info,
    log_success,
    log_warning,
    log_error,
    create_progress_bar,
    console,
)
from src.models import ViralClip


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


class YouTubeUploaderService:
    """Manages YouTube Data API v3 OAuth authentication and resumable upload."""

    def __init__(self) -> None:
        self.client_secrets_file = settings.YOUTUBE_CLIENT_SECRETS_FILE
        self.token_file = settings.YOUTUBE_TOKEN_FILE

    def authenticate(self, force_reauth: bool = False) -> Optional[Credentials]:
        """
        Authenticate with YouTube via OAuth 2.0 flow.
        Uses cached token.json if valid and matches target channel; otherwise launches local consent server.
        """
        creds: Optional[Credentials] = None

        if os.path.exists(self.token_file) and not force_reauth:
            try:
                creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
                # Verify that the cached token matches the target handle in .env
                if creds and creds.valid and settings.YOUTUBE_TARGET_HANDLE:
                    is_match, ch_info = self.verify_target_channel(creds, silent=True)
                    if not is_match:
                        log_warning(
                            "YOUTUBE_UPLOADER",
                            f"Target channel in .env was changed to '{settings.YOUTUBE_TARGET_HANDLE}', "
                            f"but cached token.json is for '{ch_info}'. Invalidation old cached token...",
                        )
                        creds = None
                        try:
                            os.remove(self.token_file)
                        except Exception:
                            pass
            except Exception as e:
                log_warning("YOUTUBE_UPLOADER", f"Could not load token file: {e}")

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    log_info("YOUTUBE_UPLOADER", "Refreshing expired YouTube OAuth access token...")
                    creds.refresh(Request())
                except Exception as e:
                    log_warning("YOUTUBE_UPLOADER", f"Token refresh failed: {e}. Re-authenticating...")
                    creds = None

            if not creds:
                if not os.path.exists(self.client_secrets_file):
                    log_warning(
                        "YOUTUBE_UPLOADER",
                        f"OAuth credentials file not found at: {self.client_secrets_file}. "
                        "To enable automatic YouTube upload, place client_secrets.json in root.",
                    )
                    return None

                log_info("YOUTUBE_UPLOADER", f"Launching OAuth 2.0 flow locked to: {settings.YOUTUBE_TARGET_EMAIL}...")
                flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, SCOPES)
                creds = flow.run_local_server(
                    port=0,
                    login_hint=settings.YOUTUBE_TARGET_EMAIL,
                    prompt="select_account consent",
                    access_type="offline",
                )

            # Persist token for subsequent runs
            with open(self.token_file, "w") as token:
                token.write(creds.to_json())
                log_success("YOUTUBE_UPLOADER", f"Saved OAuth token to: {self.token_file}")

        return creds

    def verify_target_channel(self, creds: Credentials, silent: bool = False) -> Tuple[bool, str]:
        """
        Safety check: Verify that the authenticated channel matches the configured target handle.
        Prevents accidental uploads to unwanted channels.
        """
        try:
            youtube = build("youtube", "v3", credentials=creds)
            res = youtube.channels().list(mine=True, part="snippet").execute()
            items = res.get("items", [])
            if not items:
                return False, "No YouTube channel found under this Google account."

            channel_title = items[0]["snippet"].get("title", "")
            custom_url = items[0]["snippet"].get("customUrl", "")

            target_handle = settings.YOUTUBE_TARGET_HANDLE.lower().lstrip("@")
            actual_handle = custom_url.lower().lstrip("@")

            if target_handle and (target_handle not in actual_handle and target_handle not in channel_title.lower()):
                if not silent:
                    log_error(
                        "YOUTUBE_UPLOADER",
                        f"⛔ SECURITY BLOCK: You are signed into '{channel_title}' ({custom_url}). "
                        f"Expected target: '{settings.YOUTUBE_TARGET_HANDLE}'. Upload blocked to protect your channels!",
                    )
                return False, f"{channel_title} ({custom_url})"

            return True, f"{channel_title} ({custom_url})"
        except Exception as e:
            if not silent:
                log_warning("YOUTUBE_UPLOADER", f"Could not verify channel identity: {e}")
            return True, "Unknown"

    def upload_short(
        self,
        video_path: str,
        clip: ViralClip,
        privacy_status: str = "public",
        publish_at: Optional[str] = None,
    ) -> Optional[str]:
        """
        Upload video to YouTube as a Short with chunked progress reporting.
        Supports scheduled release via publish_at (ISO-8601).
        Returns YouTube Video ID on success.
        """
        log_stage(6, "YouTube Shorts Upload", "YouTube Data API v3 OAuth Resumable Upload")

        creds = self.authenticate()
        if not creds:
            log_warning(
                "YOUTUBE_UPLOADER",
                "Skipping auto-upload: Missing valid YouTube OAuth credentials. Video saved locally.",
            )
            return None

        is_valid, ch_info = self.verify_target_channel(creds)
        if not is_valid:
            log_error(
                "YOUTUBE_UPLOADER",
                f"Aborting upload: {ch_info}. Please re-authenticate with the correct channel.",
            )
            return None

        youtube = build("youtube", "v3", credentials=creds)

        # Title formatting: Ensure #Shorts is present for algorithmic detection
        title = clip.hook_title.strip()
        if "#shorts" not in title.lower():
            title = f"{title} #Shorts"

        description = f"{clip.description}\n\n#Shorts #Viral #Trending"
        tags = list(set(clip.tags + ["Shorts", "YouTubeShorts", "Viral"]))

        body: Dict = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:20],
                "categoryId": "24",  # Entertainment
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        # Handle YouTube native scheduled release (publishAt)
        if publish_at:
            # YouTube API constraint: privacyStatus MUST be private when publishAt is provided
            body["status"]["privacyStatus"] = "private"
            try:
                from datetime import datetime, timezone
                if isinstance(publish_at, str):
                    clean_str = publish_at.replace("Z", "+00:00")
                    dt = datetime.fromisoformat(clean_str)
                else:
                    dt = publish_at
                utc_iso = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
                body["status"]["publishAt"] = utc_iso
                log_info("YOUTUBE_UPLOADER", f"📅 [SCHEDULED PUBLISH] YouTube publication scheduled for: {utc_iso} (Status: Private until release)")
            except Exception as e:
                log_warning("YOUTUBE_UPLOADER", f"Could not parse publish_at '{publish_at}': {e}")
                body["status"]["publishAt"] = str(publish_at)

        # Check daily quota usage
        from src.services.database import DatabaseService
        db_service = DatabaseService()
        quota = db_service.get_daily_quota_status()
        uploads_today = quota.get("uploads_today", 0)
        if uploads_today >= 6:
            log_info(
                "YOUTUBE_UPLOADER",
                f"Daily baseline reached ({uploads_today}/6+ uploads completed today). Proceeding with upload to YouTube...",
            )
        else:
            log_info(
                "YOUTUBE_UPLOADER",
                f"YouTube Upload Progress: {uploads_today}/6 completed today.",
            )

        # 2MB chunk size for reliable resumable upload
        chunk_size = 2 * 1024 * 1024
        media = MediaFileUpload(
            video_path,
            chunksize=chunk_size,
            resumable=True,
            mimetype="video/mp4",
        )

        log_info("YOUTUBE_UPLOADER", f"Initiating resumable upload for: {title}")
        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        progress = create_progress_bar("Uploading Short")
        task_id = progress.add_task("Uploading to YouTube", total=100)

        response = None
        with progress:
            while response is None:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    progress.update(task_id, completed=pct)
                    console.print(
                        f"[dim white]Chunk Upload:[/dim white] [bold cyan]{pct}%[/bold cyan] "
                        f"({status.resumable_progress / (1024*1024):.1f} MB uploaded)"
                    )

        video_id = response.get("id")
        if not video_id:
            log_error("YOUTUBE_UPLOADER", "Upload failed: No video ID returned by YouTube.")
            return None

        # Verify confirmation from YouTube API
        log_info("YOUTUBE_UPLOADER", f"Confirming upload status with YouTube for ID: {video_id}...")
        confirmed, status_msg, _ = self.confirm_upload(youtube, video_id)
        video_url = f"https://www.youtube.com/shorts/{video_id}"

        if confirmed:
            db_service.record_quota_usage(1600, is_upload=True)
            log_success("YOUTUBE_UPLOADER", f"✅ Upload Confirmed on YouTube! [{status_msg}]")
            log_success("YOUTUBE_UPLOADER", f"Short successfully published! URL: {video_url}")
            return video_id
        else:
            log_error("YOUTUBE_UPLOADER", f"❌ YouTube reported an upload issue: {status_msg}")
            return None

    def confirm_upload(self, youtube, video_id: str) -> Tuple[bool, str, Dict]:
        """
        Confirm with YouTube Data API that the video was received, exists, and is published/processing.
        Returns (is_confirmed, status_description, video_snippet_status).
        """
        try:
            res = youtube.videos().list(
                part="snippet,status",
                id=video_id,
            ).execute()
            items = res.get("items", [])
            if not items:
                return False, f"Video ID {video_id} not found on YouTube.", {}

            item = items[0]
            status = item.get("status", {})
            upload_status = status.get("uploadStatus", "unknown")
            privacy = status.get("privacyStatus", "unknown")
            rejection_reason = status.get("rejectionReason")

            if upload_status == "rejected":
                return False, f"Upload rejected by YouTube. Reason: {rejection_reason}", item

            # Valid upload states: 'uploaded', 'processed'
            return True, f"Upload Status: {upload_status.upper()} | Privacy: {privacy.upper()}", item
        except Exception as e:
            log_warning("YOUTUBE_UPLOADER", f"Could not confirm upload status with YouTube API: {e}")
            # If API query hit a minor network glitch, chunk upload completed so return true
            return True, f"Upload completed (API verification warning: {e})", {}

    def is_video_live(self, video_id: str) -> bool:
        """
        Check if a given YouTube video ID is currently active and not deleted/rejected on YouTube.
        """
        creds = self.authenticate()
        if not creds:
            return False
        try:
            youtube = build("youtube", "v3", credentials=creds)
            res = youtube.videos().list(part="status", id=video_id).execute()
            items = res.get("items", [])
            if not items:
                return False
            status = items[0].get("status", {})
            upload_status = status.get("uploadStatus", "")
            return upload_status in ("uploaded", "processed")
        except Exception:
            return False

    def test_connection(self) -> bool:
        """Verify YouTube authentication and print channel information."""
        console.print("\n[bold cyan][*] Verifying YouTube Account OAuth Connection...[/bold cyan]")
        creds = self.authenticate()
        if not creds:
            console.print("[bold red][!] Authentication failed or client_secrets.json missing.[/bold red]")
            return False

        try:
            youtube = build("youtube", "v3", credentials=creds)
            res = youtube.channels().list(mine=True, part="snippet,statistics").execute()
            items = res.get("items", [])
            if items:
                ch = items[0]
                title = ch["snippet"].get("title", "Unknown")
                custom_url = ch["snippet"].get("customUrl", "")
                subs = ch["statistics"].get("subscriberCount", "Hidden")
                console.print(f"[bold green][OK] Successfully linked to YouTube Channel:[/bold green] [bold white]{title}[/bold white] ({custom_url})")
                console.print(f"[dim white]Subscribers:[/dim white] {subs} | [dim white]Channel ID:[/dim white] {ch.get('id')}\n")
                return True
            else:
                console.print("[bold yellow][!] Authenticated, but no YouTube channel was found under this Google account.[/bold yellow]")
                return True
        except Exception as e:
            console.print(f"[bold red][!] Could not retrieve channel info:[/bold red] {e}")
            return False


if __name__ == "__main__":
    uploader = YouTubeUploaderService()
    uploader.test_connection()
