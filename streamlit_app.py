import altair as alt
import pandas as pd
import requests
import streamlit as st

from index import DEFAULT_CUBE_ID, UljasClient


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


st.set_page_config(page_title="Haitem • trade & economic metrics", page_icon="📊", layout="wide")
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
        font-family: Arial, Helvetica, sans-serif !important;
        font-weight: 850 !important;
        margin: 2rem 0 1rem 0;
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
st.title("Haitem • trade & economic metrics")
st.caption("Source: ULJAS (https://uljas.tulli.fi/v3rti/)")

with st.sidebar:
    st.header("Query")
    with st.form("uljas-query"):
        country = st.text_input("Partner country code", value="IL").strip().upper()
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
            "CN8 product code(s), optional",
            help="Enter exact CN8 codes separated by commas (up to 10) to query focused product time series.",
        )
        submitted = st.form_submit_button("Load statistics", type="primary")
    st.caption(
        "Data loads on submit or when a product bar is selected. Identical "
        "requests are cached for 1 hour."
    )

if submitted:
    st.session_state.pop("uljas_result", None)
    st.session_state.pop("selected_cn8_series", None)
    st.session_state.pop("selected_cn8_code", None)
    st.session_state["product_chart_version"] = (
        st.session_state.get("product_chart_version", 0) + 1
    )
    try:
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

        st.subheader(
            "Selected CN8 categories" if product_codes else "Top 33 product categories"
        )
        if product_codes:
            st.caption(
                f"Showing {len(top_products):,} of {len(all_products):,} selected "
                "categories. Click a bar to load its time series."
            )
        else:
            st.caption(
                f"Showing {len(top_products):,} of {len(all_products):,} categories. "
                "Click a bar "
                "to load its time series; hover "
                "to see its full category name."
            )
        left, right = st.columns([3, 2])
        with left:
            chart_version = st.session_state.get("product_chart_version", 0)
            if st.session_state.get("selected_cn8_code"):
                if st.button("Clear product selection", key="clear-cn8-selection"):
                    st.session_state.pop("selected_cn8_series", None)
                    st.session_state.pop("selected_cn8_code", None)
                    st.session_state["product_chart_version"] = chart_version + 1
                    chart_version += 1
            product_selection = alt.selection_point(
                fields=["Product code"],
                name="cn8_bar_selection",
                clear="dblclick",
                toggle=False,
            )
            product_chart = (
                alt.Chart(top_products)
                .mark_bar()
                .encode(
                    x=alt.X("Value (EUR):Q", title="Value (EUR)", scale=alt.Scale(zero=True)),
                    y=alt.Y("Product code:N", sort="-x", title="CN code"),
                    tooltip=[
                        alt.Tooltip("Product:N", title="Product category"),
                        alt.Tooltip("Product code:N", title="CN code"),
                        alt.Tooltip("Value (EUR):Q", format=",.0f"),
                    ],
                )
                .add_params(product_selection)
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
            chart_event = st.altair_chart(
                product_chart,
                use_container_width=True,
                key=f"product-category-chart-{chart_version}",
                on_select="rerun",
                selection_mode="cn8_bar_selection",
            )
            clicked_product_code = selected_product_code(chart_event.selection)
            if clicked_product_code != st.session_state.get("selected_cn8_code"):
                st.session_state["selected_cn8_code"] = clicked_product_code
                st.session_state.pop("selected_cn8_series", None)
        with right:
            st.dataframe(
                top_products,
                hide_index=True,
                use_container_width=True,
                height=500,
            )

        selected_code = st.session_state.get("selected_cn8_code")
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
                    with st.spinner(f"Loading CN8 {selected_code} time series..."):
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
                    st.error(f"Could not load CN8 {selected_code} time series: {error}")
                    cached_series = None
            if cached_series:
                _, series_frames = cached_series
                series_timeline, _, series_products, _ = series_frames
                if series_products.empty:
                    st.warning(f"ULJAS returned no data for CN8 {selected_code}.")
                else:
                    selected_product = series_products.iloc[0]
                    st.subheader(
                        f"{frequency.title()} time series · CN8 {selected_product['Product code']}"
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
        elif product_codes:
            st.subheader(f"{frequency.title()} trade value · selected CN8 products")
            st.caption("Each selected CN8 code is plotted as its own series.")
            time_series_chart = (
                alt.Chart(details)
                .mark_line(point=True)
                .encode(
                    x=alt.X("Date:T", title="Period"),
                    y=alt.Y("Value (EUR):Q", title="Value (EUR)"),
                    color=alt.Color("Product code:N", title="CN8 code"),
                    tooltip=[
                        alt.Tooltip("Product:N", title="Product"),
                        alt.Tooltip("Product code:N", title="CN8 code"),
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
            st.altair_chart(time_series_chart, use_container_width=True)
        else:
            st.subheader(f"{frequency.title()} trade value")
            st.caption(
                "Series is the total across all returned CN8 product categories."
            )
            st.line_chart(
                timeline,
                x="Date",
                y="Value (EUR)",
                color="#426D78",
            )

        with st.expander(f"All {len(all_products):,} product categories"):
            st.caption(
                "Scrollable table of every returned category, sorted by total "
                "value for the selected period."
            )
            st.dataframe(
                all_products,
                hide_index=True,
                use_container_width=True,
                height=500,
            )

            st.markdown("**Copy a full category label**")
            label_search = st.text_input(
                "Find by CN code or product name",
                key="product-label-search",
            ).strip().casefold()
            if len(label_search) < 2:
                st.info("Enter at least two characters to search for a copyable label.")
            else:
                matching_products = all_products[
                    all_products["Product code"].str.casefold().str.contains(
                        label_search, regex=False
                    )
                    | all_products["Product"].str.casefold().str.contains(
                        label_search, regex=False
                    )
                ]
                st.caption(f"{len(matching_products):,} matching labels.")
                if not matching_products.empty:
                    selected_label = st.selectbox(
                        "Select category",
                        matching_products.apply(
                            lambda row: f"{row['Product code']} — {row['Product']}",
                            axis=1,
                        ).tolist(),
                        key="copyable-product-label",
                    )
                    st.code(selected_label, language=None)

        with st.expander("Raw data"):
            st.caption(f"ULJAS data version: {result['version']}")
            st.caption(
                f"Showing all {len(details):,} product-period rows in a scrollable table."
            )
            st.dataframe(
                details,
                hide_index=True,
                use_container_width=True,
                height=500,
            )
            st.download_button(
                "Download CSV",
                details.to_csv(index=False).encode("utf-8"),
                file_name=f"uljas-{country}-{flow}.csv",
                mime="text/csv",
            )

st.caption("Source: Finnish Customs (Tulli), ULJAS. Quote Tulli when reusing the data.")
