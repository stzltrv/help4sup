import logging
import os
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from xxhash import xxh128_hexdigest

from sqlalchemy.orm import session
from app.models import SpamscoreList as SpamscoreListModel
from app.models import Ticket as TicketModel
from app.tsystem.base import BaseClass

log = logging.getLogger('tsystem.cerb')


class Cerb(BaseClass):
    SYSTEM_NAME = 'Cerberus'
    SYSTEM_URL = 'https://cerberus.intr'
    CERT_PATH = str
    BUCKETS = list[int]

    def __init__(self, token: str, cert_path: str, buckets: list[int]):
        self.AUTH_TOKEN = token
        self.CERT_PATH = cert_path
        self.BUCKETS = buckets

    #
    # Parse tickets
    #
    def process_tickets(self, db_session: session) -> list[TicketModel]:
        tickets = []

        for bucket_id in self.BUCKETS:
            log.debug(f'parse bucket_id: {bucket_id}')
            # Get bucket tickets html
            bucket_html = self._req_get(
                f'{self.SYSTEM_URL}/ajax.php?c=internal&a=viewRefresh&id=cust_{bucket_id}'
            )
            bucket_soup = BeautifulSoup(bucket_html, 'html.parser')
            bucket_name = bucket_soup.find('span', {'class': 'title'}).text
            log.debug(f'found bucket_name: {bucket_name}')

            # parse bucket tickets
            for bucket_ticket in bucket_soup.find(
                'table', {'class': 'worklistBody'}
            ).find_all('tbody'):
                # get local_id
                ticket_local_id = bucket_ticket.find('input', {'name': 'ticket_id[]'})[
                    'value'
                ]
                log.debug(f'found ticket_local_id: {ticket_local_id}')

                # get subject
                ticket_subject = bucket_ticket.find('a', {'class': 'subject'}).text
                log.debug(f'found ticket_subject: {ticket_subject}')

                # get url
                ticket_url = f'{self.SYSTEM_URL}{bucket_ticket.find("a", {"class": "subject"})["href"]}'
                log.debug(f'found ticket_url: {ticket_url}')

                # get mask
                ticket_mask = re.match(
                    'https://cerberus.intr/index.php/profiles/ticket/(.*)/conversation',
                    ticket_url,
                ).group(1)
                log.debug(f'found ticket_mask {ticket_mask}')

                # service dont have from
                if bucket_name == 'Service':
                    ticket_user = 'noreply@majordomo.ru'
                else:
                    # get user
                    ticket_user = bucket_ticket.find(
                        'a', {'data-context': 'cerberusweb.contexts.address'}
                    ).text
                log.debug(f'found ticket_user: {ticket_user}')

                # get updated_at
                ticket_updated_at = bucket_ticket.find(
                    'td', {'data-column': 't_updated_date'}
                )['data-timestamp']
                ticket_updated_at = datetime.fromtimestamp(int(ticket_updated_at))
                log.debug(f'found ticket_updated_at: {ticket_updated_at}')

                ticket_spamscore = 0

                # check in db by mask
                ticket = (
                    db_session.query(TicketModel).filter_by(mask=ticket_mask).first()
                )

                if ticket is not None:
                    log.debug('found mask in Database')
                    # nothing new
                    if ticket.updated_at == ticket_updated_at:
                        log.debug('nothing new, skip')
                    else:
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

                    if (datetime.now() - ticket_updated_at).total_seconds() < 61:
                        log.debug(
                            'wait cerb_bot attach hms/billing 1min after created, skip'
                        )
                        continue

                    # get spamscore ticket
                    if os.getenv('ENABLE_SPAM_SCORE') == '1':
                        log.debug('get spamscore')
                        spamscore_list = db_session.query(SpamscoreListModel).all()
                        ticket_spamscore = self.spamscore_ticket(
                            ticket_mask, spamscore_list
                        )
                        log.debug(f'found spamscore: {ticket_spamscore}')

                    ticket = TicketModel(
                        local_id=int(ticket_local_id),
                        system_name=self.SYSTEM_NAME,
                        mask=ticket_mask,
                        group=bucket_name,
                        subject=ticket_subject,
                        url=ticket_url,
                        user=ticket_user,
                        updated_at=ticket_updated_at,
                        spam_score=ticket_spamscore,
                    )

                    log.debug('add ticket to database')
                    db_session.add(ticket)

                    # autoclose tickets
                    if os.getenv('ENABLE_AUTOCLOSE') == '1':
                        if ticket.spam_score >= int(os.getenv('AUTOCLOSE_MIN_SCORE')):
                            mark_spam = True
                            # just close, dont mark spam useless tickets from spamlist, should be score >100
                            if ticket.spam_score >= 100:
                                mark_spam = False
                            self.close_ticket(ticket.local_id, mark_spam)
                            log.info(
                                f'autoclosed ticket mask:{ticket.mask} with spam_mark:{mark_spam}, skip'
                            )
                            continue
                    log.debug('add ticket to rval')
                    tickets.append(ticket)

        return tickets

    #
    # ticket spamscore
    #
    def spamscore_ticket(
        self, ticket_mask: str, spamscore_list: list[SpamscoreListModel]
    ) -> float:
        score = 0

        try:
            ticket_html = self._req_get(
                f'{self.SYSTEM_URL}/index.php/profiles/ticket/{ticket_mask}/conversation'
            )

            # check hms/billing buttons
            # TODO: links already button to... https://cerberus.intr/index.php/profiles/ticket/KP-99687-833/conversation
            if (
                ticket_html.find('<div style="color:rgb(175,175,175);">(none)</div>')
                == -1
            ):
                log.debug(f'[spamscore][{ticket_mask}] found buttons')
                score += -99
                # force return
                return score

            # Check msg/comm count
            ticket_soup = BeautifulSoup(ticket_html, 'html.parser')
            msg_count = int(
                ticket_soup.find(
                    'button',
                    {
                        'class': 'cerb-search-trigger',
                        'data-context': 'cerberusweb.contexts.message',
                    },
                ).div.text
            )
            com_count = int(
                ticket_soup.find(
                    'button',
                    {
                        'class': 'cerb-search-trigger',
                        'data-context': 'cerberusweb.contexts.comment',
                    },
                ).div.text
            )
            log.debug(
                f'[spamscore][{ticket_mask}] messages: {msg_count}, comments: {com_count}'
            )
            if msg_count > 1 or com_count > 1:
                log.debug(f'[spamscore][{ticket_mask}] found conversation')
                score += -50
                # force return
                return score

            # get ticket id
            ticket_id = re.findall(r'ticket_id=(\d+)', ticket_html)[0]
            log.debug(f'[spamscore][{ticket_mask}] found ticket_id: {ticket_id}')
            # get conversation ticket
            ticket_msg_html = self._req_get(
                f'{self.SYSTEM_URL}/ajax.php?c=display&a=showConversation&point=cerberusweb.profiles.ticket&ticket_id={ticket_id}&expand_all=1'
            )
            # get first msg id
            ticket_msg_id = re.findall(
                r'c=profiles&a=handleSectionAction&section=ticket&action=showMessageFullHeadersPopup&id=(\d+)',
                ticket_msg_html,
            )[0]
            log.debug(f'[spamscore][{ticket_mask}] found msg_id: {ticket_msg_id}')

            # conversation soap
            ticket_msg_soap = BeautifulSoup(ticket_msg_html, 'html.parser')

            # get ticket from email
            # <b>From:</b> Temu Coupon &lt;Coupon-xmv@bestpromots.click&gt;<br>
            ticket_email = re.findall(r'<b>From:</b>.*<(.*)><br>', ticket_msg_html)[0]
            log.debug(f'[spamscore][{ticket_mask}] found ticket_email: {ticket_email}')

            # get subject
            ticket_subject = re.findall(r'<b>Subject:</b>\s(.*)<br>', ticket_msg_html)
            if len(ticket_subject) > 0:
                ticket_subject = ticket_subject[0]
                log.debug(
                    f'[spamscore][{ticket_mask}] found ticket_subject: "{ticket_subject}"'
                )
            else:
                ticket_subject = '(no subject)'
                log.debug(f'[spamscore][{ticket_mask}] not found ticket_subject')

            # get headers
            ticket_headers = self._req_get(
                f'{self.SYSTEM_URL}/ajax.php?c=profiles&a=handleSectionAction&section=ticket&action=showMessageFullHeadersPopup&id={ticket_msg_id}'
            )
            _ticket_headers = BeautifulSoup(ticket_headers, 'html.parser').textarea.text
            _ticket_headers = _ticket_headers.split('\n')
            if _ticket_headers[0] == '':
                ticket_headers = '\n'.join(_ticket_headers[1:])
            else:
                ticket_headers = '\n'.join(_ticket_headers)
            log.debug(
                f'[spamscore][{ticket_mask}] found ticket_headers: len({len(ticket_headers)})'
            )

            # get body
            ticket_body_url = re.findall(
                r'(/index.php/files/\d+/original_message.html)', ticket_msg_html
            )
            # from original_message.html
            if len(ticket_body_url) > 0:
                ticket_body = self._req_get(f'{self.SYSTEM_URL}{ticket_body_url[0]}')
                log.debug(
                    f'[spamscore][{ticket_mask}] found ticket_body from original_message: len({len(ticket_body)})'
                )
            else:
                if ticket_msg_html.find('emailBodyHtml') >= 0:
                    ticket_body = str(
                        ticket_msg_soap.find('div', {'class': 'emailBodyHtml'})
                    )
                    log.debug(
                        f'[spamscore][{ticket_mask}] found ticket_body from emailBodyHtml: len({len(ticket_body)})'
                    )
                elif ticket_msg_html.find('emailbody') >= 0:
                    ticket_body = str(
                        ticket_msg_soap.find('pre', {'class': 'emailbody'})
                    )
                    # for headers new line
                    ticket_body = f'\n{ticket_body}'
                    log.debug(
                        f'[spamscore][{ticket_mask}] found ticket_body from emailbody: len({len(ticket_body)})'
                    )
                else:
                    # not found body, pass
                    raise Exception('not found ticket_body')

            ticket_body_hash = xxh128_hexdigest(ticket_body)
            log.debug(
                f'[spamscore][{ticket_mask}] found ticket_body_hash: {ticket_body_hash}'
            )

            # Check spamscore_list
            # TODO: regex
            for data in spamscore_list:
                if (
                    ticket_email.find(str(data.email)) >= 0
                    or ticket_subject.find(str(data.subject)) >= 0
                    or ticket_body.find(str(data.body)) >= 0
                    or ticket_body_hash == data.body_hash
                ):
                    log.debug(
                        f'[spamscore][{ticket_mask}] found ticket in spamscore_list'
                    )

                    email_pass = False
                    subject_pass = False
                    body_pass = False
                    body_hash_pass = False

                    # Check email
                    if data.email is None:
                        # pass
                        email_pass = True
                    else:
                        if ticket_email.find(data.email) >= 0:
                            # pass
                            log.debug(
                                f'[spamscore][{ticket_mask}][spamlist] occurrence found email:{ticket_email} - {data.email}'
                            )
                            email_pass = True

                    # Check subject
                    if data.subject is None:
                        # pass
                        subject_pass = True
                    else:
                        if ticket_subject.find(data.subject) >= 0:
                            # pass
                            log.debug(
                                f'[spamscore][{ticket_mask}][spamlist] occurrence found subject:{ticket_subject} - {data.subject}'
                            )
                            subject_pass = True

                    # Check body
                    if data.body is None:
                        # pass
                        body_pass = True
                    else:
                        if ticket_body.find(data.body) >= 0:
                            # pass
                            log.debug(
                                f'[spamscore][{ticket_mask}][spamlist] occurrence found body: ... - {data.body}'
                            )
                            body_pass = True

                    # check body_hash
                    if data.body_hash is None:
                        # pass
                        body_hash_pass = True
                    else:
                        if ticket_body_hash == data.body_hash:
                            # pass
                            log.debug(
                                f'[spamscore][{ticket_mask}][spamlist] occurrence found body_hash: {ticket_body_hash} - {data.body_hash}'
                            )
                            body_hash_pass = True

                    if (
                        email_pass is True
                        and subject_pass is True
                        and body_pass is True
                        and body_hash_pass is True
                    ):
                        log.debug(
                            f'[spamscore][{ticket_mask}] found ticket in spamscore_list, score:{data.score} comment:{data.comment}'
                        )
                        score += data.score

                        # dont need another check
                        break

            # Cerb score
            cerb_spam_score = re.findall(
                r'<b>Spam Score:</b>\n\t(\d+\.\d+)', ticket_html
            )
            if len(cerb_spam_score) > 0:
                cerb_spam_score = float(cerb_spam_score[0])
                log.debug(
                    f'[spamscore][{ticket_mask}] cerb spam_score: {cerb_spam_score}'
                )
                if cerb_spam_score == 99.99:
                    score += 1
                elif cerb_spam_score >= 99:
                    score += 0.5

            # rspamd score
            if os.getenv('ENABLE_RSPAMD') == '1':
                ticket_eml = f'{ticket_headers}{ticket_body}'

                try:
                    rspamd_score = requests.post(
                        os.getenv('RSPAMD_API_URL'), data=ticket_eml
                    ).json()
                    log.debug(f'[spamscore][{ticket_mask}] rspamd resp: {rspamd_score}')
                    rspamd_score = rspamd_score['score']
                    score += rspamd_score
                    log.debug(
                        f'[spamscore][{ticket_mask}] rspamd score: {rspamd_score}'
                    )
                except Exception as e:
                    log.error(f'[spamscore][{ticket_mask}] rspamd score error: {e}')

        except Exception as e:
            log.error(f'[spamscore][{ticket_mask}] error: {e}')
            return 0

        return score

    #
    # Close ticket
    #
    def close_ticket(self, ticket_id: int, mark_spam: bool = False) -> None:
        self._req_post(
            url=f'{self.SYSTEM_URL}/index.php/',
            data={
                'c': 'display',
                'a': 'updateProperties',
                'id': ticket_id,
                'status_id': 2 if mark_spam is False else 0,
                'spam': 0 if mark_spam is False else 1,
            },
        )

    #
    # Get request
    #
    def _req_get(self, url: str) -> str:
        log.debug(f'get request: {url}')
        resp = requests.get(
            url=url,
            headers={
                'cookie': f'Devblocks={self.AUTH_TOKEN}',
                'user-agent': self.USER_AGENT,
            },
            verify=self.CERT_PATH,
        )

        if resp.status_code != 200:
            raise Exception(f'wrong status_code from response {url}')

        return resp.text

    #
    # Post request
    #
    def _req_post(self, url: str, data: list) -> str:
        log.debug(f'post request: {url} with data: {data}')
        resp = requests.post(
            url=url,
            data=data,
            headers={
                'cookie': f'Devblocks={self.AUTH_TOKEN}',
                'user-agent': self.USER_AGENT,
            },
            verify=self.CERT_PATH,
        )

        if resp.status_code != 200:
            raise Exception(f'wrong status_code from response {url}')

        return resp.text
