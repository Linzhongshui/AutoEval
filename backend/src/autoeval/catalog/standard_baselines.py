"""Import immutable standard-repository reference baselines during input synchronization."""
import hashlib
import json
import math

from autoeval.catalog.import_benchmarks import import_baselines


def baseline_bundle(entry, repository, revision):
    attachment = entry['files'].get('baseline.json')
    if attachment is None:
        return None
    raw = attachment['raw']
    sha = hashlib.sha256(raw.encode()).hexdigest()
    if sha != attachment['sha256']:
        raise ValueError('Baseline attachment hash mismatch')
    body = json.loads(raw)
    value = body.get('median')
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Baseline median must be finite')
    unit = body['unit']
    if unit == 'percent' and not 0 <= value <= 100:
        raise ValueError('Baseline percentage out of range')
    key = hashlib.sha256((repository + '/' + attachment['path']).encode()).hexdigest()[:32]
    return {'baselines': [{
        'baseline_key': 'standard-' + key, 'version': revision,
        'dataset_key': entry['mapping']['dataset'], 'subset_scope': 'full',
        'metric_name': body['metric'], 'unit': unit, 'value': float(value),
        'direction': 'higher_is_better',
        'conditions': {'source_model': entry['source_model'], 'reference_only': True,
                       'standard_baseline': body, 'source_path': attachment['path']},
        'source_url': f'https://github.com/{repository}/blob/{revision}/{attachment["path"]}',
        'source_revision': revision, 'source_sha256': sha,
        'approved_by': 'standard-repository-auto-sync',
    }]}


async def sync_baseline(session, entry, repository, revision):
    bundle = baseline_bundle(entry, repository, revision)
    if bundle:
        return await import_baselines(session, bundle)
    return []
