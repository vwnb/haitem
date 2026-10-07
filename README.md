# Haitem

## Code layout

- `index.py` contains the low-level ULJAS API client.
- `trade_data.py` handles cached queries, tabular transformations, and CN/product
  selection helpers.
- `trade_visualizations.py` builds the trade Sankey and integrates its Plotly
  click events.
- `customs_analysis.py` computes a standardized PCA of selected customs
  product-category time series.
- `streamlit_app.py` composes those pieces into the Streamlit UI.
- `export_licences.py` retrieves and normalizes the separate public decision
  archive.

The Level 0 and Up one level controls are in the query sidebar.

## Public export-licence decision breakdown

The optional exporter chart reads the Finnish Government's public plenary-session
archive at <https://valtioneuvosto.fi/paatokset/valtioneuvoston-yleisistunto>.
The archive exposes annual pages and pagination as ordinary HTML links. Haitem
follows those links, then reads the linked session pages and selects decision
titles containing “vientiluvan myöntäminen”. Retrieved annual JSON is
stored in `data/export-licences/`.

The extraction keeps the decision ID, session date, Finnish decision title,
exporter text when present, and source decision/session URLs. When the UI loads a
selected period, it also fetches and caches the full decision text for that
period. The Plenary decisions panel includes only records whose full text
mentions a selected CN code; this literal text match is not a classification
link or evidence of de facto exports. Missing exporter names remain null and are
reported in the UI. Exporter grouping only normalizes case and whitespace.
