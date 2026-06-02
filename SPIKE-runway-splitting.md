# Spike: Splitting Overlapping Runway Layers into Distinct Regions

> **Type:** Spike outcome / technical note
> **Audience:** Developers implementing this in the production codebase
> **Status:** Investigated & validated in a Streamlit PoC (Python/Shapely)
> **Date:** 2026-06-02

This note captures the problem, the geometric solution, worked runway examples, and a
recommendation on which geometry libraries to use (**JTS + GeoTools** for Java,
**Shapely** for Python). It is meant as a reference for the actual implementation —
not a finished design doc.

---

## 1. Problem

At an airport, runways (and other areas) are modeled as rectangular/polygonal regions
("layers"). Runways frequently **physically cross or overlap** — e.g. a runway crossing
another, or one taxiway box overlapping a runway box.

When two or more such layers overlap, we currently have N independent boxes that share
area. We want to **decompose the overlapping set into non-overlapping regions**:

- the **exclusive part** of each runway (the area that belongs to it alone), and
- the **shared crossing zone(s)** (the area where two runways overlap).

Each resulting region must be **individually identifiable** (named) so it can be stored,
referenced, styled, and reasoned about independently.

**Why this matters:** downstream logic (capacity, lighting, surface ownership, conflict
detection, rendering) needs to treat "the part of Runway A that is shared with Runway B"
differently from "the part of Runway A that is exclusively A". A plain set of overlapping
boxes can't express that; a set of disjoint, named regions can.

---

## 2. Solution — Logic to Split Layers/Runways

The split is a **polygon boolean-operation** problem. Given a set `S` of selected layer
polygons:

### 2.1 Core idea

1. **Find every pairwise intersection.** For each unordered pair `(A, B)`, compute
   `A ∩ B`. Keep it only if it has **positive area** (touching edges = not an overlap).
   Each surviving intersection is a region named `A_B`.

2. **Compute each layer's remainder.** For each layer `L`, subtract the union of all
   intersections from it: `remainder = L − (∪ intersections)`. This is the part of `L`
   that belongs to it alone.

3. **Break the remainder into connected pieces.** Subtracting an overlap can split a
   layer into multiple disconnected polygons (e.g. a runway crossed in the middle becomes
   two end-pieces), or leave a single connected (possibly L-shaped) polygon. Each
   connected piece becomes its own output region.

4. **Name everything.**
   - Intersection regions → `LayerA_LayerB`.
   - Remainder pieces → the layer's base name if there's only one piece; otherwise a
     **positional suffix** (`_left/_right`, `_top/_middle/_bottom`) based on where the
     piece sits relative to the others.

### 2.2 Pseudocode

```
function splitLayers(S):                 # S = list of {name, polygon}
    intersections = []
    for each unordered pair (A, B) in S:
        inter = A.polygon ∩ B.polygon
        for each connected polygon piece p of inter where area(p) > 0:
            intersections.add({ name: A.name + "_" + B.name, geom: p, kind: INTERSECTION })

    if intersections is empty:
        return NO_OVERLAP                # caller shows "No overlap found"

    overlapUnion = union(all intersection geoms)

    results = []
    for each layer L in S:
        remainder = L.polygon − overlapUnion
        pieces    = connectedPieces(remainder)          # split MultiPolygon → polygons
        for (name, geom) in namePieces(pieces, L.name):
            results.add({ name: name, geom: geom, kind: ORIGINAL })

    results.addAll(intersections)
    return results
```

### 2.3 Positional naming (`namePieces`)

```
function namePieces(pieces, baseName):
    pieces = [p for p in pieces if area(p) > EPS]
    if pieces.size <= 1:
        return [(baseName, pieces[0])]        # single piece keeps base name, no suffix

    # Decide orientation from the spread of piece centroids
    spreadX = max(centroid.x) - min(centroid.x)   # longitude / east-west
    spreadY = max(centroid.y) - min(centroid.y)   # latitude  / north-south
    horizontal = spreadX >= spreadY

    if horizontal:
        sort pieces by centroid.x ascending        # west -> east
        labels = (n==2) ? [left,right] : (n==3) ? [left,middle,right] : [left, middle1.., right]
    else:
        sort pieces by centroid.y descending       # north -> south  (north = top)
        labels = (n==2) ? [top,bottom] : (n==3) ? [top,middle,bottom] : [top, middle1.., bottom]

    return zip(baseName + "_" + labels, pieces)
```

**Map orientation convention:** north = top, south = bottom, west = left, east = right.

### 2.4 Key properties & assumptions

- **Pairwise only.** Intersections are computed per pair. We assume **no three layers
  overlap at a single common point** (true triple-overlap regions are out of scope for
  the spike — see §5 caveats).
- **Remainder uses the union of all overlaps**, so a runway crossed by several others is
  correctly cut at every crossing.
- **Results are polygons, not bounding boxes** — a remainder can be L-shaped or a frame
  (polygon with a hole). Don't force outputs back into axis-aligned rectangles.
- **Counts are not fixed** — see worked examples.

### 2.5 Edge cases

| Case | Behaviour |
|---|---|
| Layers only touch at an edge (zero area) | Not an overlap (filtered by `area > 0`) |
| One layer fully inside another | Outer remainder = polygon **with a hole** (frame, 1 piece); inner remainder = empty |
| A selected layer overlaps nothing | Passes through as 1 `ORIGINAL` piece with its base name |
| Tiny slivers from FP error | Discard pieces with `area < EPS` (e.g. `1e-9`) |

---

## 3. Worked Examples (runways)

### Example A — Two runways crossing at a corner → **3 regions**
```
 ┌────────┐
 │   R1   ┌──┼─────┐      • R1        (exclusive part of R1 — L-shaped, 1 piece)
 │        │∩ │     │      • R2        (exclusive part of R2 — L-shaped, 1 piece)
 └────────┼──┘ R2  │      • R1_R2     (shared crossing zone)
          └────────┘
```

### Example B — Two runways crossing like a "plus" → **5 regions**
```
        ┌────┐
        │ R2 │             • R1_left    (R1 west of the crossing)
 ┌──────┼────┼──────┐      • R1_right   (R1 east of the crossing)
 │  R1  │ ∩  │  R1  │      • R2_top     (R2 north of the crossing)
 └──────┼────┼──────┘      • R2_bottom  (R2 south of the crossing)
        │ R2 │             • R1_R2      (shared crossing zone)
        └────┘
```
R1 (horizontal) is cut into **left/right**; R2 (vertical) into **top/bottom**; plus one intersection.

### Example C — Two parallel runways crossed by one perpendicular runway → **9 regions**
```
 ┌──────┬────┬──────┐      • H1_left, H1_right          (H1 split by the crossing)
 │  H1  │ ∩  │  H1  │      • H2_left, H2_right          (H2 split by the crossing)
 └──────┼────┼──────┘      • V_top, V_middle, V_bottom  (V cut into 3 by the 2 crossings)
 ┌──────┼────┼──────┐      • V_H1, V_H2                 (the 2 shared crossing zones)
 │  H2  │ ∩  │  H2  │
 └──────┴────┴──────┘      Total = 4 + 3 + 2 = 9 regions
```
This is the canonical "spike" scenario: the perpendicular runway `V` crosses both
horizontals, so `V` is split into **top / middle / bottom**, each horizontal into
**left / right**, and there are **two** distinct crossing zones `V_H1` and `V_H2`.

### Result-count formula
```
total = Σ(remainder pieces per layer) + (number of intersection regions)
```
Corner → 3, plus → 5, 2×1 grid → 9, etc. The number depends on the geometry, not a constant.

---

## 4. Reference Implementation (validated in the spike)

The logic was proven out in Python with **Shapely 2.x**. The essential calls:

```python
from shapely.geometry import shape, mapping
from shapely.ops import unary_union

def split_layers(selected):                 # selected: [{"name", "poly"}]
    intersections = []
    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            inter = selected[i]["poly"].intersection(selected[j]["poly"])
            for piece in _pieces(inter):     # Polygon / MultiPolygon / GeomCollection -> [Polygon]
                intersections.append({"name": f'{selected[i]["name"]}_{selected[j]["name"]}',
                                       "geom": piece, "kind": "intersection"})
    if not intersections:
        return None                          # -> "No overlap found"

    overlap = unary_union([x["geom"] for x in intersections])
    results = []
    for lyr in selected:
        remainder = lyr["poly"].difference(overlap)
        for name, geom in _name_pieces(_pieces(remainder), lyr["name"]):
            results.append({"name": name, "geom": geom, "kind": "layer"})
    results.extend(intersections)
    return results
```

`_pieces()` extracts connected polygons; `_name_pieces()` applies the positional naming
from §2.3. Boolean ops map 1:1 onto library primitives (`intersection`, `difference`,
`unary_union`).

---

## 5. Recommendation: which libraries to use

The algorithm is **library-agnostic** — it relies only on standard 2D polygon boolean
operations that every mature geometry library provides. Pick by target stack:

### 5.1 Java → **JTS Topology Suite + GeoTools** (recommended)

- **JTS (`org.locationtech.jts`)** is the de-facto standard for 2D vector geometry on the
  JVM and provides every primitive this algorithm needs:
  - `Geometry.intersection(Geometry)` → intersection
  - `Geometry.difference(Geometry)` → remainder
  - `UnaryUnionOp` / `Geometry.union()` → union of all overlaps
  - `Geometry.getNumGeometries()` / `getGeometryN(i)` → iterate connected pieces of a `MultiPolygon`
  - `Geometry.getArea()`, `getCentroid()` → area filtering & positional naming
- **GeoTools** sits on top of JTS and adds the things JTS itself doesn't: CRS handling and
  reprojection (`org.geotools.referencing`), GeoJSON/WKT/shapefile I/O
  (`org.geotools.data.geojson`), and feature modelling. Use GeoTools for **I/O + CRS**,
  JTS for **the geometry math**.

  > Note: JTS is the geometry engine *inside* GeoTools — they're designed to be used together,
  > not as alternatives. (Shapely is essentially the Python binding of the same GEOS/JTS lineage,
  > so behaviour matches closely — handy for cross-checking against the PoC.)

**JTS sketch:**
```java
import org.locationtech.jts.geom.*;
import org.locationtech.jts.operation.union.UnaryUnionOp;

// 1. Pairwise intersections
List<Named> intersections = new ArrayList<>();
for (int i = 0; i < layers.size(); i++) {
    for (int j = i + 1; j < layers.size(); j++) {
        Geometry inter = layers.get(i).geom.intersection(layers.get(j).geom);
        for (Polygon p : pieces(inter)) {                 // area > EPS only
            intersections.add(new Named(layers.get(i).name + "_" + layers.get(j).name,
                                        p, Kind.INTERSECTION));
        }
    }
}
if (intersections.isEmpty()) return Result.noOverlap();

// 2. Remainders
Geometry overlap = UnaryUnionOp.union(
        intersections.stream().map(n -> n.geom).collect(Collectors.toList()));
List<Named> results = new ArrayList<>();
for (Layer L : layers) {
    Geometry remainder = L.geom.difference(overlap);
    results.addAll(namePieces(pieces(remainder), L.name));   // positional naming
}
results.addAll(intersections);
```
where `pieces(Geometry g)` iterates `g.getGeometryN(i)` and keeps polygons with
`getArea() > EPS`, and `namePieces(...)` uses `getCentroid()` for orientation.

**Robustness tip (JTS):** for tricky inputs, wrap operations with
`GeometryPrecisionReducer` or use `OverlayNGRobust` (JTS ≥ 1.18) to avoid topology
exceptions from floating-point noise.

### 5.2 Python → **Shapely 2.x** (recommended)

- Direct primitives: `a.intersection(b)`, `a.difference(b)`, `shapely.ops.unary_union(...)`.
- Iterate `geom.geoms` for `MultiPolygon`/`GeometryCollection`; use `.area`, `.centroid`.
- Pair with **`pyproj`** if/when you need a projected CRS, and `shapely.geometry.mapping`/`shape`
  for GeoJSON I/O. This is what the spike PoC used and validated.

### 5.3 Cross-cutting recommendations (both stacks)

1. **Coordinate system.** The PoC computed in raw lon/lat degrees, which is fine for
   *topology* (intersection/difference are correct regardless of CRS) and for a single
   airport's small extent. **But** if you need accurate **area/length** of regions,
   reproject to a local projected/UTM CRS first (GeoTools `JTS.transform` + a UTM
   `CoordinateReferenceSystem`; Python `pyproj.Transformer`).
2. **Use an `EPS` area threshold** (e.g. `1e-9` in projected metres, or a small
   degree-based value) to drop slivers created by FP error.
3. **Preserve holes.** Don't assume remainders are rectangles — a contained layer yields a
   polygon with an interior ring. Keep full polygon geometry through to output/GeoJSON.
4. **Validate inputs.** Call `isValid()` / `buffer(0)` (JTS & Shapely) on self-touching or
   malformed polygons before boolean ops.
5. **Determinism.** Sort layers and pairs in a stable order so region naming
   (`A_B` vs `B_A`) is reproducible.

---

## 6. Open items / caveats for implementation

- **True 3-way overlaps** (three layers sharing one area) are **not** modeled distinctly
  by the pairwise approach — they'd appear as overlapping pairwise intersections. If the
  real data can have this, extend step 1 to compute higher-order intersections and subtract
  lower-order ones (inclusion–exclusion), or use an **overlay/noding** approach
  (JTS `OverlayNG` / a planar graph) to produce a fully-noded arrangement of faces.
- **Naming for >3 pieces** uses `middle1, middle2, …`; confirm the desired convention with
  product before finalizing.
- **Performance:** pairwise is `O(n²)` in the number of selected layers — fine for the
  handful of runways at an airport; revisit only if N grows large.

---

### TL;DR for developers
Implement the §2.2 algorithm using standard polygon boolean ops. **Java: JTS for the
geometry + GeoTools for CRS/GeoJSON I/O. Python: Shapely (+ pyproj for projected area).**
Reproject to a metric CRS if you need accurate areas; keep results as full polygons (holes
included); assume pairwise overlaps only unless the data says otherwise.
