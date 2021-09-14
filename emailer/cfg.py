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
from kubernetes import client

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


def reconfigure_logging():
    logging_format = "%(asctime)s %(levelname)s: %(message)s"
    logging.basicConfig(format=logging_format, stream=sys.stdout, datefmt="%Y-%m-%d %H:%M:%S")

    logging_level = logging.DEBUG
    if CFG_DICT["debug"] != "yes":
        logging_level = logging.INFO

    logging.getLogger().setLevel(logging_level)
    client.rest.logger.setLevel(logging_level)


def reconfigure(configmap: dict):
    for key in configmap.data:
        if key not in CFG_DICT:
            logging.warning(f"ignoring unknown config key '{key}' (doesn't have a previous value)")
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
