"""Lógica de sincronización: traduce los dicts normalizados que devuelven
los conectores (models/connectors/) a registros de Odoo (product.template,
res.partner, sale.order). Vive en res.company porque la configuración
(plataforma, credenciales) también está ahí y así el cron solo necesita
iterar `env["res.company"].search([])`.
"""
import logging
import time
from datetime import datetime

from odoo import _, models
from odoo.exceptions import UserError

from .connectors import get_connector
from .connectors.base import ConnectorError

_logger = logging.getLogger(__name__)

# El PoC es de solo lectura a propósito: todavía no se ha validado el
# mapeo de datos contra la tienda real de IVB, así que no se debe escribir
# nada en WooCommerce (ni Shopify el día que se implemente). El único punto
# de escritura hacia la tienda es push_stock_levels(); este flag lo bloquea
# aunque alguien active la casilla "Empujar stock" en Ajustes por error.
# Cuando se quiera activar de verdad, cambiar a False aquí explícitamente.
READ_ONLY_MODE = True


class ResCompany(models.Model):
    _inherit = "res.company"

    def _ivb_get_connector(self):
        self.ensure_one()
        if not self.ivb_connector_store_url:
            raise UserError(_("Configura la URL de la tienda antes de sincronizar."))
        return get_connector(
            self.ivb_connector_platform,
            self.ivb_connector_store_url,
            self.ivb_connector_api_key,
            self.ivb_connector_api_secret,
        )

    def _ivb_log(self, operation, status, record_count=0, message="", duration=0.0):
        self.env["ivb.connector.sync.log"].sudo().create(
            {
                "company_id": self.id,
                "platform": self.ivb_connector_platform,
                "operation": operation,
                "status": status,
                "record_count": record_count,
                "message": message,
                "duration_seconds": duration,
            }
        )

    def action_ivb_connector_test_connection(self):
        self.ensure_one()
        started = time.time()
        try:
            connector = self._ivb_get_connector()
            connector.test_connection()
        except (ConnectorError, NotImplementedError) as exc:
            self._ivb_log("test_connection", "error", message=str(exc), duration=time.time() - started)
            raise UserError(str(exc)) from exc
        self._ivb_log("test_connection", "success", duration=time.time() - started)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Conexión OK"),
                "message": _("La conexión con %s se ha probado correctamente.") % self.ivb_connector_platform,
                "type": "success",
            },
        }

    def action_ivb_connector_sync_now(self):
        for company in self:
            company._ivb_run_sync()
        return True

    def _cron_ivb_connector_sync(self):
        for company in self.search([("ivb_connector_store_url", "!=", False)]):
            try:
                company._ivb_run_sync()
            except Exception:  # noqa: BLE001 - el cron no debe romperse por una empresa
                _logger.exception("IVB Connector: fallo sincronizando %s", company.display_name)

    def _ivb_run_sync(self):
        self.ensure_one()
        connector = self._ivb_get_connector()
        since = self.ivb_connector_last_sync

        if self.ivb_connector_sync_products:
            self._ivb_sync_products(connector, since)
        if self.ivb_connector_sync_customers:
            self._ivb_sync_customers(connector, since)
        if self.ivb_connector_sync_orders:
            self._ivb_sync_orders(connector, since)
        if self.ivb_connector_push_stock and not READ_ONLY_MODE:
            self._ivb_push_stock(connector)
        elif self.ivb_connector_push_stock and READ_ONLY_MODE:
            _logger.warning(
                "IVB Connector: 'Empujar stock' está activado pero el conector está en "
                "modo solo lectura (READ_ONLY_MODE=True) — no se ha escrito nada en la tienda."
            )
            self._ivb_log(
                "push_stock", "error",
                message=_("Bloqueado: el conector está en modo solo lectura (READ_ONLY_MODE)."),
            )

        self.ivb_connector_last_sync = datetime.now()

    # -- productos ------------------------------------------------------
    def _ivb_sync_products(self, connector, since):
        started = time.time()
        try:
            products = connector.fetch_products(since=since)
            for data in products:
                self._ivb_update_or_create_product(data)
        except ConnectorError as exc:
            self._ivb_log("products", "error", message=str(exc), duration=time.time() - started)
            return
        self._ivb_log("products", "success", record_count=len(products), duration=time.time() - started)

    def _ivb_update_or_create_product(self, data):
        Product = self.env["product.template"].sudo()
        product = Product.search([("default_code", "=", data["sku"]), ("company_id", "in", [self.id, False])], limit=1)
        vals = {
            "name": data["name"],
            "default_code": data["sku"],
            "list_price": data["price"],
            "description_sale": data.get("description") or False,
        }
        if product:
            product.write(vals)
        else:
            vals.update({"type": "product", "company_id": self.id})
            Product.create(vals)

    # -- clientes ---------------------------------------------------------
    def _ivb_sync_customers(self, connector, since):
        started = time.time()
        try:
            customers = connector.fetch_customers(since=since)
            for data in customers:
                self._ivb_update_or_create_partner(data)
        except ConnectorError as exc:
            self._ivb_log("customers", "error", message=str(exc), duration=time.time() - started)
            return
        self._ivb_log("customers", "success", record_count=len(customers), duration=time.time() - started)

    def _ivb_update_or_create_partner(self, data):
        Partner = self.env["res.partner"].sudo()
        partner = None
        if data.get("email"):
            partner = Partner.search([("email", "=", data["email"]), ("company_id", "in", [self.id, False])], limit=1)
        vals = {
            "name": data["name"] or data.get("email") or "Cliente sin nombre",
            "email": data.get("email"),
            "phone": data.get("phone"),
            "street": data.get("street"),
            "city": data.get("city"),
            "zip": data.get("zip"),
            "customer_rank": 1,
        }
        if partner:
            partner.write(vals)
            return partner
        vals["company_id"] = self.id
        return Partner.create(vals)

    # -- pedidos ------------------------------------------------------
    def _ivb_sync_orders(self, connector, since):
        started = time.time()
        try:
            orders = connector.fetch_orders(since=since)
            for data in orders:
                self._ivb_update_or_create_order(data)
        except ConnectorError as exc:
            self._ivb_log("orders", "error", message=str(exc), duration=time.time() - started)
            return
        self._ivb_log("orders", "success", record_count=len(orders), duration=time.time() - started)

    def _ivb_update_or_create_order(self, data):
        SaleOrder = self.env["sale.order"].sudo()
        order = SaleOrder.search(
            [("client_order_ref", "=", data["external_id"]), ("company_id", "=", self.id)], limit=1
        )
        if order:
            # Los pedidos ya importados no se reescriben: la sincronización
            # de pedidos es de solo-creación en este PoC.
            return order

        partner = self._ivb_update_or_create_partner(data["customer"])
        Product = self.env["product.template"].sudo()
        order_lines = []
        for line in data["lines"]:
            product = Product.search([("default_code", "=", line["sku"]), ("company_id", "in", [self.id, False])], limit=1)
            if not product:
                _logger.warning(
                    "IVB Connector: SKU %s del pedido %s no existe en Odoo, se omite la línea",
                    line["sku"], data["external_id"],
                )
                continue
            order_lines.append(
                (0, 0, {
                    "product_id": product.product_variant_id.id,
                    "product_uom_qty": line["qty"],
                    "price_unit": line["price_unit"],
                })
            )

        return SaleOrder.create(
            {
                "company_id": self.id,
                "partner_id": partner.id,
                "client_order_ref": data["external_id"],
                "origin": f"{self.ivb_connector_platform}:{data['number']}",
                "order_line": order_lines,
            }
        )

    # -- stock hacia la tienda ------------------------------------------
    def _ivb_push_stock(self, connector):
        started = time.time()
        Product = self.env["product.template"].sudo()
        products = Product.search([("default_code", "!=", False), ("company_id", "in", [self.id, False])])
        updates = [
            {"sku": p.default_code, "qty": p.qty_available}
            for p in products
        ]
        try:
            connector.push_stock_levels(updates)
        except ConnectorError as exc:
            self._ivb_log("push_stock", "error", message=str(exc), duration=time.time() - started)
            return
        self._ivb_log("push_stock", "success", record_count=len(updates), duration=time.time() - started)
