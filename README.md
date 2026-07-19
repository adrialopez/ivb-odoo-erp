# IVB Odoo ERP (PoC)

Prueba de concepto de un Odoo "estilo Gextia" para **IVB Wellness Lab**: ERP
para una empresa **distribuidora/importadora, no fabricante**, conectado a
su tienda online.

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
├── docker-compose.yml       # Odoo 17 + Postgres
├── odoo.conf
├── .env.example             # copiar a .env con credenciales de Postgres
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

Requiere Docker Desktop (no estaba instalado en esta máquina al crear el
PoC — instálalo desde docker.com o `brew install --cask docker`).

```bash
cd ivb-odoo-erp
cp .env.example .env   # y cambia la contraseña de Postgres
docker compose up
```

Primer arranque: instala Odoo + todas las apps de la tabla de arriba
automáticamente (`--init=...` en `docker-compose.yml`). Tarda unos minutos.
Luego entra en http://localhost:8069, crea la base de datos si no se creó
sola, y usuario admin.

## Configurar el conector (con credenciales de prueba/placeholder)

1. Ajustes → busca "IVB Connector".
2. Plataforma: WooCommerce.
3. URL de la tienda: `https://profesional.ivbwellness.com` (o cualquier
   WooCommerce de pruebas).
4. API Key / Secret: genera un par en WooCommerce → Ajustes → Avanzado →
   REST API (permisos de solo lectura para probar; lectura/escritura si
   quieres probar el envío de stock).
5. Botón "Probar conexión" y luego "Sincronizar ahora".
6. Revisar el resultado en **IVB Connector → Historial de sincronización**.

El cron (`ir_cron_data.xml`) está **inactivo por defecto** — actívalo desde
Ajustes técnicos → Automatización → Acciones programadas una vez haya
credenciales reales, para no sincronizar contra nada con las de ejemplo.

## Qué falta para pasar de PoC a producción

- Implementar `shopify.py` cuando termine la migración (mismas firmas que
  `woocommerce.py`).
- Reglas de precio/tarifa por cliente (B2B vs B2C) — Odoo `product.pricelist`.
- Multi-almacén real si IVB tiene más de un almacén físico.
- Decisión sobre roles específicos de IVB (comercial, SEPA, recargo de
  equivalencia — ver memoria de `ivb-pedidos-comerciales`): si se quieren
  reflejar en Odoo (grupos de usuario, fiscal position RE) o quedarse solo
  en la tienda.
- Backup/restore y entorno de staging antes de tocar datos reales.
