"""Trade visualization builders and Plotly event integration."""

import json
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit.components.v1 as components
import streamlit_plotly_events

from trade_data import format_cn_code


_plotly_event_component = components.declare_component(
    "haitem_plotly_events",
    path=Path(streamlit_plotly_events.__file__).parent / "frontend" / "build",
)


def sankey_plotly_events(figure, key):
    plot_object = json.loads(figure.to_json())
    plot_object["config"] = {
        "displayModeBar": False,
        "displaylogo": False,
        "responsive": True,
    }
    component_value = _plotly_event_component(
        plot_obj=json.dumps(plot_object),
        override_height=figure.layout.height,
        override_width="100%",
        click_event=True,
        select_event=False,
        hover_event=False,
        key=key,
        default="[]",
    )
    return json.loads(component_value)


def make_trade_sankey(
    products,
    source,
    destination,
    classification_labels,
    parent_code="",
    zoom_depth=0,
):
    codes = products["Product code"].astype(str)
    valid_codes = codes.str.fullmatch(r"\d{2,8}")
    trade_products = products.loc[
        valid_codes & products["Value (EUR)"].gt(0)
    ].copy()
    trade_products["Product code"] = codes[valid_codes]
    trade_products = trade_products.loc[
        trade_products["Product code"].str.startswith(parent_code)
    ]
    max_depth = trade_products["Product code"].str.len().max()
    if pd.isna(max_depth) or max_depth <= len(parent_code):
        return None

    depth = min((zoom_depth + 1) * 2, int(max_depth))
    trade_products["Drill code"] = trade_products["Product code"].str.slice(0, depth)
    cn8_labels = trade_products.drop_duplicates("Product code").set_index(
        "Product code"
    )["Product"]
    grouped_products = (
        trade_products.groupby("Drill code", as_index=False)
        .agg({"Value (EUR)": "sum"})
        .sort_values("Value (EUR)", ascending=False)
    )
    grouped_products["Product"] = grouped_products["Drill code"].map(
        lambda code: (
            cn8_labels.get(code, "")
            if len(code) == 8
            else classification_labels.get(len(code), {}).get(code, "")
        )
    )
    total_value = grouped_products["Value (EUR)"].sum()
    trade_products = grouped_products
    if trade_products.empty:
        return None

    visible_products = trade_products.head(8).reset_index(drop=True)
    remaining_products = trade_products.iloc[8:]
    if not remaining_products.empty:
        visible_products.loc[len(visible_products)] = {
            "Drill code": None,
            "Product": f"Other products ({len(remaining_products):,} categories)",
            "Value (EUR)": remaining_products["Value (EUR)"].sum(),
        }

    category_labels = [
        row["Product"]
        if pd.isna(row["Drill code"])
        else format_cn_code(row["Drill code"])
        for _, row in visible_products.iterrows()
    ]
    category_codes = [
        None if pd.isna(code) else code for code in visible_products["Drill code"]
    ]
    category_full_names = [
        str(name) if code is not None else "Combined remaining product categories"
        for code, name in zip(category_codes, visible_products["Product"])
    ]
    category_count = len(category_labels)
    values = visible_products["Value (EUR)"].tolist()
    plot_height = 900
    gap_fraction = min(10 / plot_height, 0.5 / category_count)
    total_node_fraction = max(0.05, 1 - gap_fraction * (category_count - 1))
    node_height_fractions = [
        value / total_value * total_node_fraction for value in values
    ]
    remaining_fraction = 1 - sum(node_height_fractions) - gap_fraction * (
        category_count - 1
    )
    cursor = max(0, remaining_fraction / 2)
    category_top_positions = []
    for node_height in node_height_fractions:
        category_top_positions.append(cursor)
        cursor += node_height + gap_fraction

    figure = go.Figure(
        go.Sankey(
            arrangement="snap",
            node={
                "label": [source, *category_labels, destination],
                "color": ["#333a3d", *["#426d78"] * category_count, "#426d78"],
                "line": {"color": "#333a3d", "width": 0.5},
                "pad": 10,
                "thickness": 14,
                "x": [0.02, *[0.5] * category_count, 0.98],
                "y": [0.02, *category_top_positions, 0.02],
                "customdata": [
                    source,
                    *category_full_names,
                    destination,
                ],
                "hovertemplate": "%{label}<br>%{customdata}<extra></extra>",
            },
            link={
                "source": [0] * category_count
                + list(range(1, category_count + 1)),
                "target": list(range(1, category_count + 1))
                + [category_count + 1] * category_count,
                "value": values + values,
                "color": ["rgba(66, 109, 120, 0.76)"]
                * category_count
                + ["rgba(66, 109, 120, 0.76)"]
                * category_count,
                "customdata": [
                    [label, name]
                    for label, name in zip(category_labels, category_full_names)
                ]
                * 2,
                "hovercolor": [
                    "rgba(66, 109, 120, 0.76)",
                ]
                * category_count
                + ["rgba(66, 109, 120, 0.76)"]
                * category_count,
                "hovertemplate": (
                    "%{source.label} → %{target.label}<br>"
                    "%{customdata[0]} · %{customdata[1]}<br>"
                    "Recorded trade value: €%{value:,.0f}<extra></extra>"
                ),
            },
        )
    )
    figure.update_layout(
        height=max(plot_height, 30 * category_count + 40),
        margin={"l": 80, "r": 80, "t": 16, "b": 16},
        font={"family": "Arial, sans-serif", "size": 12, "color": "#202629"},
        hoverlabel={
            "bgcolor": "#f2f4f5",
            "bordercolor": "#426d78",
            "font": {"family": "Arial, sans-serif", "color": "#202629"},
        },
    )
    return figure, total_value, category_codes, category_labels


def selected_sankey_code(clicked_points, category_codes):
    if not clicked_points:
        return None

    point = clicked_points[0]
    if point.get("curveNumber") != 0:
        return None

    if "source" in point or "target" in point:
        source = point.get("source")
        target = point.get("target")
        category_node = (
            target
            if source == 0
            else source
            if target == len(category_codes) + 1
            else None
        )
        if (
            isinstance(category_node, int)
            and 1 <= category_node <= len(category_codes)
        ):
            return category_codes[category_node - 1]
        return None

    custom_code = point.get("customdata")
    if custom_code is not None and custom_code in category_codes:
        return custom_code

    node_index = point.get("pointNumber", point.get("pointIndex"))
    if isinstance(node_index, int) and 1 <= node_index <= len(category_codes):
        return category_codes[node_index - 1]
    return None
