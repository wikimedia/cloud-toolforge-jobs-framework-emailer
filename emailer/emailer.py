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

import sys
import asyncio
import logging
import smtplib
from queue import Queue
from kubernetes import client, config, watch

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
# The 'emailevents' dict has this layout:
#
# emailevents = {
#    "user1": {
#         "job1": [ "event 1 msg", "event 2 msg"],
#         "job2": [ "event 1 msg", "event 2 msg"],
#    }
#    "user2": {
#         "job1": [ "event 1 msg", "event 2 msg"],
#         "job2": [ "event 1 msg", "event 2 msg"],
#    }
# }

CONFIGMAP_NAME = "jobs-emailer-configmap"
CONFIGMAP_NS = "jobs-emailer"

# some defaults
CFG_DICT = {
    # process events to compose emails every this many seconds
    # if you pick a big enough number here chances are the system can collapse several emails for
    # a same user together. They will get the email delayed, but there will be fewer emails flying.
    # The default here is 5 minutes
    "task_compose_emails_loop_sleep": "300",
    # send emails every this many seconds
    "task_send_emails_loop_sleep": "30",
    # every time we send emails, send this many at max
    "task_send_emails_max": "10",
    # how long to block watching for pod events
    # not very important, but may further delay email delivery
    "task_watch_pods_timeout": "60",
    # how often to read our configmap for reconfiguration
    "task_read_configmap_sleep": "10",
    # the domain emails will go to
    "email_to_domain": "toolsbeta.wmflabs.org",
    # the prefix needed in the to address, before the tool name
    "email_to_prefix": "toolsbeta",
    # emails will come from this address
    "email_from_addr": "root@toolforge.org",
    # smtp server FQDN to use for outbout emails
    "smtp_server_fqdn": "mail.toolforge.org",
    # smtp server port to use for outbout emails
    "smtp_server_port": "465",
    # send emails for real? this should help you debug this stuff without harm
    "send_emails_for_real": "no",
    # print debug information into stdout
    "debug": "yes",
}


def send_email(to_addr: str, subject: str, body: str):
    from_addr = CFG_DICT["email_from_addr"]

    server = CFG_DICT["smtp_server_fqdn"]
    port = CFG_DICT["smtp_server_port"]

    try:
        smtp = smtplib.SMTP_SSL(server, port)
    except Exception as e:
        logging.error(f"unable to contact SMTP server at {server}:{port}: {e}")
        return

    try:
        logging.info(
            f"Sending email FROM: {from_addr} TO: {to_addr} via {server}:{port}"
        )
        logging.info(f"SUBJECT: {subject}")
        logging.info(f"BODY: {body}")
        if CFG_DICT["send_emails_fo_real"] == "yes":
            smtp.sendmail(from_addr, to_addr, f"Subject:{subject}\n\n{body}")
        else:
            logging.info("not sending email for real")
    except Exception as e:
        smtp.close()
        logging.error(f"unable to send email to {to_addr} via {server}:{port}: {e}")
        return

    smtp.close()
    logging.debug("sent email to {to_addr} via {server}:{port}!")


async def task_send_emails(emailq: Queue):
    sent = 0
    while True:
        logging.debug("task_send_emails() loop")
        if emailq.empty():
            sent = 0
            logging.info("no emails to send")
            await asyncio.sleep(int(CFG_DICT["task_send_emails_loop_sleep"]))
            continue

        address, subject, body = emailq.get()
        send_email(address, subject, body)
        sent += 1

        # let other tasks run
        await asyncio.sleep(0)

        if sent >= int(CFG_DICT["task_send_emails_max"]):
            sent = 0
            logging.warning(f"sent {sent} emails (max), waiting before sending more")
            await asyncio.sleep(int(CFG_DICT["task_send_emails_loop_sleep"]))


def compose_email(user: str, jobs: dict):
    jobcount = len(jobs)

    addr_prefix = CFG_DICT["email_to_prefix"]
    addr_domain = CFG_DICT["email_to_domain"]
    address = f"{addr_prefix}.{user}@{addr_domain}"
    subject = f"[Toolforge] notification about {jobcount} jobs"

    body = "We wanted to notify you about the activity of some jobs in Toolforge.\n"
    for job in jobs:
        eventcount = len(jobs[job])
        body += f"\n* Job '{job}' had {eventcount} events:\n"
        for event in jobs[job]:
            body += f"  -- {event}\n"

    body += "\n\n"
    body += (
        "If you requested 'filelog' for any of the jobs mentioned above, you may find "
    )
    body += "additional information about what happened in the associated log files. "
    body += "Check them from Toolforge bastions as usual.\n"
    body += "\n"
    body += "You are receiving this email because:\n"
    body += (
        " 1) when the job was created, it was requested to send email notfications\n"
    )
    body += " 2) you are listed as tool maintainer for this tool, with your email associated\n"
    body += "\n"
    body += (
        "Find help and more information in wikitech: https://wikitech.wikimedia.org/\n"
    )
    body += "\n"
    body += "Thanks for your contributions to the wikimedia movement.\n"

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
            logging.info(
                f"{new} new pending emails in the queue, new total queue size: {after}"
            )

        await asyncio.sleep(int(CFG_DICT["task_compose_emails_loop_sleep"]))


def process_event(emailevents: dict, event: dict):
    podname = event["object"].metadata.name
    namespace = event["object"].metadata.namespace

    # TODO: hardcoded labels?
    labels = event["object"].metadata.labels
    username = labels["app.kubernetes.io/created-by"]
    jobname = labels["app.kubernetes.io/name"]

    logging.info(
        f"caching event for user '{username}' in job '{jobname}', pod event '{namespace}/{podname}'"
    )

    if emailevents.get(username) is None:
        emailevents[username] = dict()

    if emailevents[username].get(jobname) is None:
        emailevents[username][jobname] = []

    statuses = event["object"].status.container_statuses
    containerstatus = statuses[0]
    restartcount = containerstatus.restart_count

    containerstate = containerstatus.state.terminated
    started_at = containerstate.started_at
    finished_at = containerstate.finished_at
    exit_code = containerstate.exit_code
    message = containerstate.message
    reason = containerstate.reason

    emailmsg = f"A pod named '{podname}' was created at {started_at}. "
    emailmsg += f"It was restarted {restartcount} times. "
    emailmsg += f"It finished at {finished_at} with exit code {exit_code}. "
    emailmsg += f"The reason was '{reason}' with message '{message}'."

    emailevents[username][jobname].append(emailmsg)


def pod_event_is_relevant(event: dict):
    name = event["object"].metadata.name
    namespace = event["object"].metadata.namespace

    logging.debug(f"evaluating event relevance for pod '{namespace}/{name}'")

    if not namespace.startswith("tool-"):
        logging.debug(f"ignoring event: not interested in namespace '{namespace}'")
        return False

    # TODO: hardcoded labels ?
    # TODO: we need a new label so users can opt-out of receiving notification emails at all
    labels = event["object"].metadata.labels
    if labels.get("toolforge", "") != "tool":
        logging.debug("ignoring event: not related to a toolforge tool")
        return False

    if labels.get("app.kubernetes.io/managed-by", "") != "toolforge-jobs-framework":
        logging.debug("ignoring event: not managed by toolforge-jobs-framework")
        return False

    if labels.get("app.kubernetes.io/component", "") not in [
        "jobs",
        "cronjobs",
        "deployments",
    ]:
        logging.debug("ignoring event: pod not a created by a proper component")
        return False

    event_type = event["type"]
    if event_type != "MODIFIED":
        logging.debug(f"ignoring event: not MODIFIED type: {event_type}")
        return False

    if event["object"].metadata.deletion_timestamp is not None:
        logging.debug("ignoring event: object being deleted")
        return False

    phase = event["object"].status.phase
    # https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-phase
    if phase not in ["Succeeded", "Failed"]:
        logging.debug(f"ignoring event: pod phase not relevant: {phase}")
        return False

    logging.debug("event seems relevant")
    return True


async def task_watch_pods(emailevents: dict):
    corev1api = client.CoreV1Api()
    w = watch.Watch()

    # prepopulating resource version so the initial stream doesn't show us events since the
    # beginning of the history
    last_seen_version = corev1api.list_pod_for_all_namespaces(
        limit=1
    ).metadata.resource_version

    # this outer loop is in theory not neccesary. But we are using a timeout in the stream watch
    # because if no events happen (unlikely in a real toolforge) then the call will block waiting
    # for events, preventing the email send routine from executing. The timeout unblocks the call
    # but then we need to restart it, hence this outer loop
    while True:
        logging.debug("task_watch_pods() loop")
        # let the others routines run if they need to
        await asyncio.sleep(0)

        for event in w.stream(
            corev1api.list_pod_for_all_namespaces,
            timeout_seconds=int(CFG_DICT["task_watch_pods_timeout"]),
            resource_version=last_seen_version,
        ):

            if pod_event_is_relevant(event):
                process_event(emailevents, event)

            last_seen_version = event["object"].metadata.resource_version
            # let other tasks run if they need to
            await asyncio.sleep(0)


def reconfigure(configmap: dict):
    for key in configmap.data:
        if key not in CFG_DICT:
            logging.warning(
                f"ignoring unknown config key '{key}' (doesn't have a previous value)"
            )
            continue

        CFG_DICT[key] = configmap.data[key]

    reconfigure_logging()
    logging.info(f"new configuration: {CFG_DICT}")


async def task_read_configmap():
    corev1api = client.CoreV1Api()
    last_seen_version = 0

    while True:
        logging.debug("task_read_configmap() loop")

        try:
            configmap = corev1api.read_namespaced_config_map(
                name=CONFIGMAP_NAME, namespace=CONFIGMAP_NS
            )
        except client.exceptions.ApiException as e:
            logging.warning(
                f"unable to query configmap {CONFIGMAP_NS}/{CONFIGMAP_NAME}: "
                f"{e.status} {e.reason}. Will use previous config."
            )
            await asyncio.sleep(int(CFG_DICT["task_read_configmap_sleep"]))
            continue

        new_version = int(configmap.metadata.resource_version)
        if new_version > last_seen_version:
            last_seen_version = new_version
            reconfigure(configmap)

        await asyncio.sleep(int(CFG_DICT["task_read_configmap_sleep"]))


def reconfigure_logging():
    logging_format = "%(asctime)s %(levelname)s: %(message)s"
    logging.basicConfig(
        format=logging_format, stream=sys.stdout, datefmt="%Y-%m-%d %H:%M:%S"
    )

    logging_level = logging.DEBUG
    if CFG_DICT["debug"] != "yes":
        logging_level = logging.INFO

    logging.getLogger().setLevel(logging_level)
    client.rest.logger.setLevel(logging_level)


def main():
    reconfigure_logging()

    # TODO: proper auth
    config.load_incluster_config()

    emailevents = {}
    emailq = Queue()

    loop = asyncio.get_event_loop()
    loop.create_task(task_read_configmap())
    loop.create_task(task_watch_pods(emailevents))
    loop.create_task(task_compose_emails(emailevents, emailq))
    loop.create_task(task_send_emails(emailq))

    try:
        loop.run_forever()
    except KeyboardInterrupt:
        loop.close()


if __name__ == "__main__":
    main()
