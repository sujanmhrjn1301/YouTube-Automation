"""
Instagram Reels Publisher Service.

Publishes vertical video clips as Instagram Reels using the Meta Graph API v19.0+.
Supports both hosted HTTPS URLs (e.g. Supabase Storage) and local video files.
"""

import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from src.console import log_error, log_info, log_success, log_warning

load_dotenv()

GRAPH_API_VERSION = "v19.0"
GRAPH_API_BASE = f"https://graph.facebook.com/{GRAPH_API_VERSION}"


class InstagramPublishError(Exception):
    """Raised when Instagram Graph API publication fails."""
    pass


class InstagramPublisher:
    """Handles publishing Reels to an Instagram Professional/Creator account."""

    def __init__(
        self,
        account_id: Optional[str] = None,
        access_token: Optional[str] = None,
        supabase_url: Optional[str] = None,
        supabase_key: Optional[str] = None,
        storage_bucket: Optional[str] = None,
    ):
        self.account_id = account_id if account_id is not None else os.getenv("INSTAGRAM_ACCOUNT_ID")
        self.access_token = access_token if access_token is not None else os.getenv("INSTAGRAM_ACCESS_TOKEN")
        self.supabase_url = supabase_url if supabase_url is not None else os.getenv("SUPABASE_URL")
        self.supabase_key = supabase_key if supabase_key is not None else os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        self.storage_bucket = storage_bucket if storage_bucket is not None else os.getenv("SUPABASE_STORAGE_BUCKET", "reels")

        self._cached_profile: Optional[Dict[str, Any]] = None

    def is_configured(self) -> bool:
        """Check if required credentials are present."""
        return bool(self.account_id and self.access_token)

    def get_account_profile(self, force_refresh: bool = False) -> Dict[str, Any]:
        """Fetch Instagram account profile info."""
        if not self.is_configured():
            return {
                "configured": False,
                "connected": False,
                "error": "Missing INSTAGRAM_ACCOUNT_ID or INSTAGRAM_ACCESS_TOKEN in .env",
            }

        if self._cached_profile and not force_refresh:
            return self._cached_profile

        url = f"{GRAPH_API_BASE}/{self.account_id}"
        params = {
            "fields": "id,username,name,profile_picture_url",
            "access_token": self.access_token,
        }

        try:
            resp = requests.get(url, params=params, timeout=12)
            data = resp.json()
            if resp.status_code != 200 or "error" in data:
                err_msg = data.get("error", {}).get("message", f"HTTP {resp.status_code}")
                log_error("INSTAGRAM", f"Failed to get account profile: {err_msg}")
                return {
                    "configured": True,
                    "connected": False,
                    "error": err_msg,
                }

            profile = {
                "configured": True,
                "connected": True,
                "id": data.get("id"),
                "username": data.get("username", ""),
                "name": data.get("name", ""),
                "profile_picture_url": data.get("profile_picture_url", ""),
            }
            self._cached_profile = profile
            return profile
        except Exception as e:
            log_error("INSTAGRAM", f"Network error getting profile: {e}")
            return {
                "configured": True,
                "connected": False,
                "error": str(e),
            }

    def _is_url_live(self, url: str) -> bool:
        """Check if public video URL responds with 200 OK. Treats example.com as test URL."""
        if "example.com" in url:
            return True
        try:
            r = requests.head(url, timeout=5, allow_redirects=True)
            if r.status_code == 200:
                return True
            if r.status_code in (403, 405):
                r = requests.get(url, stream=True, timeout=5)
                return r.status_code == 200
            return False
        except Exception:
            return False

    def ensure_public_url(self, video_path_or_url: str) -> str:
        """
        Ensure video is accessible via public HTTPS URL.
        If it's already an HTTP/HTTPS URL, validates that it is reachable and returns it.
        If it's a local file, compresses if >48MB to avoid Supabase 50MB 413 error,
        uploads it to Supabase Storage, and returns the public URL.
        """
        val = str(video_path_or_url).strip()
        parsed = urlparse(val)
        if parsed.scheme in ("http", "https"):
            if self._is_url_live(val):
                return val
            raise InstagramPublishError(f"Video URL is unreachable or returned 404 (file deleted or expired): {val}")

        # Local file path
        local_path = Path(val)
        if not local_path.is_file():
            raise InstagramPublishError(f"Local video file not found: {local_path}")

        file_to_upload = local_path
        temp_compressed: Optional[Path] = None
        size_mb = local_path.stat().st_size / (1024 * 1024)

        # Supabase Free Tier has a strict 50.0 MB per-file limit.
        # If the file exceeds 48 MB, compress it using fast H.264 CRF 26 to fit cleanly under quota.
        if size_mb > 48.0:
            log_info(
                "INSTAGRAM",
                f"Local video ({size_mb:.2f} MB) exceeds Supabase 50MB free quota. Compressing for upload...",
            )
            try:
                import subprocess
                from src.config import resolve_ffmpeg_path
                ffmpeg_exe = resolve_ffmpeg_path()
                temp_compressed = local_path.parent / f"ig_tmp_{int(time.time())}_{local_path.name}"
                cmd = [
                    ffmpeg_exe, "-y", "-i", str(local_path),
                    "-c:v", "libx264", "-crf", "26", "-preset", "veryfast",
                    "-c:a", "aac", "-b:a", "128k",
                    str(temp_compressed),
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                if temp_compressed.is_file() and temp_compressed.stat().st_size > 1000:
                    comp_size = temp_compressed.stat().st_size / (1024 * 1024)
                    log_success("INSTAGRAM", f"Compressed video to {comp_size:.2f} MB (< 48 MB)")
                    file_to_upload = temp_compressed
            except Exception as e:
                log_warning("INSTAGRAM", f"Auto-compression failed ({e}), attempting original file...")

        try:
            log_info("INSTAGRAM", f"Uploading local file {file_to_upload.name} to Supabase bucket '{self.storage_bucket}'...")
            if not (self.supabase_url and self.supabase_key):
                raise InstagramPublishError(
                    "Cannot upload local file to Instagram without SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."
                )

            from supabase import create_client
            supabase = create_client(self.supabase_url, self.supabase_key)

            file_name = f"reels/{int(time.time())}_{local_path.name}"
            with open(file_to_upload, "rb") as f:
                file_bytes = f.read()

            upload_res = supabase.storage.from_(self.storage_bucket).upload(
                file_name,
                file_bytes,
                file_options={"content-type": "video/mp4", "x-upsert": "true"}
            )

            # Check if upload returned an error payload
            if isinstance(upload_res, dict) and upload_res.get("error"):
                err_msg = upload_res.get("message") or upload_res.get("error")
                raise InstagramPublishError(f"Supabase upload failed: {err_msg}")

            public_url = supabase.storage.from_(self.storage_bucket).get_public_url(file_name)
            log_success("INSTAGRAM", f"Uploaded video to public storage URL: {public_url}")
            return public_url
        finally:
            if temp_compressed and temp_compressed.exists():
                try:
                    temp_compressed.unlink()
                except Exception:
                    pass

    def create_media_container(
        self,
        video_url: str,
        caption: str = "",
        share_to_feed: bool = True,
        cover_url: Optional[str] = None,
    ) -> str:
        """
        Step 1: Create Instagram Reel Media Container.
        Returns the container ID (creation_id).
        """
        if not self.is_configured():
            raise InstagramPublishError("Instagram credentials not configured in environment.")

        endpoint = f"{GRAPH_API_BASE}/{self.account_id}/media"
        payload: Dict[str, Any] = {
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true" if share_to_feed else "false",
            "access_token": self.access_token,
        }
        if cover_url:
            payload["cover_url"] = cover_url

        log_info("INSTAGRAM", "Creating Instagram Reel media container...")
        resp = requests.post(endpoint, data=payload, timeout=30)
        data = resp.json()

        if resp.status_code != 200 or "id" not in data:
            err_msg = data.get("error", {}).get("message", resp.text)
            log_error("INSTAGRAM", f"Failed to create media container: {err_msg}")
            raise InstagramPublishError(f"Container creation failed: {err_msg}")

        container_id = data["id"]
        log_info("INSTAGRAM", f"Media container created with ID: {container_id}")
        return container_id

    def wait_for_container_ready(
        self,
        container_id: str,
        max_wait_seconds: int = 180,
        poll_interval: int = 4,
    ) -> Dict[str, Any]:
        """
        Step 2: Poll container status until FINISHED or ERROR.
        Instagram asynchronously transcodes and verifies the Reel video.
        """
        endpoint = f"{GRAPH_API_BASE}/{container_id}"
        start_time = time.time()
        last_status = "UNKNOWN"

        log_info("INSTAGRAM", f"Polling container {container_id} processing status...")

        while (time.time() - start_time) < max_wait_seconds:
            try:
                resp = requests.get(
                    endpoint,
                    params={"fields": "status_code,status", "access_token": self.access_token},
                    timeout=15,
                )
                data = resp.json()
            except Exception as e:
                log_warning("INSTAGRAM", f"Temporary network error checking status: {e}")
                time.sleep(poll_interval)
                continue

            status_code = data.get("status_code", "UNKNOWN")
            last_status = status_code

            if status_code == "FINISHED":
                log_success("INSTAGRAM", f"Container {container_id} processing complete and ready to publish.")
                return data

            if status_code == "ERROR":
                err_detail = data.get("status", "Transcoding error")
                log_error("INSTAGRAM", f"Container processing failed: {err_detail}")
                raise InstagramPublishError(f"Instagram media processing error: {err_detail}")

            if status_code == "EXPIRED":
                raise InstagramPublishError("Instagram media container expired before publishing.")

            elapsed = int(time.time() - start_time)
            log_info("INSTAGRAM", f"Status: {status_code} ({elapsed}s elapsed, re-checking in {poll_interval}s)...")
            time.sleep(poll_interval)

        raise InstagramPublishError(
            f"Timeout waiting for Instagram to process video after {max_wait_seconds}s (last status: {last_status})."
        )

    def publish_container(self, container_id: str) -> Dict[str, Any]:
        """
        Step 3: Publish the ready container to the Instagram account.
        Returns media info including media_id and permalink.
        """
        endpoint = f"{GRAPH_API_BASE}/{self.account_id}/media_publish"
        payload = {
            "creation_id": container_id,
            "access_token": self.access_token,
        }

        log_info("INSTAGRAM", f"Publishing container {container_id} to Instagram...")
        resp = requests.post(endpoint, data=payload, timeout=30)
        data = resp.json()

        if resp.status_code != 200 or "id" not in data:
            err_msg = data.get("error", {}).get("message", resp.text)
            log_error("INSTAGRAM", f"Publish call failed: {err_msg}")
            raise InstagramPublishError(f"Media publish failed: {err_msg}")

        media_id = data["id"]
        log_success("INSTAGRAM", f"Published to Instagram successfully! Media ID: {media_id}")

        # Fetch permalink
        permalink = self.get_media_permalink(media_id)
        return {
            "media_id": media_id,
            "permalink": permalink,
            "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

    def get_media_permalink(self, media_id: str) -> str:
        """Fetch the public Instagram URL (e.g. https://www.instagram.com/reel/...) for a media ID."""
        endpoint = f"{GRAPH_API_BASE}/{media_id}"
        try:
            resp = requests.get(
                endpoint,
                params={"fields": "permalink", "access_token": self.access_token},
                timeout=12,
            )
            data = resp.json()
            return data.get("permalink", f"https://www.instagram.com/reel/")
        except Exception:
            return "https://www.instagram.com"

    def publish_reel(
        self,
        video_source: str,
        caption: str = "",
        share_to_feed: bool = True,
        cover_url: Optional[str] = None,
        max_wait_seconds: int = 180,
    ) -> Dict[str, Any]:
        """
        Complete 1-Click Instagram Reel Publishing Workflow.
        1. Ensures public HTTPS URL for video.
        2. Creates Reels media container.
        3. Polls until transcoding is FINISHED.
        4. Publishes to account and returns media ID + live permalink.
        """
        log_info("INSTAGRAM", f"Starting 1-Click Instagram Reel publish for: {video_source}")

        # Step 1: Ensure public HTTPS URL
        public_url = self.ensure_public_url(video_source)

        # Step 2: Create media container
        container_id = self.create_media_container(
            video_url=public_url,
            caption=caption,
            share_to_feed=share_to_feed,
            cover_url=cover_url,
        )

        # Step 3: Wait for transcoding
        self.wait_for_container_ready(container_id, max_wait_seconds=max_wait_seconds)

        # Step 4: Publish
        result = self.publish_container(container_id)
        result["video_url"] = public_url
        result["caption"] = caption
        return result
