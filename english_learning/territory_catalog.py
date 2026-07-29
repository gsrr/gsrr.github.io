"""Phase 1A — canonical territory catalog loader for the backend (stdlib only).

Loads the static, reviewable catalog under world-data/ (shipped next to the app,
NOT the writable /data volume) and provides resolution helpers. The backend never
trusts catalog data sent by the client — it reads these files from disk.

    from territory_catalog import catalog
    catalog.game_population("world:us")
    catalog.canonical_from_legacy("maps/china.svg#pBJ")   # -> "china:pBJ"
"""
import json
import os

CATALOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "world-data")


class TerritoryCatalog:
    def __init__(self, base_dir=CATALOG_DIR):
        self.base_dir = base_dir
        self.maps = []                    # [{id, svgFile, name}]
        self.map_by_id = {}
        self.map_by_svg = {}              # svgFile -> mapId
        self.territories = {}             # territoryId -> territory dict
        self.by_map_path = {}             # (mapId, pathId) -> territoryId
        self.legacy_to_id = {}            # "<svgFile>#<pathId>" -> territoryId
        self.meta = {}                    # catalog.json (catalogVersion/schemaVersion/...)
        self.load_errors = []             # duplicates detected while reading raw files
        self.loaded = False

    def load(self):
        self.__init__(self.base_dir)      # reset
        try:
            self.meta = json.load(open(os.path.join(self.base_dir, "catalog.json"), encoding="utf-8"))
        except Exception:
            self.meta = {}
        self.maps = json.load(open(os.path.join(self.base_dir, "maps.json"), encoding="utf-8"))
        for m in self.maps:
            if m["id"] in self.map_by_id:
                self.load_errors.append("duplicate map id " + m["id"])
            self.map_by_id[m["id"]] = m
            self.map_by_svg[m["svgFile"]] = m["id"]
        for m in self.maps:
            path = os.path.join(self.base_dir, "territories", m["id"] + ".json")
            for t in json.load(open(path, encoding="utf-8")):
                tid = t["id"]
                if tid in self.territories:
                    self.load_errors.append("duplicate territory id " + tid)
                self.territories[tid] = t
                for pk in t.get("svgPathKeys") or []:
                    if (m["id"], pk) in self.by_map_path:
                        self.load_errors.append("duplicate svg path mapping %s|%s" % (m["id"], pk))
                    self.by_map_path[(m["id"], pk)] = tid
                    self.legacy_to_id[m["svgFile"] + "#" + pk] = tid
        self.loaded = True
        return self

    def _ensure(self):
        if not self.loaded:
            self.load()

    # --- validation (returns list of error strings; empty = ok) ---
    def validate(self):
        errs = list(self.load_errors)     # duplicates found while reading raw files
        cat_schema = self.meta.get("schemaVersion")
        if cat_schema is None:
            errs.append("catalog.json missing schemaVersion")
        # orphan map: a declared map with no territories
        maps_with_terr = set(t.get("mapId") for t in self.territories.values())
        for m in self.maps:
            if m["id"] not in maps_with_terr:
                errs.append("orphan map (no territories): " + m["id"])
        schema_versions = set()
        for tid, t in self.territories.items():
            if not tid.startswith(t.get("mapId", "") + ":"):
                errs.append(tid + ": id must start with mapId")
            if t.get("mapId") not in self.map_by_id:
                errs.append(tid + ": unknown map " + str(t.get("mapId")))
            if not (t.get("svgPathKeys") or []):
                errs.append(tid + ": no svgPathKeys (orphan territory)")
            gp = t.get("gamePopulation")
            if not isinstance(gp, int) or gp < 0:
                errs.append(tid + ": bad gamePopulation")
            meta = t.get("_meta")
            if not isinstance(meta, dict):
                errs.append(tid + ": missing _meta ownership block")
                continue
            sv = meta.get("schemaVersion")
            if sv is None:
                errs.append(tid + ": _meta.schemaVersion missing")
            else:
                schema_versions.add(sv)
                if cat_schema is not None and sv != cat_schema:
                    errs.append(tid + ": schemaVersion %r != catalog %r" % (sv, cat_schema))
            if not meta.get("generatorVersion"):
                errs.append(tid + ": _meta.generatorVersion missing")
        if len(schema_versions) > 1:
            errs.append("mixed schema versions: " + str(sorted(schema_versions)))
        return errs

    # --- resolution helpers ---
    def canonical_from_legacy(self, key):
        """'maps/world.svg#us' -> 'world:us' (or None if unknown)."""
        self._ensure()
        if not key:
            return None
        if key in self.legacy_to_id:
            return self.legacy_to_id[key]
        if "#" in key:                                   # fall back: parse & resolve by (map, path)
            svg, pid = key.rsplit("#", 1)
            map_id = self.map_by_svg.get(svg)
            if map_id is not None:
                return self.by_map_path.get((map_id, pid))
        return None

    def legacy_keys_for(self, territory_id):
        self._ensure()
        t = self.territories.get(territory_id)
        if not t:
            return []
        m = self.map_by_id.get(t["mapId"])
        if not m:
            return []
        return [m["svgFile"] + "#" + pk for pk in t.get("svgPathKeys") or []]

    def territory_for_path(self, map_id, path_id):
        self._ensure()
        return self.territories.get(self.by_map_path.get((map_id, path_id)))

    def is_canonical(self, key):
        self._ensure()
        return key in self.territories

    def map_of(self, territory_id):
        self._ensure()
        t = self.territories.get(territory_id)
        return t["mapId"] if t else None

    def resolve_any(self, key):
        """Resolve ANY identifier to a canonical territory id (or None).
        Accepts a canonical id ('china:pLN'), a legacy key ('maps/china.svg#pLN_1'),
        or 'mapId#pathId'. Never guesses — unknown -> None (caller decides)."""
        self._ensure()
        if not key:
            return None
        if key in self.territories:
            return key
        if "#" in key:
            resolved = self.canonical_from_legacy(key)
            if resolved:
                return resolved
            left, pid = key.rsplit("#", 1)          # also allow 'mapId#pathId'
            if left in self.map_by_id:
                return self.by_map_path.get((left, pid))
        return None

    def game_population(self, territory_id):
        self._ensure()
        t = self.territories.get(territory_id)
        return t.get("gamePopulation") if t else None

    # ---- World-Domain adjacency graph (topology only; NOT game attack rules) ----
    def neighbors(self, territory_id):
        self._ensure()
        t = self.territories.get(territory_id)
        return list(t.get("adjacentTerritoryIds") or []) if t else []

    def are_adjacent(self, a, b):
        self._ensure()
        return b in (self.territories.get(a, {}).get("adjacentTerritoryIds") or [])

    def degree(self, territory_id):
        return len(self.neighbors(territory_id))

    def connected_component(self, territory_id):
        """Set of territory ids reachable from territory_id via adjacency (same map)."""
        self._ensure()
        if territory_id not in self.territories:
            return set()
        seen, stack = set(), [territory_id]
        while stack:
            u = stack.pop()
            if u in seen:
                continue
            seen.add(u)
            stack.extend(n for n in self.neighbors(u) if n not in seen)
        return seen

    def map_components(self, map_id):
        """List of connected components (lists of ids) for a map."""
        self._ensure()
        ids = [tid for tid, t in self.territories.items() if t.get("mapId") == map_id]
        seen, comps = set(), []
        for t in ids:
            if t in seen:
                continue
            c = self.connected_component(t)
            comps.append(sorted(c))
            seen |= c
        return comps

    def child_maps(self, map_id):
        self._ensure()
        return list((self.map_by_id.get(map_id) or {}).get("childMaps") or [])

    def count_per_map(self):
        self._ensure()
        out = {}
        for t in self.territories.values():
            out[t["mapId"]] = out.get(t["mapId"], 0) + 1
        return out


# module-level singleton (lazy)
catalog = TerritoryCatalog()


if __name__ == "__main__":
    catalog.load()
    errs = catalog.validate()
    print("territory catalog:", catalog.count_per_map(), "| total", len(catalog.territories))
    if errs:
        print("INVALID:")
        for e in errs[:50]:
            print("  -", e)
        raise SystemExit(1)
    print("OK · legacy sample:", "maps/china.svg#pBJ ->", catalog.canonical_from_legacy("maps/china.svg#pBJ"))
