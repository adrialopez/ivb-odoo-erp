"""Interfaz común para cualquier plataforma de tienda online.

No son modelos de Odoo: son clases Python normales que devuelven
diccionarios "normalizados" (mismo formato venga de WooCommerce, Shopify o
cualquier otra plataforma futura). El resto del módulo (models/*.py) solo
conoce este formato normalizado, nunca el formato nativo de cada API, así
que añadir una plataforma nueva no toca el mapeo a Odoo.
"""
from abc import ABC, abstractmethod


class EcommerceConnector(ABC):
    """Contrato que debe cumplir cualquier conector de tienda online."""

    #: identificador corto usado en res.company.ivb_connector_platform
    platform_key = None

    def __init__(self, store_url, api_key, api_secret):
        self.store_url = (store_url or "").rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret

    @abstractmethod
    def test_connection(self):
        """Devuelve True si las credenciales/URL son válidas. Lanza
        ConnectorError con un mensaje legible si no lo son."""

    @abstractmethod
    def fetch_products(self, since=None, limit=100):
        """Devuelve una lista de dicts:
        {external_id, sku, name, description, price, stock_qty, barcode, tax_class}
        tax_class es el slug de la clase de impuesto en la plataforma de origen
        (en WooCommerce: standard/tasa-reducida/tasa-cero/...-re); se mapea a
        un impuesto real de Odoo en res_company_sync.py.
        """

    @abstractmethod
    def fetch_customers(self, since=None, limit=100):
        """Devuelve una lista de dicts:
        {external_id, name, email, phone, street, city, zip, country_code,
         vat, role, tipo, comercial_email, sepa_days, sepa_min_amount,
         sepa_max_amount, purchase_limit_enabled, monthly_purchase_limit}
        - role: rol de la plataforma de origen (en WooCommerce: 'customer',
          'subscriber', 're', 'sepa', 'comercial'... son roles custom del
          sitio de IVB). role == 're' dispara la posición fiscal de recargo
          de equivalencia en res_company_sync.py.
        - comercial_email: email del comercial asignado a ese cliente.
        - vat, tipo, sepa_*, purchase_limit*: datos de negocio ya presentes
          en la ficha de cliente de WooCommerce (CIF, tipo de cliente,
          condiciones de pago SEPA, límite de compra mensual).
        """

    @abstractmethod
    def fetch_orders(self, since=None, limit=100, status=None):
        """Devuelve una lista de dicts:
        {external_id, number, date_order, status, currency, customer: {...},
         shipping_total, discount_total, amount_total,
         lines: [{sku, name, qty, price_unit}]}
        """

    @abstractmethod
    def push_stock_levels(self, updates):
        """updates: lista de {sku, qty}. Empuja el stock de Odoo hacia la
        tienda (para no vender online lo que ya no hay en almacén)."""


class ConnectorError(Exception):
    """Error de conexión o de datos con la plataforma externa."""
