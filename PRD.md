# Product Requirements Document — Airport Runway Splitter

| | |
|---|---|
| **Product** | Airport Runway Splitter |
| **Type** | Streamlit web app (proof-of-concept) |
| **Owner** | atul.mehra@foreflight.com |
| **Status** | PoC — functional |
| **Last updated** | 2026-06-02 |

---

## 1. Overview

Airport Runway Splitter is a single-page Streamlit application for visually
defining rectangular/polygonal regions ("layers") over an airport's satellite
imagery and then **splitting overlapping layers into their distinct
non-overlapping parts and shared intersection regions**.

The motivating use case: an airport has runways (and other areas) that physically
cross or overlap. A user draws a bounding box per runway, and the app
decomposes the overlapping set into clean, individually-named regions — the
exclusive part of each runway plus the shared crossing area — which can then be
inspected, exported as GeoJSON, and visualized.

---

## 2. Goals & Non-Goals

### Goals
- Let a user find any airport and view it on satellite imagery.
- Let a user draw, name, label, and manage rectangular/polygon **layers** on the map.
- **Split** a selected set of overlapping layers into:
  - the non-overlapping remainder of each layer (broken into positionally-named pieces), and
  - each pairwise intersection region (named after the two layers that form it).
- Present the split result as both a **table** and a **dedicated map**, and allow **GeoJSON export**.

### Non-Goals (current PoC)
- Production-grade, licensed map tiles (uses unofficial Google tiles / Esri for now).
- Persisting layers across sessions or users (state lives in the Streamlit session only).
- Handling **three or more layers overlapping at the same point** (assumed not to occur).
- Editing/deleting individual drawn shapes from Python (relies on the draw tool's own controls).
- Authentication, multi-user, or backend storage.

---

## 3. Users & Use Cases

- **Primary user:** an engineer/analyst modeling airport runway geometry.
- **Use case 1:** Capture a bounding box per runway/area and export coordinates.
- **Use case 2:** Given two or more overlapping runway boxes, obtain the exclusive
  segments of each runway plus the shared crossing zone, each as a named region.

---

## 4. Functional Requirements

### 4.1 Airport search & map
- FR-1: Type-ahead search across ~7,800 airports (offline dataset), by IATA/ICAO/name/city.
- FR-2: On selection, center a satellite map on the airport and show IATA/ICAO/elevation/coordinates.
- FR-3: Sidebar basemap selector (Google Satellite, Google Hybrid, Esri World Imagery) and zoom.

### 4.2 Layer drawing & management
- FR-4: A rectangle/polygon draw tool adds shapes; each shape becomes a **layer**.
- FR-5: Each layer is auto-named `Layer 1`, `Layer 2`, … and shown as a label badge on the map.
- FR-6: A table lists all layers with an editable **Label**, read-only bbox coordinates, and a **Select** checkbox.
- FR-7: All layers are exportable as a GeoJSON `FeatureCollection`.

### 4.3 Split Runway Layers
- FR-8: A **✂️ Split Runway Layers** button is enabled when ≥1 layer is selected; it requires ≥2 selected to act.
- FR-9: If no two selected layers overlap → display **"No overlap found."**
- FR-10: Otherwise, produce the split output per the algorithm in §5.
- FR-11: Render the split result as (a) a table of label/type/vertices and (b) a separate map (originals blue, intersections red, with labels), plus a GeoJSON download.
- FR-12: The main map, main table, and existing features are **not** affected by the split.

---

## 5. Core Splitting Logic (detailed)

This section is the heart of the product.

### 5.1 Definitions

- **Layer** — a user-drawn region, represented internally as a polygon (axis-aligned
  rectangle in the common case, but any simple polygon is supported).
- **Intersection region** — the geometric overlap (`A ∩ B`) of two layers, where it has positive area.
- **Remainder** — for a layer `L`, the part left after removing every intersection it
  participates in: `L − (union of all intersection regions touching L)`.
- **Piece** — a single connected polygon. A remainder may consist of one piece (e.g. an
  L-shape) or several disconnected pieces (e.g. the two ends of a runway crossed in the middle).

### 5.2 Inputs / Outputs

- **Input:** a set `S` of ≥2 selected layers, each `{name, polygon}`.
- **Output:** an ordered list of result regions, each `{name, kind, geometry}` where
  `kind ∈ {original, intersection}`; or the sentinel **"No overlap found"** when no
  pair in `S` overlaps.

### 5.3 Algorithm

```
function split(S):                              # S = list of {name, polygon}
    intersections = []
    for each unordered pair (A, B) in S:
        inter = A.polygon ∩ B.polygon
        for each connected polygon piece p of inter with area > 0:
            intersections.add({ name: f"{A.name}_{B.name}", geom: p, kind: intersection })

    if intersections is empty:
        return "No overlap found"

    overlapUnion = geometric union of all intersection geoms

    results = []
    for each layer L in S:
        remainder = L.polygon − overlapUnion          # boolean difference
        pieces = connected polygon pieces of remainder
        for (name, geom) in namePieces(pieces, L.name):   # see §5.4
            results.add({ name, geom, kind: original })

    results.add(all intersections)
    return results
```

Key properties:
- Intersections are computed **pairwise** (every unordered pair). Three-way common
  overlap at a single point is assumed not to occur (Non-Goal).
- The remainder is computed against the **union of all** intersections touching the layer,
  so a layer crossed by multiple others is correctly split at each crossing.
- All geometry operations (`∩`, `−`, `union`, connected-component extraction) use the
  **Shapely** library.

### 5.4 Positional naming of remainder pieces (`namePieces`)

When a layer's remainder splits into **2+ pieces**, each piece is given a positional
suffix; a **single** remainder piece keeps the layer's plain name (no suffix).

Orientation is decided by comparing the **spread of piece centroids**:
- If the centroids are spread **more in longitude (east–west)** than latitude →
  the pieces are arranged **horizontally**.
- Otherwise → arranged **vertically**.

Map orientation convention: **north = top, south = bottom, west = left, east = right.**

| Pieces | Horizontal layout | Vertical layout |
|---|---|---|
| 1 | *(keeps base name, no suffix)* | *(keeps base name, no suffix)* |
| 2 | `_left`, `_right` | `_top`, `_bottom` |
| 3 | `_left`, `_middle`, `_right` | `_top`, `_middle`, `_bottom` |
| n>3 | `_left`, `_middle1…`, `_right` | `_top`, `_middle1…`, `_bottom` |

Pieces are sorted along the dominant axis (west→east for horizontal, north→south for
vertical) before labels are assigned.

### 5.5 Intersection naming

Each intersection region is named `{LayerA}_{LayerB}` using the two layers that produce
it (in selection order). Because overlaps are pairwise and two convex rectangles overlap
in at most one region, names are unique. Example: a vertical runway `V` crossing two
horizontal runways `H1`, `H2` yields intersections `V_H1` and `V_H2` (distinct).

### 5.6 Worked examples

**A. Corner overlap of two boxes → 3 regions**
```
 ┌────────┐
 │   L1   ┌──┼─────┐     Result:
 │        │∩ │     │       • L1          (original, L-shaped remainder — 1 piece)
 └────────┼──┘ L2  │       • L2          (original, L-shaped remainder — 1 piece)
          └────────┘       • L1_L2       (intersection)
```

**B. Crossing / "plus" overlap → 5 regions**
```
        ┌────┐
        │ L2 │            Result:
 ┌──────┼────┼──────┐       • L1_left     (original)
 │  L1  │ ∩  │  L1  │       • L1_right    (original)
 └──────┼────┼──────┘       • L2_top      (original)
        │ L2 │              • L2_bottom   (original)
        └────┘              • L1_L2       (intersection)
```

**C. Two parallel horizontals + one vertical crossing both → 9 regions**
```
 ┌──────┬────┬──────┐      Result:
 │  H1  │ ∩  │  H1  │        • H1_left, H1_right       (originals)
 └──────┼────┼──────┘        • H2_left, H2_right       (originals)
 ┌──────┼────┼──────┐        • V_top, V_middle, V_bottom (originals)
 │  H2  │ ∩  │  H2  │        • V_H1, V_H2              (intersections)
 └──────┴────┴──────┘
                            The vertical runway is cut into 3 pieces (top/middle/bottom);
                            each horizontal into 2 (left/right); 2 crossing zones.
```

### 5.7 Result count

The number of output regions is **not fixed** — it depends on how the selected layers
overlap (corner → 3, crossing → 5, 2+1 grid → 9, etc.). The general formula:

```
total = (sum over layers of #remainder-pieces) + (#intersection regions)
```

### 5.8 Edge cases & rules

- **Edge-touching only (zero-area overlap):** treated as **no overlap** (filtered by area > 0).
- **One layer fully inside another:** the outer remainder is a polygon **with a hole**
  (a frame) — kept as a single piece; the inner layer's remainder is empty (fully consumed).
- **A selected layer overlapping nothing:** passes through unchanged as one `original` piece with its base name.
- **Non-rectangular results:** remainders may be L-shaped or otherwise non-rectangular
  polygons; outputs are stored as GeoJSON polygons (not forced into bounding boxes).
- **Degenerate slivers:** pieces with negligible area (`< 1e-12`) are discarded.

---

## 6. UX / Output Presentation

- **Results table** (below the main UI): `Label`, `Type` (Original/Intersection), `Coordinates (lat,lon)` (polygon vertices).
- **Results map** (below the table): each region rendered as a polygon —
  **🟦 blue** for originals, **🟥 red** for intersections — each with a label badge;
  auto-fit to the result bounds; uses the selected satellite basemap.
- **Download split GeoJSON** and **Clear split output** controls.
- Split output is scoped to the airport it was computed for (cleared when the airport changes).

---

## 7. Technical Notes

- **Stack:** Streamlit, streamlit-folium + Folium (Leaflet), Shapely (geometry ops), airportsdata (offline airport data), pandas.
- **Geometry:** all boolean operations via Shapely 2.x; coordinates in EPSG:4326 (lon/lat).
  Operations are performed in raw degrees — acceptable for the small spatial extents
  of a single airport; a projected CRS would be required for precise area/length at scale.
- **State:** layers, names, and split results are held in `st.session_state`.
- **Map tiles:** unofficial Google tile endpoints / Esri World Imagery; **not** licensed
  for production (see Risks).

---

## 8. Risks & Assumptions

- **R-1 (licensing):** Google tile endpoints used are undocumented and violate Google's
  ToS for production; acceptable for PoC only. Mitigation: switch default to Esri or adopt the official Map Tiles API.
- **R-2 (pairwise assumption):** Logic assumes no 3+ layers share a single overlap point.
  A true 3-way common region would currently be represented via overlapping pairwise
  intersections rather than a distinct triple region.
- **R-3 (planar degrees):** Geometry math in lat/lon degrees introduces minor distortion;
  negligible at airport scale.
- **R-4 (session-only state):** Refreshing the browser loses drawn layers and results.

---

## 9. Future Enhancements

- Wire up layer **deletion** (table + map) with app-owned geometry.
- **Per-layer colors** for originals.
- Official **Map Tiles API** basemap (key via `st.secrets`, session-token flow).
- Persist layers/results (save & reload projects).
- Support explicit **3-way intersection** regions if the use case requires it.
- Show area/length of each region (in a projected CRS).
