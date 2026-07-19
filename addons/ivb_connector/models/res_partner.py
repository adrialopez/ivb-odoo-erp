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

    # Seguimiento comercial de farmacia (WooCommerce, custom fields del
    # sitio de IVB) — tampoco tienen equivalente nativo en Odoo.
    ivb_apertura_email = fields.Char(string="Apertura (email)", help="Quién dio de alta al cliente.")
    ivb_procedencia = fields.Char(string="Procedencia")
    ivb_iqvia = fields.Char(string="Código IQVIA")
    ivb_escala = fields.Integer(string="Escala")
    ivb_escala_automatica = fields.Boolean(string="Escala automática")
    ivb_unidades_compradas = fields.Integer(string="Unidades compradas")
    ivb_fecha_cumpleanos = fields.Date(string="Fecha de cumpleaños")
    ivb_visitada = fields.Boolean(string="Visitada")
