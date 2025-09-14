import requests

from app.models import Ticket as TicketModel
from app.notification.base import BaseClass


class Telegram(BaseClass):
    BOT_TOKEN = str
    CHAT_ID = str

    def __init__(self, token: str, chat_id: int):
        self.BOT_TOKEN = token
        self.CHAT_ID = chat_id

    def notify(self, ticket: TicketModel) -> None:
        data = {
            'chat_id': self.CHAT_ID,
            'text': f'{ticket.system_name}/{ticket.group}\n<a href="{ticket.url}">{ticket.subject}</a>',
            'parse_mode': 'HTML',
            #'disable_notification': 'true',
            #'silent': 'true'
        }

        requests.post(
            f'https://api.telegram.org/bot{self.BOT_TOKEN}/sendMessage', data=data
        )
