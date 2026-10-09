"""ULJAS query, transformation, and product-selection helpers."""

import re

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
    """Return the deepest ULJAS classification that fits one cell budget.

    Navigation rule (simple, no focus tricks):

    - Root (no prefix) loads CN2+CN4 (classification 5, ~1.4k codes). It is
      cheap and the Sankey, stacked bars, and PCA all render two hierarchy
      levels at once, so the first view already has comparable structure.
    - A CN2 chapter loads CN2+CN4+CN6 under it (classification 6 restricted by
      prefix). Worst case (chapter 84/85) is ~600 CN6 codes, still cheap.
    - A CN4 heading loads CN6 under it (classification 2 restricted by
      prefix). Worst case is ~239 codes.
    - A CN6 subheading loads CN8 under it (classification 1 restricted by
      prefix). Worst case is ~61 codes.
    - A leaf CN8 code has no deeper children: show its CN6 parent's CN8
      children (siblings) instead, so a click never dead-ends.
    """
    prefixes = tuple(dict.fromkeys(str(prefix) for prefix in prefixes if prefix))
    if not prefixes:
        all_codes = load_product_classification_codes(5)
        product_codes = tuple(
            code for code in all_codes if len(code) in (2, 4)
        )
        if not product_codes:
            raise ValueError("No chapter/heading product classes are available.")
        return 5, product_codes

    if any(not prefix.isdigit() for prefix in prefixes):
        if len(prefixes) == 1:
            return 1, prefixes
        raise ValueError("Multiple product classes must use numeric CN codes.")

    # Leaf CN8 codes have no children: query the CN6 parent instead so the
    # view shows CN8 siblings rather than a single-product dead end.
    query_prefixes = tuple(
        prefix[:-2] if len(prefix) == 8 else prefix for prefix in prefixes
    )
    query_prefixes = tuple(
        dict.fromkeys(prefix for prefix in query_prefixes if prefix)
    )
    if not query_prefixes:
        all_codes = load_product_classification_codes(5)
        product_codes = tuple(
            code for code in all_codes if len(code) in (2, 4)
        )
        if not product_codes:
            raise ValueError("No chapter/heading product classes are available.")
        return 5, product_codes

    scope_level = min(len(prefix) for prefix in query_prefixes)
    if scope_level <= 2:
        # CN2 chapter (or multi-select rooted at CN2): chapters + headings +
        # subheadings under the selected chapters.
        all_codes = load_product_classification_codes(6)
        product_codes = tuple(
            code
            for code in all_codes
            if len(code) in (2, 4, 6)
            and any(
                code == prefix or code.startswith(prefix)
                for prefix in query_prefixes
            )
        )
        classification_id = 6
    elif scope_level <= 4:
        # CN4 heading: headings + subheadings underneath.
        all_codes = load_product_classification_codes(6)
        product_codes = tuple(
            code
            for code in all_codes
            if len(code) in (4, 6)
            and any(
                code == prefix or code.startswith(prefix)
                for prefix in query_prefixes
            )
        )
        classification_id = 6
    else:
        # CN6 subheading (or leaf remapped to CN6): CN8 items under the CN6
        # parents, plus the CN6 parent rows themselves. Classification 6 is
        # CN2+CN4+CN6, so it cannot carry CN8 rows: query CN8 alone and let
        # the views derive the CN6 parent locally via prefix.
        parent_prefixes = {prefix[:6] for prefix in query_prefixes}
        product_codes = tuple(
            code
            for code in load_product_classification_codes(1)
            if len(code) == 8
            and any(code.startswith(prefix) for prefix in parent_prefixes)
        )
        classification_id = 1
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
    # Mixed-hierarchy queries (e.g. CN2 chapters + CN4 headings) carry a level
    # tag so totals keep every level while Sankey/bars/PCA use leaf rows only.
    # A row is a leaf when no other loaded row extends it as a strict prefix.
    code_strings = details["Product code"].astype(str).unique().tolist()
    leaf_code_set = {
        code
        for code in code_strings
        if re.fullmatch(r"\d{2,8}", str(code)) is None
        or not any(
            other != code and str(other).startswith(str(code))
            for other in code_strings
        )
    }
    details["CN level"] = (
        details["Product code"].astype(str).str.len().fillna(0).astype(int)
    )
    details["Leaf"] = details["Product code"].astype(str).isin(leaf_code_set)
    leaf_details = details.loc[details["Leaf"]].copy()
    timeline = (
        leaf_details.groupby("Date", as_index=False)["Value (EUR)"]
        .sum()
        .sort_values("Date")
    )
    leaf_products = (
        leaf_details.groupby(["Product code", "Product"], as_index=False)["Value (EUR)"]
        .sum()
        .sort_values("Value (EUR)", ascending=False)
    )
    all_products = (
        details.groupby(["Product code", "Product"], as_index=False)["Value (EUR)"]
        .sum()
        .sort_values("Value (EUR)", ascending=False)
    )
    return timeline, leaf_products.head(33), leaf_products, all_products, details, leaf_details


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
