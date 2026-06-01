"""Airport Runway Splitter.

A small Streamlit app: search for an airport by typing, jump to a satellite
view of it, then draw a bounding box on the map to capture its coordinates.
"""

import json

import airportsdata
import folium
import pandas as pd
import streamlit as st
from folium.plugins import Draw
from shapely.geometry import mapping, shape
from shapely.ops import unary_union
from streamlit_folium import st_folium

st.set_page_config(page_title="Airport Runway Splitter", page_icon="🛰️", layout="wide")

# Satellite basemaps usable as Folium tile layers (no API key required).
TILE_SOURCES = {
    "Google Satellite": (
        "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        "Google",
    ),
    "Google Hybrid": (
        "https://mt1.google.com/vt/lyrs=y&x={x}&y={y}&z={z}",
        "Google",
    ),
    "Esri World Imagery": (
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics",
    ),
}


@st.cache_data
def load_airports():
    """Load airports keyed by a searchable label -> airport dict."""
    raw = airportsdata.load("IATA")  # dict keyed by IATA code
    options = {}
    for code, a in raw.items():
        if not code:
            continue
        if a.get("lat") in (None, 0) and a.get("lon") in (None, 0):
            continue
        label = f"{code} — {a['name']} ({a['city']}, {a['country']})"
        options[label] = a
    return dict(sorted(options.items()))


def bbox_from_drawing(drawing):
    """Return (south, west, north, east) from a drawn GeoJSON feature, or None."""
    if not drawing:
        return None
    geom = drawing.get("geometry", {})
    if geom.get("type") != "Polygon":
        return None
    ring = geom["coordinates"][0]  # list of [lon, lat]
    lons = [pt[0] for pt in ring]
    lats = [pt[1] for pt in ring]
    return min(lats), min(lons), max(lats), max(lons)


def bbox_key(bbox):
    """Stable, content-based key for a bounding box (used to remember its name)."""
    south, west, north, east = bbox
    return f"{south:.5f},{west:.5f},{north:.5f},{east:.5f}"


def badge_html(text, bg="rgba(0,0,0,.65)"):
    """HTML for a small map label badge centered above a point."""
    return (
        '<div style="display:inline-block;transform:translate(-50%,-120%);'
        f"font-size:12px;font-weight:600;color:#fff;background:{bg};"
        'padding:1px 6px;border-radius:6px;white-space:nowrap">'
        f"{text}</div>"
    )


def _polygon_pieces(geom):
    """Connected polygon pieces of a shapely geometry (drops slivers/empties)."""
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    if geom.geom_type in ("MultiPolygon", "GeometryCollection"):
        return [g for g in geom.geoms if g.geom_type == "Polygon" and g.area > 1e-12]
    return []


def _piece_labels(n, horizontal):
    """Positional suffixes for n pieces laid out horizontally or vertically."""
    presets = (
        {2: ["left", "right"], 3: ["left", "middle", "right"]}
        if horizontal
        else {2: ["top", "bottom"], 3: ["top", "middle", "bottom"]}
    )
    if n in presets:
        return presets[n]
    first, last = ("left", "right") if horizontal else ("top", "bottom")
    return [first] + [f"middle{i}" for i in range(1, n - 1)] + [last]


def _name_pieces(pieces, base_name):
    """Assign positional names (left/right/top/middle/bottom) to a layer's pieces."""
    pieces = [p for p in pieces if p.area > 1e-12]
    if len(pieces) <= 1:
        return [(base_name, p) for p in pieces]
    cxs = [p.centroid.x for p in pieces]  # longitude
    cys = [p.centroid.y for p in pieces]  # latitude
    horizontal = (max(cxs) - min(cxs)) >= (max(cys) - min(cys))
    if horizontal:
        order = sorted(range(len(pieces)), key=lambda i: cxs[i])  # west -> east
    else:
        order = sorted(range(len(pieces)), key=lambda i: -cys[i])  # north -> south
    labels = _piece_labels(len(pieces), horizontal)
    return [(f"{base_name}_{labels[rank]}", pieces[idx]) for rank, idx in enumerate(order)]


def split_runway_layers(selected):
    """Split overlapping layers into non-overlapping pieces + intersection regions.

    `selected` is a list of {"name": str, "poly": shapely polygon}. Returns a list
    of {"name", "kind", "geom"} (kind = "layer" or "intersection"), or None if
    no two layers overlap. Assumes intersections are strictly pairwise.
    """
    intersections = []
    for i in range(len(selected)):
        for j in range(i + 1, len(selected)):
            inter = selected[i]["poly"].intersection(selected[j]["poly"])
            for piece in _polygon_pieces(inter):
                intersections.append(
                    {
                        "name": f'{selected[i]["name"]}_{selected[j]["name"]}',
                        "geom": piece,
                        "kind": "intersection",
                    }
                )
    if not intersections:
        return None

    overlap_union = unary_union([x["geom"] for x in intersections])
    results = []
    for lyr in selected:
        remainder = lyr["poly"].difference(overlap_union)
        for name, geom in _name_pieces(_polygon_pieces(remainder), lyr["name"]):
            results.append({"name": name, "kind": "layer", "geom": geom})
    results.extend(intersections)
    return results


# --- Sidebar -----------------------------------------------------------------
st.sidebar.title("🛰️ Settings")
basemap = st.sidebar.selectbox("Satellite basemap", list(TILE_SOURCES.keys()))
zoom = st.sidebar.slider("Zoom", min_value=8, max_value=20, value=15)

# --- Main --------------------------------------------------------------------
st.title("🛰️ Airport Runway Splitter")
st.caption("Search for an airport, then draw a rectangle to capture a bounding box.")

airports = load_airports()
choice = st.selectbox(
    "Search for an airport (type a code, name, or city)",
    options=list(airports.keys()),
    index=None,
    placeholder="e.g. JFK, Heathrow, Tokyo…",
)

if not choice:
    st.info("👆 Start typing in the search box to find an airport.")
    st.stop()

a = airports[choice]
lat, lon = float(a["lat"]), float(a["lon"])

c1, c2, c3, c4 = st.columns(4)
c1.metric("IATA", a["iata"] or "—")
c2.metric("ICAO", a["icao"] or "—")
c3.metric("Elevation (ft)", a.get("elevation") or "—")
c4.metric("Center", f"{lat:.3f}, {lon:.3f}")

tiles_url, attr = TILE_SOURCES[basemap]
m = folium.Map(location=[lat, lon], zoom_start=zoom, tiles=tiles_url, attr=attr, control_scale=True)
folium.Marker(
    [lat, lon], tooltip=a["name"], icon=folium.Icon(color="red", icon="plane", prefix="fa")
).add_to(m)

# Drawing toolbar — restrict to rectangle (and polygon) for bounding boxes.
Draw(
    draw_options={
        "rectangle": True,
        "polygon": True,
        "polyline": False,
        "circle": False,
        "circlemarker": False,
        "marker": False,
    },
    edit_options={"edit": True, "remove": True},
).add_to(m)

# Label annotations rendered on top of the drawn boxes. Built from the previous
# run's state (the drawn geometry is only known *after* st_folium returns), and
# passed via feature_group_to_add so labels update without resetting zoom/pan.
label_fg = folium.FeatureGroup(name="labels")
for lat_a, lon_a, text in st.session_state.get("annotations", []):
    folium.Marker(
        [lat_a, lon_a],
        icon=folium.DivIcon(
            icon_size=(0, 0),
            icon_anchor=(0, 0),
            html=(
                '<div style="display:inline-block;transform:translate(-50%,-120%);'
                "font-size:12px;font-weight:600;color:#fff;background:rgba(0,0,0,.65);"
                'padding:1px 6px;border-radius:6px;white-space:nowrap">'
                f"{text}</div>"
            ),
        ),
    ).add_to(label_fg)

st.markdown("**Draw a rectangle** on the map (▭ icon, top-left) to capture its bounding box.")
map_state = st_folium(
    m,
    width=None,
    height=620,
    returned_objects=["last_active_drawing", "all_drawings"],
    feature_group_to_add=label_fg,
    key=f"map-{choice}",
)

# --- Bounding box layers -----------------------------------------------------
names = st.session_state.setdefault("layer_names", {})  # bbox_key -> label
counter = st.session_state.setdefault("layer_counter", 0)

drawings = (map_state or {}).get("all_drawings") or []
layers = []
for d in drawings:
    bbox = bbox_from_drawing(d)
    if not bbox:
        continue
    key = bbox_key(bbox)
    if key not in names:
        st.session_state.layer_counter += 1
        names[key] = f"Layer {st.session_state.layer_counter}"
    layers.append({"key": key, "bbox": bbox, "feature": d})

st.subheader("📦 Bounding box layers")
if not layers:
    st.info("No boxes drawn yet. Use the ▭ rectangle tool on the map to add layers.")
else:
    st.caption("Edit a **Label** to rename a layer. Tick **Select** to choose layers. Coordinates are read-only.")
    df = pd.DataFrame(
        [
            {
                "Select": False,
                "Label": names[lyr["key"]],
                "North": round(lyr["bbox"][2], 6),
                "South": round(lyr["bbox"][0], 6),
                "East": round(lyr["bbox"][3], 6),
                "West": round(lyr["bbox"][1], 6),
            }
            for lyr in layers
        ]
    )
    edited = st.data_editor(
        df,
        hide_index=True,
        use_container_width=True,
        disabled=["North", "South", "East", "West"],
        column_config={
            "Select": st.column_config.CheckboxColumn("Select", default=False),
            "Label": st.column_config.TextColumn("Label", required=True),
        },
        key=f"editor-{choice}",
    )
    # Persist any renamed labels back to session state.
    for lyr, label in zip(layers, edited["Label"]):
        names[lyr["key"]] = label

    # Split overlapping selected layers into separate pieces + intersections.
    any_selected = bool(edited["Select"].any())
    if st.button(
        "✂️ Split Runway Layers",
        disabled=not any_selected,
        key=f"split-{choice}",
    ):
        selected_layers = [
            {"name": names[lyr["key"]], "poly": shape(lyr["feature"]["geometry"])}
            for i, lyr in enumerate(layers)
            if bool(edited["Select"].iloc[i])
        ]
        if len(selected_layers) < 2:
            st.warning("Select at least two layers to split.")
        else:
            res = split_runway_layers(selected_layers)
            st.session_state.split_choice = choice
            if res is None:
                st.session_state.split_results = []
                st.session_state.split_msg = "No overlap found."
            else:
                st.session_state.split_results = [
                    {"name": r["name"], "kind": r["kind"], "geometry": mapping(r["geom"])}
                    for r in res
                ]
                st.session_state.split_msg = None
            st.rerun()

    # Build a named FeatureCollection for export.
    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": lyr["feature"]["geometry"],
                "properties": {
                    "label": names[lyr["key"]],
                    "airport": a["iata"] or a["icao"],
                    "south": lyr["bbox"][0],
                    "west": lyr["bbox"][1],
                    "north": lyr["bbox"][2],
                    "east": lyr["bbox"][3],
                },
            }
            for lyr in layers
        ],
    }
    dl, clr = st.columns([1, 1])
    dl.download_button(
        "⬇️ Download GeoJSON",
        data=json.dumps(fc, indent=2),
        file_name=f"{(a['iata'] or a['icao'] or 'airport').lower()}_bboxes.geojson",
        mime="application/geo+json",
        use_container_width=True,
    )
    if clr.button("🗑️ Clear saved labels", use_container_width=True):
        st.session_state.layer_names = {}
        st.session_state.layer_counter = 0
        st.rerun()

    with st.expander("View GeoJSON"):
        st.code(json.dumps(fc, indent=2), language="json")

# Recompute the on-map label annotations (position = north edge, centered).
# If they differ from what we rendered this run (new box, deleted box, or a
# renamed label), update state and rerun so the map labels catch up.
desired = [
    (
        round(lyr["bbox"][2], 6),  # north
        round((lyr["bbox"][1] + lyr["bbox"][3]) / 2, 6),  # center lon
        names[lyr["key"]],
    )
    for lyr in layers
]
if desired != st.session_state.get("annotations", []):
    st.session_state.annotations = desired
    st.rerun()

# --- Split Runway Layers output ----------------------------------------------
# Shown only for the airport the split was computed for. Renders a results table
# and a separate map below; the main map above is untouched.
if st.session_state.get("split_choice") == choice:
    split_results = st.session_state.get("split_results") or []
    split_msg = st.session_state.get("split_msg")

    if split_msg or split_results:
        st.divider()
        st.subheader("✂️ Split Runway Layers — result")

    if split_msg:
        st.info(split_msg)
    elif split_results:
        # Results table: label, type, and the piece's polygon vertices (lat,lon).
        rows = []
        for r in split_results:
            ring = r["geometry"]["coordinates"][0]
            verts = " | ".join(f"{lat:.6f},{lon:.6f}" for lon, lat in ring[:-1])
            rows.append(
                {
                    "Label": r["name"],
                    "Type": "Intersection" if r["kind"] == "intersection" else "Original",
                    "Coordinates (lat,lon)": verts,
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

        split_fc = {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": r["geometry"],
                    "properties": {"label": r["name"], "type": r["kind"]},
                }
                for r in split_results
            ],
        }
        cdl, cclr = st.columns([1, 1])
        cdl.download_button(
            "⬇️ Download split GeoJSON",
            data=json.dumps(split_fc, indent=2),
            file_name=f"{(a['iata'] or a['icao'] or 'airport').lower()}_split.geojson",
            mime="application/geo+json",
            use_container_width=True,
        )
        if cclr.button("Clear split output", use_container_width=True):
            st.session_state.split_results = []
            st.session_state.split_msg = None
            st.rerun()

        # New map: originals in blue, intersections in red, with labels.
        st.caption("🟦 Original (non-overlapping) pieces · 🟥 Intersection pieces")
        all_pts = [pt for r in split_results for pt in r["geometry"]["coordinates"][0]]
        lats = [p[1] for p in all_pts]
        lons = [p[0] for p in all_pts]
        smap = folium.Map(
            location=[sum(lats) / len(lats), sum(lons) / len(lons)],
            tiles=tiles_url,
            attr=attr,
            control_scale=True,
        )
        smap.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
        for r in split_results:
            is_inter = r["kind"] == "intersection"
            color = "#e6194b" if is_inter else "#1f6feb"
            folium.GeoJson(
                r["geometry"],
                style_function=lambda _f, c=color: {
                    "color": c,
                    "weight": 2,
                    "fillColor": c,
                    "fillOpacity": 0.3,
                },
            ).add_to(smap)
            ring = r["geometry"]["coordinates"][0]
            plat = sum(p[1] for p in ring) / len(ring)
            plon = sum(p[0] for p in ring) / len(ring)
            bg = "rgba(214,40,57,.85)" if is_inter else "rgba(20,90,170,.85)"
            folium.Marker(
                [plat, plon],
                icon=folium.DivIcon(
                    icon_size=(0, 0), icon_anchor=(0, 0), html=badge_html(r["name"], bg)
                ),
            ).add_to(smap)
        st_folium(smap, width=None, height=520, returned_objects=[], key=f"split-map-{choice}")
