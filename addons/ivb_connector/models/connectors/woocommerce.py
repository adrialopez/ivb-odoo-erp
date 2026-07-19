"""Conector para WooCommerce (REST API v3).

Referencia: https://woocommerce.github.io/woocommerce-rest-api-docs/
Auth: HTTP Basic con consumer_key/consumer_secret, válido porque la tienda
sirve por HTTPS (profesional.ivbwellness.com). Si algún día se usa por HTTP
plano habría que pasar a OAuth1 por query string en su lugar.
"""
import logging

import requests

from .base import ConnectorError, EcommerceConnector

_logger = logging.getLogger(__name__)

TIMEOUT = 30


class WooCommerceConnector(EcommerceConnector):
    platform_key = "woocommerce"

    def _get(self, endpoint, params=None):
        url = f"{self.store_url}/wp-json/wc/v3/{endpoint}"
        try:
            response = requests.get(
                url,
                params=params or {},
                auth=(self.api_key, self.api_secret),
                timeout=TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ConnectorError(f"WooCommerce API error on {endpoint}: {exc}") from exc
        return response.json()

    def _post(self, endpoint, json_body):
        url = f"{self.store_url}/wp-json/wc/v3/{endpoint}"
        try:
            response = requests.post(
                url,
                json=json_body,
                auth=(self.api_key, self.api_secret),
                timeout=TIMEOUT,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ConnectorError(f"WooCommerce API error on {endpoint}: {exc}") from exc
        return response.json()

    def test_connection(self):
        data = self._get("system_status")
        return bool(data)

    def fetch_products(self, since=None, limit=100):
        params = {"per_page": min(limit, 100)}
        if since:
            params["modified_after"] = since.isoformat()
        raw_products = self._get("products", params)
        return [self._normalize_product(p) for p in raw_products]

    def fetch_customers(self, since=None, limit=100):
        params = {"per_page": min(limit, 100)}
        if since:
            params["modified_after"] = since.isoformat()
        raw_customers = self._get("customers", params)
        return [self._normalize_customer(c) for c in raw_customers]

    def fetch_orders(self, since=None, limit=100, status=None):
        params = {"per_page": min(limit, 100)}
        if since:
            params["modified_after"] = since.isoformat()
        if status:
            params["status"] = status
        raw_orders = self._get("orders", params)
        return [self._normalize_order(o) for o in raw_orders]

    def push_stock_levels(self, updates):
        if not updates:
            return
        sku_to_qty = {u["sku"]: u["qty"] for u in updates}
        # WooCommerce no permite buscar por lote de SKUs en una sola llamada,
        # así que se resuelve un product_id por SKU antes del batch update.
        batch_update = []
        for sku, qty in sku_to_qty.items():
            matches = self._get("products", {"sku": sku})
            if not matches:
                _logger.warning("IVB Connector: SKU %s no encontrado en WooCommerce, se omite", sku)
                continue
            batch_update.append({"id": matches[0]["id"], "stock_quantity": int(qty)})
        if batch_update:
            self._post("products/batch", {"update": batch_update})

    # -- normalización WooCommerce -> formato interno -----------------
    @staticmethod
    def _meta(meta_data, key):
        """WooCommerce devuelve los custom fields como una lista de
        {id, key, value} en 'meta_data' (productos, clientes y pedidos).
        El meta 'comercial' en el cliente de WooCommerce contiene
        directamente el email del comercial asignado (confirmado contra
        la tienda real: profesional.ivbwellness.com)."""
        for entry in meta_data or []:
            if entry.get("key") == key:
                return entry.get("value") or None
        return None

    @staticmethod
    def _normalize_product(p):
        return {
            "external_id": str(p.get("id")),
            "sku": p.get("sku") or f"WOO-{p.get('id')}",
            "name": p.get("name"),
            "description": p.get("short_description") or p.get("description") or "",
            "price": float(p.get("regular_price") or p.get("price") or 0.0),
            "stock_qty": p.get("stock_quantity") if p.get("stock_quantity") is not None else 0,
            "barcode": False,
            "tax_class": p.get("tax_class") or "standard",
        }

    @classmethod
    def _normalize_customer(cls, c):
        billing = c.get("billing") or {}
        return {
            "external_id": str(c.get("id")),
            "name": (f"{c.get('first_name', '')} {c.get('last_name', '')}".strip() or c.get("username")),
            "email": c.get("email"),
            "phone": billing.get("phone"),
            "street": billing.get("address_1"),
            "city": billing.get("city"),
            "zip": billing.get("postcode"),
            "country_code": billing.get("country"),
            "vat": False,
            "comercial_email": cls._meta(c.get("meta_data"), "comercial"),
        }

    @classmethod
    def _normalize_order(cls, o):
        billing = o.get("billing") or {}
        customer = {
            "external_id": str(o.get("customer_id") or f"guest-{o.get('id')}"),
            "name": (f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip() or billing.get("company") or "Cliente WooCommerce"),
            "email": billing.get("email"),
            "phone": billing.get("phone"),
            "street": billing.get("address_1"),
            "city": billing.get("city"),
            "zip": billing.get("postcode"),
            "country_code": billing.get("country"),
            "vat": False,
        }
        lines = [
            {
                "sku": li.get("sku") or f"WOO-{li.get('product_id')}",
                "name": li.get("name"),
                "qty": li.get("quantity") or 1,
                "price_unit": float(li.get("price") or 0.0),
            }
            for li in o.get("line_items", [])
        ]
        return {
            "external_id": str(o.get("id")),
            "number": o.get("number") or str(o.get("id")),
            "date_order": o.get("date_created"),
            "status": o.get("status"),
            "currency": o.get("currency"),
            "customer": customer,
            "shipping_total": float(o.get("shipping_total") or 0.0),
            "discount_total": float(o.get("discount_total") or 0.0),
            "amount_total": float(o.get("total") or 0.0),
            "lines": lines,
        }
