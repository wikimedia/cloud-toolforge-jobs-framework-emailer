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

import asyncio
import logging
import traceback
from typing import List
from collections import deque
from kubernetes import config
import emailer.cfg as cfg
import emailer.events as events
import emailer.send as send
import emailer.compose as compose
from emailer.events import Cache

# Flooding an email server is very easy, so a word on how this works to try avoiding such flood:
#  1) task_watch_pods(): watch pod events from kubernetes
#    * events are filtered out, we only care about certain events
#    * if a relevant event happens, we extract the info and cache it in the 'emailevents' dict
#  2) task_compose_emails(): iterate the 'emailevents' dict to compose actual emails and queue them
#  3) task_send_emails(): every Y seconds, send queued emails, up to a given max
#  4) we also read a configmap every X seconds, to allow reconfiguration without restarts
#     which should help reduce the amount of lost emails
#
# The ultimate goal is to collapse per-user events into a single email, and send emails in
# controlled-size batches to avoid flooding the email servers. Remember, there could be hundred of
# events happening at the same time.
# This means an user may get a single email with reports about several events that happened to
# several jobs.
#
# The emailq queue is just a normal FIFO queue.


async def cancel_all_tasks(tasks: List[asyncio.tasks.Task]) -> None:
    """This function cancel all alive tasks, so we can gracefully shutdown the event loop."""
    for task in tasks:
        if task.done():
            continue

        task.cancel()
        await asyncio.sleep(0)


async def task_error_check(
    loop: asyncio.events.AbstractEventLoop, tasks: List[asyncio.tasks.Task]
) -> None:
    """This task checks all main program tasks to see if they are alive."""
    logging.debug("task_error_check()")

    for task in tasks:
        if task.done():
            logging.error(f"{task}")
            try:
                task.result()
            except Exception:
                logging.error(traceback.format_exc())

            await cancel_all_tasks(tasks)
            logging.warning("cancelled all tasks, bye bye")
            loop.stop()
            return

    # everything OK, reschedule myself to check again after some time
    await asyncio.sleep(60)
    loop.create_task(task_error_check(loop, tasks))


def main():
    cfg.reconfigure_logging()

    logging.info("emailer starting!")

    # TODO: proper auth
    config.load_incluster_config()

    cache = Cache()
    emailq = deque()
    tasks = []

    loop = asyncio.get_event_loop()

    # the main program tasks
    tasks.append(loop.create_task(cfg.task_read_configmap()))
    tasks.append(loop.create_task(events.task_watch_pods(cache)))
    tasks.append(loop.create_task(compose.task_compose_emails(cache, emailq)))
    tasks.append(loop.create_task(send.task_send_emails(emailq)))

    # the task that detects if we should die (if one of the main program tasks died)
    loop.create_task(task_error_check(loop, tasks))

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass

    loop.close()


if __name__ == "__main__":
    main()
