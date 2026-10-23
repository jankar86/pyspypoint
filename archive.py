"""Archive the best available version of every SPYPOINT photo."""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import sys
import tempfile

import requests

import spypoint


VARIANTS = ("hd", "large", "medium", "small")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
PRIVATE_FIELDS = {"host", "path", "headers", "url", "token", "authorization"}


def private_field(name):
    lower = name.lower()
    return lower in PRIVATE_FIELDS or any(
        marker in lower for marker in ("url", "signature", "credential", "secret"))


def positive_int(name, default, allow_zero=False):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < (0 if allow_zero else 1):
        raise ValueError(f"{name} must be {'nonnegative' if allow_zero else 'positive'}")
    return value


def identifier(value):
    if not isinstance(value, str) or not SAFE_ID.fullmatch(value):
        raise ValueError("API returned an invalid photo or camera ID")
    return value


def available_variants(photo):
    return [name for name in VARIANTS
            if getattr(getattr(photo, name, None), "path", None)
            and getattr(getattr(photo, name, None), "host", None)]


def metadata(value):
    """Convert API objects to JSON, excluding temporary download credentials."""
    if hasattr(value, "__dict__"):
        return {key: metadata(item) for key, item in vars(value).items()
                if not private_field(key) and key not in VARIANTS}
    if isinstance(value, (list, tuple)):
        return [metadata(item) for item in value]
    if isinstance(value, dict):
        return {key: metadata(item) for key, item in value.items()
                if not private_field(key) and key not in VARIANTS}
    if isinstance(value, str) and (value.startswith(("https://", "http://"))
                                   or "X-Amz-" in value):
        return "[redacted URL]"
    return value


def next_cursor(oldest):
    stamp = datetime.fromisoformat(oldest.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Photo originDate has no timezone")
    return (stamp + timedelta(milliseconds=1)).astimezone(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def utc_timestamp(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Scan state timestamp has no timezone")
    return stamp.astimezone(timezone.utc)


def iso_timestamp(value):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z")


def write_json(path, document):
    content = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if path.exists() and path.read_text() == content:
        return
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", suffix=".part",
                                     delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def image_extension(header):
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    raise ValueError("Downloaded file is not a recognized image")


def download(session, url, directory, stem):
    temporary = None
    try:
        with session.get(url, stream=True, timeout=60) as response:
            response.raise_for_status()
            digest = hashlib.sha256()
            count = 0
            header = b""
            with tempfile.NamedTemporaryFile(dir=directory, prefix=f".{stem}.",
                                             suffix=".part", delete=False) as handle:
                temporary = Path(handle.name)
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        header = (header + chunk)[:12]
                        handle.write(chunk)
                        digest.update(chunk)
                        count += len(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            if not count:
                raise ValueError("Downloaded image was empty")
            extension = image_extension(header)
            destination = directory / f"{stem}{extension}"
            os.replace(temporary, destination)
            return {"file": destination.name, "bytes": count,
                    "sha256": digest.hexdigest(),
                    "downloaded_at": datetime.now(timezone.utc).isoformat()}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def archive_photo(client, photo, root):
    camera_id = identifier(photo.camera)
    photo_id = identifier(photo.id)
    variants = available_variants(photo)
    if not variants:
        raise ValueError("No downloadable image variant")
    variant = variants[0]
    directory = root / camera_id
    directory.mkdir(parents=True, exist_ok=True)
    sidecar = directory / f"{photo_id}.json"
    existing = json.loads(sidecar.read_text()) if sidecar.exists() else {}
    stored = existing.get("archive", {})
    filename = stored.get("file", "")
    current = directory / filename if filename else None
    if (stored.get("variant") == variant and current is not None
            and current.is_file() and current.stat().st_size > 0):
        archive = stored
        downloaded = False
    else:
        archive = download(client.session, photo.url(variant), directory,
                           f"{photo_id}.{variant}")
        archive["variant"] = variant
        downloaded = True
    document = {"photo": metadata(photo), "available_variants": variants,
                "archive": archive}
    write_json(sidecar, document)
    return downloaded


def run(client, root, page_size, max_photos, cutoff=None, cameras=None, tags=()):
    if cameras is None:
        cameras = client.cameras()
    print(f"Cameras: {len(cameras)}")
    if not cameras:
        return 0
    root.mkdir(parents=True, exist_ok=True)
    cursor = "2100-01-01T00:00:00.000Z"
    seen = set()
    requested_tags = set(tags)
    downloaded = skipped = errors = 0
    while True:
        photos = client.photos(cameras, date_end=cursor, limit=page_size, tags=tags)
        if not photos:
            break
        oldest = min(photo.originDate for photo in photos)
        for photo in photos:
            if cutoff and photo.originDate < cutoff:
                continue
            if requested_tags and requested_tags.isdisjoint(
                    getattr(photo, "tag", ()) or ()):
                continue
            if photo.id in seen:
                continue
            seen.add(photo.id)
            try:
                if archive_photo(client, photo, root):
                    downloaded += 1
                else:
                    skipped += 1
            except (OSError, ValueError, AttributeError, requests.RequestException) as exc:
                errors += 1
                # HTTP exceptions can contain signed URLs, so omit their text.
                detail = f": {exc}" if isinstance(exc, ValueError) else ""
                print(f"Could not archive photo {photo.id}: {type(exc).__name__}{detail}",
                      file=sys.stderr)
            if max_photos and len(seen) >= max_photos:
                print(f"Processed: {len(seen)}, downloaded: {downloaded}, "
                      f"already saved: {skipped}, errors: {errors}")
                return 1 if errors else 0
        if cutoff and oldest < cutoff:
            break
        if len(photos) < page_size:
            break
        following = next_cursor(oldest)
        if following >= cursor:
            raise ValueError("Photo pagination stopped advancing")
        cursor = following
    print(f"Processed: {len(seen)}, downloaded: {downloaded}, "
          f"already saved: {skipped}, errors: {errors}")
    return 1 if errors else 0


def load_state(path):
    try:
        state = json.loads(path.read_text())
        if state.get("version") != 1:
            return None
        utc_timestamp(state["last_success_at"])
        utc_timestamp(state["last_full_scan_at"])
        if not isinstance(state["camera_ids"], list):
            return None
        return state
    except (OSError, ValueError, KeyError, TypeError):
        return None


def sync(client, root, page_size, max_photos, lookback_days,
         full_scan_days, force_full=False, now=None, tags=()):
    root.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    state_path = root / "_state.json"
    state = load_state(state_path)
    cameras = client.cameras()
    camera_ids = sorted(camera.id for camera in cameras)
    full = (force_full or state is None or state["camera_ids"] != camera_ids
            or state.get("tags", []) != list(tags))
    if state and not full:
        last_full = utc_timestamp(state["last_full_scan_at"])
        last_success = utc_timestamp(state["last_success_at"])
        full = (last_full > now or last_success > now or
                now - last_full >= timedelta(days=full_scan_days))
    cutoff = None if full else iso_timestamp(last_success - timedelta(days=lookback_days))
    print("Scan: full" if full else f"Scan: recent photos since {cutoff}")
    result = run(client, root, page_size, max_photos, cutoff=cutoff,
                 cameras=cameras, tags=tags)
    if result == 0 and max_photos == 0:
        write_json(state_path, {
            "version": 1,
            "last_success_at": iso_timestamp(now),
            "last_full_scan_at": iso_timestamp(now) if full else state["last_full_scan_at"],
            "camera_ids": camera_ids,
            "tags": list(tags),
        })
    return result


def main():
    username = os.getenv("SPYPOINT_USERNAME")
    password = os.getenv("SPYPOINT_PASSWORD")
    if not username or not password:
        print("Set SPYPOINT_USERNAME and SPYPOINT_PASSWORD.", file=sys.stderr)
        return 2
    try:
        page_size = positive_int("SPYPOINT_PAGE_SIZE", 100)
        if page_size < 2:
            raise ValueError("SPYPOINT_PAGE_SIZE must be at least 2 for pagination")
        max_photos = positive_int("SPYPOINT_MAX_PHOTOS", 0, allow_zero=True)
        lookback_days = positive_int("SPYPOINT_LOOKBACK_DAYS", 7)
        full_scan_days = positive_int("SPYPOINT_FULL_SCAN_DAYS", 30)
        force_full = os.getenv("SPYPOINT_FULL_SCAN", "0") == "1"
        tags = tuple(sorted({tag.strip().lower() for tag in
                             os.getenv("SPYPOINT_TAGS", "").split(",") if tag.strip()}))
        root = Path(os.getenv("SPYPOINT_ARCHIVE_DIR", "/archive"))
        return sync(spypoint.Client(username, password), root, page_size, max_photos,
                    lookback_days, full_scan_days, force_full, tags=tags)
    except (OSError, ValueError, spypoint.SpypointException) as exc:
        print(f"Archive failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
