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

    def authenticate(self) -> Optional[Credentials]:
        """
        Authenticate with YouTube via OAuth 2.0 flow.
        Uses cached token.json if valid; otherwise launches local consent server.
        """
        creds: Optional[Credentials] = None

        if os.path.exists(self.token_file):
            try:
                creds = Credentials.from_authorized_user_file(self.token_file, SCOPES)
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

                log_info("YOUTUBE_UPLOADER", "Launching OAuth 2.0 browser authorization flow...")
                flow = InstalledAppFlow.from_client_secrets_file(self.client_secrets_file, SCOPES)
                creds = flow.run_local_server(port=0)

            # Persist token for subsequent runs
            with open(self.token_file, "w") as token:
                token.write(creds.to_json())
                log_success("YOUTUBE_UPLOADER", f"Saved OAuth token to: {self.token_file}")

        return creds

    def upload_short(
        self,
        video_path: str,
        clip: ViralClip,
        privacy_status: str = "public",
    ) -> Optional[str]:
        """
        Upload video to YouTube as a Short with chunked progress reporting.
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
        video_url = f"https://www.youtube.com/shorts/{video_id}"
        log_success("YOUTUBE_UPLOADER", f"Short successfully published! URL: {video_url}")
        return video_id

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
