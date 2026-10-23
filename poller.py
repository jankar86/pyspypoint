"""Run the archive job on a quiet, configurable interval."""

import os
import signal
import sys
from threading import Event

import archive


def main():
    try:
        hours = float(os.getenv("SPYPOINT_POLL_HOURS", "6"))
        if not 0.25 <= hours <= 168:
            raise ValueError
    except ValueError:
        print("SPYPOINT_POLL_HOURS must be between 0.25 and 168.", file=sys.stderr)
        return 2

    stop = Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    print(f"Polling every {hours:g} hours")
    while not stop.is_set():
        result = archive.main()
        if result == 2:
            return result
        if result:
            print("Archive run failed; will retry at the next interval.", file=sys.stderr)
        if not stop.is_set():
            stop.wait(hours * 3600)
    return 0


if __name__ == "__main__":
    sys.exit(main())
