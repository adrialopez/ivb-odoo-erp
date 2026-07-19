"""Conector para Shopify (PLACEHOLDER).

IVB está migrando su tienda de WooCommerce a Shopify (ver proyecto
ivb-shopify-export). Este conector deja preparada la interfaz para cuando
la migración termine y haya credenciales de la Admin API, pero no está
implementado todavía: cualquier método lanza NotImplementedError con un
mensaje explícito en vez de fallar en silencio o devolver datos falsos.

Cuando se implemente, usar la Shopify Admin REST API
(https://shopify.dev/docs/api/admin-rest) con un access token de app
custom, siguiendo la misma normalización que woocommerce.py: fetch_products,
fetch_customers y fetch_orders deben devolver los mismos dicts que ese
conector para que ivb_connector_manager.py no necesite cambios.
"""
from .base import EcommerceConnector


class ShopifyConnector(EcommerceConnector):
    platform_key = "shopify"

    _NOT_READY = (
        "El conector de Shopify es un placeholder: IVB todavía está "
        "migrando la tienda desde WooCommerce. Implementar contra la "
        "Shopify Admin API cuando haya credenciales definitivas."
    )

    def test_connection(self):
        raise NotImplementedError(self._NOT_READY)

    def fetch_products(self, since=None, limit=100):
        raise NotImplementedError(self._NOT_READY)

    def fetch_customers(self, since=None, limit=100):
        raise NotImplementedError(self._NOT_READY)

    def fetch_orders(self, since=None, limit=100, status=None):
        raise NotImplementedError(self._NOT_READY)

    def push_stock_levels(self, updates):
        raise NotImplementedError(self._NOT_READY)
