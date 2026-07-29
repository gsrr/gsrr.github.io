# world-data — authoritative world database

`world-data/` is **production content**. Treat it like source code / game assets, not a
build artifact. Future systems read territory information **only** from here, and future
changes are made through **explicit migrations, `--merge`, or designer edits** — never by
regenerating from scratch (unless the developer explicitly asks).

## Purpose

The single source of truth for:

- territory identity (`<mapId>:<regionCode>`)
- map identity
- game population (`gamePopulation`)
- display names / localization
- future world metadata (reserved placeholders — see below)

## Directory layout

```
world-data/
  catalog.json                 catalog + schema version, counts, timestamps
  maps.json                    [ {id, svgFile, name} ]
  territories/
    taiwan.json                [ territory, ... ]
    taipei.json
    china.json
    world.json
```

## Versioning

- `catalog.json.catalogVersion` — bumped when the data set changes shape meaningfully.
- `catalog.json.schemaVersion` — the object schema version. **Every** territory carries
  `_meta.schemaVersion`; the validator rejects a catalog whose territories disagree with
  each other or with `catalog.json` (no mixed schema versions).
- Current: **catalogVersion 1, schemaVersion 1**.

## Ownership

Each territory has a `_meta` block describing provenance:

```json
"_meta": {
  "schemaVersion": 1, "catalogVersion": 1,
  "generatedBy": "tools/gen_territory_catalog.js",
  "generatedAt": "<iso>", "generatorVersion": "1.0.0",
  "lastDesignerEdit": null
}
```

**Generator owns** (may create/repair): new territory discovery, `svgPathKeys` (SVG mapping),
`regionCode`/`mapId`, `administrativeCode`, `metadata.continent`, the *initial* population
freeze and *initial* display names, and the structural `_meta` version fields.

**Designer owns** (generator must NEVER overwrite): `gamePopulation` edits, `displayName` /
`localizedNames` edits, `terrainType`, `settlementType`, `features`, `adjacentTerritoryIds`,
`economy`, `quests`, `ai`, `events`, and `_meta.lastDesignerEdit`. When you hand-edit a
territory, set `_meta.lastDesignerEdit` to a timestamp; the generator preserves it.

## Generator (`tools/gen_territory_catalog.js`)

Bootstrap / sync only. Reads `maps/*.svg` + freezes population from `index.html`'s `popForName`.

| Mode | Writes? | Behaviour |
|---|---|---|
| `--check` (default) | no | Report missing / obsolete / duplicate / unknown territories. Non-zero exit on drift. |
| `--init` | creates only | Create territory files that do **not** exist. Never touches an existing file. |
| `--merge` | edits | Add newly-discovered territories; repair `svgPathKeys` to match the SVG; back-fill any missing schema/placeholder fields; **preserve every designer field**. |

`TERR_CATALOG_DIR=<dir>` overrides the output directory (used by tests).

## Merge strategy

Priority: **designer edits > generator defaults.** On `--merge`, for an existing territory the
generator only *adds missing* fields and *refreshes structural* fields (`svgPathKeys`, `_meta`
version numbers). It never replaces a present designer-authored value. If a territory’s SVG
paths disappear, its `svgPathKeys` are cleared and the record is **kept and reported** for
designer review — never silently deleted.

## Validation

`python3 tools/validate_territory_catalog.py` (stdlib only, non-zero exit on error) checks:
unique map/territory ids, id ⟶ mapId prefix, valid map refs, ≥1 svgPathKey, non-negative
integer `gamePopulation`, no fabricated `populationSource` provenance, `localizedNames`
objects, no duplicate region codes / SVG mappings, all rendered SVG regions represented,
placeholders still empty/null, `_meta` present with `generatorVersion`, `schemaVersion`
matching `catalog.json`, and **no mixed schema versions**.

The backend loader (`territory_catalog.py`) performs an equivalent validation at startup
(logged, non-fatal) and never trusts catalog data sent by the client.

## Future extension points (reserved — do not populate yet)

`terrainType`, `settlementType`, `features`, `adjacentTerritoryIds`, `economy`, `quests`,
`ai`, `events`. These exist so future phases extend the schema in place rather than inventing
parallel world-metadata stores elsewhere. Adding real values to them is a **designer/migration**
action and must bump `schemaVersion` if the shape changes.
