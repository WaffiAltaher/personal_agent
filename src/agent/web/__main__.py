"""``python -m agent.web``: start the web interface (see ``agent.web.server``)."""

import asyncio
import sys

from agent.web.server import serve

if __name__ == "__main__":
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        sys.exit(130)
