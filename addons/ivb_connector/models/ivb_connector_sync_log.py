from odoo import fields, models


class IvbConnectorSyncLog(models.Model):
    _name = "ivb.connector.sync.log"
    _description = "Registro de sincronización con la tienda online"
    _order = "create_date desc"

    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    platform = fields.Selection(
        [("woocommerce", "WooCommerce"), ("shopify", "Shopify")], required=True
    )
    operation = fields.Selection(
        [
            ("products", "Productos"),
            ("customers", "Clientes"),
            ("orders", "Pedidos"),
            ("push_stock", "Envío de stock"),
            ("test_connection", "Prueba de conexión"),
        ],
        required=True,
    )
    status = fields.Selection([("success", "OK"), ("error", "Error")], required=True)
    record_count = fields.Integer(string="Registros procesados", default=0)
    message = fields.Text(string="Detalle / error")
    duration_seconds = fields.Float(string="Duración (s)")
