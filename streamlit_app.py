import colorsys
import json
import zlib
from pathlib import Path

import altair as alt
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import streamlit.components.v1 as components
import streamlit_plotly_events

from export_licences import (
    decisions_in_period,
    load_year as load_licence_decisions_year,
    top_exporters,
)
from index import DEFAULT_CUBE_ID, UljasClient


_plotly_event_component = components.declare_component(
    "haitem_plotly_events",
    path=Path(streamlit_plotly_events.__file__).parent / "frontend" / "build",
)


@st.cache_data(ttl=3600, max_entries=8, show_spinner=False)
def load_data(country, flow, frequency, start, end, classification_id, product_codes):
    client = UljasClient()
    return client.query_trade(
        country_code=country,
        flow=flow,
        start_period=start or None,
        end_period=end or None,
        frequency=frequency,
        cube_id=DEFAULT_CUBE_ID,
        product_classification_id=classification_id,
        product_codes=list(product_codes) if product_codes else None,
    )


@st.cache_data(ttl=3600, max_entries=1, show_spinner=False)
def load_product_classification_labels():
    client = UljasClient()
    return {
        2: client.product_classification_labels(4),
        4: client.product_classification_labels(5),
        6: client.product_classification_labels(6),
    }


def make_dataframes(result, frequency):
    products = result["variables"]["0"]["items"]
    periods = result["variables"]["1"]["items"]
    values = result["values"]
    expected_values = len(products) * len(periods)
    if len(values) != expected_values:
        raise ValueError(
            f"ULJAS returned {len(values)} values; expected {expected_values}."
        )

    records = []
    for product_index, product in enumerate(products):
        for period_index, period in enumerate(periods):
            records.append(
                {
                    "Product code": product["code"],
                    "Product": product["label"],
                    "Period": period["code"],
                    "Value (EUR)": values[product_index * len(periods) + period_index],
                }
            )

    details = pd.DataFrame.from_records(records)
    date_format = "%Y%m" if frequency == "month" else "%Y"
    details["Date"] = pd.to_datetime(details["Period"], format=date_format)
    timeline = (
        details.groupby("Date", as_index=False)["Value (EUR)"]
        .sum()
        .sort_values("Date")
    )
    all_products = (
        details.groupby(["Product code", "Product"], as_index=False)["Value (EUR)"]
        .sum()
        .sort_values("Value (EUR)", ascending=False)
    )
    return timeline, all_products.head(33), all_products, details

def format_cn_code(code):
    return f"CN {str(code)[:2]}"


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

    depth = min(len(parent_code) + 2, int(max_depth))
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
    if point.get("curveNumber") != 0 or "source" in point or "target" in point:
        return None

    custom_code = point.get("customdata")
    if custom_code is not None and custom_code in category_codes:
        return custom_code

    node_index = point.get("pointNumber", point.get("pointIndex"))
    if isinstance(node_index, int) and 1 <= node_index <= len(category_codes):
        return category_codes[node_index - 1]
    return None


def parse_product_codes(raw_codes):
    codes = tuple(
        sorted({code.strip().upper() for code in raw_codes.split(",") if code.strip()})
    )
    if len(codes) > 10:
        raise ValueError("Enter at most 10 CN8 product codes per query.")
    return codes


def selected_product_code(selection):
    selected_items = selection.get("cn8_bar_selection", [])
    if not selected_items:
        return None
    return selected_items[0].get("Product code")


def selected_table_product_code(selection, products):
    if not selection.rows:
        return None
    return str(products.iloc[selection.rows[0]]["Product code"])


st.set_page_config(page_title="Haitem • trade & economic metrics", page_icon="📊", layout="wide")
st.session_state.setdefault("selectedProductClass", None)
st.markdown(
    """
    <style>
    :root {
        --paper: #f2f4f5;
        --surface: #e2e7e9;
        --cyan: #426d78;
        --cyan-soft: #a9c0c8;
        --charcoal: #333a3d;
        --ink: #202629;
        --muted-ink: #566166;
    }

    html, body, body *:not(.material-symbols-rounded):not([data-testid="stIconMaterial"]) {
        font-family: Arial, Helvetica, sans-serif !important;
    }

    .stApp {
        background:
            linear-gradient(90deg, transparent 39px, #426d780d 40px, transparent 41px),
            var(--paper);
        color: var(--ink);
    }

    .block-container {
        max-width: 1480px;
        padding-bottom: 2rem;
    }

    div[data-testid="stVerticalBlock"] {
        gap: 0.85rem;
    }

    h1, h2, h3 {
        color: var(--ink);
        font-family: Arial, Helvetica, sans-serif;
        font-weight: 850;
        margin: 2rem 0 1rem 0;
    }

    h1 a, h2 a, h3 a {
        display: none !important;
    }

    h1 {
        font-size: 3em;
    }

    [data-testid="stCaptionContainer"] p,
    [data-testid="stWidgetLabel"] p {
        color: var(--muted-ink);
    }

    section[data-testid="stSidebar"] {
        background: var(--charcoal);
    }

    section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        gap: 0.55rem;
    }

    section[data-testid="stSidebar"] h2,
    section[data-testid="stSidebar"] h3,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] p {
        color: var(--paper);
    }

    section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,
    section[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {
        color: var(--cyan-soft);
    }

    div[data-testid="stTextInput"] div[data-baseweb="input"],
    div[data-testid="stSelectbox"] div[data-baseweb="select"] > div {
        background: var(--paper) !important;
        border: 2px solid var(--cyan-soft) !important;
        box-shadow: none !important;
    }

    div[data-testid="stTextInput"] input,
    div[data-testid="stSelectbox"] input,
    div[data-testid="stSelectbox"] [role="combobox"],
    div[data-testid="stSelectbox"] svg {
        background: transparent !important;
        border: 0 !important;
        box-shadow: none !important;
        color: var(--ink) !important;
        -webkit-text-fill-color: var(--ink) !important;
    }

    div[data-testid="stForm"] {
        background: #333a3d12;
    }

    div[data-testid="stForm"] [data-testid="stVerticalBlock"] {
        gap: 0.55rem;
    }

    div[data-testid="stFormSubmitButton"] button {
        width: 100%;
        margin: 1rem 0;
        min-height: 3.6rem;
        padding: 1rem;
        background: var(--cyan) !important;
        color: var(--paper) !important;
        border: 3px solid var(--cyan) !important;
        box-shadow: 8px 8px 0 var(--charcoal);
    }

    div[data-testid="stFormSubmitButton"] button:hover {
        background: var(--cyan) !important;
        color: var(--paper) !important;
        border-color: var(--cyan) !important;
        transform: skew(-10deg, 0);
        transition: transform 0.3s ease-in-out;
    }

    div[data-testid="stButton"] button {
        transition: background-color 0.16s ease, color 0.16s ease, transform 0.16s ease;
    }

    div[data-testid="stButton"] button:hover {
        background: var(--cyan) !important;
        color: var(--paper) !important;
        border-color: var(--cyan) !important;
        transform: translateY(-1px);
    }

    .st-key-all-product-classes-table [data-testid="stDataFrame"] {
        cursor: pointer;
        transition: border-color 0.16s ease, box-shadow 0.16s ease;
    }

    .st-key-all-product-classes-table:hover [data-testid="stDataFrame"] {
        border-color: var(--cyan) !important;
        box-shadow: 0 0 0 2px #426d7826;
    }

    div[data-testid="stMetric"] {
        background: var(--surface);
    }

    div[data-testid="stMetric"] label {
        color: #4b565b;
    }

    [data-testid="stDataFrame"] {
        border: 2px solid var(--cyan-soft);
    }

    [data-testid="stExpander"] {
        border: 2px solid var(--cyan-soft);
        border-radius: 0;
        background: #f2f4f580;
    }

    pre {
        white-space: pre-wrap;
        overflow-wrap: anywhere;
    }

    :focus-visible {
        outline: 3px solid var(--cyan-soft) !important;
        outline-offset: 2px;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
st.title("𓅋 Haitem • Trade & procurement flows of Finland")

with st.sidebar:
    st.header("Query")
    with st.form("uljas-query"):
        country = st.text_input(
            "Partner country code (ISO-2)", value="", placeholder="e.g. SE"
        ).strip().upper()
        flow = st.selectbox("Trade flow", ["exports", "imports"])
        frequency = st.selectbox("Time interval", ["month", "year"])
        period_format = "YYYYMM" if frequency == "month" else "YYYY"
        default_start = "202301" if frequency == "month" else "2023"
        start = st.text_input(
            f"Start period ({period_format})",
            value=default_start,
            key=f"start-{frequency}",
        )
        end = st.text_input(
            f"End period ({period_format}; blank = latest)", value="", key=f"end-{frequency}"
        )
        product_code_input = st.text_input(
            "CN8 product codes (comma-separated, optional)"
        )
        submitted = st.form_submit_button("Load statistics", type="primary")
    st.caption(
        "Data loads on submit or when a product bar is selected. Identical "
        "requests are cached for 1 hour."
    )

if submitted:
    st.session_state.pop("uljas_result", None)
    st.session_state.pop("product_classification_labels", None)
    st.session_state.pop("selected_cn8_series", None)
    st.session_state.pop("selectedProductClass", None)
    st.session_state.pop("sankey_prefix", None)
    st.session_state["product_chart_version"] = (
        st.session_state.get("product_chart_version", 0) + 1
    )
    st.session_state["sankey_chart_version"] = (
        st.session_state.get("sankey_chart_version", 0) + 1
    )
    try:
        if not country:
            raise ValueError("Enter a partner country code (ISO-2).")
        product_codes = parse_product_codes(product_code_input)
        with st.spinner("Loading data from ULJAS..."):
            result = load_data(
                country,
                flow,
                frequency,
                start,
                end,
                1,
                product_codes,
            )
        timeline, top_products, all_products, details = make_dataframes(
            result, frequency
        )
        classification_labels = load_product_classification_labels()
        st.session_state["uljas_result"] = (
            result,
            timeline,
            top_products,
            all_products,
            details,
            country,
            flow,
            frequency,
            product_codes,
            start,
            end,
        )
        st.session_state["product_classification_labels"] = classification_labels
    except (requests.RequestException, RuntimeError, ValueError) as error:
        st.error(f"Could not load ULJAS data: {error}")

if "uljas_result" not in st.session_state:
    st.info("Choose a partner country, trade flow, period, and commodity detail.")
else:
    (
        result,
        timeline,
        top_products,
        all_products,
        details,
        country,
        flow,
        frequency,
        product_codes,
        start,
        end,
    ) = st.session_state["uljas_result"]
    st.subheader(f"{flow.title()}")
    if timeline.empty:
        st.warning("ULJAS returned no data for that selection.")
    else:
        total = timeline["Value (EUR)"].sum()
        date_format = "%Y%m" if frequency == "month" else "%Y"
        first_period = timeline["Date"].min().strftime(date_format)
        last_period = timeline["Date"].max().strftime(date_format)
        product_scope = (
            "selected CN8 products" if product_codes else "all CN8 products"
        )
        st.metric(
            f"Total value · {product_scope} · {first_period}–{last_period}",
            f"€{total:,.0f}",
        )

        source = "Finland" if flow == "exports" else country
        destination = country if flow == "exports" else "Finland"
        st.subheader(f"Trade flow · {source} → {destination}")
        sankey_prefix = st.session_state.get("sankey_prefix", "")
        if sankey_prefix:
            st.caption(
                f"Breakdown path: {source} → {format_cn_code(sankey_prefix)} "
                f"→ {destination}"
            )
            back_column, reset_column = st.columns(2)
            with back_column:
                if st.button("Back one level", key="sankey-back"):
                    st.session_state["sankey_prefix"] = sankey_prefix[:-2]
                    st.session_state["product_chart_version"] = (
                        st.session_state.get("product_chart_version", 0) + 1
                    )
                    st.session_state["sankey_chart_version"] = (
                        st.session_state.get("sankey_chart_version", 0) + 1
                    )
                    st.rerun()
            with reset_column:
                if st.button("Reset Sankey", key="sankey-reset"):
                    st.session_state.pop("sankey_prefix", None)
                    st.session_state["product_chart_version"] = (
                        st.session_state.get("product_chart_version", 0) + 1
                    )
                    st.session_state["sankey_chart_version"] = (
                        st.session_state.get("sankey_chart_version", 0) + 1
                    )
                    st.rerun()
        st.caption(
            f"Showing product classes for {source} → {destination} · "
            f"{first_period}–{last_period}"
        )
        trade_sankey = make_trade_sankey(
            all_products,
            source,
            destination,
            st.session_state.get("product_classification_labels", {}),
            sankey_prefix,
        )
        if trade_sankey is None:
            if sankey_prefix:
                st.info(
                    f"{format_cn_code(sankey_prefix)} is at the most detailed "
                    "level available. "
                    "Its time series is shown below."
                )
            else:
                st.info(
                    "No positive trade values are available for this selection. "
                    "Clear any CN8 product filter to check all categories."
                )
        else:
            figure, represented_value, category_codes, _ = trade_sankey
            st.metric("Positive trade value shown", f"€{represented_value:,.0f}")
            clicked_points = sankey_plotly_events(
                figure,
                key=(
                    f"trade-sankey-{sankey_prefix or 'root'}-"
                    f"{st.session_state.get('sankey_chart_version', 0)}"
                ),
            )
            clicked_category_code = selected_sankey_code(
                clicked_points, category_codes
            )
            if clicked_category_code:
                st.session_state["sankey_prefix"] = clicked_category_code
                st.session_state.pop("selected_cn8_series", None)
                st.session_state.pop("selectedProductClass", None)
                st.session_state["product_chart_version"] = (
                    st.session_state.get("product_chart_version", 0) + 1
                )
                st.session_state["sankey_chart_version"] = (
                    st.session_state.get("sankey_chart_version", 0) + 1
                )
                st.rerun()
            st.caption(
                "Flow widths show recorded customs trade value, not money transfers. "
                "Hover a node or band for its full product name; click a code node "
                "to drill down. "
                "The 8 largest visible positive categories are shown individually; "
                "remaining positive categories are grouped as non-clickable Other."
            )

        if sankey_prefix:
            selected_rows = details.loc[
                details["Product code"].astype(str).str.startswith(sankey_prefix)
            ]
            selected_timeline = (
                selected_rows.groupby("Date", as_index=False)["Value (EUR)"]
                .sum()
                .sort_values("Date")
            )
            st.subheader(
                f"{frequency.title()} trade value · {format_cn_code(sankey_prefix)}"
            )
            if selected_timeline.empty:
                st.info("No time-series values are available for this category.")
            else:
                st.line_chart(
                    selected_timeline,
                    x="Date",
                    y="Value (EUR)",
                    color="#426D78",
                )

        chart_version = st.session_state.get("product_chart_version", 0)
        product_chart_column, licence_chart_column = st.columns([2, 1])
        with product_chart_column:
            st.subheader(
                "Selected CN8 categories" if product_codes else "Top 33 product classes"
            )
            if product_codes:
                st.caption(
                    f"Showing {len(top_products):,} of {len(all_products):,} selected "
                    "categories. Click a bar to load its time series."
                )
            else:
                st.caption(
                    f"Showing {len(top_products):,} of {len(all_products):,} categories. "
                    "Hover a bar to highlight it and see its full name; click to load "
                    "its time series."
                )
            if st.session_state.get("selectedProductClass"):
                if st.button("Clear product selection", key="clear-cn8-selection"):
                    st.session_state.pop("selected_cn8_series", None)
                    st.session_state.pop("selectedProductClass", None)
                    st.session_state["product_chart_version"] = chart_version + 1
                    chart_version += 1
        product_selection = alt.selection_point(
            fields=["Product code"],
            name="cn8_bar_selection",
            clear=False,
            toggle=False,
        )
        bar_hover = alt.selection_point(
            fields=["Product code"],
            on="pointerover",
            clear="pointerout",
        )
        product_chart = (
            alt.Chart(
                top_products.assign(
                    **{
                        "CN code": top_products["Product code"]
                        .astype(str)
                        .map(format_cn_code)
                    }
                )
            )
            .mark_bar(orient="horizontal", cursor="pointer")
            .encode(
                x=alt.X("Value (EUR):Q", title="Value (EUR)", scale=alt.Scale(zero=True)),
                y=alt.Y(
                    "CN code:N",
                    sort="-x",
                    axis=alt.Axis(title="CN code"),
                ),
                color=alt.Color(
                    "Value (EUR):Q",
                    scale=alt.Scale(range=["#A9C0C8", "#426D78"]),
                    legend=None,
                ),
                opacity=alt.condition(bar_hover, alt.value(1), alt.value(0.82)),
                tooltip=[
                    alt.Tooltip("Product:N", title="product class"),
                    alt.Tooltip("CN code:N", title="CN code"),
                    alt.Tooltip("Value (EUR):Q", format=",.0f"),
                ],
            )
            .add_params(product_selection)
            .add_params(bar_hover)
            .interactive()
            .configure_axis(
                labelColor="#333A3D",
                titleColor="#333A3D",
                gridColor="#A9C0C866",
                domainColor="#A9C0C8",
                labelFont="Arial",
                titleFont="Arial",
            )
            .configure_view(stroke="#A9C0C8")
        )
        with product_chart_column:
            chart_event = st.altair_chart(
                product_chart,
                width="stretch",
                key=f"product-category-chart-{chart_version}",
                on_select="rerun",
                selection_mode="cn8_bar_selection",
            )
        with licence_chart_column:
            st.subheader("Top 5 exporters · plenary decisions")
            st.caption(
                "Ranked by listed decision count across all destinations in this period. "
                "This plenary archive is not register of de facto exports."
            )
            period_frequency = "M" if frequency == "month" else "Y"
            period_start = pd.Period(
                start or timeline["Date"].min(), freq=period_frequency
            ).start_time.date()
            period_end = pd.Period(
                end or timeline["Date"].max(), freq=period_frequency
            ).end_time.date()
            licence_years = tuple(range(period_start.year, period_end.year + 1))
            loaded_licences = st.session_state.get("public_licence_decisions")
            has_matching_years = (
                loaded_licences is not None and loaded_licences[0] == licence_years
            )
            load_col, refresh_col = st.columns(2)
            with load_col:
                load_licences = st.button(
                    "Load decisions",
                    key=f"load-licence-decisions-{licence_years}",
                    help="Loads cached decisions, or retrieves the official archive by year.",
                )
            with refresh_col:
                refresh_licences = st.button(
                    "Refresh",
                    key=f"refresh-licence-decisions-{licence_years}",
                    help="Re-enumerates the official yearly archive pages.",
                )
            if load_licences or refresh_licences:
                try:
                    with st.spinner("Loading public export-licence decisions..."):
                        datasets = [
                            load_licence_decisions_year(
                                year, refresh=refresh_licences
                            )
                            for year in licence_years
                        ]
                    st.session_state["public_licence_decisions"] = (
                        licence_years,
                        datasets,
                    )
                    loaded_licences = (licence_years, datasets)
                    has_matching_years = True
                except requests.RequestException as error:
                    st.error(f"Could not load the public decision archive: {error}")
            if has_matching_years:
                period_decisions = decisions_in_period(
                    loaded_licences[1], period_start, period_end
                )
                exporters = top_exporters(
                    loaded_licences[1], period_start, period_end
                )
                if exporters:
                    exporter_frame = pd.DataFrame(exporters)
                    exporter_chart = (
                        alt.Chart(exporter_frame)
                        .mark_bar(color="#426D78")
                        .encode(
                            x=alt.X("Decisions:Q", title="Decision count"),
                            y=alt.Y("Exporter:N", sort="-x", title=None),
                            tooltip=[
                                alt.Tooltip("Exporter:N", title="Exporter"),
                                alt.Tooltip("Decisions:Q", title="Public decisions"),
                            ],
                        )
                        .configure_axis(
                            labelColor="#333A3D",
                            titleColor="#333A3D",
                            gridColor="#A9C0C866",
                            domainColor="#A9C0C8",
                            labelFont="Arial",
                            titleFont="Arial",
                        )
                        .configure_view(stroke="#A9C0C8")
                    )
                    st.altair_chart(exporter_chart, width="stretch")
                else:
                    st.info("No exporter names were parsed for this period.")
                warnings = [
                    warning
                    for dataset in loaded_licences[1]
                    for warning in dataset["warnings"]
                ]
                if warnings:
                    st.warning(
                        f"{len(warnings)} archive entries could not be fully parsed. "
                        f"Example: {warnings[0]}"
                    )
                with st.expander(
                    f"Decision sources · {len(period_decisions)} records"
                ):
                    source_rows = [
                        {
                            "Date": record["decisionDate"],
                            "Exporter": record["exporter"] or "Not identified",
                            "Decision": record["decisionTitle"],
                            "Source": record["sourceUrl"],
                        }
                        for record in period_decisions
                    ]
                    st.dataframe(
                        pd.DataFrame(
                            source_rows,
                            columns=["Date", "Exporter", "Decision", "Source"],
                        ),
                        hide_index=True,
                        width="stretch",
                        column_config={
                            "Source": st.column_config.LinkColumn(
                                "Source", display_text="Open decision"
                            )
                        },
                    )
            else:
                st.info(
                    "Load the public archive to see decision counts. "
                    "Yearly results are cached locally."
                )
        clicked_product_code = selected_product_code(chart_event.selection)
        if (
            clicked_product_code
            and clicked_product_code != st.session_state.get("selectedProductClass")
        ):
            st.session_state["selectedProductClass"] = clicked_product_code
            st.session_state.pop("selected_cn8_series", None)
            st.session_state.pop("sankey_prefix", None)
            st.session_state["sankey_chart_version"] = (
                st.session_state.get("sankey_chart_version", 0) + 1
            )

        selected_code = st.session_state.get("selectedProductClass")
        if selected_code:
            selection_signature = (
                country,
                flow,
                frequency,
                start,
                end,
                selected_code,
            )
            cached_series = st.session_state.get("selected_cn8_series")
            if not cached_series or cached_series[0] != selection_signature:
                try:
                    with st.spinner(
                        f"Loading {format_cn_code(selected_code)} time series..."
                    ):
                        series_result = load_data(
                            country,
                            flow,
                            frequency,
                            start,
                            end,
                            1,
                            (selected_code,),
                        )
                    series_frames = make_dataframes(series_result, frequency)
                    st.session_state["selected_cn8_series"] = (
                        selection_signature,
                        series_frames,
                    )
                    cached_series = st.session_state["selected_cn8_series"]
                except (requests.RequestException, RuntimeError, ValueError) as error:
                    st.error(
                        f"Could not load {format_cn_code(selected_code)} time series: "
                        f"{error}"
                    )
                    cached_series = None
            if cached_series:
                _, series_frames = cached_series
                series_timeline, _, series_products, _ = series_frames
                if series_products.empty:
                    st.warning(
                        f"ULJAS returned no data for {format_cn_code(selected_code)}."
                    )
                else:
                    selected_product = series_products.iloc[0]
                    st.subheader(
                        f"{frequency.title()} time series · "
                        f"{format_cn_code(selected_product['Product code'])}"
                    )
                    st.caption(
                        f"{selected_product['Product']} · {flow} with {country} · "
                        f"{first_period}–{last_period}"
                    )
                    st.line_chart(
                        series_timeline,
                        x="Date",
                        y="Value (EUR)",
                        color="#426D78",
                    )
        elif not sankey_prefix and product_codes:
            st.subheader(f"{frequency.title()} trade value · selected CN8 products")
            st.caption("Each selected CN8 code is plotted as its own series.")
            time_series_chart = (
                alt.Chart(
                    details.assign(
                        **{
                            "CN code": details["Product code"]
                            .astype(str)
                            .map(format_cn_code)
                        }
                    )
                )
                .mark_line(point=True)
                .encode(
                    x=alt.X("Date:T", title="Period"),
                    y=alt.Y("Value (EUR):Q", title="Value (EUR)"),
                    color=alt.Color("CN code:N", title="CN code"),
                    tooltip=[
                        alt.Tooltip("Product:N", title="Product"),
                        alt.Tooltip("CN code:N", title="CN code"),
                        alt.Tooltip("Date:T", title="Period"),
                        alt.Tooltip("Value (EUR):Q", format=",.0f"),
                    ],
                )
                .interactive()
                .configure_axis(
                    labelColor="#333A3D",
                    titleColor="#333A3D",
                    gridColor="#A9C0C866",
                    domainColor="#A9C0C8",
                    labelFont="Arial",
                    titleFont="Arial",
                )
                .configure_view(stroke="#A9C0C8")
            )
            st.altair_chart(time_series_chart, width="stretch")
        elif not sankey_prefix:
            st.subheader(f"{frequency.title()} trade value")
            st.caption(
                "Series is the total across all returned CN8 product classes."
            )
            st.line_chart(
                timeline,
                x="Date",
                y="Value (EUR)",
                color="#426D78",
            )

        with st.expander(f"All {len(all_products):,} product classes"):
            with st.container(key="all-product-classes-table"):
                st.caption(
                    "Select a row to view its time series. Categories are sorted by "
                    "total value for the selected period."
                )
                table_selection = st.dataframe(
                    all_products.assign(
                        **{
                            "Product code": all_products["Product code"]
                            .astype(str)
                            .map(format_cn_code)
                        }
                    ),
                    hide_index=True,
                    width="stretch",
                    height=min(400, 30 * len(top_products) + 40),
                    on_select="rerun",
                    selection_mode="single-row",
                    key=f"all-product-classes-{chart_version}",
                )
            table_product_code = selected_table_product_code(
                table_selection.selection, all_products
            )
            if (
                table_product_code
                and table_product_code != st.session_state.get("selectedProductClass")
            ):
                st.session_state["selectedProductClass"] = table_product_code
                st.session_state.pop("selected_cn8_series", None)
                st.session_state.pop("sankey_prefix", None)
                st.session_state["sankey_chart_version"] = (
                    st.session_state.get("sankey_chart_version", 0) + 1
                )
                st.rerun()

        with st.expander("Raw data"):
            st.caption(f"ULJAS data version: {result['version']}")
            st.caption(
                f"Showing all {len(details):,} product-period rows in a scrollable table."
            )
            st.dataframe(
                details.assign(
                    **{
                        "Product code": details["Product code"]
                        .astype(str)
                        .map(format_cn_code)
                    }
                ),
                hide_index=True,
                width="stretch",
                height=min(400, 30 * len(top_products) + 40),
            )
            st.download_button(
                "Download CSV",
                details.to_csv(index=False).encode("utf-8"),
                file_name=f"uljas-{country}-{flow}.csv",
                mime="text/csv",
            )

st.caption("Source: Finnish Customs (Tulli), ULJAS. Quote Tulli when reusing the data.")
