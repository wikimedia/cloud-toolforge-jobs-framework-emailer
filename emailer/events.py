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
from kubernetes import client, watch
import cfg
import compose


def process_event(emailevents: dict, event: dict):
    podname = event["object"].metadata.name
    namespace = event["object"].metadata.namespace

    # TODO: hardcoded labels?
    username = event["object"].metadata.labels["app.kubernetes.io/created-by"]
    jobname = event["object"].metadata.labels["app.kubernetes.io/name"]

    if emailevents.get(username) is None:
        emailevents[username] = dict()

    if emailevents[username].get(jobname) is None:
        emailevents[username][jobname] = []

    eventmsg = compose.event2message(event)
    emailevents[username][jobname].append(eventmsg)
    logging.info(
        f"caching event for user '{username}' in job '{jobname}', pod event '{namespace}/{podname}'"
    )
    logging.debug(f"{eventmsg}")


def user_requested_notifications_for_this(event: dict, emails: str):
    if emails == "none":
        return False

    if emails == "all":
        return True

    phase = event["object"].status.phase
    if emails == "onfinish" and phase in ["Succeeded", "Failed"]:
        return True

    if emails == "onfailure" and phase == "Failed":
        return True

    # TODO: we may need a special case here to correctly handle some weirdness with cont jobs

    # otherwise, we don't know, default to ignore
    return False


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
    if phase not in ["Running", "Succeeded", "Failed"]:
        logging.debug(f"ignoring event: pod phase not relevant: {phase}")
        return False

    emails = event["object"].metadata.labels.get("jobs.toolforge.org/emails", "none")
    if not user_requested_notifications_for_this(event, emails):
        logging.debug(f"ignoring event: per user request, label set to '{emails}'")
        return False

    logging.debug("event seems relevant")
    return True


async def task_watch_pods(emailevents: dict):
    corev1api = client.CoreV1Api()
    w = watch.Watch()

    # prepopulating resource version so the initial stream doesn't show us events since the
    # beginning of the history
    last_seen_version = corev1api.list_pod_for_all_namespaces(limit=1).metadata.resource_version

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
            timeout_seconds=int(cfg.CFG_DICT["task_watch_pods_timeout"]),
            resource_version=last_seen_version,
        ):

            if pod_event_is_relevant(event):
                process_event(emailevents, event)

            last_seen_version = event["object"].metadata.resource_version
            # let other tasks run if they need to
            await asyncio.sleep(0)
