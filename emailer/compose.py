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
from dataclasses import dataclass
from collections import deque
import emailer.cfg as cfg
from emailer.events import Cache, UserJobs


@dataclass(frozen=True)
class Email:
    """Class to represent an email."""

    subject: str
    to_addr: str
    from_addr: str
    body: str

    def message(self) -> str:
        """method to generate a message string suitable for smptlib.sendmail()."""
        # headers
        ret = ""
        ret += f"Subject: {self.subject}\n"
        ret += f"To: {self.to_addr}\n"
        ret += f"From: {self.from_addr}"

        # content
        ret += "\n\n"
        ret += self.body

        return ret


def _compose_subject(userjobs: UserJobs) -> str:
    subject = f"[Toolforge] [{userjobs.username}] notification about "

    jobcount = len(userjobs.jobs)
    if jobcount == 1:
        subject += f"job {userjobs.jobs[0].name}"
    else:
        subject += f"{jobcount} jobs"

    return subject


def compose_email(userjobs: UserJobs) -> Email:
    addr_prefix = cfg.CFG_DICT["email_to_prefix"]
    addr_domain = cfg.CFG_DICT["email_to_domain"]
    address = f"{addr_prefix}.{userjobs.username}@{addr_domain}"
    subject = _compose_subject(userjobs)

    body = "We wanted to notify you about the activity of some jobs "
    body += f"in the '{userjobs.username}' Toolforge tool.\n"

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
    body += " 1) when the job was created, it was requested to send email notfications.\n"
    body += " 2) you are listed as tool maintainer for this tool.\n"
    body += "\n"
    body += "Find help and more information in wikitech: https://wikitech.wikimedia.org/\n"
    body += "\n"
    body += "Thanks for your contributions to the Wikimedia movement.\n"

    # TODO: run the extra mile and include the last few log lines in the email?

    return Email(
        from_addr=cfg.CFG_DICT["email_from_addr"], to_addr=address, subject=subject, body=body
    )


async def task_compose_emails(cache: Cache, emailq: deque):
    while True:
        logging.debug("task_compose_emails() loop")
        before = len(emailq)

        for userjobs in cache.cache:
            emailq.append(compose_email(userjobs))

        after = len(emailq)
        new = after - before

        if new > 0:
            logging.info(f"{new} new pending emails in the queue, new total queue size: {after}")
            cache.flush()

        await asyncio.sleep(int(cfg.CFG_DICT["task_compose_emails_loop_sleep"]))
