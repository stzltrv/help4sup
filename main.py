import logging
import os
import sys
from datetime import datetime
from time import sleep

from dotenv import load_dotenv

load_dotenv()

from app.db import Base, engine, get_db
from app.notification.telegram import Telegram
from app.tsystem.cerb import Cerb
from app.tsystem.guru import Guru
from app.utils import am_i_working_now

log = logging.getLogger()
log.setLevel(logging.DEBUG)
log_formatter = logging.Formatter('[%(asctime)s][%(name)s][%(levelname)s][%(message)s]')

# stdout handler
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
handler.setFormatter(log_formatter)

# file handler
fileHandler = logging.FileHandler('app.log')
fileHandler.setFormatter(log_formatter)

log.addHandler(fileHandler)
log.addHandler(handler)

# Disable url3lib debug msg
logging.getLogger('urllib3').setLevel(logging.WARNING)


def main():
    # create tables
    Base.metadata.create_all(engine)

    # init ticket systems
    ticket_systems = [
        Cerb(
            token=os.getenv('CERBERUS_TOKEN'),
            cert_path=f'{os.path.dirname(os.path.realpath(__file__))}/Majordomo_LLC_Root_CA.crt',
            buckets=[
                600,  # Service
                601,  # Support
                # 1175, # Admin
                # 1972, # Noc
            ],
        ),
        Guru(
            token=os.getenv('GURU_TOKEN'),
        ),
    ]

    # notification handler
    notification = Telegram(
        token=os.getenv('TELEGRAM_TOKEN'), chat_id=os.getenv('TELEGRAM_CHAT_ID')
    )

    # Main loop
    while True:
        # update env every loop
        load_dotenv(override=True)

        # update autoclose var on work/non work days
        if os.getenv('CHECK_WORK_DAYS') == '1':
            if am_i_working_now(cycle_start=datetime(2025, 9, 11)) is False:
                os.environ['ENABLE_AUTOCLOSE'] = '0'
            else:
                os.environ['ENABLE_AUTOCLOSE'] = '1'

        try:
            with get_db() as db_session:
                for ticket_system in ticket_systems:
                    for ticket in ticket_system.process_tickets(db_session):
                        # skip notify
                        if ticket.spam_score <= int(os.getenv('NOTIFY_MAX_SCORE')):
                            notification.notify(ticket)

        except Exception as e:
            log.error(e)
        except KeyboardInterrupt:
            exit()
        finally:
            sleep(int(os.getenv('SLEEP_TIME')))


if __name__ == '__main__':
    main()
