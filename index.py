#!/usr/bin/env python3

import argparse
import json
import re
import sys

import requests

API_BASE = "https://uljas.tulli.fi/verti-tieto-0"
DEFAULT_CUBE_ID = 57
DEFAULT_PRODUCT_CLASSIFICATION_ID = 4

FLOW_CODES = {
    "imports": "1",
    "exports": "2",
}
METRIC_IDS = {
    "value": 0,
    "quantity": 2,
    "quantity_unit": 3,
    "supplementary_quantity": 5,
    "supplementary_quantity_unit": 6,
}


class UljasClient:
    def __init__(self, language="en"):
        self.language = language
        self.session = requests.Session()
        self._classifications = {}
        self.database = self._get_json("/api/database")

    def _get_json(self, path):
        response = self.session.get(
            f"{API_BASE}{path}",
            params={"language": self.language},
            headers={"Accept": "application/json"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("errorId"):
            raise RuntimeError(payload.get("message", payload["errorId"]))
        return payload

    def _get_classification(self, classification_id):
        classification_id = str(classification_id)
        if classification_id not in self._classifications:
            self._classifications[classification_id] = self._get_json(
                f"/api/classifications/{classification_id}"
            )
        return self._classifications[classification_id]

    def _find_member(self, classification_ids, code):
        for classification_id in classification_ids:
            classification = self._get_classification(classification_id)
            for member in classification.get("classes", []):
                if str(member.get("code", "")).upper() == str(code).upper():
                    return classification_id, member
        raise ValueError(f"No ULJAS classification member found for code {code!r}")

    def _select_periods(self, time_dimension, frequency, start_period, end_period):
        if frequency not in ("month", "year"):
            raise ValueError("frequency must be 'month' or 'year'")
        pattern = r"\d{6}" if frequency == "month" else r"\d{4}"
        period_format = "YYYYMM" if frequency == "month" else "YYYY"
        start_period = start_period or ("202301" if frequency == "month" else "2023")

        for classification_id in time_dimension["classifications"]:
            classification = self._get_classification(classification_id)
            periods = [
                member
                for member in classification.get("classes", [])
                if re.fullmatch(pattern, str(member.get("code", "")))
            ]
            if not periods:
                continue

            latest_period = max(member["code"] for member in periods)
            selected_end = end_period or latest_period
            if not re.fullmatch(pattern, start_period):
                raise ValueError(f"Use {period_format} format for --start")
            if not re.fullmatch(pattern, selected_end):
                raise ValueError(f"Use {period_format} format for --end")
            if start_period > selected_end:
                raise ValueError("--start must not be later than --end")

            selected = [
                member
                for member in periods
                if start_period <= member["code"] <= selected_end
            ]
            if not selected:
                raise ValueError(
                    f"No {frequency} periods available between "
                    f"{start_period} and {selected_end}"
                )
            return classification_id, sorted(selected, key=lambda item: item["code"])

        raise ValueError(f"No {frequency} time classification is available")

    def query_trade(
        self,
        country_code="IL",
        flow="exports",
        start_period=None,
        end_period=None,
        frequency="month",
        cube_id=DEFAULT_CUBE_ID,
        product_classification_id=DEFAULT_PRODUCT_CLASSIFICATION_ID,
        product_codes=None,
        metric="value",
        output_format="json",
    ):
        cube = self.database["cubes"][str(cube_id)]
        dimensions = cube["dimensions"]
        product_dimension = next(d for d in dimensions if d.get("role") == "product")
        time_dimension = next(d for d in dimensions if d.get("role") == "time")
        geo_dimension = next(d for d in dimensions if d.get("role") == "geo")
        flow_dimension = next(d for d in dimensions if d.get("label") == "Flow")
        metric_dimension = next(d for d in dimensions if d.get("role") == "metric")

        product_classification_id = str(product_classification_id)
        if product_classification_id not in product_dimension["classifications"]:
            raise ValueError(
                f"Product classification {product_classification_id} is not available "
                f"in cube {cube_id}"
            )
        product_classification = self._get_classification(product_classification_id)
        if product_codes:
            product_items = []
            for code in product_codes:
                matches = [
                    item
                    for item in product_classification.get("classes", [])
                    if str(item.get("code", "")).upper() == code.upper()
                ]
                if not matches:
                    raise ValueError(
                        f"Product code {code!r} is not in classification "
                        f"{product_classification_id}"
                    )
                product_items.extend(matches)
        else:
            product_items = [
                item
                for item in product_classification.get("classes", [])
                if item.get("aggregate") != "TOTAL"
            ]
        if not product_items:
            raise ValueError("The product selection contains no classification members")

        geo_classification_id, country = self._find_member(
            geo_dimension["classifications"], country_code
        )
        flow_code = FLOW_CODES.get(flow)
        if flow_code is None:
            raise ValueError(f"Unsupported flow {flow!r}; choose imports or exports")
        flow_classification_id, flow_member = self._find_member(
            flow_dimension["classifications"], flow_code
        )
        time_classification_id, periods = self._select_periods(
            time_dimension, frequency, start_period, end_period
        )
        metric_id = METRIC_IDS.get(metric)
        if metric_id is None:
            raise ValueError(f"Unsupported metric {metric!r}")

        max_cells = self.database["config"]["maxCellsLimit"]
        cell_count = len(product_items) * len(periods)
        if cell_count > max_cells:
            raise ValueError(
                f"Selection has {cell_count:,} product-period cells; "
                f"ULJAS's current limit is {max_cells:,}. Choose fewer periods "
                "or a coarser product classification."
            )

        selected = {
            product_dimension["id"]: (
                product_classification_id,
                [item["id"] for item in product_items],
            ),
            time_dimension["id"]: (
                time_classification_id,
                [item["id"] for item in periods],
            ),
            geo_dimension["id"]: (geo_classification_id, [country["id"]]),
            flow_dimension["id"]: (flow_classification_id, [flow_member["id"]]),
            metric_dimension["id"]: (
                metric_dimension["measures"],
                [metric_id],
            ),
        }
        query = {
            "cube": cube_id,
            "dimensions": [
                {
                    "id": dimension["id"],
                    "element": int(selected[dimension["id"]][0]),
                    "items": selected[dimension["id"]][1],
                }
                for dimension in dimensions
            ],
            "pivoting": {
                "rows": [
                    dimension["id"]
                    for dimension in dimensions
                    if dimension["id"] != metric_dimension["id"]
                ],
                "columns": [metric_dimension["id"]],
            },
        }

        params = {"language": self.language}
        headers = {"Accept": "application/json"}
        if output_format == "csv":
            params["format"] = "csv"
            headers["Accept"] = "application/json, text/plain"
        elif output_format != "json":
            raise ValueError("output_format must be 'json' or 'csv'")

        response = self.session.post(
            f"{API_BASE}/api/dataset",
            params=params,
            json=query,
            headers=headers,
            timeout=120,
        )
        response.raise_for_status()
        if output_format == "csv":
            return response.text

        payload = response.json()
        if payload.get("errorId"):
            raise RuntimeError(payload.get("message", payload["errorId"]))
        return payload


def main():
    parser = argparse.ArgumentParser(
        description="Query public Finnish Customs ULJAS trade statistics."
    )
    parser.add_argument("--country", default="IL", help="Partner country ISO code")
    parser.add_argument(
        "--flow", choices=FLOW_CODES, default="exports", help="Trade direction"
    )
    parser.add_argument("--start", help="First period: YYYYMM or YYYY")
    parser.add_argument("--end", help="Last period: YYYYMM or YYYY")
    parser.add_argument(
        "--frequency", choices=("month", "year"), default="month"
    )
    parser.add_argument("--cube", type=int, default=DEFAULT_CUBE_ID)
    parser.add_argument(
        "--product-classification-id",
        type=int,
        default=DEFAULT_PRODUCT_CLASSIFICATION_ID,
        help="Classification ID available on the selected cube",
    )
    parser.add_argument(
        "--product-code",
        action="append",
        help="Exact product code; repeat to select multiple codes. "
        "Omit to return all members except the total aggregate.",
    )
    parser.add_argument(
        "--metric",
        choices=METRIC_IDS,
        default="value",
        help="One measure per request; run again for another measure.",
    )
    parser.add_argument("--language", default="en", choices=("en", "fi", "sv"))
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    args = parser.parse_args()

    client = UljasClient(language=args.language)
    result = client.query_trade(
        country_code=args.country,
        flow=args.flow,
        start_period=args.start,
        end_period=args.end,
        frequency=args.frequency,
        cube_id=args.cube,
        product_classification_id=args.product_classification_id,
        product_codes=args.product_code,
        metric=args.metric,
        output_format=args.format,
    )
    if args.format == "csv":
        sys.stdout.write(result)
    else:
        json.dump(result, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
