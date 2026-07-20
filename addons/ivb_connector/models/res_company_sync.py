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

# Clase de impuesto de WooCommerce -> nombre del impuesto de venta en el plan
# contable español (plantilla es_pymes). El sufijo "-re" de WooCommerce marca
# la variante de recargo de equivalencia del mismo producto para ese tipo de
# cliente; en Odoo el recargo se aplica por *cliente* (posición fiscal), no
# por producto, así que aquí solo nos importa el tipo base de IVA.
WOOCOMMERCE_TAX_CLASS_TO_ODOO_TAX = {
    "standard": "21% S",
    "estandar-re": "21% S",
    "tasa-reducida": "10% S",
    "tasa-reducida-re": "10% S",
    "tasa-cero": "0% S",
}


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
        # tracking_disable corta CUALQUIER efecto de mail.thread durante el
        # sync: sin esto, asignar comercial (res.partner.user_id) dispara
        # una notificación "Has sido asignado a <cliente>" al chatter/bandeja
        # de ese usuario — un aviso real, aunque no sea un email explícito.
        # No se quiere avisar a nadie todavía, así que se corta de raíz para
        # todo lo que haga este método (partners, productos, pedidos).
        self = self.with_context(tracking_disable=True, mail_create_nolog=True, mail_notrack=True)
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
        tax_cache = self._ivb_build_sale_tax_cache()
        try:
            products = connector.fetch_products(since=since)
            for data in products:
                self._ivb_update_or_create_product(data, tax_cache)
        except ConnectorError as exc:
            self._ivb_log("products", "error", message=str(exc), duration=time.time() - started)
            return
        self._ivb_log("products", "success", record_count=len(products), duration=time.time() - started)

    def _ivb_build_sale_tax_cache(self):
        """Resuelve una vez por sincronización el account.tax de venta que
        corresponde a cada tax_class de WooCommerce (no se puede cachear en
        el propio recordset: los modelos de Odoo usan __slots__ y no admiten
        atributos nuevos, de ahí este dict aparte pasado por parámetro)."""
        self.ensure_one()
        AccountTax = self.env["account.tax"].sudo()
        cache = {}
        for tax_class, tax_name in WOOCOMMERCE_TAX_CLASS_TO_ODOO_TAX.items():
            tax = AccountTax.search(
                [("company_id", "=", self.id), ("type_tax_use", "=", "sale"), ("name", "=", tax_name)], limit=1
            )
            if not tax:
                _logger.warning(
                    "IVB Connector: no se encontró el impuesto '%s' en la empresa %s — "
                    "¿se cargó el plan contable español (l10n_es)?",
                    tax_name, self.display_name,
                )
            cache[tax_class] = tax
        return cache

    def _ivb_update_or_create_product(self, data, tax_cache):
        Product = self.env["product.template"].sudo()
        product = Product.search([("default_code", "=", data["sku"]), ("company_id", "in", [self.id, False])], limit=1)
        vals = {
            "name": data["name"],
            "default_code": data["sku"],
            "list_price": data["price"],
            "description_sale": data.get("description") or False,
        }
        if product:
            # No se toca taxes_id en un producto ya existente: si alguien lo
            # corrigió a mano en Odoo, un resync no debe deshacerlo.
            product.write(vals)
        else:
            # Odoo 19: ya no existe type="product" para artículos con stock;
            # ahora es type="consu" + is_storable=True (antes de 18 sí existía
            # el valor "product" en el selection, por eso el fallo original).
            tax = tax_cache.get(data.get("tax_class")) or tax_cache.get("standard")
            vals.update({
                "type": "consu",
                "is_storable": True,
                "company_id": self.id,
                "taxes_id": [(6, 0, tax.ids)] if tax else False,
            })
            Product.create(vals)

    # -- clientes ---------------------------------------------------------
    def _ivb_sync_customers(self, connector, since):
        started = time.time()
        try:
            customers = connector.fetch_customers(since=since)
        except ConnectorError as exc:
            self._ivb_log("customers", "error", message=str(exc), duration=time.time() - started)
            return
        skipped = 0
        for data in customers:
            try:
                with self.env.cr.savepoint():
                    self._ivb_update_or_create_partner(data)
            except Exception:  # noqa: BLE001 - datos sucios de un cliente no
                # deben tumbar la sincronización de los demás (ej. un CIF
                # placeholder inválido que rompe la validación de NIF de Odoo
                # en cuanto se conoce el país del contacto).
                skipped += 1
                _logger.warning(
                    "IVB Connector: no se pudo sincronizar el cliente %s, se omite",
                    data.get("email") or data.get("external_id"), exc_info=True,
                )
        self._ivb_log(
            "customers", "success", record_count=len(customers) - skipped,
            message=(f"{skipped} clientes omitidos por datos inválidos" if skipped else ""),
            duration=time.time() - started,
        )

    def _ivb_find_salesperson(self, comercial_email):
        """Busca el res.users cuyo login es el email del comercial (meta
        'comercial' del cliente en WooCommerce); si no existe, lo crea como
        usuario interno mínimo. no_reset_password=True es imprescindible:
        sin ese contexto, auth_signup.ResUsers.create() manda automáticamente
        un email de invitación/alta de contraseña al crear el usuario, y
        todavía no se quiere avisar a nadie de esto (PoC)."""
        if not comercial_email:
            return self.env["res.users"]
        Users = self.env["res.users"].sudo()
        user = Users.search([("login", "=", comercial_email)], limit=1)
        if user:
            return user
        _logger.info("IVB Connector: creando usuario interno para el comercial '%s'", comercial_email)
        name = comercial_email.split("@")[0].replace(".", " ").replace("_", " ").title()
        return Users.with_context(no_reset_password=True).create({
            "name": name,
            "login": comercial_email,
            "email": comercial_email,
            "group_ids": [(4, self.env.ref("base.group_user").id)],
        })

    def _ivb_get_or_create_tag(self, name):
        if not name:
            return self.env["res.partner.category"]
        Category = self.env["res.partner.category"].sudo()
        tag = Category.search([("name", "=", name)], limit=1)
        return tag or Category.create({"name": name})

    def _ivb_get_or_create_grupo_compra(self, name):
        """'grupo' en WooCommerce es la central de compras del cliente
        (ej. Cofares, Bidafarma...). Se modela como empresa matriz
        (res.partner.parent_id) en vez de como etiqueta: es una relación
        jerárquica real, no una simple clasificación, y así Odoo la
        muestra de forma nativa en la ficha de la empresa (contactos hijos)."""
        Partner = self.env["res.partner"].sudo()
        grupo = Partner.search([("name", "=", name), ("is_company", "=", True), ("company_id", "in", [self.id, False])], limit=1)
        return grupo or Partner.create({"name": name, "is_company": True, "company_id": self.id})

    def _ivb_get_re_fiscal_position(self):
        """Posición fiscal de recargo de equivalencia que ya trae la
        plantilla contable es_pymes (ver README, sección Impuestos)."""
        return self.env["account.fiscal.position"].sudo().search(
            [("company_id", "=", self.id), ("name", "=", "Equivalence surcharge")], limit=1
        )

    def _ivb_get_country(self, country_code):
        if not country_code:
            return self.env["res.country"]
        return self.env["res.country"].sudo().search([("code", "=", country_code.upper())], limit=1)

    def _ivb_get_state(self, country, state_code):
        if not country or not state_code:
            return self.env["res.country.state"]
        State = self.env["res.country.state"].sudo()
        # WooCommerce manda el código de provincia (ej. "V" para Valencia);
        # a veces también manda el nombre completo, así que se prueba
        # primero por código exacto y si no por nombre.
        state = State.search([("country_id", "=", country.id), ("code", "=", state_code.upper())], limit=1)
        return state or State.search([("country_id", "=", country.id), ("name", "=ilike", state_code)], limit=1)

    def _ivb_update_or_create_partner(self, data):
        Partner = self.env["res.partner"].sudo()
        partner = None
        if data.get("email"):
            partner = Partner.search([("email", "=", data["email"]), ("company_id", "in", [self.id, False])], limit=1)
        country = self._ivb_get_country(data.get("country_code"))
        vals = {
            "name": data["name"] or data.get("email") or "Cliente sin nombre",
            "email": data.get("email"),
            "phone": data.get("phone"),
            "street": data.get("street"),
            "city": data.get("city"),
            "zip": data.get("zip"),
            "customer_rank": 1,
            # IVB es una empresa española y todos sus clientes son de aquí:
            # la interfaz de cada contacto se ve siempre en español,
            # independientemente del idioma del navegador con el que se
            # registraron en la tienda.
            "lang": "es_ES",
        }
        if data.get("company_name"):
            vals["company_name"] = data["company_name"]
        if country:
            vals["country_id"] = country.id
            state = self._ivb_get_state(country, data.get("state_code"))
            if state:
                vals["state_id"] = state.id
        if data.get("vat"):
            vals["vat"] = data["vat"]
        if data.get("tipo"):
            tag = self._ivb_get_or_create_tag(data["tipo"].capitalize())
            vals["category_id"] = [(4, tag.id)]
        if data.get("sepa_days") is not None:
            vals["ivb_sepa_days"] = int(data["sepa_days"])
        if data.get("sepa_min_amount") is not None:
            vals["ivb_sepa_min_amount"] = data["sepa_min_amount"]
        if data.get("sepa_max_amount") is not None:
            vals["ivb_sepa_max_amount"] = data["sepa_max_amount"]
        if "purchase_limit_enabled" in data:
            vals["ivb_purchase_limit_enabled"] = bool(data["purchase_limit_enabled"])
        if data.get("monthly_purchase_limit") is not None:
            vals["ivb_monthly_purchase_limit"] = data["monthly_purchase_limit"]
        if data.get("apertura_email"):
            vals["ivb_apertura_email"] = data["apertura_email"]
        if data.get("procedencia"):
            vals["ivb_procedencia"] = data["procedencia"]
        if data.get("iqvia"):
            vals["ivb_iqvia"] = data["iqvia"]
        if data.get("escala") is not None:
            vals["ivb_escala"] = data["escala"]
        if "escala_automatica" in data:
            vals["ivb_escala_automatica"] = bool(data["escala_automatica"])
        if data.get("unidades_compradas") is not None:
            vals["ivb_unidades_compradas"] = data["unidades_compradas"]
        if data.get("fecha_cumpleanos"):
            vals["ivb_fecha_cumpleanos"] = data["fecha_cumpleanos"]
        if "visitada" in data:
            vals["ivb_visitada"] = bool(data["visitada"])
        if data.get("grupo_compra"):
            grupo = self._ivb_get_or_create_grupo_compra(data["grupo_compra"])
            vals["parent_id"] = grupo.id
        # Recargo de equivalencia: rol 're' en WooCommerce (mismo rol que ya
        # usa ivb-pedidos-comerciales para bloquear/permitir formas de pago)
        # -> posición fiscal "Equivalence surcharge" de la plantilla es_pymes,
        # que añade el recargo encima del IVA base automáticamente.
        if data.get("role") == "re":
            re_position = self._ivb_get_re_fiscal_position()
            if re_position:
                vals["property_account_position_id"] = re_position.id
            else:
                _logger.warning(
                    "IVB Connector: cliente %s tiene rol 're' pero no se encontró la "
                    "posición fiscal 'Equivalence surcharge' en la empresa",
                    data.get("email"),
                )

        salesperson = self._ivb_find_salesperson(data.get("comercial_email"))
        if salesperson:
            vals["user_id"] = salesperson.id
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

        order = SaleOrder.create(
            {
                "company_id": self.id,
                "partner_id": partner.id,
                # El comercial se asigna por cliente (meta 'comercial'
                # en WooCommerce, resuelto en _ivb_update_or_create_partner);
                # el pedido simplemente hereda el de su cliente.
                "user_id": partner.user_id.id if partner.user_id else False,
                "client_order_ref": data["external_id"],
                "origin": f"{self.ivb_connector_platform}:{data['number']}",
                "order_line": order_lines,
            }
        )
        # Solo confirmamos (deja de ser presupuesto) los pedidos que en la
        # tienda ya están pagados/en curso. Los que están pendientes de pago,
        # en espera, cancelados o reembolsados se quedan como presupuesto:
        # confirmarlos en Odoo sería mentir sobre su estado real.
        if data.get("status") in ("processing", "completed") and order_lines:
            try:
                order.action_confirm()
            except Exception:  # noqa: BLE001 - no debe tumbar el resto del sync
                _logger.exception(
                    "IVB Connector: no se pudo confirmar el pedido %s (se deja como presupuesto)",
                    data["external_id"],
                )
        return order

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
