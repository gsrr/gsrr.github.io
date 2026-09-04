"""Economy domain: passive Gold settlement (backend-authoritative). Pure functions mirroring
server.py econ_get's gold math exactly. No client-supplied resulting Gold; no double settlement."""
from . import config
from .army import clampi


def calculate_passive_gold(gold, population, region_pop, last, now):
    """Return (new_gold, new_last). THE one passive-income authority, shared by humans and AI:
       days = floor((now-last)/PASSIVE_PERIOD_SECONDS)          # whole elapsed periods only
       gold += min(days, PASSIVE_MAX_CATCHUP_DAYS) * round((population+region_pop)*GOLD_RATE)
       last += days*PASSIVE_PERIOD_SECONDS   (advances the clock so repeats don't double-count)

    Phase 14A.10A changed the PERIOD from an hour to a day and nothing else. The shape is
    unchanged, and so is its treatment of an existing `last` timestamp: it is read as plain
    elapsed wall-clock seconds, never as a calendar date, so a record last settled 12 hours ago
    simply earns nothing yet -- it does not become 12 payouts of either size."""
    gold = clampi(gold)
    days = int((now - last) // config.PASSIVE_PERIOD_SECONDS)
    if days <= 0:                                     # under one whole day: no partial payout
        return gold, last
    per_day = int(round((clampi(population) + clampi(region_pop)) * config.GOLD_RATE))
    gold = clampi(gold + min(days, config.PASSIVE_MAX_CATCHUP_DAYS) * per_day)
    last = last + days * config.PASSIVE_PERIOD_SECONDS
    return gold, last
