"""Validated binary DAGs and exact enumeration, including evidence marginalization."""
import itertools
import math
import time
from kg_rootcause.common import digest


class ModelError(ValueError):
    pass


def validate(model):
    seen = set()
    if not isinstance(model, dict) or not model.get('nodes'):
        raise ModelError('empty model')
    for node in model['nodes']:
        name, parents, cpt = node['name'], node['parents'], node['cpt']
        if name in seen or len(parents) != len(set(parents)) or not set(parents) <= seen:
            raise ModelError('duplicate node/parent or non-topological DAG')
        keys = {''.join(map(str, bits)) for bits in itertools.product((0, 1), repeat=len(parents))}
        if set(cpt) != keys:
            raise ModelError('missing or extra CPT rows')
        for row in cpt.values():
            if len(row) != 2 or any(type(p) not in (int, float) or not math.isfinite(p) or not 0 <= p <= 1 for p in row) or abs(sum(row)-1) > 1e-12:
                raise ModelError('invalid CPT probability row')
        seen.add(name)
    if model['target'] not in seen:
        raise ModelError('unknown target')
    return {'valid': True, 'model_hash': digest(model), 'normalization_tolerance': 1e-12}


class ExactNetwork:
    def __init__(self, model):
        self.validation = validate(model)
        self.model = model
        self.names = [n['name'] for n in model['nodes']]
        self.joint = []
        for bits in itertools.product((0, 1), repeat=len(self.names)):
            values = dict(zip(self.names, bits))
            p = 1.0
            for node in model['nodes']:
                key = ''.join(str(values[parent]) for parent in node['parents'])
                p *= node['cpt'][key][values[node['name']]]
            self.joint.append((values, p))

    def posterior(self, evidence, deadline=None):
        if not set(evidence) <= set(self.names) or any(type(v) is not int or v not in (0, 1) for v in evidence.values()):
            raise ModelError('unknown evidence state')
        total = positive = 0.0
        for values, p in self.joint:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError('inference deadline exceeded')
            if all(values[k] == v for k, v in evidence.items()):
                total += p
                positive += p * values[self.model['target']]
        if total <= 0 or not math.isfinite(total):
            raise ModelError('impossible evidence')
        return positive / total


def analyze(networks, evidence, deadline=None):
    probabilities = {name: net.posterior(evidence, deadline) for name, net in networks.items()}
    baseline = probabilities['baseline']
    influence = []
    for name in sorted(evidence):
        without = networks['baseline'].posterior({k: v for k, v in evidence.items() if k != name}, deadline)
        influence.append({'feature': name, 'posterior': baseline, 'without_feature': without,
                          'delta': baseline-without, 'comparison': 'marginalize omitted evidence',
                          'interpretation': 'raises estimate' if baseline > without else 'lowers estimate' if baseline < without else 'unchanged'})
    return {'baseline': baseline, 'minimum': min(probabilities.values()), 'maximum': max(probabilities.values()),
            'scenarios': probabilities, 'influence': influence,
            'range_kind': 'expert parameter sensitivity; not a confidence interval'}
