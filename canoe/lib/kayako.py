import base64
import hmac
import random
import requests
from xml.etree import ElementTree
from requests.auth import AuthBase
from urllib.parse import urlsplit, parse_qsl, urlencode


class KayakoAuth(AuthBase):

    def __init__(self, api_key, secret_key):
        self._api_key = api_key
        self._secret_key = secret_key.encode('utf-8')

    def __call__(self, request):
        salt = str(random.getrandbits(32)).encode('utf-8')
        digest = hmac.digest(self._secret_key, msg=salt, digest='sha256')
        signature = base64.encodebytes(digest).replace(b'\n', b'')

        url_split = urlsplit(request.url)
        query = dict(parse_qsl(url_split.query))
        query['apikey'] = self._api_key
        query['salt'] = salt
        query['signature'] = signature
        auth_url_split = url_split._replace(query=urlencode(query))
        request.url = auth_url_split.geturl()
        return request


class Kayako:

    def __init__(self, url, api_key, secret_key):
        self._url = url
        self._session = requests.Session()
        self._session.auth = KayakoAuth(api_key, secret_key)

    def list_departments(self):
        text = self.request('get', '/Base/Department')
        return ElementTree.fromstring(text)

    def list_open_tickets(self, department_id):
        action = f'/Tickets/Ticket/ListAll/{department_id}/1/-1/-1/-1/-1/ticketid/ASC'
        text = self.request('get', action)
        return ElementTree.fromstring(text)

    def get_ticket(self, ticket_id):
        action = f'/Tickets/Ticket/{ticket_id}'
        text = self.request('get', action)
        return ElementTree.fromstring(text)

    def request(self, method, action, params=None, **kwargs):
        params = params or {}
        params['e'] = action
        response = self._session.request(
            method, self._url, params=params, **kwargs)
        response.raise_for_status()
        return response.text
