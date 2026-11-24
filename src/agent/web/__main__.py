"""``python -m agent.web``: start the web interface (see ``agent.web.server``)."""

import asyncio
import faulthandler
import sys

from agent.web.server import serve

if __name__ == "__main__":
    # A native crash kills the process before any except or finally runs: print every thread's
    # Python traceback to stderr instead of exiting silently.
    faulthandler.enable()
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        sys.exit(130)
