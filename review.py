"""Optional calendar-day review recommendations; never a limit on studying."""
import json
import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from storage import db, using_postgres

RATINGS = {'again', 'hard', 'good', 'easy'}
INTERVALS = (1, 3, 7, 14, 30, 60, 90)


class ReviewError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def today_in_zone(name='UTC'):
    try:
        zone = ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise ReviewError('La zona horaria no es válida.') from None
    return datetime.now(timezone.utc).astimezone(zone).date()


def empty_progress():
    return dict(revision=None, due_on=None, interval_days=0, success_days=0,
                first_success_on=None, last_success_on=None, difficult_on=None,
                last_review_on=None, last_rating=None)


def progress_view(state, today):
    day = today.isoformat()
    consolidated = bool(state['success_days'] >= 3 and state['first_success_on']
                        and (date.fromisoformat(state['last_success_on']) -
                             date.fromisoformat(state['first_success_on'])).days >= 7)
    if consolidated:
        status = 'consolidated'
    elif state['last_review_on'] == day and state['last_rating'] in ('good', 'easy'):
        status = 'learned_today'
    elif state['last_review_on']:
        status = 'learning'
    else:
        status = 'new'
    return dict(state, status=status, due=not state['due_on'] or state['due_on'] <= day)


def next_progress(previous, rating, today, event_id):
    state = dict(previous)
    day = today.isoformat()
    if rating in ('again', 'hard'):
        state.update(due_on=day, interval_days=0, success_days=0,
                     first_success_on=None, last_success_on=None, difficult_on=day)
    elif (not state['due_on'] or state['due_on'] <= day) and state['last_success_on'] != day:
        # Only a due recall on a new day earns another step. Extra practice
        # cannot postpone a due date or create mastery in one sitting.
        state['success_days'] += 1
        state['first_success_on'] = state['first_success_on'] or day
        state['last_success_on'] = day
        step = state['success_days'] - 1
        if rating == 'easy' and state['difficult_on'] != day:
            step += 1
        interval = INTERVALS[min(step, len(INTERVALS) - 1)]
        state.update(interval_days=interval, due_on=(today + timedelta(days=interval)).isoformat())
    state.update(revision=event_id, last_rating=rating, last_review_on=day)
    return state


def progress_for_deck(connection, key, today):
    return {row['id']: progress_view(json.loads(row['state']) if row['state'] else empty_progress(), today)
            for row in connection.execute('SELECT cards.id,card_progress.state FROM cards '
                'LEFT JOIN card_progress ON card_progress.card_id=cards.id WHERE cards.deck=?', (key,))}


def deck_summaries(connection, today, library=None):
    summaries = {}
    query = ('SELECT cards.deck,card_progress.state FROM cards '
             'LEFT JOIN card_progress ON card_progress.card_id=cards.id')
    parameters = ()
    if library is not None:
        query += (" LEFT JOIN deck_libraries ON deck_libraries.deck_id=cards.deck"
                  " WHERE COALESCE(deck_libraries.library_id,'main')=?")
        parameters = (library,)
    for row in connection.execute(query, parameters):
        summary = summaries.setdefault(row['deck'], dict(new=0, due=0, learned_today=0, learning=0,
                                                        consolidated=0, next_due=None))
        state = progress_view(json.loads(row['state']) if row['state'] else empty_progress(), today)
        summary[state['status']] += 1
        if state['status'] != 'new' and state['due']:
            summary['due'] += 1
        due = state['due_on']
        if due and due > today.isoformat() and (not summary['next_due'] or due < summary['next_due']):
            summary['next_due'] = due
    return summaries


def lock_card(connection, deck, card):
    if not using_postgres():
        connection.execute('BEGIN IMMEDIATE')
    suffix = ' FOR UPDATE' if using_postgres() else ''
    if not connection.execute('SELECT id FROM cards WHERE id=? AND deck=?' + suffix, (card, deck)).fetchone():
        raise ReviewError('La tarjeta ya no existe en este mazo.', 404)


def read_progress(connection, card):
    row = connection.execute('SELECT state FROM card_progress WHERE card_id=?', (card,)).fetchone()
    return json.loads(row['state']) if row else empty_progress()


def write_progress(connection, card, state):
    connection.execute('INSERT INTO card_progress (card_id,state) VALUES (?,?) '
                       'ON CONFLICT (card_id) DO UPDATE SET state=excluded.state', (card, json.dumps(state)))


def record_review(deck, card, body):
    if not isinstance(body, dict):
        raise ReviewError('La calificación no es válida.')
    rating, event_id = body.get('rating'), body.get('event_id')
    if not isinstance(rating, str) or rating not in RATINGS or not isinstance(event_id, str) or not re.fullmatch(r'[a-f0-9]{32}', event_id):
        raise ReviewError('La calificación no es válida.')
    if 'expected_revision' not in body:
        raise ReviewError('Falta la versión del progreso. Vuelve a abrir el mazo.')
    today = today_in_zone(body.get('timezone', 'UTC'))
    with db() as connection:
        lock_card(connection, deck, card)
        state = read_progress(connection, card)
        existing = connection.execute('SELECT * FROM review_events WHERE id=?', (event_id,)).fetchone()
        if existing:
            if (existing['card_id'] != card or existing['rating'] != rating or
                    json.loads(existing['previous_state'])['revision'] != body['expected_revision']):
                raise ReviewError('Este intento pertenece a otra calificación.', 409)
            # Retrying a request after a lost response must not count twice.
            if existing['undone'] or state['revision'] != event_id:
                raise ReviewError('El progreso cambió. Vuelve a abrir el mazo para actualizarlo.', 409)
        else:
            if state['revision'] != body['expected_revision']:
                raise ReviewError('El progreso cambió en otra sesión. Vuelve a abrir el mazo para actualizarlo.', 409)
            previous = state
            state = next_progress(previous, rating, today, event_id)
            connection.execute('INSERT INTO review_events (id,card_id,rating,previous_state,undone) '
                               'VALUES (?,?,?,?,0)', (event_id, card, rating, json.dumps(previous)))
            write_progress(connection, card, state)
    return dict(progress=progress_view(state, today), today=today.isoformat())


def undo_review(deck, card, event_id, body):
    if not isinstance(body, dict):
        raise ReviewError('La solicitud no es válida.')
    today = today_in_zone(body.get('timezone', 'UTC'))
    with db() as connection:
        lock_card(connection, deck, card)
        state = read_progress(connection, card)
        event = connection.execute('SELECT * FROM review_events WHERE id=? AND card_id=?', (event_id, card)).fetchone()
        if not event:
            raise ReviewError('No se encontró la calificación que quieres deshacer.', 404)
        previous = json.loads(event['previous_state'])
        expected = previous['revision'] if event['undone'] else event_id
        if state['revision'] != expected:
            raise ReviewError('Hay un repaso más reciente. Vuelve a abrir el mazo para actualizarlo.', 409)
        if not event['undone']:
            write_progress(connection, card, previous)
            connection.execute('UPDATE review_events SET undone=1 WHERE id=?', (event_id,))
        state = previous
    return dict(progress=progress_view(state, today), today=today.isoformat())
