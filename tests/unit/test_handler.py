# coding: utf-8

import io
import pytest
from unittest.mock import Mock
import xml.etree.ElementTree as ElementTree


from canoe import app


@pytest.fixture()
def kayako():
    client = Mock()
    departments = """<?xml version="1.0" encoding="UTF-8"?>
    <departments>
        <department>
            <id><![CDATA[1]]></id>
            <title><![CDATA[Project Name]]></title>
        </department>
        <department>
            <id><![CDATA[2]]></id>
            <title><![CDATA[Customer 2]]></title>
            <parentdepartmentid><![CDATA[1]]></parentdepartmentid>
        </department>
        <department>
            <id><![CDATA[3]]></id>
            <title><![CDATA[Customer 3]]></title>
            <parentdepartmentid><![CDATA[1]]></parentdepartmentid>
        </department>
        <department>
            <id><![CDATA[4]]></id>
            <title><![CDATA[Customer 4]]></title>
            <parentdepartmentid><![CDATA[1]]></parentdepartmentid>
        </department>
    </departments>
    """
    client.list_departments.return_value = ElementTree.fromstring(departments)
    tickets = """<?xml version="1.0" encoding="UTF-8"?>
        <tickets>
        <ticket id="273" flagtype="5">
            <displayid><![CDATA[MAB-597-12345]]></displayid>
        </ticket>
        <ticket id="274" flagtype="5">
            <displayid><![CDATA[JAB-293-54321]]></displayid>
        </ticket>
    </tickets>
    """
    client.list_open_tickets.return_value = ElementTree.fromstring(tickets)
    posts = """<?xml version="1.0" encoding="UTF-8"?>
    <tickets>
        <ticket id="277" flagtype="5">
            <displayid><![CDATA[CYA-293-12345]]></displayid>
            <departmentid><![CDATA[20]]></departmentid>
            <userorganization><![CDATA[Customer Name]]></userorganization>
            <ownerstaffname><![CDATA[Staff Owner]]></ownerstaffname>
            <fullname><![CDATA[Customer]]></fullname>
            <email><![CDATA[customer-email@example.com]]></email>
            <subject><![CDATA[Mayday Mayday]]></subject>
            <posts>
                <post>
                    <id><![CDATA[3]]></id>
                    <ticketpostid><![CDATA[1496]]></ticketpostid>
                    <ticketid><![CDATA[277]]></ticketid>
                    <dateline><![CDATA[1552419863]]></dateline>
                    <fullname><![CDATA[Sender FullName (customer)]]></fullname>
                    <email><![CDATA[customer-email@customer.com]]></email>
                    <contents><![CDATA[Thanks mate

                    ]]></contents>
                </post>
                <post>
                    <id><![CDATA[2]]></id>
                    <ticketpostid><![CDATA[1495]]></ticketpostid>
                    <ticketid><![CDATA[277]]></ticketid>
                    <dateline><![CDATA[1552418863]]></dateline>
                    <fullname><![CDATA[Sender FullName]]></fullname>
                    <email><![CDATA[sender-email@example.com]]></email>
                    <contents><![CDATA[Any time!

                    Thank you,
                    Your support

                    ]]></contents>
                </post>
                <post>
                    <id><![CDATA[1]]></id>
                    <ticketpostid><![CDATA[1488]]></ticketpostid>
                    <ticketid><![CDATA[277]]></ticketid>
                    <dateline><![CDATA[1552317114]]></dateline>
                    <fullname><![CDATA[Sender FullName (customer)]]></fullname>
                    <email><![CDATA[sender-email@customer.com]]></email>
                    <contents><![CDATA[This fixed it,

                    Thank you!

                    ]]></contents>
                </post>
            </posts>
        </ticket>
    </tickets>
    """
    client.get_ticket.return_value = ElementTree.fromstring(posts)
    return client


@pytest.fixture()
def slack(monkeypatch):
    client = Mock()
    monkeypatch.setattr('canoe.app.slack_client', client)
    return client


@pytest.fixture()
def seed_event():
    return {'type': 'seed'}


@pytest.fixture()
def context():
    return {}


def test_list_children_department_ids(kayako):
    ids = app.list_children_department_ids(kayako, 'Project Name')
    assert ['2', '3', '4'] == list(ids)


def test_seed_handler(seed_event, context, kayako, monkeypatch):
    session = Mock()
    monkeypatch.setattr('canoe.app.session', session)
    sqs = session.resource.return_value
    queue = sqs.Queue.return_value
    monkeypatch.setattr('canoe.app.kayako', kayako)
    monkeypatch.setenv('CANOE_ROOT_PROJECT_NAME', 'Project Name')
    app.seed_handler(seed_event, context)
    queue.send_messages.assert_called_with(
        Entries=[
            {'Id': '2', 'MessageBody': '{"department_id": "2"}'},
            {'Id': '3', 'MessageBody': '{"department_id": "3"}'},
            {'Id': '4', 'MessageBody': '{"department_id": "4"}'}
        ]
    )


@pytest.fixture()
def sqs_departments_event():
    return {
        'Records': [
            {
                'body': '{"department_id": "2"}',
            }
        ]
    }


def test_distribute_departments_tickets_handler(
        sqs_departments_event, context, kayako, monkeypatch):
    session = Mock()
    monkeypatch.setattr('canoe.app.session', session)
    sqs = session.resource.return_value
    queue = sqs.Queue.return_value
    monkeypatch.setattr('canoe.app.kayako', kayako)
    app.distribute_departments_tickets_handler(sqs_departments_event, context)
    queue.send_messages.assert_called_with(
        Entries=[
            {'Id': '273', 'MessageBody': '{"ticket_id": "273"}'},
            {'Id': '274', 'MessageBody': '{"ticket_id": "274"}'}
        ]
    )


@pytest.fixture()
def sqs_check_tickets_event():
    return {
        'Records': [
            {
                'body': '{"ticket_id": "273"}',
            }
        ]
    }


def test_check_ticket_handler(
        sqs_check_tickets_event, context, kayako, monkeypatch):
    s3 = Mock()
    monkeypatch.setattr('canoe.app.s3', s3)
    state = """<?xml version="1.0" encoding="UTF-8"?>
    <tickets>
        <ticket id="277" flagtype="5">
            <displayid><![CDATA[CYA-293-12345]]></displayid>
            <departmentid><![CDATA[20]]></departmentid>
            <userorganization><![CDATA[Customer Name]]></userorganization>
            <ownerstaffname><![CDATA[Staff Owner]]></ownerstaffname>
            <fullname><![CDATA[Customer]]></fullname>
            <email><![CDATA[customer-email@example.com]]></email>
            <subject><![CDATA[Mayday Mayday]]></subject>
            <posts>
                <post>
                    <id><![CDATA[2]]></id>
                    <ticketpostid><![CDATA[1495]]></ticketpostid>
                    <ticketid><![CDATA[277]]></ticketid>
                    <dateline><![CDATA[1552418863]]></dateline>
                    <fullname><![CDATA[Sender FullName]]></fullname>
                    <email><![CDATA[sender-email@example.com]]></email>
                    <contents><![CDATA[Any time!

                    Thank you,
                    Your support

                    ]]></contents>
                </post>
                <post>
                    <id><![CDATA[1]]></id>
                    <ticketpostid><![CDATA[1488]]></ticketpostid>
                    <ticketid><![CDATA[277]]></ticketid>
                    <dateline><![CDATA[1552317114]]></dateline>
                    <fullname><![CDATA[Sender FullName (customer)]]></fullname>
                    <email><![CDATA[sender-email@customer.com]]></email>
                    <contents><![CDATA[This fixed it,

                    Thank you!

                    ]]></contents>
                </post>
            </posts>
        </ticket>
    </tickets>
    """
    s3_obj = {'Body': io.StringIO(state)}
    s3.get_object.return_value = s3_obj
    session = Mock()
    monkeypatch.setattr('canoe.app.session', session)
    sqs = session.resource.return_value
    queue = sqs.Queue.return_value
    monkeypatch.setattr('canoe.app.kayako', kayako)
    app.check_ticket_handler(sqs_check_tickets_event, context)
    queue.send_messages.assert_called_with(
        Entries=[
            {
                'Id': '0',
                'MessageBody': '{"type": "new_post", "object": {"dateline": "1552419863", "fullname": "Sender FullName (customer)", "email": "customer-email@customer.com", "contents": "Thanks mate\\n\\n                    ", "displayid": "CYA-293-12345", "userorganization": "Customer Name", "subject": "Mayday Mayday", "ticket_id": "273"}}'  # noqa: E501
            }
        ]
    )


def test_diff_new_posts_empty_state():
    posts = """<?xml version="1.0" encoding="UTF-8"?>
    <tickets>
        <ticket>
            <posts>
                <post>
                    <ticketpostid><![CDATA[1496]]></ticketpostid>
                    <dateline><![CDATA[1552419863]]></dateline>
                </post>
                <post>
                    <ticketpostid><![CDATA[1495]]></ticketpostid>
                    <dateline><![CDATA[1552418863]]></dateline>
                </post>
                <post>
                    <ticketpostid><![CDATA[1488]]></ticketpostid>
                    <dateline><![CDATA[1552317114]]></dateline>
                </post>
            </posts>
        </ticket>
    </tickets>
    """
    diff = app.diff_new_posts(ElementTree.fromstring(posts), None)
    diff_xml = [ElementTree.tostring(el, encoding="unicode") for el in diff]
    assert diff_xml == [
        '<post>\n'
        '                    <ticketpostid>1488</ticketpostid>\n'
        '                    <dateline>1552317114</dateline>\n'
        '                </post>\n'
        '            ',
        '<post>\n'
        '                    <ticketpostid>1495</ticketpostid>\n'
        '                    <dateline>1552418863</dateline>\n'
        '                </post>\n'
        '                ',
        '<post>\n'
        '                    <ticketpostid>1496</ticketpostid>\n'
        '                    <dateline>1552419863</dateline>\n'
        '                </post>\n'
        '                '
    ]


def test_diff_new_posts_empty_many_items():
    posts = """<?xml version="1.0" encoding="UTF-8"?>
    <tickets>
        <ticket>
            <posts>
                <post>
                    <ticketpostid><![CDATA[1496]]></ticketpostid>
                    <dateline><![CDATA[1552419863]]></dateline>
                </post>
                <post>
                    <ticketpostid><![CDATA[1495]]></ticketpostid>
                    <dateline><![CDATA[1552418863]]></dateline>
                </post>
                <post>
                    <ticketpostid><![CDATA[1488]]></ticketpostid>
                    <dateline><![CDATA[1552317114]]></dateline>
                </post>
            </posts>
        </ticket>
    </tickets>
    """
    state = """<?xml version="1.0" encoding="UTF-8"?>
    <tickets>
        <ticket>
            <posts>
                <post>
                    <ticketpostid><![CDATA[1488]]></ticketpostid>
                    <dateline><![CDATA[1552317114]]></dateline>
                </post>
            </posts>
        </ticket>
    </tickets>
    """
    diff = app.diff_new_posts(ElementTree.fromstring(posts), ElementTree.fromstring(state))
    diff_xml = [ElementTree.tostring(el, encoding="unicode") for el in diff]
    assert diff_xml == [
        '<post>\n'
        '                    <ticketpostid>1495</ticketpostid>\n'
        '                    <dateline>1552418863</dateline>\n'
        '                </post>\n'
        '                ',
        '<post>\n'
        '                    <ticketpostid>1496</ticketpostid>\n'
        '                    <dateline>1552419863</dateline>\n'
        '                </post>\n'
        '                '
    ]


@pytest.fixture()
def updates_event():
    return {
        'Records': [
            {
                'body': '{"type": "new_post", "object": {"dateline": "1552419863", "fullname": "Sender FullName (customer)", "email": "customer-email@customer.com", "contents": "Thanks mate\\n\\n                    ", "displayid": "CYA-293-12345", "userorganization": "Customer Name", "subject": "Mayday Mayday", "ticket_id": "273"}}'  # noqa: E501
            }
        ]
    }


def test_updates_notifications_handler(monkeypatch, slack, updates_event, context):
    app.updates_notifications_handler(updates_event, context)
    slack.chat_postMessage.assert_called_with(
        channel='PROJECTID',
        text='[CYA-293-12345]: Mayday Mayday\n@here Sender FullName (customer) left a comment on a ticket',
        blocks=[
            {
                'type': 'section',
                'text': {
                    'type': 'mrkdwn',
                    'text': '<https://kayako-srv.com?/Tickets/Ticket/View/273|[CYA-293-12345]: Mayday Mayday>'
                }
            },
            {
                'type': 'section',
                'text': {
                    'type': 'mrkdwn',
                    'text': '@here Sender FullName (customer) left a comment on a ticket'
                }
            }
        ]
    )
