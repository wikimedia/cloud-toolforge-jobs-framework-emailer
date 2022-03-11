# Copyright (C) 2022 Arturo Borrero Gonzalez <aborrero@wikimedia.org>
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
import json
from kubernetes import client, watch
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional, List
import emailer.cfg as cfg


class JobEmailsConfig(Enum):
    """Class to represent a Toolforge job email configuration."""

    NONE = auto()
    ONFAILURE = auto()
    ONFINISH = auto()
    ALL = auto()

    def __str__(self):
        """String representation."""
        return self.name.lower()

    @classmethod
    def from_event(self, event):
        """Returns a JobEmailsConfig from a k8s event dictionary."""
        jobemailsconfig = event["metadata"]["labels"].get("jobs.toolforge.org/emails", "none")
        if jobemailsconfig == "onfailure":
            return JobEmailsConfig.ONFAILURE
        if jobemailsconfig == "onfinish":
            return JobEmailsConfig.ONFINISH
        if jobemailsconfig == "all":
            return JobEmailsConfig.ALL

        return JobEmailsConfig.NONE


class JobType(Enum):
    """Class to represent a Toolforge job type."""

    UNKNOWN = auto()
    NORMAL = auto()
    CRONJOB = auto()
    CONTINUOUS = auto()

    def __str__(self):
        """String representation."""
        return self.name.lower()

    @classmethod
    def from_event(self, event: dict):
        """Returns a JobType from a k8s event dictionary."""
        jobtype = event["metadata"]["labels"].get("app.kubernetes.io/component", "none")

        if jobtype == "jobs":
            return JobType.NORMAL
        elif jobtype == "cronjobs":
            return JobType.CRONJOB
        elif jobtype == "deployments":
            return JobType.CONTINUOUS

        return JobType.UNKNOWN


class ContainerState(Enum):
    """Class to represent a kubernetes container state."""

    UNKNOWN = auto()
    RUNNING = auto()
    TERMINATED = auto()
    WAITING = auto()

    def __str__(self):
        """String representation."""
        return self.name.lower()


@dataclass()
class JobEvent:
    """Class to represent a Toolforge Kubernetes job event."""

    podname: Optional[str]
    phase: Optional[str] = None
    container_state: Optional[ContainerState] = ContainerState.UNKNOWN
    exit_code: Optional[int] = None
    start_timestamp: Optional[str] = field(compare=False, default=None)
    stop_timestamp: Optional[str] = field(compare=False, default=None)
    reason: Optional[str] = field(compare=False, default=None)
    message: Optional[str] = field(compare=False, default=None)
    original_event: dict = field(compare=False, default=None)

    @classmethod
    def from_event(cls, event: dict):
        """Builds a JobEvent object from a kubernetes event."""
        podname = event["metadata"]["name"]
        phase = event["status"]["phase"]

        # https://github.com/kubernetes-client/python/blob/master/kubernetes/docs/V1ContainerState.md
        statuses = event["status"].get("containerStatuses", None)
        if statuses is not None and statuses[0] is not None:
            containerstatus = statuses[0]
            running_state = containerstatus["state"].get("running", None)
            terminated_state = containerstatus["state"].get("terminated", None)
            waiting_state = containerstatus["state"].get("waiting", None)
        else:
            running_state = None
            terminated_state = None
            waiting_state = None

        if running_state is not None:
            start_timestamp = running_state.get("startedAt", None)
            container_state = ContainerState.RUNNING
            extra_args = dict(start_timestamp=start_timestamp)
        elif terminated_state is not None:
            start = terminated_state.get("startedAt", None)
            stop = terminated_state.get("finishedAt", None)
            exit_code = terminated_state.get("exitCode", None)
            reason = terminated_state.get("reason", None)
            message = terminated_state.get("message", None)
            container_state = ContainerState.TERMINATED
            extra_args = dict(
                start_timestamp=start,
                stop_timestamp=stop,
                exit_code=exit_code,
                reason=reason,
                message=message,
            )
        elif waiting_state is not None:
            reason = waiting_state.get("reason", None)
            message = waiting_state.get("message", None)
            container_state = ContainerState.WAITING
            extra_args = dict(
                reason=reason,
                message=message,
            )
        else:
            container_state = ContainerState.UNKNOWN
            extra_args = dict()

        common_args = dict(
            podname=podname,
            phase=phase,
            original_event=event,
            container_state=container_state,
        )
        args = {**common_args, **extra_args}

        return cls(**args)

    def __repr__(self):
        """String representation."""
        s = ""

        if self.podname:
            s += f"Pod '{self.podname}'. "

        if self.phase:
            s += f"Phase: '{self.phase.lower()}'. "

        if self.container_state:
            s += f"Container state: '{self.container_state}'. "

        if self.start_timestamp:
            s += f"Start timestamp {self.start_timestamp}. "

        if self.stop_timestamp:
            s += f"Finish timestamp {self.stop_timestamp}. "

        if self.exit_code:
            s += f"Exit code was '{self.exit_code}'. "

        if self.reason:
            s += f"With reason '{self.reason}'. "

        if self.message:
            s += f"With message: '{self.message}'. "

        return s


class JobEventNotRelevant(Exception):
    """Exception that indicates that a JobEvent is not relevant."""


@dataclass
class Job:
    """Class to represent a collection of events related to a particular Toolforge tool."""

    name: str
    type: JobType
    emailsconfig: Optional[JobEmailsConfig] = JobEmailsConfig.NONE
    events: List[JobEvent] = field(init=False, default_factory=list)

    def _relevance_test(self, new_event: JobEvent) -> None:
        """Evaluates if a new event is worth storing as job event."""
        if self.emailsconfig == JobEmailsConfig.NONE:
            raise JobEventNotRelevant(f"job emails config is {self.emailsconfig}")

        if new_event in self.events:
            raise JobEventNotRelevant("we already have a similar event (duplicated)")

        if new_event.container_state == ContainerState.UNKNOWN and new_event.phase == "Pending":
            raise JobEventNotRelevant("this event has no meaningful information")

        if self.emailsconfig == JobEmailsConfig.ALL:
            logging.debug(
                f"user wants emails about all events on this job, caching event: {new_event}"
            )
            return

        if (
            self.emailsconfig == JobEmailsConfig.ONFINISH
            and new_event.container_state == ContainerState.TERMINATED
        ):
            logging.debug(
                f"user wants emails about onfinish events on this job, caching event: {new_event}"
            )
            return

        if (
            self.emailsconfig == JobEmailsConfig.ONFAILURE
            and new_event.container_state == ContainerState.TERMINATED
            and new_event.exit_code != 0
        ):
            logging.debug(
                f"user wants emails about onfailure events on this job, caching event: {new_event}"
            )
            return

        raise JobEventNotRelevant(f"found no reason to track this event: {self.name} {new_event}")

    def add_event(self, event: dict) -> None:
        """Add an entry to the list of job events."""
        new_event = JobEvent.from_event(event)
        self._relevance_test(new_event)
        self.events.append(new_event)

    def __str__(self):
        """String representation."""
        return f"{self.name} ({self.type}) (emails: {self.emailsconfig})"


@dataclass
class UserJobs:
    """Class to represent all job events produced by an user."""

    username: str
    jobs: List[Job] = field(init=False, default_factory=list)

    def _get_or_create(self, event: dict) -> Job:
        """Get a previous cached job from this user or create a new one if none exists."""
        jobname = event["metadata"]["labels"]["app.kubernetes.io/name"]
        jobtype = JobType.from_event(event)
        jobemailsconfig = JobEmailsConfig.from_event(event)

        for job in self.jobs:
            if job.name == jobname and job.type == jobtype and job.emailsconfig == jobemailsconfig:
                return job

        new_job = Job(name=jobname, type=jobtype, emailsconfig=jobemailsconfig)
        return new_job

    def add_event(self, event: dict) -> None:
        """Add an event to the list of kubernetes job events."""
        job = self._get_or_create(event)
        job.add_event(event)

        # we just created this entry
        if job not in self.jobs:
            self.jobs.append(job)


@dataclass
class Cache:
    """Class to represent collected Toolforge Kubernetes job events."""

    cache: List[UserJobs] = field(init=False, default_factory=list)

    def _get_or_create(self, username: str) -> UserJobs:
        """Get the user job events object from the cache, or create one if it doesn't exists."""
        for userjobs in self.cache:
            if userjobs.username == username:
                return userjobs

        new_userjobs = UserJobs(username)
        return new_userjobs

    def add_event(self, event: dict) -> None:
        """Add an event to the cache."""
        username = event["metadata"]["labels"]["app.kubernetes.io/created-by"]
        userjobs = self._get_or_create(username)
        userjobs.add_event(event)

        # we just created this entry
        if userjobs not in self.cache:
            self.cache.append(userjobs)

    def flush(self) -> None:
        """Delete the cache."""
        self.cache.clear()
        logging.debug("cache flushed")


def event_early_filter(event: dict, event_type: str) -> None:
    """Evaluate if a k8s pod event is interesting to the emailer, before any caching routine."""
    name = event["metadata"]["name"]
    namespace = event["metadata"]["namespace"]

    logging.debug(f"evaluating event relevance for pod '{namespace}/{name}'")

    if not namespace.startswith("tool-"):
        raise JobEventNotRelevant(f"not interested in in namespace '{namespace}'")

    # TODO: hardcoded labels ?
    labels = event["metadata"]["labels"]
    if labels.get("toolforge", "") != "tool":
        raise JobEventNotRelevant("not related to a toolforge tool")

    if labels.get("app.kubernetes.io/managed-by", "") != "toolforge-jobs-framework":
        raise JobEventNotRelevant("not managed by toolforge-jobs-framework")

    if labels.get("app.kubernetes.io/component", "") not in [
        "jobs",
        "cronjobs",
        "deployments",
    ]:
        raise JobEventNotRelevant("not created by a known component")

    if event_type != "MODIFIED":
        raise JobEventNotRelevant(f"not interested in this type {event_type}")

    if event["metadata"].get("deletion_timestamp", None) is not None:
        raise JobEventNotRelevant("object being deleted")

    phase = event["status"]["phase"]
    # https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-phase
    if phase not in ["Pending", "Running", "Succeeded", "Failed"]:
        raise JobEventNotRelevant(f"pod phase not relevant: {phase}")

    # ignore early some obvious discards by configuration
    # further filtering is done later when we decode and do the math to calculate if an
    # event matches the requested config
    emails = event["metadata"]["labels"].get("jobs.toolforge.org/emails", "none")
    if emails == "none":
        raise JobEventNotRelevant("user configuration requested no emails")

    logging.debug("event seems relevant in the early filter")


async def task_watch_pods(cache: Cache):
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

            raw_event_dict = event["raw_object"]

            try:
                event_early_filter(raw_event_dict, event["type"])
                cache.add_event(raw_event_dict)
            except KeyError as e:
                logging.error(f"potential bug while reading the k8s JSON, missing key {e}")
                logging.error("offending JSON follows:")
                logging.error(json.dumps(event, sort_keys=True, indent=4))
                pass
            except JobEventNotRelevant as e:
                logging.debug(f"ignoring job event: {e}")
                pass

            last_seen_version = event["object"].metadata.resource_version
            # let other tasks run if they need to
            await asyncio.sleep(0)
