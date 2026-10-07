import altair as alt
import pandas as pd
import requests
import streamlit as st

from customs_analysis import make_customs_pca
from export_licences import (
    decisions_in_period,
    load_year as load_licence_decisions_year,
    top_exporters,
)
from trade_data import (
    format_cn_code,
    load_data,
    load_product_classification_labels,
    make_dataframes,
    product_query_for_codes,
    selected_product_codes,
    selected_table_product_codes,
)
from trade_visualizations import (
    make_trade_sankey,
    sankey_plotly_events,
    selected_sankey_code,
)


st.set_page_config(page_title="Haitem • trade & economic metrics", page_icon="📊", layout="wide")
if "selectedProductClasses" not in st.session_state:
    previous_selected_class = st.session_state.get("selectedProductClass")
    st.session_state["selectedProductClasses"] = (
        [str(previous_selected_class)] if previous_selected_class else []
    )


def bump_chart_versions():
    for key in ("product_chart_version", "sankey_chart_version"):
        st.session_state[key] = st.session_state.get(key, 0) + 1


def request_product_query(product_prefix, sankey_prefix, selected_codes=None):
    product_prefix = str(product_prefix)
    sankey_prefix = str(sankey_prefix)
    if selected_codes is None:
        selected_codes = (product_prefix,) if product_prefix else ()
    elif isinstance(selected_codes, str):
        selected_codes = (selected_codes,)
    else:
        selected_codes = tuple(dict.fromkeys(str(code) for code in selected_codes))
    query_prefixes = selected_codes or ((product_prefix,) if product_prefix else ())
    st.session_state["pending_product_prefixes"] = query_prefixes
    st.session_state["sankey_prefix"] = sankey_prefix
    st.session_state["sankey_depth"] = len(sankey_prefix) // 2
    st.session_state["selectedProductClasses"] = list(selected_codes)
    bump_chart_versions()


def navigate_to_product_classes(product_codes):
    if not product_codes:
        return False
    if isinstance(product_codes, str):
        product_codes = (product_codes,)
    current_codes = st.session_state.get("selectedProductClasses", [])
    selected_codes = list(
        dict.fromkeys([*current_codes, *(str(code) for code in product_codes)])
    )
    if (
        selected_codes == current_codes
        and "pending_product_prefixes" not in st.session_state
    ):
        return False
    sankey_prefix = ""
    if len(selected_codes) == 1:
        selected_code = selected_codes[0]
        sankey_prefix = (
            selected_code[:-2]
            if selected_code.isdigit() and len(selected_code) == 8
            else selected_code
        )
    request_product_query(selected_codes[0], sankey_prefix, selected_codes)
    return True


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
        padding-bottom: 3rem;
    }

    div[data-testid="stVerticalBlock"] {
        gap: 0.85rem;
    }

    h1, h2, h3 {
        color: var(--ink);
        font-family: Arial, Helvetica, sans-serif;
        font-weight: 850;
        margin: 3rem 0 1rem 0;
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

    section[data-testid="stSidebar"] h2 {
        font-size: 1.5rem;
        margin: 0 0 0.5rem 0;
    }

    section[data-testid="stSidebar"] [class*="st-key-remove-query-class"] button {
        width: 100%;
        min-width: 2.6rem;
        min-height: 2.6rem;
        padding: 0.25rem;
        background: var(--muted-ink) !important;
        border: 2px solid var(--muted-ink) !important;
        color: var(--ink) !important;
        font-size: 1.25rem;
        font-weight: 800;
    }

    section[data-testid="stSidebar"] [class*="st-key-remove-query-class"] button:hover {
        background: var(--muted-ink) !important;
        border-color: var(--muted-ink) !important;
        color: var(--ink) !important;
        transform: scale(1.06);
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
    selected_query_codes = st.session_state.get("selectedProductClasses", [])
    for selected_query_code in selected_query_codes:
        classification_labels = st.session_state.get(
            "product_classification_labels", {}
        )
        selected_query_label = classification_labels.get(
            len(selected_query_code), {}
        ).get(selected_query_code)
        previous_result = st.session_state.get("uljas_result")
        if not selected_query_label and previous_result:
            previous_products = previous_result[3]
            matching_product = previous_products.loc[
                previous_products["Product code"].astype(str).eq(selected_query_code),
                "Product",
            ]
            if not matching_product.empty:
                selected_query_label = matching_product.iloc[0]
        with st.container(border=True):
            category_column, remove_column = st.columns([3, 1])
            category_column.markdown(
                f"<span style='color:#D27A37;font-weight:800'>"
                f"{format_cn_code(selected_query_code)}</span>",
                unsafe_allow_html=True,
            )
            category_column.caption(
                selected_query_label or "Selected product class"
            )
            if remove_column.button(
                "×",
                key=f"remove-query-class-{selected_query_code}",
                help=f"Remove {format_cn_code(selected_query_code)} from the query.",
            ):
                remaining_codes = [
                    code
                    for code in selected_query_codes
                    if code != selected_query_code
                ]
                request_product_query("", "", remaining_codes)
                st.rerun()
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
        submitted = st.form_submit_button("Load statistics", type="primary")
    st.caption(
        "Data loads on submit or when product classes are selected. Identical "
        "requests are cached for 1 hour."
    )

pending_product_query = "pending_product_prefixes" in st.session_state
if submitted or pending_product_query:
    bump_chart_versions()
    load_status = st.empty()
    try:
        if not country:
            raise ValueError("Enter a partner country code (ISO-2).")
        if submitted:
            query_prefixes = ()
            st.session_state.pop("pending_product_prefixes", None)
            st.session_state["selectedProductClasses"] = []
            st.session_state["sankey_prefix"] = ""
            st.session_state["sankey_depth"] = 0
        else:
            query_prefixes = st.session_state.pop("pending_product_prefixes")
        st.session_state.pop("uljas_result", None)
        classification_id, product_codes = product_query_for_codes(query_prefixes)
        query_prefix = query_prefixes[0] if len(query_prefixes) == 1 else ""
        query_scope = (
            f"the selected {len(query_prefixes):,} product classes"
            if query_prefixes
            else "all product classes"
        )
        load_status.caption(f"Querying {query_scope} from ULJAS...")
        result = load_data(
            country,
            flow,
            frequency,
            start,
            end,
            classification_id,
            product_codes,
        )
        load_status.caption("Preparing product classes and time series...")
        (
            timeline,
            top_products,
            all_products,
            details,
        ) = make_dataframes(result, frequency)
        load_status.caption("Loading product-class labels...")
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
        st.session_state["active_product_prefix"] = query_prefix
        load_status.caption("Trade data ready.")
    except (requests.RequestException, RuntimeError, ValueError) as error:
        load_status.empty()
        st.error(f"Could not load ULJAS data: {error}")

if "uljas_result" not in st.session_state:
    st.info("Choose a partner country, trade flow, and period.")
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
        active_product_prefix = st.session_state.get("active_product_prefix", "")
        selected_scope_codes = st.session_state.get("selectedProductClasses", [])
        product_scope = (
            f"{len(selected_scope_codes):,} selected product classes"
            if len(selected_scope_codes) > 1
            else f"{format_cn_code(active_product_prefix)} and descendants"
            if active_product_prefix
            else "all product classes"
        )
        st.metric(
            f"Total value · {product_scope} · {first_period}–{last_period}",
            f"€{total:,.0f}",
        )

        source = "Finland" if flow == "exports" else country
        destination = country if flow == "exports" else "Finland"
        st.subheader(f"Trade flow · {source} → {destination}")
        sankey_prefix = st.session_state.get("sankey_prefix", "")
        sankey_depth = st.session_state.get("sankey_depth", len(sankey_prefix) // 2)
        st.caption(f"Sankey zoom depth: {sankey_depth} / 4")
        if sankey_prefix:
            st.caption(
                f"Breakdown path: {source} → {format_cn_code(sankey_prefix)} "
                f"→ {destination}"
            )
            back_column, reset_column = st.columns(2)
            with back_column:
                if st.button("Back one level", key="sankey-back"):
                    parent_prefix = sankey_prefix[:-2]
                    request_product_query(
                        parent_prefix, parent_prefix
                    )
                    st.rerun()
            with reset_column:
                if st.button("Reset Sankey", key="sankey-reset"):
                    request_product_query("", "", None)
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
            sankey_depth,
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
                    "Check another partner, period, or trade flow."
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
            if navigate_to_product_classes(clicked_category_code):
                st.rerun()
            st.caption(
                "Flow widths show recorded customs trade value, not money transfers. "
                "Hover a node or band for its full product name; click a code node "
                "or flow band to drill down. "
                "The 8 largest visible positive product classes are shown "
                "individually; remaining product classes are grouped as "
                "non-clickable Other."
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
                st.info("No time-series values are available for this product class.")
            else:
                st.line_chart(
                    selected_timeline,
                    x="Date",
                    y="Value (EUR)",
                    color="#426D78",
                )

        chart_version = st.session_state.get("product_chart_version", 0)
        product_chart_column, licence_chart_column = st.columns([2, 1])
        product_class_codes = all_products["Product code"].astype(str).tolist()
        product_class_labels = (
            all_products.assign(
                **{"Product code": all_products["Product code"].astype(str)}
            )
            .set_index("Product code")["Product"]
            .to_dict()
        )
        selected_class_codes = st.multiselect(
            "Product classes to display",
            options=product_class_codes,
            default=product_class_codes[: min(40, len(product_class_codes))],
            format_func=lambda code: (
                f"{format_cn_code(code)} · {product_class_labels.get(code, code)}"
            ),
            key=(
                f"selected-product-classes-{country}-{flow}-{frequency}-"
                f"{start}-{end}-{hash(tuple(product_class_codes))}"
            ),
        )
        if selected_class_codes and st.button(
            "Query selected product classes",
            key="query-selected-product-classes",
            help="Load the union of the selected CN classes in all charts.",
        ):
            request_product_query(
                selected_class_codes[0], "", selected_class_codes
            )
            st.rerun()
        selected_products = all_products.loc[
            all_products["Product code"].astype(str).isin(selected_class_codes)
        ].copy()
        selected_products["Product code"] = selected_products["Product code"].astype(
            str
        )
        selected_products["CN code"] = selected_products["Product code"].map(
            format_cn_code
        )
        selected_products["CN group"] = selected_products["Product code"].str[:2].map(
            format_cn_code
        )
        selected_group_count = selected_products["CN group"].nunique()
        with product_chart_column:
            st.subheader("Product classes · 2-digit groups")
            st.caption(
                f"Showing {len(selected_class_codes):,} selected classes across "
                f"{selected_group_count:,} groups. Each bar is grouped by its "
                "two-digit code and stacked by product class; select a segment "
                "to load its time series."
            )
            if st.session_state.get("selectedProductClasses"):
                if st.button(
                    "Clear selected product classes", key="clear-product-selection"
                ):
                    request_product_query("", "", None)
                    st.rerun()
        product_selection = alt.selection_point(
            fields=["Product code"],
            name="product_class_bar_selection",
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
                selected_products.assign(
                    **{
                        "Selected": selected_products["Product code"].map(
                            lambda code: any(
                                code.startswith(selected_code)
                                for selected_code in st.session_state.get(
                                    "selectedProductClasses", []
                                )
                            )
                        ),
                    }
                )
            )
            .mark_bar(orient="horizontal", cursor="pointer")
            .encode(
                x=alt.X(
                    "Value (EUR):Q",
                    title="Value (EUR)",
                    scale=alt.Scale(zero=True),
                    stack="zero",
                ),
                y=alt.Y(
                    "CN group:N",
                    sort=alt.EncodingSortField(
                        field="Value (EUR)", op="sum", order="descending"
                    ),
                    axis=alt.Axis(title="2-digit CN group"),
                ),
                color=alt.condition(
                    alt.datum.Selected,
                    alt.value("#D27A37"),
                    alt.Color(
                        "Value (EUR):Q",
                        scale=alt.Scale(range=["#A9C0C8", "#426D78"]),
                        legend=None,
                    ),
                ),
                opacity=alt.condition(bar_hover, alt.value(1), alt.value(0.82)),
                tooltip=[
                    alt.Tooltip("Product:N", title="Product class"),
                    alt.Tooltip("CN code:N", title="Product class code"),
                    alt.Tooltip("Value (EUR):Q", format=",.0f"),
                ],
            )
            .properties(
                height=min(900, max(420, 40 * selected_group_count + 50))
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
                key=(
                    f"product-category-chart-{chart_version}-"
                    f"{hash(tuple(selected_class_codes))}"
                ),
                on_select="rerun",
                selection_mode="product_class_bar_selection",
            )
        clicked_product_codes = selected_product_codes(chart_event.selection)
        if navigate_to_product_classes(clicked_product_codes):
            st.rerun()

        with licence_chart_column:
            selected_product_classes = st.session_state.get(
                "selectedProductClasses", []
            )
            if not selected_product_classes:
                st.subheader("Plenary decisions")
                st.info("Select a product class to view plenary decisions.")
            else:
                st.subheader(
                    "Plenary decisions · "
                    + ", ".join(
                        format_cn_code(code)
                        for code in selected_product_classes
                    )
                )
                st.caption(
                    "Decision counts and sources cover the selected period; the "
                    "plenary archive does not identify customs product classes. "
                    "This archive is not a register of de facto exports."
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
                    loaded_licences is not None
                    and loaded_licences[0] == licence_years
                )
                load_col, refresh_col = st.columns(2)
                with load_col:
                    load_licences = st.button(
                        "Load decisions",
                        key=f"load-licence-decisions-{licence_years}",
                        help=(
                            "Loads cached decisions, or retrieves the official "
                            "archive by year."
                        ),
                    )
                with refresh_col:
                    refresh_licences = st.button(
                        "Refresh",
                        key=f"refresh-licence-decisions-{licence_years}",
                        help="Re-enumerates the official yearly archive pages.",
                    )
                if load_licences or refresh_licences:
                    licence_status = st.empty()
                    try:
                        datasets = []
                        for index, year in enumerate(licence_years, start=1):
                            licence_status.caption(
                                f"Loading archive year {year} "
                                f"({index}/{len(licence_years)})..."
                            )
                            datasets.append(
                                load_licence_decisions_year(
                                    year, refresh=refresh_licences
                                )
                            )
                        licence_status.caption("Export-licence decisions ready.")
                        st.session_state["public_licence_decisions"] = (
                            licence_years,
                            datasets,
                        )
                        loaded_licences = (licence_years, datasets)
                        has_matching_years = True
                    except requests.RequestException as error:
                        licence_status.empty()
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
                                    alt.Tooltip(
                                        "Decisions:Q", title="Public decisions"
                                    ),
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
        st.subheader("Product class PCA")
        with st.container():
            st.write(
                "Compare how selected product classes move together over time. "
                "Period dots show customs-value profiles; labeled diamonds show "
                "each product class's contribution to the axes."
            )
            st.write(
                "Values are standardized by product class so large classes do not "
                "dominate. This uses customs data, not procurement data. "
                "The available customs and exporter datasets do not link company "
                "names to product classes or customs values."
            )
            pca_codes = product_class_codes
            pca_labels = (
                all_products.assign(
                    **{"Product code": all_products["Product code"].astype(str)}
                )
                .set_index("Product code")["Product"]
                .to_dict()
            )
            selected_pca_codes = st.multiselect(
                "Product classes in PCA",
                options=pca_codes,
                default=selected_class_codes[: min(8, len(selected_class_codes))],
                format_func=lambda code: (
                    f"{format_cn_code(code)} · {pca_labels.get(code, code)}"
                ),
                max_selections=12,
                key=(
                    f"customs-pca-{country}-{flow}-{frequency}-{start}-{end}-"
                    f"{hash(tuple(pca_codes))}"
                ),
            )
            try:
                pca_scores, pca_categories, explained_variance = make_customs_pca(
                    details, selected_pca_codes
                )
            except ValueError as error:
                st.info(str(error))
            else:
                st.metric(
                    "Variance explained by displayed axes",
                    f"{explained_variance.sum():.1%}",
                )
                period_chart = (
                    alt.Chart(pca_scores)
                    .mark_circle(
                        size=100,
                        filled=True,
                        color="#426D78",
                        stroke="#202629",
                        strokeWidth=1,
                    )
                    .encode(
                        x=alt.X(
                            "PC1:Q",
                            title=f"PC1 ({explained_variance[0]:.1%})",
                            scale=alt.Scale(zero=False),
                        ),
                        y=alt.Y(
                            "PC2:Q",
                            title=f"PC2 ({explained_variance[1]:.1%})",
                            scale=alt.Scale(zero=False),
                        ),
                        tooltip=[
                            alt.Tooltip("Period:T", title="Period"),
                            alt.Tooltip("PC1:Q", format=".3f"),
                            alt.Tooltip("PC2:Q", format=".3f"),
                        ],
                    )
                )
                selected_product_classes = st.session_state.get(
                    "selectedProductClasses", []
                )
                category_points = (
                    alt.Chart(
                        pca_categories.assign(
                            **{
                                "Selected": pca_categories["Product code"].map(
                                    lambda code: any(
                                        str(code).startswith(selected_code)
                                        for selected_code in selected_product_classes
                                    )
                                )
                            }
                        )
                    )
                    .mark_point(
                        shape="diamond",
                        size=110,
                        filled=True,
                        strokeWidth=2,
                    )
                    .encode(
                        x=alt.X("PC1:Q"),
                        y=alt.Y("PC2:Q"),
                        fill=alt.condition(
                            alt.datum.Selected,
                            alt.value("#D27A37"),
                            alt.value("#333A3D"),
                        ),
                        size=alt.condition(
                            alt.datum.Selected,
                            alt.value(260),
                            alt.value(110),
                        ),
                        stroke=alt.condition(
                            alt.datum.Selected,
                            alt.value("#202629"),
                            alt.value("#333A3D"),
                        ),
                        tooltip=[
                            alt.Tooltip("Product:N", title="Product class"),
                            alt.Tooltip("Product code:N", title="Product class code"),
                            alt.Tooltip("PC1:Q", title="PC1 coordinate", format=".3f"),
                            alt.Tooltip("PC2:Q", title="PC2 coordinate", format=".3f"),
                            alt.Tooltip(
                                "Confidence:Q",
                                title="Two-PC representation quality",
                                format=".1%",
                            ),
                        ],
                    )
                    .add_params(
                        alt.selection_point(
                            fields=["Product code"],
                            name="product_class_bar_selection",
                            clear=False,
                            toggle=False,
                        )
                    )
                )
                category_labels = (
                    alt.Chart(
                        pca_categories.assign(
                            **{
                                "CN code": pca_categories["Product code"].map(
                                    format_cn_code
                                )
                            }
                        )
                    )
                    .mark_text(
                        align="left",
                        baseline="middle",
                        dx=7,
                        fontSize=11,
                        fontWeight="bold",
                        color="#202629",
                    )
                    .encode(
                        x=alt.X("PC1:Q"),
                        y=alt.Y("PC2:Q"),
                        text=alt.Text("CN code:N"),
                    )
                )
                pca_chart = (
                    (period_chart + category_points + category_labels)
                    .properties(height=440)
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
                pca_chart_event = st.altair_chart(
                    pca_chart,
                    width="stretch",
                    key=(
                        f"pca-product-classes-{country}-{flow}-{frequency}-"
                        f"{start}-{end}-{hash(tuple(selected_pca_codes))}-"
                        f"{hash(tuple(selected_product_classes))}"
                    ),
                    on_select="rerun",
                    selection_mode="product_class_bar_selection",
                )
                clicked_pca_codes = selected_product_codes(pca_chart_event.selection)
                if navigate_to_product_classes(clicked_pca_codes):
                    st.rerun()
                st.caption(
                    "Nearby periods have similar standardized customs-value "
                    "profiles. Product-class coordinates indicate association "
                    "with each axis; they are not company-level observations. "
                    "The confidence score is cos²: the share of product-class variation "
                    "represented by the displayed two components, not statistical "
                    "certainty. High 🟢 means over 90% representation."
                )
                pca_table = pca_categories.sort_values(
                    "Confidence", ascending=False
                ).reset_index(drop=True)
                pca_table["Assessment"] = pca_table["Confidence"].map(
                    lambda score: "High 🟢" if score > 0.9 else "—"
                )
                pca_table_selection = st.dataframe(
                    pca_table,
                    hide_index=True,
                    width="stretch",
                    column_config={
                        "PC1": st.column_config.NumberColumn(
                            "PC1 coordinate", format="%.3f"
                        ),
                        "PC2": st.column_config.NumberColumn(
                            "PC2 coordinate", format="%.3f"
                        ),
                        "Confidence": st.column_config.NumberColumn(
                            "Confidence score", format="percent"
                        ),
                        "Assessment": st.column_config.TextColumn("Assessment"),
                    },
                    on_select="rerun",
                    selection_mode="multi-row",
                    key=(
                        f"pca-product-class-table-{country}-{flow}-{frequency}-"
                        f"{start}-{end}-{hash(tuple(selected_pca_codes))}"
                    ),
                )
                pca_table_product_codes = selected_table_product_codes(
                    pca_table_selection.selection, pca_table
                )
                if navigate_to_product_classes(pca_table_product_codes):
                    st.rerun()

        if not sankey_prefix:
            st.subheader(f"{frequency.title()} trade value")
            st.caption(
                "Series is the total across all returned product classes."
            )
            st.line_chart(
                timeline,
                x="Date",
                y="Value (EUR)",
                color="#426D78",
            )

st.caption("Source: Finnish Customs (Tulli), ULJAS. Quote Tulli when reusing the data.")
