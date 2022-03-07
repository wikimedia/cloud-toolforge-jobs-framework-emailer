import os  # noqa: F401
import sys  # noqa: F401
import copy
from typing import Generator

from .context import JobType, JobEmailsConfig


class FakeK8sPodGenerator:
    """Helper class to generate fake k8s pod dictionaries."""

    pod_template = {
        "metadata": {
            "namespace": "",
            "labels": {
                "app.kubernetes.io/managed-by": "toolforge-jobs-framework",
                "app.kubernetes.io/created-by": "",
                "app.kubernetes.io/component": "",
                "app.kubernetes.io/name": "",
                "jobs.toolforge.org/emails": "",
                "toolforge": "tool",
            },
            "name": "",
        },
        "status": {
            "phase": "Succeeded",
            "containerStatuses": [
                {"state": {}},
            ],
        },
    }

    def _job_type_to_k8s_type(jobtype: JobType):
        """Translate a JobType to the associated k8s object type."""
        if jobtype == JobType.NORMAL:
            return "jobs"
        if jobtype == JobType.CRONJOB:
            return "cronjobs"
        if jobtype == JobType.CONTINUOUS:
            return "deployments"

    def new(
        namespace: str = "tool-test-account",
        account: str = "test-account",
        component: JobType = JobType.NORMAL,
        name: str = "fake-pod-name",
        job_name: str = "mytestjob",
        job_emails: JobEmailsConfig = JobEmailsConfig.NONE,
        phase: str = "Pending",
        container_status: str = "waiting",
        reason: str = "uknown reason",
        exit_code: int = 0,
        message: str = "unknown message",
        start_time: str = "20220307 14:48:00 UTC",
        stop_time: str = "20220307 14:49:10 UTC",
    ) -> dict:
        """Creates a new fake k8s pod dictionary."""
        obj = copy.deepcopy(FakeK8sPodGenerator.pod_template)
        obj["metadata"]["namespace"] = namespace
        obj["metadata"]["name"] = name
        obj["metadata"]["labels"]["app.kubernetes.io/created-by"] = account
        _component = FakeK8sPodGenerator._job_type_to_k8s_type(component)
        obj["metadata"]["labels"]["app.kubernetes.io/component"] = _component
        obj["metadata"]["labels"]["app.kubernetes.io/name"] = job_name
        obj["metadata"]["labels"]["jobs.toolforge.org/emails"] = f"{job_emails}"
        obj["status"]["phase"] = phase

        status = dict()
        if container_status == "waiting":
            status["reason"] = reason
            status["message"] = message
        if container_status == "running":
            status["started_at"] = start_time
        if container_status == "terminated":
            status["reason"] = reason
            status["message"] = message
            status["exit_code"] = exit_code
            status["started_at"] = start_time
            status["finished_at"] = stop_time

        # only one container per job
        obj["status"]["containerStatuses"][0]["state"][container_status] = status

        return obj

    def phase_ok_sequence(
        account: str = "mytool",
        job_name: str = "myjob",
        emails: JobEmailsConfig = JobEmailsConfig.NONE,
        component: JobType = JobType.NORMAL,
    ) -> Generator[dict, dict, dict]:
        """Returns fake k8s pod dictionaries in a sequence resembling a good pod scheduling."""
        pending_event = FakeK8sPodGenerator.new(
            account=account,
            job_name=job_name,
            phase="Pending",
            container_status="waiting",
            job_emails=emails,
            component=component,
        )
        yield pending_event

        running_event = FakeK8sPodGenerator.new(
            account=account,
            job_name=job_name,
            phase="Running",
            container_status="running",
            job_emails=emails,
            component=component,
        )
        yield running_event

        finish_event = FakeK8sPodGenerator.new(
            account=account,
            job_name=job_name,
            phase="Succeeded",
            container_status="terminated",
            job_emails=emails,
            component=component,
        )
        yield finish_event

    def phase_failed_sequence(
        account: str = "mytool",
        job_name: str = "myjob",
        emails: JobEmailsConfig = JobEmailsConfig.NONE,
        component: JobType = JobType.NORMAL,
    ) -> Generator[dict, dict, dict]:
        """Returns fake k8s pod dictionaries in a sequence resembling a bad pod scheduling."""
        pending_event = FakeK8sPodGenerator.new(
            account=account,
            job_name=job_name,
            phase="Pending",
            container_status="waiting",
            job_emails=emails,
            component=component,
        )
        yield pending_event

        running_event = FakeK8sPodGenerator.new(
            account=account,
            job_name=job_name,
            phase="Running",
            container_status="running",
            job_emails=emails,
            component=component,
        )
        yield running_event

        finish_event = FakeK8sPodGenerator.new(
            account=account,
            job_name=job_name,
            phase="Failed",
            container_status="terminated",
            exit_code=99,
            reason="fake failure",
            message="this is a fake failure",
            stop_time="2022-03-08 13:02 UTC",
            job_emails=emails,
            component=component,
        )
        yield finish_event

    def multiple_sequence(n: int = 3) -> Generator[dict, dict, dict]:
        """Returns multiple fake k8s pod dictionaries in sequences."""
        tested_jobtypes = [JobType.NORMAL, JobType.CRONJOB, JobType.CONTINUOUS]
        tested_emailconf = [
            JobEmailsConfig.ONFINISH,
            JobEmailsConfig.ONFAILURE,
            JobEmailsConfig.ALL,
        ]
        events = []

        for i in range(n):
            for j in range(n):
                account = f"mytool-{i}"
                jobname = f"{account}-job-{j}"
                for jobtype in tested_jobtypes:
                    for emails in tested_emailconf:
                        for event in FakeK8sPodGenerator.phase_ok_sequence(
                            account=account, job_name=jobname, emails=emails, component=jobtype
                        ):
                            events.append(event)

                        for event in FakeK8sPodGenerator.phase_failed_sequence(
                            account=account, job_name=jobname, emails=emails, component=jobtype
                        ):
                            events.append(event)

        return events
