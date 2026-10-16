"""Rebuildable metadata cache. Source JSON and existing strict loaders own science.

Every query inventories only the two history directories (mtime_ns, ctime_ns,
size). Only new/changed files are decoded, with no numerical validation or
diagnostic computation. A same-size edit with deliberately restored timestamps
requires an explicit rebuild. SQLite corruption rebuilds the cache, never JSON.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from threading import RLock
import time

from flask import jsonify, request


def _dict(value):
    return value if isinstance(value, dict) else {}


def _reject_constant(value):
    raise ValueError('Nonfinite JSON constant: ' + value)


def _digest(value):
    if value is None:
        return None
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _message(value):
    return str(value)[:4000] if value is not None else None


def _urls(kind, identifier, schema, artifact_type):
    if len(identifier) != 32 or any(c not in '0123456789abcdef' for c in identifier):
        return None, None
    if kind == 'run':
        return '/api/runs/' + identifier, '/api/m7/runs/' + identifier + '/csv' if schema == '7.0' else None
    if kind == 'comparison':
        return '/api/comparisons/' + identifier, None
    prefix = {'timing_sweep': '/api/m3/sweeps/',
              'geometry_sweep': '/api/m4/sweeps/',
              'solver_sweep': '/api/m5/sweeps/',
              'robust_sweep': '/api/m6/sweeps/'}.get(artifact_type, '/api/sweeps/')
    return prefix + identifier, prefix + identifier + '/csv' if schema != '2.0' else None


def _summary(data, key, identifier, stamp, source_path):
    artifact_type = data.get('artifact_type')
    if not isinstance(data.get('schema_version'), str):
        raise ValueError('Saved result needs a schema_version string')
    if artifact_type is not None and not isinstance(artifact_type, str):
        raise ValueError('artifact_type must be a string')
    if 'status' in data and not isinstance(data['status'], str):
        raise ValueError('status must be a string')
    if not artifact_type and not isinstance(data.get('experiment'), dict):
        raise ValueError('Saved run experiment must be an object')
    if 'options' in data and not isinstance(data['options'], dict):
        raise ValueError('Saved options must be an object')
    kind = 'comparison' if artifact_type == 'comparison' else 'benchmark' if artifact_type else 'run'
    experiment = _dict(data.get('experiment'))
    config = _dict(data.get('config')) if kind == 'benchmark' else _dict(experiment.get('config'))
    options = _dict(data.get('options')) if kind == 'run' else _dict(config.get('options'))
    base = _dict(config.get('base_experiment', config.get('experiment')))
    scenario = config.get('scenario') or base.get('scenario')
    source = 'imported' if data.get('library_import_provenance') else str(data.get('source') or ('named_reference' if data.get('reference_name') else 'saved'))[:120]
    settings = {name: options.get(name) for name in (
        'mode', 'solver', 'loss', 'initialization', 'timing_model', 'tag_height_model',
        'beacon_height_model', 'height_parameterization', 'starts', 'max_nfev', 'seed')
        if name in options}
    if config.get('factor') is not None:
        settings['factor'] = config['factor']
    starts = data.get('starts') if isinstance(data.get('starts'), list) else []
    attempts = [{'index': s.get('index', i), 'status': s.get('status', 'unknown'),
                 'selected': s.get('index', i) == data.get('selected_start'),
                 'error': _message(s.get('error') or _dict(s.get('solver')).get('message'))}
                for i, s in enumerate(starts) if isinstance(s, dict)]
    if kind == 'comparison':
        if not isinstance(data.get('runs'), list):
            raise ValueError('Comparison runs must be a list')
        entries = [{'index': side, 'run': run} for side, run in enumerate(data['runs'])]
    else:
        entries = data.get('entries') if isinstance(data.get('entries'), list) else []
    run_counts = Counter(_dict(_dict(e).get('run')).get('status', 'unknown') for e in entries)
    attempt_counts = Counter(a['status'] for a in attempts)
    for entry in entries:
        for start in _dict(_dict(entry).get('run')).get('starts', []) or []:
            if isinstance(start, dict):
                attempt_counts[start.get('status', 'unknown')] += 1
    status = data.get('status', 'saved' if kind == 'comparison' else 'unknown')
    if kind == 'benchmark' and status == 'complete' and len(run_counts) > 1:
        status = 'mixed'
    expected = None
    expected_cells = None
    attempted_cells = None
    if isinstance(config.get('values'), list) and isinstance(config.get('seeds'), list):
        expected_cells = len(config['values']) * len(config['seeds'])
        attempted_cells = len({(str(_dict(e).get('value_index')), str(_dict(e).get('seed'))) for e in entries})
        variants = config.get('variants')
        variant_count = len(variants) if isinstance(variants, list) else 2 if artifact_type == 'timing_sweep' else None
        if variant_count is not None:
            expected = len(config['values']) * len(config['seeds']) * variant_count
    recorded_label = data.get('label') or data.get('reference_name')
    label = recorded_label or (config.get('factor') if kind == 'benchmark' else scenario)
    if kind == 'benchmark' and not recorded_label:
        label = ' · '.join(str(v) for v in (config.get('factor') or 'Benchmark', scenario, identifier[:8]) if v)
    if kind == 'comparison' and not label:
        names = []
        for run in data.get('runs', []):
            if not isinstance(run, dict):
                continue
            run_options = _dict(run.get('options'))
            run_config = _dict(_dict(run.get('experiment')).get('config'))
            names.append(str(run.get('reference_name') or run.get('label') or
                             ' · '.join(str(v) for v in (run_config.get('scenario') or 'Run',
                                                          run_options.get('loss') or run_options.get('mode'),
                                                          str(run.get('id') or '')[:8]) if v))[:70])
        label = ' ↔ '.join(names)
    label = str(label or (kind.title() + ' ' + identifier[:8])).replace('_', ' ')[:240]
    details = []
    if kind == 'comparison':
        details.append('saved ' + str(data.get('alignment', 'raw')) + ' comparison · scale 1 · no reflection')
    elif kind == 'benchmark':
        for name in ('values', 'seeds'):
            if isinstance(config.get(name), list):
                details.append(name + ': ' + ', '.join(str(v) for v in config[name][:10]))
        variants = config.get('variants')
        if isinstance(variants, list):
            details.append('variants: ' + ', '.join(str(_dict(v).get('label', '?')) for v in variants[:8]))
    else:
        for name in ('mode', 'solver', 'loss', 'timing_model', 'tag_height_model', 'beacon_height_model'):
            if options.get(name) is not None:
                details.append(str(options[name]))
        if config.get('seed') is not None:
            details.append('data seed ' + str(config['seed']))
        if config.get('noise_std_m') is not None:
            details.append('noise ' + str(config['noise_std_m'])[:80] + ' m')
        if options.get('initialization') is not None:
            details.append('start: ' + str(options['initialization']))
    open_url, csv_url = _urls(kind, identifier, str(data.get('schema_version')), artifact_type)
    estimator_input = experiment.get('estimator_input')
    initials = [s.get('initial') for s in starts if isinstance(s, dict)]
    return {'key': key, 'id': identifier, 'recorded_id': data.get('id'), 'kind': kind,
            'artifact_type': artifact_type, 'schema_version': data.get('schema_version'),
            'label': label, 'recorded_label': data.get('label'), 'reference_name': data.get('reference_name'),
            'distinguishing_settings': details, 'scenario': scenario, 'status': status, 'saved_status': data.get('status'),
            'date': datetime.fromtimestamp(stamp[0] / 1e9, timezone.utc).isoformat(),
            'date_basis': 'source file modification time', 'recorded_date': data.get('created_at'),
            'model': str(options.get('mode') or 'unknown'), 'source': source,
            'settings': settings, 'source_path': source_path,
            'child_count': len(entries), 'attempt_counts': dict(attempt_counts),
            'run_counts': dict(run_counts), 'expected_runs': expected,
            'unattempted': max(0, expected - len(entries)) if expected is not None else None,
            'unattempted_unit': 'scheduled run/variant combinations',
            'expected_data_cells': expected_cells, 'attempted_data_cells': attempted_cells,
            'unattempted_data_cells': max(0, expected_cells - attempted_cells) if expected_cells is not None else None,
            'attempts': attempts, 'selected_start': data.get('selected_start'),
            'error': _message(data.get('error')), 'infrastructure_status': data.get('infrastructure_status'),
            'summary_validation': 'metadata only; full record unchecked',
            'observation_fingerprint': _digest(estimator_input) if estimator_input else None,
            'starts_fingerprint': _digest(initials) if initials and all(v is not None for v in initials) else None,
            'open_url': open_url, 'export_json_url': open_url, 'export_csv_url': csv_url}


class LibraryIndex:
    """Thread-safe local SQLite index, lazily scanned on the first request.

    Cache failures are recoverable and are disclosed. No source file is ever
    changed or removed by this class. ``refresh`` inventories on every query,
    so successful saves/imports/checkpoints and external edits appear next time.
    Temporary checkpoint recovery remains exclusively in the strict endpoints.
    """

    def __init__(self, directory, *, cache_path=None, jobs=None, job_lock=None):
        self.directory = Path(directory)
        self.cache_path = Path(cache_path or self.directory / '.library.sqlite3')
        self.lock = RLock()
        self.jobs = jobs
        self.job_lock = job_lock
        self.progress = {'state': 'not_scanned', 'scanned': 0, 'changed': 0,
                         'freshness': 'Filesystem timestamps checked at each request; JSON authoritative.'}

    def _connect(self):
        connection = sqlite3.connect(self.cache_path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            # Bound the cache to 64 MiB, enough to avoid repeated random-page
            # spills while building a 10k metadata fixture on Windows. This is
            # a disposable index; scientific durability belongs to JSON saves.
            connection.execute('PRAGMA cache_size=-65536')
            connection.execute('PRAGMA synchronous=NORMAL')
            if connection.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise sqlite3.DatabaseError('Metadata cache integrity check failed')
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY, mtime INTEGER, size INTEGER, ctime INTEGER);
                CREATE TABLE IF NOT EXISTS items (
                    key TEXT PRIMARY KEY, path TEXT NOT NULL, id TEXT, kind TEXT,
                    status TEXT, model TEXT, source TEXT, label TEXT, mtime INTEGER,
                    search TEXT, summary TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS children (
                    parent TEXT NOT NULL, ordinal INTEGER NOT NULL, child_id TEXT,
                    summary TEXT NOT NULL, PRIMARY KEY(parent, ordinal));
                CREATE INDEX IF NOT EXISTS child_ids ON children(child_id);
                CREATE INDEX IF NOT EXISTS item_path ON items(path);
                CREATE INDEX IF NOT EXISTS item_date ON items(mtime DESC, key);
            ''')
            if connection.execute('PRAGMA user_version').fetchone()[0] != 4:
                with connection:
                    for table in ('children', 'items', 'files'):
                        connection.execute('DELETE FROM ' + table)
                    connection.execute('PRAGMA user_version=4')
            return connection
        except sqlite3.DatabaseError:
            connection.close()
            raise

    def _recover_connection(self):
        try:
            return self._connect()
        except sqlite3.DatabaseError as exc:
            backup = self.cache_path.with_name(self.cache_path.name + '.corrupt.' + str(time.time_ns()))
            if self.cache_path.exists():
                self.cache_path.replace(backup)
            self.progress['cache_recovery'] = 'Rebuilt corrupt metadata cache: ' + str(exc)
            return self._connect()

    def _inventory(self):
        result = {}
        for folder, prefix in ((self.directory, ''), (self.directory / 'artifacts', 'artifacts/')):
            if not folder.exists():
                continue
            with os.scandir(folder) as entries:
                for entry in entries:
                    if entry.name.endswith('.json') and entry.is_file(follow_symlinks=False):
                        try:
                            stat = entry.stat(follow_symlinks=False)
                        except FileNotFoundError:
                            continue
                        result[prefix + entry.name] = (stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns)
        return result

    def _insert_file(self, db, relative, stamp):
        identifier = Path(relative).stem
        key = ('artifact:' if relative.startswith('artifacts/') else 'run:') + identifier
        try:
            with (self.directory / relative).open('r', encoding='utf-8-sig') as stream:
                data = json.load(stream, parse_constant=_reject_constant)
            if not isinstance(data, dict):
                raise ValueError('Saved JSON must be an object')
            if not data.get('artifact_type') and 'experiment' not in data:
                if 'config' in data and 'estimator_input' in data:
                    return  # A standalone experiment is not a saved result.
                raise ValueError('No saved-run experiment or artifact type')
            summary = _summary(data, key, identifier, stamp, relative)
            if summary['kind'] in ('benchmark', 'comparison'):
                entries = ([{'index': side, 'run': run} for side, run in enumerate(data['runs'])]
                           if summary['kind'] == 'comparison' else data.get('entries', []))
                for ordinal, entry in enumerate(entries):
                    entry = _dict(entry)
                    run = _dict(entry.get('run'))
                    if not run:
                        continue
                    run_id = run.get('id')
                    child_key = key + ':entry:' + str(ordinal)
                    child = _summary(run, child_key, str(run_id or ''), stamp, relative)
                    child.update(parent_key=key, run_id=run_id, entry_index=entry.get('index', ordinal),
                                 entry_ordinal=ordinal, cell={k: entry.get(k) for k in ('value_index', 'value', 'seed')},
                                 variant=entry.get('variant'), variant_index=entry.get('variant_index'),
                                 pairing_error=entry.get('pairing_error'),
                                 initial_reference_entry=entry.get('initial_reference_entry'))
                    if summary['kind'] == 'comparison':
                        child['comparison_side'] = ordinal
                        child['distinguishing_settings'] = ['Comparison side ' + ('A' if ordinal == 0 else 'B')] + child['distinguishing_settings']
                    # Embedded entries open their validated parent; UI explicitly chooses the entry/start.
                    child['parent_open_url'] = summary['open_url']
                    child['open_url'] = summary['open_url']
                    child['export_json_url'] = child['open_url']
                    db.execute('INSERT INTO children VALUES (?,?,?,?)',
                               (key, ordinal, run_id, json.dumps(child, allow_nan=False)))
                    # Embedded records without a retained copy also belong to
                    # All runs. Exact recorded IDs select a local copy where
                    # present; no similarity/duplicate guessing is involved.
                    self._insert_item(db, child, relative, stamp)
        except (ValueError, OSError, TypeError, AttributeError, OverflowError, RecursionError) as exc:
            # Retain corrupt rows and clear partial relationships from failed extraction.
            db.execute('DELETE FROM children WHERE parent=?', (key,))
            db.execute('DELETE FROM items WHERE path=?', (relative,))
            summary = {'key': key, 'id': identifier, 'kind': 'benchmark' if relative.startswith('artifacts/') else 'run',
                       'label': 'Unreadable ' + identifier[:8], 'status': 'unreadable',
                       'error': f'{type(exc).__name__}: {exc}', 'source_path': relative,
                       'schema_version': None, 'model': 'unknown', 'source': 'saved',
                       'date': datetime.fromtimestamp(stamp[0] / 1e9, timezone.utc).isoformat(),
                       'summary_validation': 'unreadable; source preserved', 'open_url': None,
                       'export_json_url': None, 'export_csv_url': None, 'attempt_counts': {}, 'child_count': 0}
        self._insert_item(db, summary, relative, stamp)

    def _insert_item(self, db, summary, relative, stamp):
        searchable = ' '.join(str(summary.get(k) or '') for k in
                              ('label', 'id', 'recorded_id', 'scenario', 'schema_version', 'settings', 'source', 'error'))
        db.execute('INSERT INTO items VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                   (summary['key'], relative, summary['id'], summary['kind'], summary['status'], summary['model'],
                    summary['source'], summary['label'], stamp[0], searchable.casefold(), json.dumps(summary, allow_nan=False)))

    def _refresh(self, db):
        started = time.perf_counter()
        self.progress.update(state='scanning', scanned=0, changed=0)
        inventory = self._inventory()
        cached = {r['path']: (r['mtime'], r['size'], r['ctime']) for r in db.execute('SELECT * FROM files')}
        changed = [p for p, stamp in inventory.items() if cached.get(p) != stamp]
        removed = set(cached) - set(inventory)
        self.progress.update(discovered=len(inventory), pending=len(changed))
        with db:
            for relative in list(removed) + changed:
                keys = [r[0] for r in db.execute('SELECT key FROM items WHERE path=?', (relative,))]
                for key in keys:
                    db.execute('DELETE FROM children WHERE parent=?', (key,))
                db.execute('DELETE FROM items WHERE path=?', (relative,))
                db.execute('DELETE FROM files WHERE path=?', (relative,))
            for i, relative in enumerate(changed):
                self._insert_file(db, relative, inventory[relative])
                db.execute('INSERT INTO files VALUES (?,?,?,?)', (relative, *inventory[relative]))
                self.progress.update(scanned=i + 1)
        self.progress.update(state='ready', changed=len(changed), removed=len(removed), pending=0,
                             checked_at=datetime.now(timezone.utc).isoformat(),
                             scan_ms=round((time.perf_counter() - started) * 1000, 3),
                             summary_validation='Metadata extraction only; strict existing endpoints validate detail/export.')

    def rebuild(self):
        """Invalidate metadata only; the next query rereads authoritative JSON."""
        with self.lock:
            db = self._recover_connection()
            try:
                with db:
                    for table in ('children', 'items', 'files'):
                        db.execute('DELETE FROM ' + table)
            finally:
                db.close()

    def _active_ids(self):
        if self.jobs is None:
            return None
        if self.job_lock:
            with self.job_lock:
                return {k for k, v in self.jobs.items() if v.get('status') == 'running'}
        return {k for k, v in self.jobs.items() if v.get('status') == 'running'}

    def _decorate(self, db, summary):
        if summary.get('kind') == 'run' and ':entry:' not in summary['key']:
            summary['parents'] = [r[0] for r in db.execute('SELECT DISTINCT parent FROM children WHERE child_id=? ORDER BY parent', (summary['id'],))]
        else:
            summary['parents'] = [summary['parent_key']] if summary.get('parent_key') else []
        active = self._active_ids()
        worker_id = summary.get('parent_key', '').removeprefix('artifact:') or summary['id']
        if summary.get('saved_status') == 'running' and active is not None and worker_id not in active:
            summary['status'] = 'interrupted'
            summary['interruption_notice'] = 'No active worker; saved attempts retained. No implicit restart.'
        return summary

    def query(self, **params):
        page = max(1, int(params.get('page') or 1))
        page_size = min(50, max(1, int(params.get('page_size') or 25)))
        kind = params.get('type', 'all')
        if kind not in ('all', 'run', 'benchmark', 'comparison'):
            raise ValueError('Unknown Library type')
        sort = params.get('sort') or 'newest'
        orders = {'newest': 'mtime DESC, key', 'oldest': 'mtime ASC, key',
                  'name': 'label COLLATE NOCASE, key', 'status': 'status, key'}
        if sort not in orders:
            raise ValueError('Unknown Library sort')
        view = params.get('view') or 'grouped'
        if view not in ('grouped', 'all'):
            raise ValueError('Unknown Library view')
        with self.lock:
            db = self._recover_connection()
            try:
                self._refresh(db)
                if params.get('parent'):
                    return self._query_children(db, params['parent'], params, page, page_size)
                clauses, values = [], []
                if view == 'grouped':
                    clauses.append("NOT (kind='run' AND (instr(key, ':entry:')>0 OR EXISTS (SELECT 1 FROM children c JOIN items p ON p.key=c.parent WHERE c.child_id=items.id AND p.kind='benchmark')))")
                else:
                    clauses.append("NOT (instr(key, ':entry:')>0 AND EXISTS (SELECT 1 FROM items r WHERE r.key='run:' || items.id))")
                scope = ' AND '.join(clauses) or '1'
                total = db.execute('SELECT COUNT(*) FROM items WHERE ' + scope).fetchone()[0]
                if kind != 'all':
                    clauses.append('kind=?'); values.append(kind)
                for field in ('status', 'model', 'source'):
                    value = params.get(field)
                    if value and value != 'all':
                        if field == 'status' and value == 'interrupted' and self.jobs is not None:
                            active = self._active_ids()
                            clauses.append("status='running'")
                            if active:
                                clauses.append('id NOT IN (' + ','.join('?' for _ in active) + ')')
                                values.extend(sorted(active))
                        elif field == 'status' and value == 'running' and self.jobs is not None:
                            active = self._active_ids()
                            if active:
                                clauses.append("status='running' AND id IN (" + ','.join('?' for _ in active) + ')')
                                values.extend(sorted(active))
                            else:
                                clauses.append('0')
                        else:
                            clauses.append(field + '=?'); values.append(value)
                if params.get('q'):
                    clauses.append('instr(search, ?) > 0'); values.append(str(params['q']).casefold()[:500])
                where = ' AND '.join(clauses) or '1'
                filtered = db.execute('SELECT COUNT(*) FROM items WHERE ' + where, values).fetchone()[0]
                pages = max(1, (filtered + page_size - 1) // page_size)
                page = min(page, pages)
                rows = db.execute('SELECT summary FROM items WHERE ' + where + ' ORDER BY ' + orders[sort] + ' LIMIT ? OFFSET ?',
                                  [*values, page_size, (page - 1) * page_size]).fetchall()
                items = [self._decorate(db, json.loads(r[0])) for r in rows]
                facets = {field: [r[0] for r in db.execute('SELECT DISTINCT ' + field + ' FROM items ORDER BY ' + field)]
                          for field in ('kind', 'status', 'model', 'source')}
                if self.jobs is not None and 'running' in facets['status']:
                    facets['status'] = sorted(set(facets['status'] + ['interrupted']))
                overall = self._overall_total(db)
                return dict(items=items, total=total, overall_total=overall, filtered=filtered, page=page,
                            page_size=page_size, pages=pages, facets=facets, index=dict(self.progress))
            finally:
                db.close()

    def _query_children(self, db, parent, params, page, page_size):
        # Child summaries are at most the recorded benchmark size (bounded by
        # its source schema); SQL still retrieves only the requested page.
        total = db.execute('SELECT COUNT(*) FROM children WHERE parent=?', (parent,)).fetchone()[0]
        clauses, values = ['parent=?'], [parent]
        if params.get('q'):
            clauses.append('instr(lower(summary), lower(?))>0'); values.append(params['q'][:500])
        for field in ('status', 'model', 'source'):
            if params.get(field) and params[field] != 'all':
                if field == 'status' and params[field] in ('running', 'interrupted') and self.jobs is not None:
                    active = parent.removeprefix('artifact:') in self._active_ids()
                    if active == (params[field] == 'running'):
                        clauses.append("json_extract(summary, '$.saved_status')='running'")
                    else:
                        clauses.append('0')
                else:
                    clauses.append("json_extract(summary, '$." + field + "')=?"); values.append(params[field])
        where = ' AND '.join(clauses)
        filtered = db.execute('SELECT COUNT(*) FROM children WHERE ' + where, values).fetchone()[0]
        pages = max(1, (filtered + page_size - 1) // page_size)
        page = min(page, pages)
        order = {'name': "json_extract(summary, '$.label') COLLATE NOCASE, ordinal",
                 'status': "json_extract(summary, '$.status'), ordinal"}.get(params.get('sort'), 'ordinal')
        rows = db.execute('SELECT summary FROM children WHERE ' + where + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?',
                          [*values, page_size, (page - 1) * page_size]).fetchall()
        facets = {field: [r[0] for r in db.execute("SELECT DISTINCT json_extract(summary, '$." + field + "') FROM children WHERE parent=? ORDER BY 1", (parent,))]
                  for field in ('kind', 'status', 'model', 'source')}
        if self.jobs is not None and 'running' in facets['status']:
            facets['status'] = sorted(set(facets['status'] + ['interrupted']))
        return dict(items=[self._decorate(db, json.loads(r[0])) for r in rows], total=total, filtered=filtered,
                    overall_total=self._overall_total(db), page=page, page_size=page_size, pages=pages,
                    parent=parent, index=dict(self.progress), facets=facets,
                    sort_basis='Child dates inherit parent source modification time; ties use recorded cell/variant order.')

    @staticmethod
    def _overall_total(db):
        return db.execute("SELECT COUNT(*) FROM items WHERE NOT (instr(key, ':entry:')>0 AND EXISTS (SELECT 1 FROM items r WHERE r.key='run:' || items.id))").fetchone()[0]

    def preview(self, key):
        with self.lock:
            db = self._recover_connection()
            try:
                self._refresh(db)
                row = db.execute('SELECT summary FROM items WHERE key=?', (key,)).fetchone()
                if row is None and ':entry:' in key:
                    parent, ordinal = key.rsplit(':entry:', 1)
                    if ordinal.isdigit():
                        row = db.execute('SELECT summary FROM children WHERE parent=? AND ordinal=?', (parent, int(ordinal))).fetchone()
                return self._decorate(db, json.loads(row[0])) if row else None
            finally:
                db.close()


def register_library(app, directory, *, jobs=None, job_lock=None):
    """Register metadata-only endpoints; existing open/import/export routes stay strict."""
    index = LibraryIndex(directory, jobs=jobs, job_lock=job_lock)
    app.extensions['library_index'] = index

    @app.get('/api/library')
    def library_page():
        try:
            return jsonify(index.query(**request.args.to_dict()))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except (OSError, sqlite3.DatabaseError) as exc:
            return jsonify(error=f'Library cache unavailable: {exc}', retry=True), 503

    @app.get('/api/library/status')
    def library_status():
        return jsonify(dict(index.progress))

    @app.post('/api/library/rebuild')
    def rebuild_library():
        try:
            index.rebuild()
            return jsonify(index.query())
        except (OSError, sqlite3.DatabaseError) as exc:
            return jsonify(error=f'Library rebuild failed: {exc}', retry=True), 503

    @app.get('/api/library/<key>')
    def library_preview(key):
        try:
            item = index.preview(key)
            return jsonify(item) if item is not None else (jsonify(error='Unknown Library item'), 404)
        except (OSError, sqlite3.DatabaseError) as exc:
            return jsonify(error=f'Library preview unavailable: {exc}', retry=True), 503

    return index
