# Copyright (C) 2021 Arturo Borrero Gonzalez <aborrero@wikimedia.org>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
#

import logging
import asyncio
from aiohttp import web

LISTEN_TCP_PORT = 8080
LISTEN_ADDR = "0.0.0.0"


async def healthz(request):
    """This function handles requests to /healthz (liveness probes by k8s)."""
    logging.debug(f"healthz(): {request}")

    data = {"state": "pretty much alive :-)"}
    return web.json_response(data)


async def webserver_run():
    """This class runs a small embedded webserver to handle some simple requests."""
    app = web.Application()
    app.add_routes(
        [
            web.get("/healthz", healthz),
        ]
    )

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, LISTEN_ADDR, LISTEN_TCP_PORT).start()

    # this awaits forever in a noop. We need this so the webserver stays running
    await asyncio.Event().wait()
