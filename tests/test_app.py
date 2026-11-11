"""Synthetic fixtures only: never add real album links or media metadata."""

import json
import os
from pathlib import Path
import stat
import tempfile
import unittest

from timeshow.album import GooglePhotosAlbum, RPC_URL
from timeshow.app import download_one
from timeshow.http import HttpClient, Response, TimeshowError, validate_url

ALBUM_URL = "https://photos.google.com/share/synthetic?key=synthetic"
JPEG = b"\xff\xd8\xff\xe0synthetic-image"


def item(number, *, video=False):
    metadata = {"76647426": []} if video else {}
    return [f"synthetic-{number}",
            [f"https://lh3.googleusercontent.com/synthetic-{number}", 4000, 3000],
            1000, None, None, 2000, None, None, None, metadata]


def html_page(items, token=None):
    data = [None, items, token, []]
    return ("AF_initDataCallback({key: 'ds:1', data:" + json.dumps(data)
            + ", sideChannel: {}});"
            + 'snAcKc request:["synthetic-album",null,null,"synthetic-key"]').encode()


def rpc_page(items, token=None):
    payload = json.dumps([None, items, token])
    return (")]}\x27\n\n123\n" + json.dumps([["wrb.fr", "snAcKc", payload]])).encode()


class FakeClient(HttpClient):
    def __init__(self, html, pages=(), image=JPEG):
        self.html = html
        self.pages = iter(pages)
        self.image = image
        self.downloads = 0
        self.requests = []

    def fetch(self, url, data=None):
        self.requests.append((url, data))
        if url == ALBUM_URL:
            return Response(self.html, "text/html")
        if url == RPC_URL:
            return Response(next(self.pages), "application/json")
        self.downloads += 1
        return Response(self.image, "image/jpeg")


class AlbumTests(unittest.TestCase):
    def test_all_pages_deduplicated_and_video_excluded(self):
        client = FakeClient(
            html_page([item(n) for n in range(300)], "page-2"),
            [rpc_page([item(299), item(300), item(301, video=True)])],
        )
        images = GooglePhotosAlbum(client).list_images(ALBUM_URL)
        self.assertEqual(len(images), 301)
        self.assertEqual(images[-1].media_id, "synthetic-300")
        self.assertEqual(len(client.requests), 2)
        self.assertEqual(client.downloads, 0)

    def test_looping_continuation_fails(self):
        client = FakeClient(html_page([item(1)], "loop"), [rpc_page([item(2)], "loop")])
        with self.assertRaisesRegex(TimeshowError, "repeated"):
            GooglePhotosAlbum(client).list_images(ALBUM_URL)

    def test_invalid_continuation_is_not_a_partial_success(self):
        client = FakeClient(html_page([item(1)], "next"), [b"unexpected response"])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            with self.assertRaisesRegex(TimeshowError, "continuation"):
                download_one(ALBUM_URL, output, client)
            self.assertFalse(output.exists())
            self.assertEqual(client.downloads, 0)

    def test_missing_continuation_request_fails(self):
        client = FakeClient(html_page([item(1)], "next").split(b"snAcKc")[0])
        with self.assertRaisesRegex(TimeshowError, "missing"):
            GooglePhotosAlbum(client).list_images(ALBUM_URL)

    def test_invalid_entry_fails_instead_of_biasing_selection(self):
        client = FakeClient(html_page([item(1), ["unexpected"]]))
        with self.assertRaisesRegex(TimeshowError, "media entry"):
            GooglePhotosAlbum(client).list_images(ALBUM_URL)


class WorkflowTests(unittest.TestCase):
    def test_download_exactly_one_from_complete_list(self):
        client = FakeClient(html_page([item(1)], "next"), [rpc_page([item(2)])])
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            result = download_one(ALBUM_URL, output, client)
            candidates = json.loads((output / "candidates.json").read_text())
            selection = json.loads((output / "selection.json").read_text())
            self.assertEqual(result.candidate_count, 2)
            self.assertEqual(len(candidates), 2)
            self.assertIn(selection["candidate"], candidates)
            self.assertEqual(result.image_path.read_bytes(), JPEG)
            self.assertEqual(selection["filename"], result.image_path.name)
            self.assertEqual(len(list(output.glob("image-*"))), 1)
            self.assertEqual(client.downloads, 1)
            self.assertEqual(client.requests[-1][0], selection["candidate"]["url"] + "=w4000-h3000")
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
                for path in output.iterdir():
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_html_response_is_not_saved_as_photo(self):
        client = FakeClient(html_page([item(1)]), image=b"<html>Sign in</html>")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with self.assertRaisesRegex(TimeshowError, "not a supported"):
                download_one(ALBUM_URL, output, client)
            self.assertEqual(list(output.glob("image-*")), [])
            self.assertFalse((output / "selection.json").exists())

    def test_empty_photo_list_downloads_nothing(self):
        client = FakeClient(html_page([item(1, video=True)]))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(TimeshowError, "no eligible"):
                download_one(ALBUM_URL, Path(directory), client)
            self.assertEqual(client.downloads, 0)

    def test_untrusted_hosts_credentials_and_schemes_rejected(self):
        for url in ["http://photos.google.com/share/synthetic",
                    "https://photos.google.com.evil.test/share/synthetic",
                    "https://user:password@photos.google.com/share/synthetic",
                    "https://photos.google.com:444/share/synthetic",
                    "file:///tmp/image.jpg"]:
            with self.subTest(url=url), self.assertRaises(TimeshowError):
                validate_url(url, album=True)
