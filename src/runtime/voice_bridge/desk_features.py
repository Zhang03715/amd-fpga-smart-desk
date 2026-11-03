"""Non-actuator desk features. SQLite stores records, never physical filing state.

Posture input must come from a real detector or an explicitly labelled test source.
This module does not classify images and does not drive motors, lamps or cameras.
"""
from collections import deque, OrderedDict
from datetime import date, datetime
import math
import sqlite3
import time

ACTIONS = frozenset(
    [prefix + operation for prefix in ('paper.record.', 'wrong_question.')
     for operation in ('create', 'get', 'list', 'update', 'delete')]
    + ['exam.set', 'exam.get', 'exam.clear', 'timetable.get', 'timetable.set', 'timetable.update', 'timetable.config', 'posture.config', 'posture.update', 'posture.status'])


class FeatureService:
    """execute(action, params) returns data or raises ValueError with a stable code.

    Actions: paper.record/wrong_question + .create/.get/.list/.update/.delete;
    exam.set/get/clear; posture.config/update/status. poll_events drains a bounded
    JSON-compatible event queue. close() releases the database. Call serially;
    callers sharing an instance across threads MUST lock all execute/poll/close.
    now supplies local datetime for exam dates; clock supplies monotonic seconds.
    """

    ACTIONS = ACTIONS

    def __init__(self, db_path=':memory:', now=datetime.now, clock=time.monotonic, event_limit=32, wall_clock=time.time):
        if type(event_limit) is not int or not 1 <= event_limit <= 128:
            raise ValueError('invalid_event_limit')
        self.now, self.clock, self.wall_clock = now, clock, wall_clock
        self.events = deque(maxlen=event_limit)
        self.db = sqlite3.connect(str(db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE IF NOT EXISTS records (id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, subject TEXT NOT NULL, notes TEXT NOT NULL, location TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0)')
        self.db.execute('CREATE TABLE IF NOT EXISTS exam (singleton INTEGER PRIMARY KEY CHECK(singleton=1), name TEXT NOT NULL, target TEXT NOT NULL)')
        self.db.commit()
        from voice_bridge.exam_schedule import initialize
        initialize(self.db)
        from voice_bridge.timetable import initialize as init_timetable
        init_timetable(self.db)
        self.bad_since = self.last_sample = self.last_reminder = None
        self.classification = 'unknown'
        self.transition_reminders = False
        self.reminder_armed = False
        self.detector_samples = OrderedDict()
        self.detector_session = None
        self.last_provenance = None
        self.duration, self.cooldown, self.max_gap = 10.0, 60.0, 5.0

    def close(self):
        self.db.close()

    @staticmethod
    def _text(params, key, maximum, required=False, default=''):
        value = params.get(key, default)
        if not isinstance(value, str) or len(value) > maximum or (required and not value.strip()):
            raise ValueError('invalid_' + key)
        return value.strip()

    @staticmethod
    def _id(params):
        value = params.get('id')
        if type(value) is not int or value < 1:
            raise ValueError('invalid_record_id')
        return value

    def execute(self, action, params):
        """Record fields: title, subject, notes, location, resolved (bool).

        List: limit 1..3, offset >=0, optional subject/resolved filters;
        returns compact summaries (use .get for notes/location/subject details).
        Exam set: name and ISO YYYY-MM-DD date. Posture update: classification
        bad/good/unknown, optional source label; no sample means no reminder.
        """
        if not isinstance(params, dict) or not isinstance(action, str):
            raise ValueError('invalid_params')
        for prefix, kind in (('paper.record.', 'paper'), ('wrong_question.', 'wrong_question')):
            if action.startswith(prefix):
                return self._record(kind, action[len(prefix):], params)
        if action in ('timetable.get','timetable.set','timetable.update', 'timetable.config'):
            from voice_bridge.timetable import execute
            return execute(self,action,params)
        if action in ('exam.set','exam.get','exam.clear'):
            from voice_bridge.exam_schedule import execute
            return execute(self,action,params)
        if action == 'posture.config':
            values = {}
            for key, current, low, high in (('duration', self.duration, 0, 600), ('cooldown', self.cooldown, 1, 3600), ('max_gap', self.max_gap, 0.1, 60)):
                value = params.get(key, current)
                if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                    raise ValueError('invalid_' + key)
                values[key] = float(value)
            self.duration, self.cooldown, self.max_gap = values['duration'], values['cooldown'], values['max_gap']
            self.bad_since = self.last_sample = None
            self.classification = 'unknown'
            self.reminder_armed = False
            return values
        if action == 'posture.update':
            classification = params.get('classification')
            if classification not in ('bad', 'good', 'unknown'):
                raise ValueError('invalid_classification')
            source = self._text(params, 'source', 80, default='external')
            current = self.clock()
            if 'source_kind' in params:
                sample = self._detector_sample(params)
                if sample['ignored']:
                    stale = self.last_sample is None or self.clock() - self.last_sample > self.max_gap
                    if stale:
                        self.bad_since = None
                        self.reminder_armed = False
                    return dict(classification='unknown' if stale else self.classification, reminded=False, **sample)
                self.last_provenance = {key: params[key] for key in ('source', 'source_kind', 'captured_at', 'session_id', 'frame_id')}
                classification = sample['classification']
                current = sample['sample_clock']
            if self.last_sample is not None and (current < self.last_sample or current - self.last_sample > self.max_gap):
                self.bad_since = None
                self.reminder_armed = False
            edge = classification == 'bad' and self.reminder_armed
            if classification == 'good':self.reminder_armed = True
            elif classification == 'bad':self.reminder_armed = False
            self.last_sample = current
            self.classification = classification
            reminded = False
            if classification != 'bad':
                self.bad_since = None
            else:
                if self.bad_since is None:
                    self.bad_since = current
                if (edge if self.transition_reminders else current - self.bad_since >= self.duration and (self.last_reminder is None or current - self.last_reminder >= self.cooldown)):
                    self.events.append({'v': 1, 'type': 'event', 'name': 'posture.bad', 'data': {'classification': 'bad', 'source': source, **({key: params[key] for key in ('source_kind', 'captured_at', 'session_id', 'frame_id')} if 'source_kind' in params else {})}})
                    self.last_reminder = current
                    reminded = True
            return {'classification': classification, 'reminded': reminded}
        if action == 'posture.status':
            stale = self.last_sample is None or self.clock() - self.last_sample > self.max_gap
            return {'classification': 'unknown' if stale else self.classification, 'stale': stale, 'detector_connected': not stale and (self.last_provenance is None or self.last_provenance['source_kind'] == 'camera'), 'sample': self.last_provenance}
        raise ValueError('unknown_action')

    def _detector_sample(self, params):
        """Capture provenance, not repeated arrival time, drives live continuity.

        Offline image/video is debug evidence only. Metadata validation is also
        applied to the UART/dashboard path when these fields are supplied.
        """
        kind = params.get('source_kind')
        if kind not in ('camera', 'video', 'image'):
            raise ValueError('invalid_source_kind')
        session = self._text(params, 'session_id', 80, True)
        frame = params.get('frame_id')
        captured = params.get('captured_at')
        if type(frame) is not int or frame < 0:
            raise ValueError('invalid_frame_id')
        if type(captured) not in (int, float) or not math.isfinite(captured):
            raise ValueError('invalid_captured_at')
        age = self.wall_clock() - captured
        previous = self.detector_samples.get(session)
        if previous is not None and frame <= previous[0]:
            return {'ignored': True, 'reason': 'duplicate_or_out_of_order'}
        ordered = previous is None or captured > previous[1]
        self.detector_samples[session] = (frame, max(captured, previous[1]) if previous else captured)
        self.detector_samples.move_to_end(session)
        while len(self.detector_samples) > 32:
            self.detector_samples.popitem(last=False)
        if session != self.detector_session:
            self.bad_since = self.last_sample = None
            self.detector_session = session
        usable = kind == 'camera' and ordered and 0 <= age <= self.max_gap
        return {'ignored': False, 'classification': params['classification'] if usable else 'unknown',
                'sample_clock': self.clock() - age if usable else self.clock(),
                'reason': 'live' if usable else 'offline_debug' if kind != 'camera' else 'expired_or_future'}

    def _record(self, kind, operation, params):
        if operation == 'list':
            limit, offset = params.get('limit', 3), params.get('offset', 0)
            if type(limit) is not int or not 1 <= limit <= 3 or type(offset) is not int or not 0 <= offset <= 1000000:
                raise ValueError('invalid_pagination')
            clauses, values = ['kind=?'], [kind]
            if 'subject' in params:
                clauses.append('subject=?')
                values.append(self._text(params, 'subject', 80))
            if 'resolved' in params:
                if type(params['resolved']) is not bool:
                    raise ValueError('invalid_resolved')
                clauses.append('resolved=?')
                values.append(int(params['resolved']))
            rows = self.db.execute('SELECT * FROM records WHERE ' + ' AND '.join(clauses) + ' ORDER BY id LIMIT ? OFFSET ?', values + [limit, offset]).fetchall()
            summaries = [dict(id=row['id'], title=row['title'], resolved=bool(row['resolved']), physical_filing=False) for row in rows]
            return {'records': summaries, 'limit': limit, 'offset': offset}
        if operation not in ('create', 'get', 'update', 'delete'):
            raise ValueError('unknown_action')
        if operation != 'create':
            rid = self._id(params)
            row = self.db.execute('SELECT * FROM records WHERE id=? AND kind=?', (rid, kind)).fetchone()
            if row is None:
                raise ValueError('record_not_found')
            if operation == 'get':
                return self._row(row)
            if operation == 'delete':
                with self.db:
                    self.db.execute('DELETE FROM records WHERE id=? AND kind=?', (rid, kind))
                return {'id': rid, 'deleted': True, 'physical_filing': False}
        defaults = {} if operation == 'create' else dict(row)
        fields = {key: self._text(params, key, maximum, key == 'title', defaults.get(key, '')) for key, maximum in (('title', 100), ('subject', 80), ('notes', 200), ('location', 120))}
        resolved = params.get('resolved', bool(defaults.get('resolved', False)))
        if type(resolved) is not bool:
            raise ValueError('invalid_resolved')
        with self.db:
            if operation == 'create':
                cursor = self.db.execute('INSERT INTO records (kind,title,subject,notes,location,resolved) VALUES (?,?,?,?,?,?)', (kind, fields['title'], fields['subject'], fields['notes'], fields['location'], int(resolved)))
                rid = cursor.lastrowid
            else:
                self.db.execute('UPDATE records SET title=?,subject=?,notes=?,location=?,resolved=? WHERE id=? AND kind=?', (fields['title'], fields['subject'], fields['notes'], fields['location'], int(resolved), rid, kind))
        return self._row(self.db.execute('SELECT * FROM records WHERE id=?', (rid,)).fetchone())

    @staticmethod
    def _row(row):
        result = dict(row)
        result['resolved'] = bool(result['resolved'])
        result['physical_filing'] = False
        return result

    def poll_events(self):
        """Drain queued posture reminders; never infer events from missing samples."""
        events = list(self.events)
        self.events.clear()
        return events

