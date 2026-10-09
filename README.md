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
