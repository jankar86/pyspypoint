"""Run a single SPYPOINT API check and print recent photo URLs."""

import os
import sys

import spypoint


def main():
    username = os.getenv("SPYPOINT_USERNAME")
    password = os.getenv("SPYPOINT_PASSWORD")
    if not username or not password:
        print("Set SPYPOINT_USERNAME and SPYPOINT_PASSWORD in .env.", file=sys.stderr)
        return 2

    try:
        limit = int(os.getenv("SPYPOINT_PHOTO_LIMIT", "1"))
        if limit < 1:
            raise ValueError
    except ValueError:
        print("SPYPOINT_PHOTO_LIMIT must be a positive integer.", file=sys.stderr)
        return 2

    show_urls = os.getenv("SPYPOINT_SHOW_URLS", "1") != "0"
    client = spypoint.Client(username, password)
    try:
        cameras = client.cameras()
        print(f"Cameras: {len(cameras)}")
        for camera in cameras:
            print(f"  {camera.id}")

        if not cameras:
            return 0

        photos = client.photos(cameras, limit=limit)
        print(f"Recent photos: {len(photos)} (requested limit: {limit})")
        for photo in photos:
            url = photo.url()
            print(f"  {photo.id}: {url if show_urls else '[URL hidden]'}")
    except (spypoint.SpypointException, KeyError, AttributeError) as exc:
        print(f"SPYPOINT check failed: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
