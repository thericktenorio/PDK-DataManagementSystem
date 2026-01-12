from decimal import Decimal


def map_line_item(line: dict, item_ref: dict) -> dict:
    '''
    Input: {"description": "1040 Preparation", "amount_cents": 15000, "qty": 1}
    Output: QBO SalesItem line dict
    '''

    amount = round(line["amount-cents"] / 100.0, 2)
    qty = line.get("qty", 1)
    return {
        "DetailType": "SalesItemLineDetail", "Amount": amount,
        "Description": line.get("description"),
        "SalesItemLineDetail": {"ItemRef": {"value": item_ref["value"], "name": item_ref["name"]}, "Qty": qty},
    }


def pa_to_qbo_sales_item(pa) -> dict:
    """
    Convert a ProductAssignment into a QBO SalesItem line.
    - Amount: max(fee - discount, 0). Flls back to product.default_price if fee is None.
    - Description: "<ProductType> - TY <year> - <FilingType (if any)>"
    """
    default_price = pa.product.default_price or Decimal("0")
    fee = pa.fee if pa.fee is not None else default_price
    discount = pa.discount or Decimal("0")
    unit_price = fee - discount
    if unit_price < 0:
        unit_price = Decimal("0")
    
    product_type = getattr(pa.product, "product_type", "Service")
    year = getattr(pa.tax_year, "year", "")
    filing = getattr(pa.filing_type, "filing_type", "") or ""

    parts = [product_type, f"TY {year}"]
    if filing:
        parts.append(filing)
    desc = " - ".join(parts)

    return {
        "DetailType": "SalesItemLineDetail",
        "Amount": float(unit_price),
        "Description": desc,
        "SalesItemLineDetail": {
            # provider can inject ItemRef if QBO_DEFAULT_ITEM_ID is configured
            "Qty": 1,
            "UnitPrice": float(unit_price),
        },
    }

