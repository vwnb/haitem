"""Analysis helpers for customs product-class time series."""

import numpy as np
import pandas as pd


def make_customs_pca(details, product_codes, group_length=None):
    """Return period scores, product-class coordinates, and explained variance.

    When ``group_length`` is given, leaf rows are aggregated to that CN scope
    first, so mixed-hierarchy queries compare groups without double-counting
    parent rows.
    """
    selected_codes = tuple(dict.fromkeys(str(code) for code in product_codes))
    if len(selected_codes) < 2:
        raise ValueError("Select at least two product classes.")

    frame = details.copy()
    if group_length is not None:
        frame = frame.loc[
            frame["Product code"].astype(str).str.fullmatch(r"\d{2,8}")
        ].copy()
        frame["Product code"] = frame["Product code"].astype(str).str[:group_length]
        frame["Product"] = frame["Product code"]
    selected = frame.loc[
        frame["Product code"].astype(str).isin(selected_codes),
        ["Date", "Product code", "Product", "Value (EUR)"],
    ].copy()
    if selected.empty:
        raise ValueError("No customs values are available for the selected product classes.")
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
        raise ValueError("At least two selected product classes must vary over time.")

    standardized = (values - values.mean(axis=0)) / standard_deviations
    left_vectors, singular_values, right_vectors = np.linalg.svd(
        standardized.to_numpy(), full_matrices=False
    )
    if len(singular_values) < 2:
        raise ValueError("The selected data supports fewer than two principal components.")

    variances = singular_values**2
    explained_variance = variances / variances.sum()
    period_totals = values.sum(axis=1)
    category_totals = values.sum(axis=0)
    scores = pd.DataFrame(
        {
            "Period": values.index,
            "PC1": left_vectors[:, 0] * singular_values[0],
            "PC2": left_vectors[:, 1] * singular_values[1],
            "Value (EUR)": period_totals.to_numpy(),
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
            "Value (EUR)": category_totals.to_numpy(),
            "PC1": right_vectors[0, :] * singular_values[0] / np.sqrt(len(values) - 1),
            "PC2": right_vectors[1, :] * singular_values[1] / np.sqrt(len(values) - 1),
            "Confidence": (
                (right_vectors[:2, :] ** 2).T @ variances[:2]
            )
            / ((right_vectors**2).T @ variances),
        }
    )
    return scores, category_coordinates, explained_variance[:2]


def cluster_pca_points(frame, n_clusters=3):
    """Label PC1/PC2 points with simple deterministic k-means clusters.

    The PC axes are range-standardized internally so PC1 does not dominate
    the distances; returned centers are in the original PC coordinates.
    Returns ``(labels, centers)`` where ``labels`` is a list of
    ``"Cluster N"`` strings aligned to ``frame`` order and ``centers`` is a
    DataFrame with ``Cluster``/``PC1``/``PC2`` columns.
    """
    points = frame[["PC1", "PC2"]].to_numpy(dtype=float)
    finite_mask = np.isfinite(points).all(axis=1)
    finite_points = points[finite_mask]
    count = len(finite_points)
    clusters = max(1, min(int(n_clusters), count) if count else 1)
    labels_order = [f"Cluster {index + 1}" for index in range(clusters)]

    if count == 0:
        centers = pd.DataFrame(
            {"Cluster": labels_order, "PC1": [np.nan], "PC2": [np.nan]}
        )
        return [labels_order[0]] * len(frame), centers

    minimum = finite_points.min(axis=0)
    scales = finite_points.max(axis=0) - minimum
    scales[scales == 0] = 1.0
    scaled = (finite_points - minimum) / scales

    order = np.lexsort((scaled[:, 1], scaled[:, 0]))
    seeds = np.linspace(0, count - 1, clusters).round().astype(int)
    centroids = scaled[order[seeds]].copy()

    assignments = np.zeros(count, dtype=int)
    for _ in range(100):
        distances = ((scaled[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        new_assignments = distances.argmin(axis=1)
        if np.array_equal(new_assignments, assignments):
            break
        assignments = new_assignments
        closest = distances.min(axis=1)
        for cluster in range(clusters):
            members = scaled[assignments == cluster]
            if len(members):
                centroids[cluster] = members.mean(axis=0)
            else:
                centroids[cluster] = scaled[int(closest.argmax())]

    centers_scaled = np.array(
        [
            scaled[assignments == cluster].mean(axis=0)
            if (assignments == cluster).any()
            else centroids[cluster]
            for cluster in range(clusters)
        ]
    )
    centers_original = centers_scaled * scales + minimum
    centers = pd.DataFrame(
        {
            "Cluster": labels_order,
            "PC1": centers_original[:, 0],
            "PC2": centers_original[:, 1],
        }
    )

    labels = [labels_order[0]] * len(frame)
    finite_indices = np.where(finite_mask)[0]
    for position, index in enumerate(finite_indices):
        labels[index] = labels_order[int(assignments[position])]
    return labels, centers
