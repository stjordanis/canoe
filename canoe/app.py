import boto3
import json
import os
import logging
import sys
import bisect
import itertools

import slack

from xml.etree import ElementTree

CWD = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(CWD, 'lib'))

from kayako import Kayako       # noqa: E402

LOG_LEVEL = logging.INFO
boto3.set_stream_logger('', LOG_LEVEL)
logger = logging.getLogger()
logger.setLevel(LOG_LEVEL)

# Global variables are reused across execution contexts (if available)
session = boto3.Session()
s3 = session.client('s3')

kayako = Kayako(os.getenv('CANOE_KAYAKO_API_URL'),
                os.getenv('CANOE_KAYAKO_API_KEY'),
                os.getenv('CANOE_KAYAKO_SECRET_KEY'))

SLACK_CHANNEL_ID = os.getenv('CANOE_SLACK_CHANNEL_ID')
slack_client = slack.WebClient(token=os.getenv('CANOE_SLACK_API_TOKEN'))


def seed_handler(event, context):
    if event.get('type', None) != 'seed':
        logger.warning(f'unexpected event: {event}')
        return

    project_name = os.getenv('CANOE_ROOT_PROJECT_NAME')
    dep_ids = list_children_department_ids(kayako, project_name)
    queue_url = os.getenv('CANOE_CHECK_DEPARTMENT_QUEUE_URL')
    sqs = session.resource('sqs')
    queue = sqs.Queue(queue_url)
    messages = sqs_messages(dep_ids)
    if not messages:
        logger.warning('no messages to send')
        return

    send_messages(queue, messages)


def send_messages(queue, items, batch_size=10):
    iter_items = [iter(items)] * batch_size
    for batch in itertools.zip_longest(*iter_items, fillvalue=None):
        batch = list(filter(None, batch))
        queue.send_messages(Entries=batch)


def distribute_departments_tickets_handler(event, context):
    ticket_ids = []

    for record in event['Records']:
        message = json.loads(record['body'])
        department_id = message['department_id']
        tickets = kayako.list_open_tickets(department_id)
        for ticket in tickets.findall('.//ticket'):
            ticket_id = ticket.get('id')
            ticket_ids.append(ticket_id)

    queue_url = os.getenv('CANOE_CHECK_TICKET_QUEUE_URL')
    sqs = session.resource('sqs')
    queue = sqs.Queue(queue_url)
    messages = check_ticket_messages(ticket_ids)
    send_messages(queue, messages)


def list_children_department_ids(kayako, project_name):
    departments = kayako.list_departments()
    parent_el_ids = departments.findall(f".//department/title[.='{project_name}']../id")
    for parent_el_id in parent_el_ids:
        xpath = f".//department/parentdepartmentid[.='{parent_el_id.text}']../id"
        for dep_id_el in departments.findall(xpath):
            yield dep_id_el.text


def check_ticket_handler(event, context):
    tickets_updates = []
    for record in event['Records']:
        message = json.loads(record['body'])
        ticket_id = message['ticket_id']

        state = get_ticket_state(ticket_id)
        ticket = kayako.get_ticket(ticket_id)
        new_posts = diff_new_posts(ticket, state)
        updates = list(ticket_updates(ticket_id, ticket, new_posts))
        tickets_updates.extend(updates)
        if updates:
            save_ticket_state(ticket_id, ticket)

    if not is_in_learning_mode():
        queue_url = os.getenv('CANOE_TICKETS_UPDATES_QUEUE_URL')
        sqs = session.resource('sqs')
        queue = sqs.Queue(queue_url)
        messages = tickets_updates_messages(tickets_updates)
        send_messages(queue, messages)


def is_in_learning_mode():
    return os.getenv('CANOE_LEARNING_MODE') == 'true'


def updates_notifications_handler(event, context):
    for record in event['Records']:
        body = json.loads(record['body'])
        if body['type'] == 'new_post':
            new_post = body['object']
            text = message_text(new_post)
            blocks = message_blocks(new_post)
            slack_client.chat_postMessage(
                channel=SLACK_CHANNEL_ID,
                text=text,
                blocks=blocks)


def message_text(new_post):
    tmpl = ('[{displayid}]: {subject}\n'
            '@here {fullname} left a comment on a ticket')
    return tmpl.format(**new_post)


def message_blocks(new_post):
    portal_uri = os.getenv('CANOE_KAYAKO_UI_URL')
    ticket_link = '{portal_uri}?/Tickets/Ticket/View/{ticket_id}'.format(
        portal_uri=portal_uri, **new_post)
    return [
	{
	    'type': 'section',
	    'text': {
		'type': 'mrkdwn',
		'text': '<{link}|[{displayid}]: {subject}>'.format(link=ticket_link, **new_post)
	    }
	},
	{
	    'type': 'section',
	    'text': {
		'type': 'mrkdwn',
		'text': '@here {fullname} left a comment on a ticket'.format(**new_post)
	    }
	}
    ]


def save_ticket_state(ticket_id, ticket):
    bucket = tickets_state_bucket()
    key = ticket_state_key(ticket_id)
    xml = ElementTree.tostring(ticket, encoding="utf-8")
    s3.put_object(Bucket=bucket, Key=key, Body=xml)


def diff_new_posts(ticket, state):
    state_dateline = latest_post_dateline(state)
    posts = ticket.findall('.//posts/post')
    datelines = [int(post.find('dateline').text) for post in posts]
    datelined_posts = list(zip(datelines, posts))
    datelined_posts.sort(key=lambda p: p[0])
    datelines, posts = zip(*datelined_posts)
    pos = bisect.bisect_right(datelines, state_dateline)
    return posts[pos:]


def ticket_updates(ticket_id, ticket, posts):
    fields = ['displayid', 'userorganization', 'subject']
    update_base = extract_fields(ticket, fields, './/ticket/{}')
    update_base['ticket_id'] = ticket_id
    for post in posts:
        ticket_fields = ['dateline', 'fullname', 'email', 'contents']
        ticket_update = extract_fields(post, ticket_fields)
        ticket_update.update(update_base)
        yield ticket_update


def extract_fields(element, fields, path_tmpl=None):
    path_fn = lambda p: path_tmpl.format(p) if path_tmpl else p
    return {field: element.find(path_fn(field)).text for field in fields}


def latest_post_dateline(state):
    if not state:
        return 0

    dateline_els = state.findall('.//post/dateline')
    return max([int(dl.text) for dl in dateline_els])


def get_ticket_state(ticket_id):
    state = read_ticket_state(ticket_id)
    if state:
        return ElementTree.parse(state)


def read_ticket_state(ticket_id):
    key = ticket_state_key(ticket_id)
    bucket = tickets_state_bucket()

    try:
        s3_object = s3.get_object(Bucket=bucket, Key=key)
        return s3_object['Body']
    except s3.exceptions.NoSuchKey:
        logger.info(f'No state found {bucket}/{key}')


def ticket_state_key(ticket_id):
    return f'tickets/{ticket_id}.xml'


def tickets_state_bucket():
    return os.getenv('CANOE_TICKETS_STATE_BUCKET')


def sqs_messages(department_ids):
    return [
        {
            'Id': dep_id,
            'MessageBody': json.dumps({'department_id': dep_id})
        }
        for dep_id in department_ids
    ]


def check_ticket_messages(ticket_ids):
    return [
        {
            'Id': ticket_id,
            'MessageBody': json.dumps({'ticket_id': ticket_id})
        }
        for ticket_id in ticket_ids
    ]


def tickets_updates_messages(updates):
    return [
        {
            'Id': str(index),
            'MessageBody': json.dumps({
                'type': 'new_post',
                'object': update
            })
        }
        for index, update in enumerate(updates)
    ]
