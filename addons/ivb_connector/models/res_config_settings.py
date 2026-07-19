from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ivb_connector_platform = fields.Selection(related="company_id.ivb_connector_platform", readonly=False)
    ivb_connector_store_url = fields.Char(related="company_id.ivb_connector_store_url", readonly=False)
    ivb_connector_api_key = fields.Char(related="company_id.ivb_connector_api_key", readonly=False)
    ivb_connector_api_secret = fields.Char(related="company_id.ivb_connector_api_secret", readonly=False)
    ivb_connector_sync_products = fields.Boolean(related="company_id.ivb_connector_sync_products", readonly=False)
    ivb_connector_sync_customers = fields.Boolean(related="company_id.ivb_connector_sync_customers", readonly=False)
    ivb_connector_sync_orders = fields.Boolean(related="company_id.ivb_connector_sync_orders", readonly=False)
    ivb_connector_push_stock = fields.Boolean(related="company_id.ivb_connector_push_stock", readonly=False)
    ivb_connector_last_sync = fields.Datetime(related="company_id.ivb_connector_last_sync")

    def action_ivb_connector_test_connection(self):
        self.ensure_one()
        return self.company_id.action_ivb_connector_test_connection()

    def action_ivb_connector_sync_now(self):
        self.ensure_one()
        return self.company_id.action_ivb_connector_sync_now()
