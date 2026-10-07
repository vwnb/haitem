"""Analysis helpers for customs product-category time series."""

import numpy as np
import pandas as pd


def make_customs_pca(details, product_codes):
    """Return period scores, category coordinates, and explained variance for a PCA biplot."""
    selected_codes = tuple(dict.fromkeys(str(code) for code in product_codes))
    if len(selected_codes) < 2:
        raise ValueError("Select at least two product categories.")

    selected = details.loc[
        details["Product code"].astype(str).isin(selected_codes),
        ["Date", "Product code", "Product", "Value (EUR)"],
    ].copy()
    if selected.empty:
        raise ValueError("No customs values are available for the selected categories.")
    selected["Product code"] = selected["Product code"].astype(str)

    values = (
        selected.pivot_table(
            index="Date",
            columns="Product code",
            values="Value (EUR)",
            aggfunc="sum",
            fill_value=0,
        )
        .reindex(columns=selected_codes, fill_value=0)
        .sort_index()
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0)
    )
    if len(values.index) < 3:
        raise ValueError("PCA needs at least three time periods.")

    standard_deviations = values.std(axis=0, ddof=0)
    variable_categories = standard_deviations.gt(0)
    values = values.loc[:, variable_categories]
    standard_deviations = standard_deviations.loc[variable_categories]
    if values.shape[1] < 2:
        raise ValueError("At least two selected categories must vary over time.")

    standardized = (values - values.mean(axis=0)) / standard_deviations
    left_vectors, singular_values, right_vectors = np.linalg.svd(
        standardized.to_numpy(), full_matrices=False
    )
    if len(singular_values) < 2:
        raise ValueError("The selected data supports fewer than two principal components.")

    variances = singular_values**2
    explained_variance = variances / variances.sum()
    scores = pd.DataFrame(
        {
            "Period": values.index,
            "PC1": left_vectors[:, 0] * singular_values[0],
            "PC2": left_vectors[:, 1] * singular_values[1],
        }
    )

    category_labels = (
        selected.drop_duplicates("Product code")
        .set_index("Product code")["Product"]
        .reindex(values.columns)
    )
    category_coordinates = pd.DataFrame(
        {
            "Product code": values.columns,
            "Product": category_labels.to_numpy(),
            "PC1": right_vectors[0, :] * singular_values[0] / np.sqrt(len(values) - 1),
            "PC2": right_vectors[1, :] * singular_values[1] / np.sqrt(len(values) - 1),
        }
    )
    return scores, category_coordinates, explained_variance[:2]
