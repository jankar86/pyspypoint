import contextlib
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest

import archive
import spypoint


class FakeResponse:
    headers = {"Content-Type": "image/jpeg"}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield b"\xff\xd8\xfftest image bytes"


class FakeSession:
    def __init__(self):
        self.downloads = []

    def get(self, url, stream, timeout):
        self.downloads.append(url)
        return FakeResponse()


class FakeClient:
    def __init__(self, photos):
        self.items = photos
        self.session = FakeSession()
        self.photo_calls = 0
        self.camera_ids = ["camera-1"]

    def cameras(self):
        return [spypoint.Camera(camera_id) for camera_id in self.camera_ids]

    def photos(self, cameras, date_end, limit, tags=()):
        self.photo_calls += 1
        return [p for p in self.items if p.originDate < date_end
                and (not tags or not set(tags).isdisjoint(p.tag))][:limit]


def photo(number):
    stamp = f"2026-10-2{number}T12:00:00.000Z"
    return spypoint.Photo(
        id=f"photo-{number}", camera="camera-1", date=stamp,
        originDate=stamp, originName=f"PICT{number}.JPG", originSize=123,
        tag=["deer"], preview=["https://example.test/?X-Amz-Signature=secret"],
        small={"host": "images.example", "path": "small?signature=secret",
               "verb": "GET", "headers": []},
        large={"host": "images.example", "path": "large?signature=secret",
               "verb": "GET", "headers": []},
    )


class TestArchive(unittest.TestCase):
    def test_pagination_repeated_run_and_hd_upgrade(self):
        items = [photo(3), photo(2), photo(1)]
        client = FakeClient(items)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, archive.run(client, root, page_size=2, max_photos=0))
            self.assertEqual(3, len(client.session.downloads))
            sidecar = root / "camera-1" / "photo-3.json"
            data = json.loads(sidecar.read_text())
            self.assertEqual("large", data["archive"]["variant"])
            self.assertEqual(["deer"], data["photo"]["tag"])
            self.assertNotIn("signature", sidecar.read_text())
            self.assertTrue((root / "camera-1" / "photo-3.large.jpg").exists())

            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, archive.run(client, root, page_size=2, max_photos=0))
            self.assertEqual(3, len(client.session.downloads))

            items[0].hd = spypoint.Photo(hd={"host": "images.example",
                                            "path": "hd?signature=secret"}).hd
            items[0].hdUploaded = True
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, archive.run(client, root, page_size=2, max_photos=0))
            self.assertEqual(4, len(client.session.downloads))
            self.assertEqual("hd", json.loads(sidecar.read_text())["archive"]["variant"])
            self.assertTrue((root / "camera-1" / "photo-3.hd.jpg").exists())

    def test_checkpoint_limits_repeat_queries_and_full_scan_recurs(self):
        items = [photo(3), photo(2), photo(1)]
        items[1].originDate = "2026-09-20T12:00:00.000Z"
        items[2].originDate = "2026-09-19T12:00:00.000Z"
        client = FakeClient(items)
        now = datetime(2026, 10, 24, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, archive.sync(client, root, 2, 0, 7, 30, now=now))
            self.assertEqual(3, client.photo_calls)
            state = json.loads((root / "_state.json").read_text())
            self.assertEqual(state["last_success_at"], state["last_full_scan_at"])

            client.photo_calls = 0
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, archive.sync(client, root, 2, 0, 7, 30,
                                                 now=now + timedelta(hours=4)))
            self.assertEqual(1, client.photo_calls)
            self.assertEqual(3, len(client.session.downloads))

            client.camera_ids.append("camera-2")
            client.photo_calls = 0
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, archive.sync(client, root, 2, 0, 7, 30,
                                                 now=now + timedelta(hours=8)))
            self.assertGreater(client.photo_calls, 1)

            client.photo_calls = 0
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, archive.sync(client, root, 2, 0, 7, 30,
                                                 now=now + timedelta(days=31)))
            self.assertGreater(client.photo_calls, 1)
            state = json.loads((root / "_state.json").read_text())
            self.assertEqual(state["last_success_at"], state["last_full_scan_at"])

    def test_limited_trial_does_not_advance_checkpoint(self):
        client = FakeClient([photo(1)])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, archive.sync(client, root, 2, 1, 7, 30))
            self.assertFalse((root / "_state.json").exists())

    def test_tag_filter_and_checkpoint_change(self):
        items = [photo(3), photo(2), photo(1)]
        items[0].tag = ("buck",)
        items[1].tag = ("deer",)
        items[2].tag = ("buck",)
        client = FakeClient(items)
        now = datetime(2026, 10, 24, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, archive.sync(client, root, 3, 0, 7, 30,
                                                 now=now, tags=("buck",)))
            self.assertEqual(2, len(client.session.downloads))
            self.assertFalse((root / "camera-1" / "photo-2.json").exists())
            self.assertEqual(["buck"], json.loads((root / "_state.json").read_text())["tags"])

            client.photo_calls = 0
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, archive.sync(client, root, 3, 0, 7, 30,
                                                 now=now + timedelta(hours=1),
                                                 tags=("buck",)))
            self.assertEqual(1, client.photo_calls)

            client.photo_calls = 0
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(0, archive.sync(client, root, 3, 0, 7, 30,
                                                 now=now + timedelta(hours=2)))
            self.assertGreater(client.photo_calls, 1)
            self.assertEqual(3, len(client.session.downloads))
