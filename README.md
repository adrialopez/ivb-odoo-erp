# IVB Odoo ERP (PoC)

Prueba de concepto de un Odoo "estilo Gextia" para **IVB Wellness Lab**: ERP
para una empresa **distribuidora/importadora, no fabricante**, conectado a
su tienda online.

> **Modo solo lectura:** por ahora el conector nunca escribe nada en la
> tienda online. El único punto de escritura hacia fuera (`push_stock_levels`,
> que empujaría stock a WooCommerce) está bloqueado a nivel de código con
> `READ_ONLY_MODE = True` en `models/res_company_sync.py` — no basta con
> desmarcar la casilla en Ajustes, hay que cambiar esa constante
> explícitamente cuando se quiera activar de verdad. La lectura (traer
> productos/clientes/pedidos de la tienda hacia Odoo) sí funciona.

> **Nota de contexto:** la tienda de IVB (`profesional.ivbwellness.com`) está
> en proceso de migración de WooCommerce a Shopify (ver proyecto
> `ivb-shopify-export`). Por eso este PoC conecta contra WooCommerce ahora
> mismo pero con una capa de conector abstracta — cambiar a Shopify más
> adelante no debería tocar nada fuera de `models/connectors/`.

## Por qué estos módulos (y no otros)

Gextia es un ERP típico de **distribución/importación**, no de fabricación:
gestiona compras a proveedores, venta a clientes (a menudo B2B con
comerciales y tarifas), stock multi-almacén con trazabilidad por lote
(muy relevante aquí — IVB vende suplementos con caducidad), y facturación.
No necesita **Fabricación (MRP)**, listas de materiales, ni órdenes de
producción, porque IVB no fabrica lo que vende.

Apps de Odoo instaladas en este PoC (ver `--init` en `docker-compose.yml`):

| App | Por qué |
|---|---|
| **Ventas** (`sale_management`) | Pedidos de venta, presupuestos — el núcleo de un distribuidor. |
| **Compras** (`purchase`) | Pedidos a proveedores/importación. |
| **Inventario** (`stock`) | Stock multi-almacén, movimientos, trazabilidad. |
| **Fechas de caducidad** (`product_expiry`) | Los suplementos/wellness tienen lote + caducidad — trazabilidad exigida en distribución de este tipo de producto. |
| **Contabilidad/Facturación** (`account` + `l10n_es`) | Plan contable español, facturación. |
| **CRM** (`crm`) | Pipeline comercial — encaja con los roles "comercial" que ya existen en `ivb-pedidos-comerciales`. |
| **Contactos** (`contacts`) | Clientes/proveedores. |
| **Código de barras** (`barcodes`) | Recepción/picking ágil en almacén. |
| **IVB Connector** (`ivb_connector`, este repo) | Sincroniza productos/clientes/pedidos con la tienda online. |

Deliberadamente **fuera** de este PoC:
- **Fabricación (MRP)** — no aplica, IVB no fabrica.
- **Punto de Venta (POS)** — IVB ya tiene un TPV propio a medida
  (`ivb-pedidos-comerciales`); si algún día se quiere unificar, sería una
  fase posterior, no parte del PoC.
- **Shopify connector real** — placeholder hasta que la migración termine.

## Estructura

```
ivb-odoo-erp/
├── docker-compose.yml       # Odoo 19 + Postgres
├── odoo.conf
├── .env.example             # copiar a .env con credenciales de Postgres
├── scripts/bootstrap.sh     # instala + localización ES + idioma + arranca el servidor
└── addons/
    └── ivb_connector/
        ├── models/
        │   ├── connectors/          # capa de plataforma (WooCommerce, Shopify)
        │   │   ├── base.py          # interfaz abstracta (ABC)
        │   │   ├── woocommerce.py   # implementado (REST API v3)
        │   │   ├── shopify.py       # placeholder, lanza NotImplementedError
        │   │   └── registry.py      # factory get_connector(platform, ...)
        │   ├── res_company.py       # config (URL, credenciales, flags de sync)
        │   ├── res_company_sync.py  # mapeo dict normalizado -> Odoo (product/partner/sale.order)
        │   ├── res_config_settings.py
        │   └── ivb_connector_sync_log.py
        ├── data/ir_cron_data.xml    # cron cada 30 min (inactivo por defecto)
        └── views/                   # ajustes + historial de sincronización
```

### Por qué está desacoplado así

`models/connectors/` no depende de Odoo en absoluto — son clases Python
puras (`EcommerceConnector` ABC) que devuelven diccionarios normalizados
(mismo formato venga de WooCommerce o de Shopify). `res_company_sync.py` es
el único sitio que traduce esos dicts a `product.template`, `res.partner` y
`sale.order`. Así, cuando se implemente Shopify de verdad, solo hace falta
rellenar `shopify.py` con las mismas firmas — el resto del módulo no cambia.

## Cómo levantarlo

Requiere Docker Desktop.

```bash
cd ivb-odoo-erp
cp .env.example .env   # y cambia la contraseña de Postgres
docker compose up
```

Todo el arranque (instalar módulos, país España + plan contable PYMES,
idioma español del admin) lo hace `scripts/bootstrap.sh`, que es el
`command:` del contenedor Odoo en `docker-compose.yml` — no hace falta
ningún paso manual, incluso partiendo de `docker compose down -v` (borrado
total). Tarda unos minutos la primera vez. Luego entra en
http://localhost:8069 con `admin` / `admin` (cámbiala en cuanto entres).

`bootstrap.sh` existe en vez de un `post_init_hook` normal de Odoo porque
se probó y **no es fiable**: cargar el plan contable español dentro de un
post_init_hook se revertía a mitad de la instalación (algo posterior en la
misma transacción de instalación lo pisaba con el plan contable genérico;
no se identificó la causa exacta pese a varios intentos). Ejecutarlo en su
propio proceso `odoo shell`, después de que la instalación de módulos ya
haya hecho commit, funciona de forma consistente — así que el script hace
eso: instala módulos → (proceso aparte) idioma → (proceso aparte) país +
plan contable → arranca el servidor real.

## Configurar el conector

1. Ajustes → busca "IVB Connector".
2. Plataforma: WooCommerce.
3. URL de la tienda, API Key/Secret (WooCommerce → Ajustes → Avanzado →
   REST API; solo lectura mientras el conector esté en modo solo lectura).
4. Botón "Probar conexión" y luego "Sincronizar ahora".
5. Revisar el resultado en **IVB Connector → Historial de sincronización**.

Estas credenciales viven en la base de datos (`res.company`), no en el
código — un `docker compose down -v` las borra y hay que volver a
introducirlas a mano.

El cron (`ir_cron_data.xml`) está **inactivo por defecto** — actívalo desde
Ajustes técnicos → Automatización → Acciones programadas una vez haya
credenciales reales, para no sincronizar contra nada con las de ejemplo.

## Impuestos (IVA + recargo de equivalencia)

El plan contable español (`es_pymes`, cargado automáticamente por
`bootstrap.sh`) trae los tipos de IVA reales (21%/10%/4%/0%, cada uno con
variante "G"/"S") y los de recargo de equivalencia (RE) como impuestos de
recargo independientes (`5.2% SE`, `1.4% SE`, `0.5% SE`...), más una
posición fiscal ya lista llamada **"Equivalence surcharge"** que añade el
recargo correspondiente encima del IVA base sin tocar nada más.

**Por producto:** cada producto sincronizado desde WooCommerce trae su
`tax_class` (`standard`, `tasa-reducida`, `tasa-cero`, y las variantes
`-re`) y `_ivb_get_sale_tax`/`WOOCOMMERCE_TAX_CLASS_TO_ODOO_TAX` en
`res_company_sync.py` lo mapean al impuesto real de venta (`21% S`,
`10% S`, `0% S`) al crear el producto en Odoo. Solo se asigna al crear —
un resync no pisa un impuesto que se haya corregido a mano.

**Por cliente (RE):** en Odoo el recargo se aplica por *cliente*
(posición fiscal), no por producto — mucho más limpio que el hack de
WooCommerce de duplicar cada producto en una clase `-re`. **Hecho:** el
cliente de WooCommerce con rol `re` (mismo rol que ya usa
`ivb-pedidos-comerciales` para bloquear formas de pago) recibe
automáticamente la posición fiscal "Equivalence surcharge" en
`res.partner.property_account_position_id`.

## Otros datos del cliente que se importan

Además de nombre/email/teléfono/dirección/comercial, el cliente de
WooCommerce trae más metadatos de negocio reales (revisados a mano contra
la tienda real, descartando ruido de tracking/analytics tipo fingerprint
de navegador o sync de HubSpot):

| Meta/campo WooCommerce | Campo en Odoo |
|---|---|
| `cif` | `res.partner.vat` |
| `tipo` (ej. `farmacia`) | Etiqueta de contacto (`res.partner.category_id`), se crea si no existe |
| `role` == `re` | Posición fiscal "Equivalence surcharge" |
| `comercial` | `res.partner.user_id` (ver sección de comerciales) |
| `grupo` (central de compras, ej. Cofares) | Empresa matriz (`res.partner.parent_id`), se crea si no existe |
| `sepa_days` / `sepa_min_amount` / `sepa_max_amount` | Campos propios `ivb_sepa_*` (sin equivalente nativo en Odoo) |
| `purchase_limit_enabled` / `monthly_purchase_limit` | Campos propios `ivb_purchase_limit_enabled` / `ivb_monthly_purchase_limit` |
| `apertura` / `procedencia` / `iqvia` / `escala` / `escalaAuto` / `unidadesCompradas` / `fecha_cumpleanos` / `visitada` | Campos propios `ivb_apertura_email`, `ivb_procedencia`, `ivb_iqvia`, `ivb_escala`, `ivb_escala_automatica`, `ivb_unidades_compradas`, `ivb_fecha_cumpleanos`, `ivb_visitada` — seguimiento comercial de farmacia, se importan tal cual |

**Deliberadamente fuera** (revisados en el admin de WooCommerce pero
descartados por ser seguimiento de material promocional, no ficha de
cliente): `regletas`, `vademecum`, `stoppers`, `expositor`, `vinilo`,
`vinilo_navidad` — encajan más con `material-promocional-b2b` que con el
ERP.

Valores placeholder de WooCommerce como `"No asignado"`/`"No asignada"` se
normalizan a vacío en vez de guardarse como texto literal (`_meta_clean`
en `woocommerce.py`).

Los campos propios se ven en la ficha de contacto, pestaña **"IVB -
Condiciones"**. Solo se importaron los 3 clientes que WooCommerce expone
en su endpoint `/customers` con cuenta registrada — la mayoría de clientes
de IVB probablemente se gestionan como pedidos sin cuenta (checkout
guest), así que estos datos de ficha de cliente no cubren toda la base de
clientes todavía.

## Pedidos: se confirman solos si ya están pagados

Un pedido de WooCommerce con estado `processing` o `completed` se importa
**ya confirmado** (`sale.order` en estado `sale`, no presupuesto) —
`action_confirm()` se llama automáticamente en `_ivb_update_or_create_order`.
Pedidos `pending`, `on-hold`, `cancelled` o `refunded` se quedan como
presupuesto (`draft`): confirmarlos en Odoo sería mentir sobre su estado
real en la tienda. Si un pedido no tiene ninguna línea reconocida (todos
los SKU son desconocidos en Odoo) tampoco se confirma, aunque el estado
en origen sea `completed`.

## Qué falta para pasar de PoC a producción

- Implementar `shopify.py` cuando termine la migración (mismas firmas que
  `woocommerce.py`).
- Asignar la posición fiscal de recargo de equivalencia por cliente (ver
  sección de impuestos arriba) — falta decidir la fuente de esa
  información en WooCommerce.
- ~~Asignación de comercial por cliente~~ — **hecho.** El cliente de
  WooCommerce trae un meta `comercial` con el email del comercial asignado
  (confirmado contra `profesional.ivbwellness.com`, no es
  `_ipc_comercial_email` como se pensó al principio — ese es el meta a
  nivel de *pedido* que usa el TPV, este es a nivel de *cliente*).
  `_ivb_find_salesperson` en `res_company_sync.py` busca un `res.users` con
  ese email como login y lo asigna como `res.partner.user_id`
  ("Salesperson"); el pedido hereda el comercial de su cliente al crearse.
  Si el comercial no existe todavía en Odoo, **se crea automáticamente**
  como usuario interno mínimo (nombre derivado del email, sin contraseña).
  Todo el sync corre con `tracking_disable=True` para que ni la creación
  del usuario (`no_reset_password=True`, evita el email de invitación de
  `auth_signup`) ni la asignación como Salesperson (que si no, dispara una
  notificación "Has sido asignado a `<cliente>`" al chatter del usuario)
  avisen a nadie todavía — verificado comparando `mail.mail` antes/después
  de sincronizar (delta 0).
- Reglas de precio/tarifa por cliente (B2B vs B2C) — Odoo `product.pricelist`.
- Multi-almacén real si IVB tiene más de un almacén físico.
- Paginación completa del catálogo al sincronizar productos (ahora mismo
  solo se trae la primera página de 100, así que pedidos con SKUs fuera de
  esa página se importan con esas líneas omitidas — hay un warning en el
  log de Odoo por cada línea omitida).
- Backup/restore y entorno de staging antes de tocar datos reales.
