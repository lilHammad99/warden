"""Process-wide control signals shared between tools and the main app.

A tool runs on the agent thread, deep inside ``agent.chat``; it has no handle
on the speaker, HUD, camera or the main loop. When the user asks Jarvis to shut
himself down, the ``shutdown_jarvis`` tool just sets ``SHUTDOWN`` here, and a
watcher thread started in ``app.main`` sees it, lets the farewell finish, tears
everything down and exits the process cleanly.
"""

import threading

# set by the shutdown_jarvis tool; awaited by the watcher in app.main
SHUTDOWN = threading.Event()


def request_shutdown() -> None:
    SHUTDOWN.set()
