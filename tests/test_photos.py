"""Exercise the public retrieval interface with synthetic album responses."""

import unittest

from timeshow.photos import DownloadedImage, PhotosClient, PhotosError

from test_app import ALBUM_URL, JPEG, FakeClient, html_page, item, rpc_page


class PhotosClientTests(unittest.TestCase):
    def test_list_then_pull_from_later_page(self):
        transport = FakeClient(html_page([item(1)], "next"), [rpc_page([item(2)])])
        client = PhotosClient(transport)

        candidates = client.list_images(ALBUM_URL)
        self.assertEqual(transport.downloads, 0)
        downloaded = client.pull_image(candidates[-1])

        self.assertIsInstance(downloaded, DownloadedImage)
        self.assertEqual(downloaded.body, JPEG)
        self.assertEqual(downloaded.extension, ".jpg")
        self.assertEqual(transport.downloads, 1)
        self.assertEqual(transport.requests[-1][0], candidates[-1].download_url)
        self.assertEqual(len(transport.requests), 3)

    def test_invalid_download_raises_public_error(self):
        client = PhotosClient(FakeClient(html_page([item(1)]), image=b"<html>error</html>"))
        image = client.list_images(ALBUM_URL)[0]
        with self.assertRaises(PhotosError):
            client.pull_image(image)

    def test_listing_error_is_not_an_empty_album(self):
        client = PhotosClient(FakeClient(html_page([item(1)], "next"), [b"bad page"]))
        with self.assertRaises(PhotosError):
            client.list_images(ALBUM_URL)
