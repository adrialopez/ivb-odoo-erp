#!/bin/bash
# Arranque del contenedor Odoo: instala módulos, aplica la configuración
# española (país + plan contable PYMES + idioma) que Odoo no deja resolver
# de forma fiable desde un post_init_hook (probado: try_loading() dentro de
# un post_init_hook se revierte por algo que corre después en la misma
# transacción de instalación — nunca se identificó la causa exacta, pero
# ejecutarlo en su propio proceso, después de que la instalación ya haya
# hecho commit, funciona de forma consistente), y luego arranca el servidor.
set -euo pipefail

DB="${ODOO_DB:-ivb_odoo}"
MODULES="sale_management,purchase,stock,product_expiry,account,l10n_es,crm,contacts,barcodes,ivb_connector"

# Al arrancar este script directamente como comando del contenedor nos
# saltamos el "case" del entrypoint.sh de la imagen oficial que normalmente
# espera a Postgres antes de exec'utar odoo, así que lo hacemos a mano.
wait-for-psql.py --db_host="$HOST" --db_port="${PORT:-5432}" --db_user="$USER" --db_password="$PASSWORD" --timeout=30

echo "== IVB bootstrap: instalando/actualizando módulos =="
odoo -d "$DB" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" \
     --init="$MODULES" --without-demo=all --stop-after-init

echo "== IVB bootstrap: cargando idioma español =="
odoo -d "$DB" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" \
     --load-language=es_ES --stop-after-init

echo "== IVB bootstrap: aplicando país España + plan contable PYMES + idioma admin =="
odoo shell -d "$DB" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD" --no-http <<'PYEOF'
company = env['res.company'].search([], limit=1)
spain = env['res.country'].search([('code', '=', 'ES')], limit=1)

if company.chart_template != 'es_pymes':
    company.write({'country_id': spain.id, 'currency_id': env.ref('base.EUR').id})
    env.cr.commit()
    env['account.chart.template'].try_loading(template_code='es_pymes', company=company)
    env.cr.commit()
    print(f"[bootstrap] plan contable: {company.chart_template}, impuestos: {env['account.tax'].search_count([('company_id', '=', company.id)])}")
else:
    print("[bootstrap] plan contable ya era es_pymes, no se toca")

admin = env['res.users'].search([('login', '=', 'admin')], limit=1)
if admin and admin.lang != 'es_ES':
    admin.write({'lang': 'es_ES'})
    env.cr.commit()
    print("[bootstrap] idioma del admin puesto a es_ES")
PYEOF

echo "== IVB bootstrap: arrancando servidor =="
exec odoo -d "$DB" --db_host="$HOST" --db_user="$USER" --db_password="$PASSWORD"
