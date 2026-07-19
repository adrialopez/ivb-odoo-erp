from .base import ConnectorError
from .shopify import ShopifyConnector
from .woocommerce import WooCommerceConnector

CONNECTORS = {
    WooCommerceConnector.platform_key: WooCommerceConnector,
    ShopifyConnector.platform_key: ShopifyConnector,
}


def get_connector(platform, store_url, api_key, api_secret):
    """Factory: elige la implementación por platform_key sin que el
    resto del módulo (cron, wizards, sync manager) conozca las clases
    concretas. Añadir una plataforma nueva solo requiere registrarla aquí.
    """
    connector_class = CONNECTORS.get(platform)
    if not connector_class:
        raise ConnectorError(f"Plataforma de conector desconocida: {platform}")
    return connector_class(store_url, api_key, api_secret)
