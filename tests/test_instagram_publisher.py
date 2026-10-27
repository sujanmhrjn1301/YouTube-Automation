"""
Tests for Instagram Publisher Service.
"""

from unittest.mock import MagicMock, patch
import pytest

from src.services.instagram_publisher import InstagramPublisher, InstagramPublishError
from publish_instagram import build_default_caption


def test_instagram_publisher_configured():
    publisher = InstagramPublisher(account_id="12345", access_token="token_abc")
    assert publisher.is_configured() is True
    assert publisher.account_id == "12345"
    assert publisher.access_token == "token_abc"


def test_instagram_publisher_not_configured():
    publisher = InstagramPublisher(account_id="", access_token="")
    assert publisher.is_configured() is False


def test_build_default_caption():
    caption = build_default_caption("Epic Minecraft Boss Fight", "gaming, warden, minecraft")
    assert "Epic Minecraft Boss Fight" in caption
    assert "#reels" in caption
    assert "#gaming" in caption
    assert "#warden" in caption
    assert "#minecraft" in caption


@patch("src.services.instagram_publisher.requests.get")
def test_get_account_profile_success(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "id": "17841417434600593",
        "username": "sicre.ator",
        "name": "SIcreator",
        "profile_picture_url": "https://example.com/pic.jpg",
    }
    mock_get.return_value = mock_resp

    publisher = InstagramPublisher(account_id="17841417434600593", access_token="valid_token")
    profile = publisher.get_account_profile()

    assert profile["connected"] is True
    assert profile["username"] == "sicre.ator"
    assert profile["name"] == "SIcreator"


@patch("src.services.instagram_publisher.requests.post")
def test_create_media_container_success(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"id": "container_9999"}
    mock_post.return_value = mock_resp

    publisher = InstagramPublisher(account_id="17841417434600593", access_token="valid_token")
    cid = publisher.create_media_container("https://example.com/video.mp4", caption="Hello Reels")
    assert cid == "container_9999"


@patch("src.services.instagram_publisher.requests.post")
def test_create_media_container_failure(mock_post):
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.json.return_value = {"error": {"message": "Invalid video format"}}
    mock_resp.text = "Invalid video format"
    mock_post.return_value = mock_resp

    publisher = InstagramPublisher(account_id="17841417434600593", access_token="valid_token")
    with pytest.raises(InstagramPublishError, match="Invalid video format"):
        publisher.create_media_container("https://example.com/bad.mp4")


@patch("src.services.instagram_publisher.requests.get")
def test_wait_for_container_ready_finished(mock_get):
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status_code": "FINISHED", "id": "container_9999"}
    mock_get.return_value = mock_resp

    publisher = InstagramPublisher(account_id="17841417434600593", access_token="valid_token")
    res = publisher.wait_for_container_ready("container_9999", max_wait_seconds=10, poll_interval=1)
    assert res["status_code"] == "FINISHED"


@patch("src.services.instagram_publisher.requests.post")
@patch("src.services.instagram_publisher.requests.get")
def test_publish_container_success(mock_get, mock_post):
    mock_post_resp = MagicMock()
    mock_post_resp.status_code = 200
    mock_post_resp.json.return_value = {"id": "media_7777"}
    mock_post.return_value = mock_post_resp

    mock_get_resp = MagicMock()
    mock_get_resp.status_code = 200
    mock_get_resp.json.return_value = {"permalink": "https://www.instagram.com/reel/XYZ123/"}
    mock_get.return_value = mock_get_resp

    publisher = InstagramPublisher(account_id="17841417434600593", access_token="valid_token")
    res = publisher.publish_container("container_9999")
    assert res["media_id"] == "media_7777"
    assert "https://www.instagram.com/reel/" in res["permalink"]
