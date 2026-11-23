# Repeater Discovery & Terrain Routing

This guide covers the core point-to-point, multi-leg, and mesh repeater discovery workflows in `lora-gis`, starting from a single two-town command and scaling up to custom candidate sites and JSON network topologies.

---

## 1. Simple Point-to-Point & Multi-Leg Routes (`--route`)

Pass town or summit names (resolved automatically via USGS GeoNames) or inline `name=lat,lon` coordinates. By default, single-link routes search for both **1-hop** (single repeater) and **2-hop** (two-repeater pair) solutions whenever direct line-of-sight is blocked by terrain.

```bash
# Nationwide US lookup with state code
python3 -m lora_gis --route "Beacon, NY" "New Paltz, NY"

# Colorado Front Range example with custom relay mast height
python3 -m lora_gis --route "Boulder, CO" "Nederland, CO" --relay-height 45ft

# Inline coordinates (works anywhere in the world)
python3 -m lora_gis --route valley_node=41.504,-73.969 ridge_node=41.747,-74.087

# Sequential 3-town route (evaluates Leg 1: A <-> B and Leg 2: B <-> C)
python3 -m lora_gis --state NY --route "Roscoe" "Livingston Manor" "Liberty"
```

### Frequency & Height Tuning

- Use `--freq-mhz 868.0` for EU868 or `--freq-mhz 433.0` for 433 MHz (defaults to `915.0` MHz for US915).
- Override endpoint heights globally with `--observer-height 33ft`, intermediate relay heights with `--relay-height 60ft`, or individual nodes with `--height`:

```bash
python3 -m lora_gis --state NY \
  --route "Beacon" "New Paltz" \
  --height beacon=25ft new-paltz=45ft \
  --relay-height 50ft
```

---

## 2. Branching & Mesh Topologies (`--links`)

When your network is a star or branching mesh rather than a linear chain, pass explicit `node1:node2` link pairs (delimiters `:`, `->`, and `<->` are all supported):

```bash
python3 -m lora_gis --state NY \
  --links beacon:new-paltz new-paltz:kingston new-paltz:poughkeepsie \
  --height new-paltz=45ft
```

In multi-link mode:

- Any node with degree `>= 2` is automatically treated as an intermediate **Repeater Hub** (default mount height `--repeater-height 30ft` unless overridden via `--height`).
- `lora-gis` automatically generates **mount-height sensitivity tables** (`30 ft` through `90 ft`) for hub nodes so you can see how much mast height opens up 1-hop solutions.
- Multi-link topologies default to `--hops 1` per leg for speed; add `--hops 2` to enable 2-hop repeater pair discovery on every leg.

---

## 3. Reusable JSON Configuration Files (`--config`)

Store recurring locations, antenna heights, and RF settings in a JSON file so you can re-run or tweak a regional mesh without retyping long commands:

```json
{
  "title": "HudsonValleyMesh",
  "default_state": "NY",
  "freq_mhz": 915.0,
  "relay_height": "60ft",
  "dem_source": "usgs-3dep",
  "locations": {
    "beacon":    { "name": "Beacon",    "lat": 41.5048, "lon": -73.9696, "height": "33ft" },
    "new-paltz": { "name": "New Paltz", "lat": 41.7476, "lon": -74.0868, "height": "30ft" },
    "kingston":  { "name": "Kingston",  "lat": 41.9270, "lon": -73.9974, "height": "33ft" }
  },
  "links": [
    ["beacon", "new-paltz"],
    ["new-paltz", "kingston"]
  ]
}
```

Run it with:

```bash
python3 -m lora_gis --config network.json
```

Any CLI flag passed alongside `--config` overrides the value in the JSON file (for example, `python3 -m lora_gis --config network.json --hops 2 --freq-mhz 868.0`).

---

## 4. Explicit Candidate Relay Evaluation (`--candidates`)

If you already have specific properties, ridge access points, fire towers, or rooftops in mind, pass them with `--candidates` to test their exact coordinates alongside the automatic grid search:

```bash
python3 -m lora_gis --state NY \
  --route "Willowemoc, NY" "Livingston Manor, NY" \
  --hops 2 \
  --candidates site1=41.8926,-74.7838 site2=41.8905,-74.6927 \
  --candidate-height 30ft
```

What `--candidates` adds to the output:

- **Automatic extent expansion**: The DEM grid and rendered map expand to include all candidate sites.
- **Leg-by-leg clearance table**: Exact distance, minimum clearance, 1st Fresnel ratio ($F_1$), and FSPL for both `Endpoint A -> Candidate` and `Candidate -> Endpoint B`.
- **Cross-sectional terrain profiles (`candidate_profiles.png`)**: Side-by-side elevation profiles plotting the terrain (+ 4/3 Earth curvature bulge), direct LOS line, 1st Fresnel Zone envelope, and exact worst blockage point.
- **2-Hop candidate & hybrid pairs**: When `--hops 2` is enabled, evaluates candidate-to-candidate 2-hop pairs as well as hybrid solutions pairing one of your known sites with one discovered grid relay.
- **Dedicated map symbology**: Green diamonds and dashed green sightlines for clear candidate legs, purple diamonds and red `x` ridge blockage markers for blocked legs.

Candidates can also be defined in JSON via `"candidate_relays"` and `"candidate_height"`.

---

## 5. Understanding the Outputs

Each run writes a timestamped folder under `results/YYYY-MM-DD_HH-MM-SS/` (configurable via `--output-dir`):

- `map.png`: `1920x1080` topographic (or street/satellite) map showing endpoints, viable relay zones, optimal 1-hop (dashed blue) and 2-hop (solid red) paths, candidate sightlines, and USGS GeoNames peaks/towns.
- `candidate_profiles.png`: Cross-sectional elevation and Fresnel clearance plots (generated whenever `--candidates` or `--auto-candidates` are evaluated).
- `report.md`: Complete Markdown RF report containing:
  - **1st Fresnel Zone ($F_1$) clearance**: Targets `>= 60%` $F_1$ clearance (`--min-fresnel 0.60`), the standard threshold for near-free-space RF propagation without diffraction loss.
  - **4/3 Earth curvature**: Uses an effective Earth radius of `8,495 km` to model standard atmospheric RF refraction.
  - **Free-Space Path Loss (FSPL)**: Theoretical link loss in dB for each hop at the chosen LoRa frequency.
  - **Grid Resolution Scan Summary**: Shows how many grid candidates were visible from each endpoint as the solver refined from `--grid-step` (`500 m`) down to `--min-grid-step` (`150 m`).

---

## Next Steps

- Planning a flat or urban city deployment with buildings, water towers, and rooftops? Continue to **[City & DSM Analysis](city-and-dsm-analysis.md)**.
- Looking for a specific flag or JSON field? See the **[CLI & Config Reference](cli-reference.md)**.
