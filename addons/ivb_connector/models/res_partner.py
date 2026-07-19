from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    # No hay campo nativo de Odoo para condiciones SEPA / límite de compra
    # mensual estilo Gextia — se guardan aquí en vez de en una nota de texto
    # para poder filtrarlos/reportarlos más adelante.
    ivb_sepa_days = fields.Integer(string="Días SEPA")
    ivb_sepa_min_amount = fields.Float(string="Importe mínimo SEPA")
    ivb_sepa_max_amount = fields.Float(string="Importe máximo SEPA")
    ivb_purchase_limit_enabled = fields.Boolean(string="Límite de compra mensual activo")
    ivb_monthly_purchase_limit = fields.Float(string="Límite de compra mensual")
