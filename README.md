# 🛰️ Airport Runway Splitter

A small Streamlit app: type to search for any airport, jump to a satellite view
of it, draw and name bounding-box layers, and split overlapping layers into their
non-overlapping pieces and shared intersections.

## Features
- **Type-ahead search** over ~7,800 airports (by IATA/ICAO code, name, or city) — offline, no API needed.
- **Satellite basemaps** — Google Satellite, Google Hybrid, or Esri World Imagery (no API key required).
- **Draw bounding-box layers** — use the rectangle/polygon tool to draw on the map. Each shape is captured as a layer, auto-named `Layer 1`, `Layer 2`, …
- **Named, labelled layers** — rename any layer in the table; its label is shown as a badge on the map. Download all layers as GeoJSON.
- **Split Runway Layers** — select two or more overlapping layers and split them into separate, named pieces plus their shared intersection(s).

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/streamlit run app.py
```

The app opens at http://localhost:8501.

## Usage
1. Search for an airport in the box (e.g. `JFK`, `Heathrow`, `Tokyo`).
2. The satellite map centers on it. Pick a basemap in the sidebar.
3. Click the **▭ rectangle tool** (top-left of the map) and drag to draw a box. It becomes a named layer with a label badge on the map.
4. Manage layers in the **Bounding box layers** table — rename via the **Label** column, tick **Select** to choose layers, and download all layers as GeoJSON.

## Split Runway Layers

Tick **Select** on two or more layers, then click **✂️ Split Runway Layers**:

- If the selected layers don't overlap → **"No overlap found."**
- If they overlap → each layer's non-overlapping remainder is broken into pieces
  (named by position — `_left` / `_right`, `_top` / `_middle` / `_bottom`), and each
  shared overlap becomes its own piece named `LayerA_LayerB`.

The number of resulting pieces depends on how the layers overlap:

| Overlap type | Result |
|---|---|
| Corner overlap of 2 layers | **3** pieces — `Layer1`, `Layer2`, `Layer1_Layer2` |
| Crossing ("plus") of 2 layers | **5** pieces — `H_left`, `H_right`, `V_top`, `V_bottom`, `H_V` |
| 2 parallel + 1 crossing layer | **9** pieces — `H1_left/right`, `H2_left/right`, `V_top/middle/bottom`, `H1_V`, `H2_V` |

> Assumes intersections are strictly pairwise (no three layers overlapping at the same point).

Results appear below the main map as:
- A **table** of each piece's label, type (Original / Intersection), and polygon vertices.
- A **separate map** rendering the pieces — 🟦 originals in blue, 🟥 intersections in red, each labelled — plus a **Download split GeoJSON** button.

## Dependencies
`streamlit`, `streamlit-folium`, `folium`, `airportsdata`, `shapely` (see [requirements.txt](requirements.txt)).
