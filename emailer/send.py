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
import smtplib
from queue import Queue
import emailer.cfg as cfg


def send_email(to_addr: str, subject: str, body: str):
    from_addr = cfg.CFG_DICT["email_from_addr"]

    server = cfg.CFG_DICT["smtp_server_fqdn"]
    port = cfg.CFG_DICT["smtp_server_port"]

    logging.info(f"Sending email FROM: {from_addr} TO: {to_addr} via {server}:{port}")
    logging.debug(f"SUBJECT: {subject}")
    logging.debug(f"BODY: {body}")

    if cfg.CFG_DICT["send_emails_for_real"] != "yes":
        logging.info("not sending email for real")
        return

    try:
        # TODO: TLS support?
        smtp = smtplib.SMTP(server, port)
    except Exception as e:
        logging.error(f"unable to contact SMTP server at {server}:{port}: {e}")
        return

    try:
        smtp.sendmail(from_addr, to_addr, f"Subject:{subject}\n\n{body}")
    except Exception as e:
        smtp.close()
        logging.error(f"unable to send email to {to_addr} via {server}:{port}: {e}")
        return

    smtp.close()
    logging.debug(f"sent email to {to_addr} via {server}:{port}!")


async def task_send_emails(emailq: Queue):
    sent = 0
    while True:
        logging.debug("task_send_emails() loop")
        if emailq.empty():
            sent = 0
            logging.info("no emails to send")
            await asyncio.sleep(int(cfg.CFG_DICT["task_send_emails_loop_sleep"]))
            continue

        address, subject, body = emailq.get()

        # send email in a different thread so we don't block the general emailer loop here
        await asyncio.to_thread(send_email, address, subject, body)

        sent += 1
        if sent >= int(cfg.CFG_DICT["task_send_emails_max"]):
            logging.warning(f"sent {sent} emails (max), waiting before sending more")
            sent = 0
            await asyncio.sleep(int(cfg.CFG_DICT["task_send_emails_loop_sleep"]))
