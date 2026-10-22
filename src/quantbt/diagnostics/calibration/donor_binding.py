"""Bind optional coordinate donors to the actual continuous destination."""

from quantbt.mode5.continuous_binding import restore_geometry
from quantbt.mode5.dossier.records import Record

from .donors import ArchiveDonorPlan, CoordinateDonorTarget, _space
from .worksheet import selection_access


def continuous_donor_target(dossier, binding, *, seed):
    """Use the actual composite economics witness, not invented decompositions.

    Continuous producers currently hash instrument/constraints, costs and funding
    together. Requiring that exact same composite for all three slots is stricter
    than comparing a hand-written symbol/fee; it does not claim decomposed proof.
    """
    d, b = dossier.record.data['context'], binding.data
    c = b['continuous']
    geometry = restore_geometry(c['geometry'])
    space = _space(geometry)
    return CoordinateDonorTarget(strategy_identity=c['source']['alpha'],
        space_identity=space.identity, market_snapshot=d['data'], instrument=d['economics'],
        timeframe='bar_interval_ns:' + str(b['metrics']['bar_interval_ns']),
        clock=Record.of(c['execution']['clock']).identity, route=c['execution']['route'],
        costs=d['economics'], funding=d['economics'], scenario_seed=seed,
        warmup=Record.of(dict(policy='full_original_prefix_no_external_history',
            history_start_ns=c['witness']['start_ns'])).identity,
        source_backend=Record.of(c['source']).identity, mode='MODE5_CALIBRATION')


def verify_recipe_donors(recipe, *, dossier, binding, catalog, access):
    d = recipe.record.data
    raw = d['spec']['reuse'].get('archive_donors')
    if raw is None:
        return
    donors = ArchiveDonorPlan(Record.of(raw))
    starts = donors.warm_start_records(catalog=catalog,
        access=selection_access(d['spec']['reuse']['selection_policy']),
        target=continuous_donor_target(dossier, binding, seed=d['spec']['sampler']['seeds'][0]),
        geometry=restore_geometry(binding.data['continuous']['geometry']), budget=d['spec']['search_budget'])
    if access != selection_access(d['spec']['reuse']['selection_policy']):
        raise PermissionError('current donor selection rights differ from frozen recipe')
    if Record.of(dict(rows=starts)) != Record.of(dict(rows=binding.data['warm_start'])):
        raise ValueError('actual in-budget warm starts differ from explicit donor plan')
