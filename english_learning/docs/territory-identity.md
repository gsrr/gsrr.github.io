# Territory Identity

There is exactly **one logical territory identity**: the **Canonical Territory ID**.
Three identifiers exist with strictly separated responsibilities — they are never
interchangeable:

| Identifier | Example | Responsibility | Where it lives |
|---|---|---|---|
| **Canonical Territory ID** | `china:pLN`, `world:us` | **game identity** — ownership, selection, hover, labels, claim, population; the ONLY id future phases (adjacency, AI, battle, learning) may depend on | storage, game logic, APIs |
| **SVG Path Key** | `pLN_1`, `pLN_2`, `us` | **rendering identity** — which `<path>` to draw/click | SVG files + `svgPathKeys` in the catalog |
| **Administrative Code** | `US` | **real-world reference** only | catalog `administrativeCode` |

Canonical id format: `<mapId>:<regionCode>` (maps: `taiwan`, `taipei`, `china`, `world`).

## The single resolver

SVG paths are resolved to a canonical id in exactly one place per side, both
**catalog-driven** (the `svgPathKeys` index built from `world-data/`):

- **Frontend:** `resolveSvgPath(mapId, pathId)` → canonical id. `regionKey(spec, p)`
  calls it, so every downstream feature (ownership key, labels, claim, colouring) uses
  canonical ids and nothing keeps a raw SVG id internally.
- **Backend:** `territory_catalog.resolve_any(key)` accepts a canonical id, a legacy
  `maps/china.svg#pLN_1` key, or `mapId#pathId`, and returns the canonical id.

The **china multi-path suffix rule** (`pXX`, `pXX_<n>` → `china:pXX`) is defined once, in
`tools/gen_territory_catalog.js` (`regionCodeFor`), and baked into each territory's
`svgPathKeys` (e.g. `china:pLN` owns `["pLN_1","pLN_2"]`). The frontend resolver keeps a
documented offline fallback that strips the suffix so grouping still holds if the catalog
fails to load. No suffix logic is duplicated anywhere else.

## Legacy keys

Older rooms stored ownership under legacy SVG keys `"<svgFile>#<pathId>"`
(`maps/world.svg#us`). These remain **readable** but are no longer written.

## Storage

- **Reads:** `load_territory_store()` and the learned population cache canonicalize keys on
  load (legacy → canonical, in memory). Unknown keys are kept (never discarded); collisions
  keep the first and are counted.
- **Writes:** every save writes canonical ids only. Existing rooms therefore auto-migrate on
  their next save. **Writing a legacy key is forbidden.**

## Backend authority

The client may send an SVG path, a legacy key, or a canonical id — the backend never trusts
it as a storage key. `_handle_territory_claim` (and the other territory handlers via
`_canon`) resolve the identifier through the catalog and validate:

1. catalog loaded,
2. resolves to a territory that **exists** in the catalog,
3. the territory **belongs to the room's map** (`LEVEL_TO_MAPS`),
4. **population available** (taken from the catalog, not the client).

Anything else is rejected. The stored key and population are always the canonical/catalog
values.

## Migration

`load`-time canonicalization already auto-migrates rooms on next save. For an explicit,
auditable bulk migration use:

```
python3 tools/migrate_room_keys.py --rooms /data/rooms          # dry-run
python3 tools/migrate_room_keys.py --rooms /data/rooms --apply  # writes + .bak backups
```

It is **idempotent**, reports every changed key, **keeps and reports** unknown territories,
and **detects collisions** (two legacy keys → one canonical with different owners) — refusing
to merge them.

## Compatibility

Legacy rooms load and play unchanged; new saves are canonical. China now exposes all 34
provinces (the 8 multi-path ones became claimable — this is the intended identity completion,
not a balance change). Population values are the same frozen `gamePopulation` from
Phase 1A/1A.5, so economy behaviour is unchanged. On GitHub Pages (no backend) the frontend
resolver still yields canonical ids via the offline fallback.
