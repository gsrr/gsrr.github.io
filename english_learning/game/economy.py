"""Economy domain: passive Gold settlement (backend-authoritative). Pure functions mirroring
server.py econ_get's gold math exactly. No client-supplied resulting Gold; no double settlement."""
from . import config
from .army import clampi


def calculate_passive_gold(gold, population, region_pop, last, now):
    """Return (new_gold, new_last). Mirrors econ_get:
       hours = floor((now-last)/GROW_SECONDS)
       gold += min(hours, ECON_MAX_CATCHUP) * round((population+region_pop)*GOLD_RATE)
       last += hours*GROW_SECONDS   (advances the clock so repeats don't double-count)"""
    gold = clampi(gold)
    hours = int((now - last) // config.GROW_SECONDS)
    if hours <= 0:
        return gold, last
    per_hour = int(round((clampi(population) + clampi(region_pop)) * config.GOLD_RATE))
    gold = clampi(gold + min(hours, config.ECON_MAX_CATCHUP) * per_hour)
    last = last + hours * config.GROW_SECONDS
    return gold, last
