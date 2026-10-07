"""ULJAS query, transformation, and product-selection helpers."""

import pandas as pd
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


@st.cache_data(ttl=3600, max_entries=1, show_spinner=False)
def load_product_classification_labels():
    client = UljasClient()
    return {
        2: client.product_classification_labels(4),
        4: client.product_classification_labels(5),
        6: client.product_classification_labels(6),
    }


@st.cache_data(ttl=3600, max_entries=3, show_spinner=False)
def load_product_classification_codes(classification_id):
    client = UljasClient()
    return client.product_classification_codes(classification_id)


def product_query_for_prefix(prefix):
    """Return the next deeper ULJAS classification and matching product classes."""
    return product_query_for_codes((prefix,) if prefix else ())


def product_query_for_codes(prefixes):
    """Return one classification containing descendants of all selected CN codes."""
    prefixes = tuple(dict.fromkeys(str(prefix) for prefix in prefixes if prefix))
    if not prefixes:
        return 1, ()

    if any(not prefix.isdigit() for prefix in prefixes):
        if len(prefixes) == 1:
            return 1, prefixes
        raise ValueError("Multiple product classes must use numeric CN codes.")

    target_code_length = max(min(len(prefix) + 2, 8) for prefix in prefixes)
    classification_id = {4: 3, 6: 2, 8: 1}.get(target_code_length)
    if classification_id is None:
        raise ValueError("Product class navigation must use 2-digit CN levels.")
    product_codes = tuple(
        code
        for code in load_product_classification_codes(classification_id)
        if len(code) == target_code_length
        and any(code.startswith(prefix) for prefix in prefixes)
    )
    if not product_codes:
        formatted_prefixes = ", ".join(format_cn_code(prefix) for prefix in prefixes)
        raise ValueError(
            f"No deeper product classes found under {formatted_prefixes}."
        )
    return classification_id, product_codes


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
    code = str(code)
    if code.isdigit():
        return "CN " + " ".join(
            code[index : index + 2] for index in range(0, len(code), 2)
        )
    return f"CN {code}"


def selected_product_codes(selection):
    selected_items = selection.get("product_class_bar_selection", [])
    return [
        str(item["Product code"])
        for item in selected_items
        if item.get("Product code") is not None
    ]


def selected_table_product_codes(selection, products):
    if not selection.rows:
        return []
    return [
        str(products.iloc[row]["Product code"])
        for row in selection.rows
    ]
