# Territory Adjacency — curated review report (Phase 1C, Solution A)

Authoritative source = curated land borders (`world-data/curated/*.reviewed.json`). SVG geometry is cross-validation only. Land borders only; islands are legitimately isolated.


## taiwan — 22 territories, 34 edges, avg degree 3.09, 3 isolated, 4 components
- provenance: SVG geometry candidates (taiwan.svg has no transforms), reviewed: outlying-island counties (Penghu/Kinmen/Lienchiang) correctly isolated. Land borders only.
- isolated (land-border degree 0): taiwan:kinmen-county, taiwan:lienchiang-county, taiwan:penghu-county
- geometry-only edges NOT in curated (likely sea/estuary, excluded): 0
- curated-only edges (geometry missed): 0

## taipei — 12 territories, 24 edges, avg degree 4.00, 0 isolated, 1 components
- provenance: Hand-authored Taipei City district land borders (geometry unusable: districts span a transformed SVG group). Land borders only.
- isolated (land-border degree 0): none
- geometry-only edges NOT in curated (likely sea/estuary, excluded): 9 e.g. taipei:daan~taipei:datong, taipei:daan~taipei:wanhua, taipei:datong~taipei:neihu, taipei:datong~taipei:xinyi, taipei:nangang~taipei:wanhua, taipei:nangang~taipei:zhongshan, taipei:songshan~taipei:wanhua, taipei:wanhua~taipei:xinyi, taipei:xinyi~taipei:zhongshan
- curated-only edges (geometry missed): 12 e.g. taipei:daan~taipei:songshan, taipei:daan~taipei:wenshan, taipei:daan~taipei:zhongshan, taipei:datong~taipei:wanhua, taipei:datong~taipei:zhongzheng, taipei:nangang~taipei:wenshan, taipei:nangang~taipei:xinyi, taipei:shilin~taipei:zhongshan, taipei:wanhua~taipei:zhongzheng, taipei:wenshan~taipei:xinyi, taipei:wenshan~taipei:zhongzheng, taipei:zhongshan~taipei:zhongzheng

## china — 34 territories, 71 edges, avg degree 4.18, 2 isolated, 3 components
- provenance: SVG geometry candidates (china.svg has no transforms), human-reviewed: island/strait sea false-positives removed. Land borders only.
- isolated (land-border degree 0): china:pHI, china:pTW
- geometry-only edges NOT in curated (likely sea/estuary, excluded): 3 e.g. china:pFJ~china:pTW, china:pGD~china:pHI, china:pHK~china:pMO
- curated-only edges (geometry missed): 0

## world — 250 territories, 321 edges, avg degree 2.57, 90 isolated, 93 components
- provenance: Curated land-border adjacency by ISO 3166-1 alpha-2 (hand-authored from standard geography). LAND borders only: no sea/strait connections (Taiwan-China, UK-France, Japan-Korea, Australia-Indonesia are intentionally excluded). Island states/territories have no entry and are correctly isolated. Edges are symmetrised by the populate tool; listed once here. Candidate/ambiguous cases (e.g. Spanish enclaves Ceuta/Melilla es-ma) are intentionally NOT asserted.
- isolated (land-border degree 0): world:ag, world:ai, world:as, world:au, world:aw, world:ax, world:bb, world:bh, world:bl, world:bm, world:bq, world:bs, world:bv, world:cc, world:ck, world:cu, world:cv, world:cw, world:cx, world:cy, world:dm, world:do, world:fj, world:fk, world:fm, world:fo, world:gd, world:gg, world:gl, world:go, world:gp, world:gs, world:gu, world:hm, world:ht, world:im, world:io, world:is, world:je, world:jm, world:jp, world:ju, world:ki, world:km, world:kn, world:ky, world:lc, world:lk, world:mf, world:mg, world:mh, world:mp, world:mq, world:ms, world:mt, world:mu, world:mv, world:nc, world:nf, world:nr, world:nu, world:nz, world:pf, world:ph, world:pm, world:pn, world:pr, world:pw, world:re, world:sb, world:sc, world:sg, world:sh, world:sj, world:st, world:sx, world:tc, world:tf, world:tk, world:to, world:tt, world:tv, world:tw, world:vc, world:vg, world:vi, world:vu, world:wf, world:ws, world:yt
- geometry-only edges NOT in curated (likely sea/estuary, excluded): 180 e.g. world:ae~world:ir, world:ae~world:qa, world:af~world:kg, world:ag~world:ai, world:ag~world:bl, world:ag~world:bq, world:ag~world:dm, world:ag~world:gp, world:ag~world:kn, world:ag~world:mf, world:ag~world:ms, world:ag~world:sx
- curated-only edges (geometry missed): 0
