"""Strict validation of accepted requests that stopped before a first result."""
import json


def mark_import(data):
    """Keep supplied identifiers/provenance when assigning a safe local ID."""
    if data.get('id') is not None:
        data.setdefault('source_id', data['id'])
    data['library_import_provenance'] = {
        'supplied_id': data.get('id'),
        'supplied_source': data.get('source'),
        'reference_name': data.get('reference_name'),
    }
    entries = data.get('entries')
    for entry in entries if isinstance(entries, list) else []:
        run = entry.get('run') if isinstance(entry, dict) else None
        if isinstance(run, dict) and run.get('id') is not None:
            run.setdefault('source_id', run['id'])


def validate_empty_sweep(data, schema, kind, normalize_config, validate_artifact):
    """Validate a minimal pending request without inventing completed attempts.

    Full checkpoints, including zero-entry checkpoints, still use their family's
    complete validator. This exception is only the pre-dispatch request envelope.
    """
    if not isinstance(data, dict):
        raise ValueError('Saved request must be an object')
    json.dumps(data, allow_nan=False)
    if data.get('schema_version') != schema or data.get('artifact_type') != kind:
        raise ValueError('Saved request schema/type differs from this endpoint')
    if data.get('entries') != []:
        raise ValueError('Minimal request must retain an explicit empty entries list')
    if any(key in data for key in ('thresholds', 'start_table', 'aggregates', 'solution_groups')):
        validate_artifact(data)
        return
    if data.get('status') not in ('running', 'failed', 'interrupted'):
        raise ValueError('A completed artifact requires its complete result accounting')
    if not isinstance(data.get('config'), dict) or normalize_config(data['config']) != data['config']:
        raise ValueError('Saved request configuration must be complete and normalized')
    if data['status'] in ('failed', 'interrupted') and (not isinstance(data.get('error'), str) or not data['error']):
        raise ValueError('A failed/interrupted request must retain its infrastructure error')
