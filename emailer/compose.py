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
from queue import Queue
from kubernetes import client
import cfg


def compose_email(user: str, jobs: dict):
    jobcount = len(jobs)

    addr_prefix = cfg.CFG_DICT["email_to_prefix"]
    addr_domain = cfg.CFG_DICT["email_to_domain"]
    address = f"{addr_prefix}.{user}@{addr_domain}"
    subject = f"[Toolforge] notification about {jobcount} jobs"

    body = "We wanted to notify you about the activity of some jobs in Toolforge.\n"
    for job in jobs:
        eventcount = len(jobs[job])
        body += f"\n* Job '{job}' had {eventcount} events:\n"
        for event in jobs[job]:
            body += f"  -- {event}\n"

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


async def task_compose_emails(emailevents: dict, emailq: Queue):
    while True:
        logging.debug("task_compose_emails() loop")

        before = emailq.qsize()

        for user in list(emailevents):
            emailq.put(compose_email(user, emailevents[user]))
            del emailevents[user]

        after = emailq.qsize()
        new = after - before

        if new > 0:
            logging.info(f"{new} new pending emails in the queue, new total queue size: {after}")

        await asyncio.sleep(int(cfg.CFG_DICT["task_compose_emails_loop_sleep"]))


def running_generate_msg(state: client.V1ContainerStateRunning):
    eventmsg = f"It was started at {state.started_at}."
    return eventmsg


def terminated_generate_msg(state: client.V1ContainerStateTerminated):
    eventmsg = f"It was created at {state.started_at}. "

    finished_at = state.finished_at
    if finished_at is not None:
        eventmsg += f"The pod eventually finished at {finished_at}. "

    exit_code = state.exit_code
    if exit_code is not None:
        eventmsg += f"The exit code was {exit_code}. "

    reason = state.reason
    if reason is not None:
        eventmsg += f"The reason was '{reason}'. "

    message = state.message
    if message is not None:
        eventmsg += f"With associated message '{message}'. "

    return eventmsg


def waiting_generate_msg(state: client.V1ContainerStateWaiting):
    eventmsg = "Pod is in waiting state."

    msg = state.message
    if msg is not None:
        eventmsg += f" Not running yet with message: {msg}."

    reason = state.reason
    if reason is not None:
        eventmsg += f" Reason '{reason}'."

    return eventmsg


def event2message(event: dict):
    podname = event["object"].metadata.name
    statuses = event["object"].status.container_statuses
    containerstatus = statuses[0]

    eventmsg = f"Event for pod '{podname}'. "

    # https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/V1ContainerState.md
    running_state = containerstatus.state.running
    terminated_state = containerstatus.state.terminated
    waiting_state = containerstatus.state.waiting

    if running_state is not None:
        eventmsg += running_generate_msg(running_state)
    elif terminated_state is not None:
        eventmsg += terminated_generate_msg(terminated_state)
    elif waiting_state is not None:
        eventmsg += waiting_generate_msg(waiting_state)
    else:
        eventmsg += "Unknown container state."

    return eventmsg
