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
from collections import deque
import emailer.cfg as cfg
from emailer.events import Cache, UserJobs


def compose_email(userjobs: UserJobs) -> None:
    jobcount = len(userjobs.jobs)

    addr_prefix = cfg.CFG_DICT["email_to_prefix"]
    addr_domain = cfg.CFG_DICT["email_to_domain"]
    address = f"{addr_prefix}.{userjobs.username}@{addr_domain}"
    subject = f"[Toolforge] notification about {jobcount} job events"

    body = "We wanted to notify you about the activity of some jobs in Toolforge.\n"
    for job in userjobs.jobs:
        eventcount = len(job.events)
        body += f"\n* Job '{job.name}' ({job.type}) (emails: {job.emailsconfig}) "
        body += f"had {eventcount} events:\n"
        for jobevent in job.events:
            body += f"  -- {jobevent}\n"

    body += "\n\n"
    body += "If you requested 'filelog' for any of the jobs mentioned above, you may find "
    body += "additional information about what happened in the associated log files. "
    body += "Check them from Toolforge bastions as usual.\n"
    body += "\n"
    body += "You are receiving this email because:\n"
    body += " 1) when the job was created, it was requested to send email notfications\n"
    body += " 2) you are listed as tool maintainer for this tool\n"
    body += "\n"
    body += "Find help and more information in wikitech: https://wikitech.wikimedia.org/\n"
    body += "\n"
    body += "Thanks for your contributions to the Wikimedia movement.\n"

    # TODO: run the extra mile and include the last few log lines in the email?

    return address, subject, body


async def task_compose_emails(cache: Cache, emailq: deque):
    while True:
        logging.debug("task_compose_emails() loop")
        before = len(emailq)

        for userjobs in cache.cache:
            emailq.append(compose_email(userjobs))
            cache.delete(userjobs)

        after = len(emailq)
        new = after - before

        if new > 0:
            logging.info(f"{new} new pending emails in the queue, new total queue size: {after}")

        await asyncio.sleep(int(cfg.CFG_DICT["task_compose_emails_loop_sleep"]))
