import datetime
import logging

import requests

from sqlalchemy.orm import session
from app.models import Ticket as TicketModel
from app.tsystem.base import BaseClass

log = logging.getLogger('tsystem.guru')


class Guru(BaseClass):
    SYSTEM_NAME = 'Guru'
    SYSTEM_URL = 'https://ihc.guru'

    def __init__(self, token: str):
        self.AUTH_TOKEN = token

    #
    # Parse tickets
    #
    def process_tickets(self, db_session: session) -> list[TicketModel]:
        tickets = []

        data = self._req_post(
            url=f'{self.SYSTEM_URL}/ticket/search',
            data='{"query":"статус:1,4 отдел:2,6 ","counters":{"4":"отдел:2,6 статус:4"},"sort":{"field":"byactivity","order":-1}}',
        )

        if 'list' not in data:
            raise Exception('guru: not found tickets list in response, Wrong token?')

        for ticket_data in data['list']:
            ticket_id = int(ticket_data['ticket']['id'])
            ticket_mask = ticket_data['ticket']['mask']
            ticket_subject = ticket_data['ticket']['subject']
            ticket_user = ticket_data['ticket']['username']
            ticket_group = 'Hms'
            if ticket_data['ticket']['panelPrefix'] == 'md':
                ticket_group = 'Vps'
            ticket_url = f'{self.SYSTEM_URL}/#/support/chat/{ticket_data["ticket"]["panelPrefix"]}/{ticket_id}'
            ticket_updated_at = datetime.datetime.strptime(
                ticket_data['ticket']['lastActivity'], '%Y-%m-%d %H:%M:%S'
            )

            ticket = db_session.query(TicketModel).filter_by(mask=ticket_mask).first()

            if ticket is not None:
                log.debug('found mask in Database')
                if ticket.updated_at == ticket_updated_at:
                    log.debug('nothing new, skip')
                else:
                    # TODO: filter lastActivity
                    if (ticket_updated_at - ticket.updated_at).total_seconds() < 61:
                        log.debug('dont double notify < 1min, update time and skip')
                        ticket.updated_at = ticket_updated_at
                        db_session.flush()
                    else:
                        log.debug('updated ticket, add to rval')
                        ticket.updated_at = ticket_updated_at
                        db_session.flush()
                        tickets.append(ticket)
            else:
                log.debug('found new ticket')
                ticket = TicketModel(
                    system_name=self.SYSTEM_NAME,
                    mask=ticket_mask,
                    group=ticket_group,
                    subject=ticket_subject,
                    url=ticket_url,
                    user=ticket_user,
                    updated_at=ticket_updated_at,
                    # System clients only
                    spam_score=-99,
                )
                log.debug('add ticket to database')
                db_session.add(ticket)
                log.debug('add ticket to rval')
                tickets.append(ticket)

        return tickets

    #
    # Post request
    #
    def _req_post(self, url: str, data: list) -> dict:
        log.debug(f'post request: {url} with data: {data}')
        resp = requests.post(
            url=url,
            data=data,
            headers={
                'cookie': f'JSESSIONID={self.AUTH_TOKEN}',
                'user-agent': self.USER_AGENT,
                'Origin': 'https://ihc.guru',
                'Referer': 'https://ihc.guru/',
            },
        )

        if resp.status_code != 200:
            raise Exception(f'wrong status_code from response {url}')

        return resp.json()
