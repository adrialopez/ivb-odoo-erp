{
    "name": "IVB eCommerce Connector",
    "version": "17.0.1.0.0",
    "summary": "Sincroniza productos, clientes y pedidos entre Odoo y la tienda online (WooCommerce hoy, Shopify más adelante)",
    "description": """
IVB eCommerce Connector
========================
Módulo puente entre Odoo y la tienda online del cliente. Pensado para una
empresa distribuidora/importadora (no fabricante): sincroniza catálogo,
clientes y pedidos de venta, sin depender de módulos de fabricación.

La lógica de conexión está desacoplada de la plataforma concreta
(`models/connectors/`), de forma que WooCommerce (implementado) y Shopify
(placeholder, a completar cuando termine la migración del cliente) comparten
la misma interfaz y el resto del módulo (settings, cron, logs, mapeo a
Odoo) no cambia al cambiar de plataforma.
    """,
    "author": "Adrià López",
    "website": "https://adria-lopez.com",
    "license": "LGPL-3",
    "category": "Sales/Sales",
    "depends": ["base", "sale_management", "purchase", "stock", "contacts"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/res_config_settings_views.xml",
        "views/ivb_connector_sync_log_views.xml",
        "views/ivb_connector_menus.xml",
    ],
    "installable": True,
    "application": True,
}
