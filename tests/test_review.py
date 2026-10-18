import json
import os
import unittest
import uuid
from datetime import date, datetime, timezone
from unittest.mock import patch

from test_config import configure_test_database
configure_test_database()
from app import app
from storage import db, initialize_storage
from review import empty_progress, next_progress, progress_view, today_in_zone, ReviewError


class Scheduling(unittest.TestCase):
    def grade(self, state, rating, day):
        return next_progress(state, rating, date.fromisoformat(day), uuid.uuid4().hex)

    def test_extra_practice_does_not_create_mastery_or_delay_due_date(self):
        state = self.grade(empty_progress(), 'good', '2026-01-01')
        self.assertEqual(state['due_on'], '2026-01-02')
        for _ in range(20):
            state = self.grade(state, 'easy', '2026-01-01')
        self.assertEqual(state['success_days'], 1)
        self.assertEqual(state['due_on'], '2026-01-02')
        self.assertEqual(progress_view(state, date(2026, 1, 1))['status'], 'learned_today')
        state = self.grade(state, 'good', '2026-01-02')
        self.assertEqual(state['due_on'], '2026-01-05')
        state = self.grade(state, 'easy', '2026-01-03')
        self.assertEqual(state['success_days'], 2)
        self.assertEqual(state['due_on'], '2026-01-05')

    def test_mastery_requires_separate_due_days_and_at_least_one_week(self):
        state = empty_progress()
        for day in ('2026-01-01', '2026-01-02', '2026-01-05'):
            state = self.grade(state, 'good', day)
            self.assertNotEqual(progress_view(state, date.fromisoformat(day))['status'], 'consolidated')
        self.assertEqual(state['due_on'], '2026-01-12')
        state = self.grade(state, 'good', '2026-01-12')
        self.assertEqual(progress_view(state, date(2026, 1, 12))['status'], 'consolidated')
        self.assertEqual(state['due_on'], '2026-01-26')
        for rating in ('again', 'hard'):
            difficult = self.grade(state, rating, '2026-01-12')
            self.assertEqual(progress_view(difficult, date(2026, 1, 12))['status'], 'learning')
            self.assertEqual(difficult['success_days'], 0)
            retry = self.grade(difficult, 'easy', '2026-01-12')
            self.assertEqual(retry['due_on'], '2026-01-13')
            self.assertEqual(retry['success_days'], 1)

    def test_easy_changes_interval_but_never_grants_instant_mastery(self):
        state = self.grade(empty_progress(), 'easy', '2026-01-01')
        self.assertEqual(state['due_on'], '2026-01-04')
        self.assertEqual(progress_view(state, date(2026, 1, 1))['status'], 'learned_today')
        self.assertEqual(progress_view(state, date(2026, 1, 2))['status'], 'learning')
        self.assertFalse(progress_view(state, date(2026, 1, 2))['due'])
        state = self.grade(state, 'easy', '2026-01-04')
        state = self.grade(state, 'easy', '2026-01-11')
        self.assertEqual(progress_view(state, date(2026, 1, 11))['status'], 'consolidated')
        self.assertTrue(progress_view(state, date(2026, 2, 11))['due'])

    def test_local_day_comes_from_server_time_and_browser_timezone(self):
        with patch('review.datetime') as clock:
            clock.now.return_value = datetime(2026, 1, 2, 2, 0, tzinfo=timezone.utc)
            self.assertEqual(today_in_zone('America/Lima'), date(2026, 1, 1))
            self.assertEqual(today_in_zone('Asia/Tokyo'), date(2026, 1, 2))
        for zone in ('missing/example', '/etc/passwd', None, {}):
            with self.assertRaises(ReviewError):
                today_in_zone(zone)


class PersistentReviews(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.deck = self.client.post('/api/decks', json={'name': 'Repasos'}).json['id']
        self.client.post(f'/api/decks/{self.deck}/cards', json={'front': 'Pregunta', 'back': 'Respuesta'})
        self.card = self.client.get(f'/api/decks/{self.deck}/cards').json[0]['id']
        self.url = f'/api/decks/{self.deck}/cards/{self.card}/reviews'
        self.clock = patch('review.today_in_zone', return_value=date(2026, 1, 1))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.app_clock = patch('app.today_in_zone', return_value=date(2026, 1, 1))
        self.app_clock.start()
        self.addCleanup(self.app_clock.stop)

    def body(self, revision=None, rating='good'):
        return dict(event_id=uuid.uuid4().hex, expected_revision=revision, rating=rating, timezone='America/Lima')

    def progress(self):
        return self.client.get(f'/api/decks/{self.deck}/study').json['cards'][0]['progress']

    def test_grade_persists_after_reinitialization_and_retries_do_not_duplicate(self):
        body = self.body()
        response = self.client.post(self.url, json=body)
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual(response.json['progress']['status'], 'learned_today')
        initialize_storage()
        self.client = app.test_client()
        self.assertEqual(self.progress(), response.json['progress'])
        self.assertEqual(self.client.post(self.url, json=body).json, response.json)
        with db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM review_events WHERE card_id=?', (self.card,)).fetchone()[0], 1)
        summary = next(d['review'] for d in self.client.get('/api/decks').json if d['id'] == self.deck)
        self.assertEqual(summary['learned_today'], 1)
        self.assertEqual(summary['consolidated'], 0)
        self.assertEqual(summary['due'], 0)
        self.assertEqual(summary['next_due'], '2026-01-02')

    def test_undo_restores_schedule_mastery_and_allows_multiple_undos(self):
        initial = self.progress()
        first = self.body(rating='easy')
        saved = self.client.post(self.url, json=first).json['progress']
        second = self.body(saved['revision'], 'hard')
        self.assertEqual(self.client.post(self.url, json=second).status_code, 200)
        self.assertTrue(self.progress()['due'])
        for body, expected in ((second, saved), (first, initial)):
            undo_url = self.url + '/' + body['event_id'] + '/undo'
            for _ in range(2):
                response = self.client.post(undo_url, json={})
                self.assertEqual(response.status_code, 200, response.json)
                self.assertEqual(response.json['progress'], expected)
        self.assertEqual(self.progress(), initial)
        # A delayed retry of the original POST must not reapply an undone grade.
        self.assertEqual(self.client.post(self.url, json=first).status_code, 409)

    def test_stale_tabs_and_old_undo_cannot_overwrite_later_reviews(self):
        first = self.body()
        self.client.post(self.url, json=first)
        stale = self.client.post(self.url, json=self.body())
        self.assertEqual(stale.status_code, 409)
        second = self.body(first['event_id'])
        saved = self.client.post(self.url, json=second).json['progress']
        self.assertEqual(self.client.post(self.url + '/' + first['event_id'] + '/undo', json={}).status_code, 409)
        self.assertEqual(self.progress(), saved)

    def test_unlimited_study_and_edits_keep_card_ids_and_progress(self):
        saved = self.client.post(self.url, json=self.body()).json['progress']
        for _ in range(3):
            self.assertEqual(len(self.client.get(f'/api/decks/{self.deck}/study').json['cards']), 1)
        self.assertEqual(self.client.patch(self.url.removesuffix('/reviews'), json={'front':'Editada', 'back':'Respuesta'}).status_code, 200)
        self.assertEqual(self.progress(), saved)

    def test_delete_all_cascades_to_progress_and_undo_history(self):
        self.client.post(self.url, json=self.body())
        self.assertEqual(self.client.delete('/api/decks', json={'confirm':True}).status_code, 200)
        with db() as c:
            for table in ('card_progress', 'review_events'):
                self.assertEqual(c.execute(f'SELECT count(*) FROM {table}').fetchone()[0], 0)

    def test_invalid_input_and_cross_deck_requests_do_not_record_progress(self):
        for body in ([], {}, self.body(rating='unknown'), self.body(rating=[]), dict(self.body(), event_id='bad')):
            self.assertEqual(self.client.post(self.url, json=body).status_code, 400)
        self.assertEqual(self.client.post(self.url.replace(self.deck, 'other'), json=self.body()).status_code, 404)
        with patch.dict(os.environ, {'ANKIMIO_PASSWORD':'test-only'}):
            self.assertEqual(self.client.post(self.url, json=self.body()).status_code, 401)
        self.assertEqual(self.progress()['status'], 'new')

    def test_failure_rolls_back_event_and_progress_together(self):
        with patch('review.write_progress', side_effect=RuntimeError('test rollback')):
            with patch.dict(app.config, {'TESTING':True}):
                with self.assertRaises(RuntimeError):
                    self.client.post(self.url, json=self.body())
        self.assertEqual(self.progress()['status'], 'new')
        with db() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM review_events WHERE card_id=?', (self.card,)).fetchone()[0], 0)
