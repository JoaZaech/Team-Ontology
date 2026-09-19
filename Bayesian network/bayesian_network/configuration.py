"""Load committed expert assumptions; no training on historical outcomes."""
import json
import math
from . import ROOT
from .inference import ExactNetwork, ModelError


def load():
    config = json.loads((ROOT/'config/model.json').read_text())
    validate_config(config)
    return config


def validate_config(config):
    if not config.get('version') or not config['policy'].get('version') or any(not m.get('version') for m in config['models'].values()):
        raise ModelError('unversioned configuration')
    threshold = config['policy']['threshold']
    if type(threshold) not in (int, float) or not math.isfinite(threshold) or not 0 < threshold < 1:
        raise ModelError('invalid threshold')
    if config['policy']['sensitivity_action'] != 'step_up_if_any_scenario_at_or_above':
        raise ModelError('unsupported policy')
    if set(config['models']) != {'baseline', 'less_sensitive', 'more_sensitive'}:
        raise ModelError('missing sensitivity scenarios')
    for model in config['models'].values():
        net = ExactNetwork(model)
        if net.names != ['merchant', 'country', 'device', 'velocity', 'amount', 'session', 'anomaly'] or model['target'] != 'anomaly':
            raise ModelError('unsupported feature binding')
    return config
