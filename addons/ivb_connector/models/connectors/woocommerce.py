"""Conector para WooCommerce (REST API v3).

Referencia: https://woocommerce.github.io/woocommerce-rest-api-docs/
Auth: HTTP Basic con consumer_key/consumer_secret, válido porque la tienda
sirve por HTTPS (profesional.ivbwellness.com). Si algún día se usa por HTTP
plano habría que pasar a OAuth1 por query string en su lugar.
"""
import logging
from datetime import datetime

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

    #: tope de páginas al paginar /customers, solo para no entrar en un
    #: bucle infinito si la API se comporta de forma rara; 50*100 = 5000
    #: clientes, muy por encima de lo que tiene la tienda de IVB hoy.
    MAX_CUSTOMER_PAGES = 50

    def fetch_customers(self, since=None, limit=100):
        # role='all': por defecto /customers de WooCommerce SOLO devuelve
        # usuarios con rol 'customer' (y similares) — descubierto con datos
        # reales: una clienta con rol 'farmacia' (ficha completa: CIF,
        # comercial, SEPA...) no aparecía en absoluto sin este parámetro,
        # y con él el listado pasó de 3 a 100+ clientes en la primera
        # página. Sin este fix, roles de negocio reales como 're'
        # (recargo de equivalencia) quedaban invisibles para el conector.
        params = {"per_page": min(limit, 100), "role": "all"}
        if since:
            params["modified_after"] = since.isoformat()

        all_customers = []
        page = 1
        while page <= self.MAX_CUSTOMER_PAGES:
            params["page"] = page
            raw_page = self._get("customers", params)
            if not raw_page:
                break
            all_customers.extend(raw_page)
            if len(raw_page) < params["per_page"]:
                break
            page += 1
        return [self._normalize_customer(c) for c in all_customers]

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

    @staticmethod
    def _meta_float(meta_data, key):
        value = WooCommerceConnector._meta(meta_data, key)
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _meta_bool(meta_data, key):
        value = WooCommerceConnector._meta(meta_data, key)
        return str(value) in ("1", "true", "True", "yes")

    # Placeholders que el sitio de IVB usa quiere decir "sin asignar" en vez
    # de un valor real; se normalizan a None para no meter texto basura en
    # los campos de Odoo.
    _EMPTY_PLACEHOLDERS = {"no asignado", "no asignada", "n/a", "-", "ninguno", "ninguna", "none"}

    @classmethod
    def _meta_clean(cls, meta_data, key):
        value = cls._meta(meta_data, key)
        if value is None or str(value).strip().lower() in cls._EMPTY_PLACEHOLDERS:
            return None
        return value

    @classmethod
    def _meta_int(cls, meta_data, key):
        value = cls._meta_float(meta_data, key)
        return int(value) if value is not None else None

    @classmethod
    def _meta_date(cls, meta_data, key):
        value = cls._meta_clean(meta_data, key)
        if not value:
            return None
        for fmt in ("%Y%m%d", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(value, fmt).date().isoformat()
            except ValueError:
                continue
        _logger.warning("IVB Connector: fecha '%s' del meta '%s' no reconocida, se omite", value, key)
        return None

    @classmethod
    def _normalize_customer(cls, c):
        billing = c.get("billing") or {}
        meta = c.get("meta_data")
        return {
            "external_id": str(c.get("id")),
            "name": (f"{c.get('first_name', '')} {c.get('last_name', '')}".strip() or c.get("username")),
            "email": c.get("email"),
            "phone": billing.get("phone"),
            "company_name": billing.get("company") or None,
            "street": billing.get("address_1"),
            "city": billing.get("city"),
            "zip": billing.get("postcode"),
            "state_code": billing.get("state") or None,
            "country_code": billing.get("country") or "ES",
            "vat": cls._meta_clean(meta, "cif"),
            "role": c.get("role"),
            "tipo": cls._meta_clean(meta, "tipo"),
            "comercial_email": cls._meta_clean(meta, "comercial"),
            "sepa_days": cls._meta_float(meta, "sepa_days"),
            "sepa_min_amount": cls._meta_float(meta, "sepa_min_amount"),
            "sepa_max_amount": cls._meta_float(meta, "sepa_max_amount"),
            "purchase_limit_enabled": cls._meta_bool(meta, "purchase_limit_enabled"),
            "monthly_purchase_limit": cls._meta_float(meta, "monthly_purchase_limit"),
            "apertura_email": cls._meta_clean(meta, "apertura"),
            "procedencia": cls._meta_clean(meta, "procedencia"),
            "iqvia": cls._meta_clean(meta, "iqvia"),
            "escala": cls._meta_int(meta, "escala"),
            "escala_automatica": cls._meta_bool(meta, "escalaAuto"),
            "unidades_compradas": cls._meta_int(meta, "unidadesCompradas"),
            "fecha_cumpleanos": cls._meta_date(meta, "fecha_cumpleanos"),
            "visitada": cls._meta_bool(meta, "visitada"),
            "grupo_compra": cls._meta_clean(meta, "grupo"),
        }

    @classmethod
    def _normalize_order(cls, o):
        billing = o.get("billing") or {}
        customer = {
            "external_id": str(o.get("customer_id") or f"guest-{o.get('id')}"),
            "name": (f"{billing.get('first_name', '')} {billing.get('last_name', '')}".strip() or billing.get("company") or "Cliente WooCommerce"),
            "email": billing.get("email"),
            "phone": billing.get("phone"),
            "company_name": billing.get("company") or None,
            "street": billing.get("address_1"),
            "city": billing.get("city"),
            "zip": billing.get("postcode"),
            "state_code": billing.get("state") or None,
            "country_code": billing.get("country") or "ES",
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
