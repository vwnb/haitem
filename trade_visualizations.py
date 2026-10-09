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
    max_visible=8,
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
    if trade_products.empty:
        return None
    # Leaf rows only: mixed queries carry parent rows for labels/totals, but
    # the Sankey must aggregate leaves or every euro counts twice. A code is
    # a leaf when no other loaded code extends it.
    loaded_codes = trade_products["Product code"].unique().tolist()
    leaf_mask = trade_products["Product code"].map(
        lambda code: not any(
            other != code and str(other).startswith(str(code))
            for other in loaded_codes
        )
    )
    trade_products = trade_products.loc[leaf_mask].copy()
    if trade_products.empty:
        return None
    max_depth = trade_products["Product code"].str.len().max()
    if pd.isna(max_depth):
        return None

    # Two hierarchy levels at once: the scope level (CN2 at root, the clicked
    # branch below) plus one level deeper. Single-level branches were the
    # zoom-then-climb trap; two levels make every view compositional. When
    # the branch holds a single level (CN8 leaves), derive the scope locally
    # via prefix so the view still shows composition.
    deepest = int(max_depth)
    if deepest <= len(parent_code):
        scope_depth = max(len(parent_code) - 2, 2)
        child_depth = len(parent_code)
    else:
        scope_depth = max(len(parent_code), min(deepest - 2, 6))
        if scope_depth < 2:
            scope_depth = 2
        child_depth = deepest
    trade_products["Scope code"] = trade_products["Product code"].str.slice(
        0, scope_depth
    )
    trade_products["Drill code"] = trade_products["Product code"].str.slice(
        0, child_depth
    )
    cn8_labels = trade_products.drop_duplicates("Product code").set_index(
        "Product code"
    )["Product"]

    def class_label(code):
        if not code:
            return ""
        if len(str(code)) == 8:
            return str(cn8_labels.get(code, ""))
        return str(classification_labels.get(len(str(code)), {}).get(code, ""))

    # Top scope nodes (CN2 chapters at root, the clicked branch below) by
    # value, with one child level under each: two hierarchy levels in one
    # view so every navigation level has composition to compare.
    scope_totals = (
        trade_products.groupby("Scope code", as_index=False)
        .agg({"Value (EUR)": "sum"})
        .sort_values("Value (EUR)", ascending=False)
    )
    if scope_totals.empty:
        return None
    visible_scopes = scope_totals.head(max_visible).copy()
    scope_set = set(visible_scopes["Scope code"])
    ranked_children = (
        trade_products.loc[trade_products["Scope code"].isin(scope_set)]
        .groupby(["Scope code", "Drill code"], as_index=False)
        .agg({"Value (EUR)": "sum"})
        .sort_values("Value (EUR)", ascending=False)
    )
    other_scopes = scope_totals.loc[~scope_totals["Scope code"].isin(scope_set)]
    other_value = float(other_scopes["Value (EUR)"].sum()) if not other_scopes.empty else 0.0
    total_value = float(scope_totals["Value (EUR)"].sum())

    scope_labels = [format_cn_code(code) for code in visible_scopes["Scope code"]]
    scope_names = [class_label(code) for code in visible_scopes["Scope code"]]
    child_labels = [format_cn_code(code) for code in ranked_children["Drill code"]]
    child_names = [class_label(code) for code in ranked_children["Drill code"]]

    node_labels = [source, *scope_labels, *child_labels]
    if other_value > 0:
        node_labels.append(f"Other ({len(other_scopes):,})")
    node_labels.append(destination)
    node_names = [source, *scope_names, *child_names]
    if other_value > 0:
        node_names.append("Combined remaining product classes")
    node_names.append(destination)
    scope_count = len(visible_scopes)
    child_count = len(ranked_children)
    has_other = other_value > 0
    scope_index = {code: index + 1 for index, code in enumerate(visible_scopes["Scope code"])}
    child_index = {code: scope_count + 1 + index for index, code in enumerate(ranked_children["Drill code"])}
    destination_index = scope_count + child_count + (1 if has_other else 0) + 1

    link_source, link_target, link_value, link_custom = [], [], [], []
    for position, row in enumerate(visible_scopes.itertuples()):
        link_source.append(0)
        link_target.append(scope_index[row._1])
        link_value.append(float(row._2))
        link_custom.append([scope_labels[position], scope_names[position]])
    for row in ranked_children.itertuples():
        position = child_index[row._2] - scope_count - 1
        link_source.append(scope_index[row._1])
        link_target.append(child_index[row._2])
        link_value.append(float(row._3))
        link_custom.append([child_labels[position], child_names[position]])
    for row in ranked_children.itertuples():
        position = child_index[row._2] - scope_count - 1
        link_source.append(child_index[row._2])
        link_target.append(destination_index)
        link_value.append(float(row._3))
        link_custom.append([child_labels[position], child_names[position]])
    if has_other:
        other_index = scope_count + child_count + 1
        link_source.extend([0, other_index])
        link_target.extend([other_index, destination_index])
        link_value.extend([other_value, other_value])
        link_custom.extend([[f"Other ({len(other_scopes):,})", "Combined remaining product classes"]] * 2)

    node_count = len(node_labels)
    plot_height = 900
    category_codes = visible_scopes["Scope code"].tolist() + ranked_children["Drill code"].tolist()
    category_labels = scope_labels + child_labels
    category_count = node_count - 2
    scope_x = [0.02] + [0.32] * scope_count + [0.66] * child_count + ([0.66] if has_other else []) + [0.98]
    scope_y = [0.02] + [0.02] * (node_count - 2) + [0.02]

    figure = go.Figure(
        go.Sankey(
            arrangement="snap",
            node={
                "label": node_labels,
                "color": ["#333a3d", *["#426d78"] * category_count, "#426d78"],
                "line": {"color": "#333a3d", "width": 0.5},
                "pad": 10,
                "thickness": 14,
                "x": scope_x,
                "y": scope_y,
                "customdata": node_names,
                "hovertemplate": "%{label}<br>%{customdata}<extra></extra>",
            },
            link={
                "source": link_source,
                "target": link_target,
                "value": link_value,
                "color": ["rgba(66, 109, 120, 0.55)"] * len(link_value),
                "customdata": link_custom,
                "hovercolor": ["rgba(66, 109, 120, 0.76)"] * len(link_value),
                "hovertemplate": (
                    "%{source.label} → %{target.label}<br>"
                    "%{customdata[0]} · %{customdata[1]}<br>"
                    "Recorded trade value: €%{value:,.0f}<extra></extra>"
                ),
            },
        )
    )
    figure.update_layout(
        height=plot_height,
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

    # Two-level layout: node 0 is the source, the last node is the
    # destination, everything in between is a clickable CN code. Link clicks
    # resolve to the CN endpoint rather than the source/destination.
    node_count = len(category_codes) + 2
    if "source" in point or "target" in point:
        source = point.get("source")
        target = point.get("target")
        for node in (target, source):
            if isinstance(node, int) and 1 <= node <= len(category_codes):
                return category_codes[node - 1]
        return None

    custom_code = point.get("customdata")
    if custom_code is not None and custom_code in category_codes:
        return custom_code

    node_index = point.get("pointNumber", point.get("pointIndex"))
    if isinstance(node_index, int) and 1 <= node_index <= len(category_codes):
        return category_codes[node_index - 1]
    return None
