from odoo import fields, models


class ResCompany(models.Model):
    _inherit = "res.company"

    ivb_connector_platform = fields.Selection(
        [("woocommerce", "WooCommerce"), ("shopify", "Shopify")],
        string="Plataforma de tienda online",
        default="woocommerce",
    )
    ivb_connector_store_url = fields.Char(string="URL de la tienda")
    ivb_connector_api_key = fields.Char(string="API Key / Consumer Key")
    ivb_connector_api_secret = fields.Char(string="API Secret / Consumer Secret")
    ivb_connector_sync_products = fields.Boolean(string="Sincronizar productos", default=True)
    ivb_connector_sync_customers = fields.Boolean(string="Sincronizar clientes", default=True)
    ivb_connector_sync_orders = fields.Boolean(string="Sincronizar pedidos", default=True)
    ivb_connector_push_stock = fields.Boolean(
        string="Empujar stock hacia la tienda", default=False,
        help="Si está activo, tras cada sincronización se envía el stock disponible en Odoo a la tienda.",
    )
    ivb_connector_last_sync = fields.Datetime(string="Última sincronización", readonly=True)
