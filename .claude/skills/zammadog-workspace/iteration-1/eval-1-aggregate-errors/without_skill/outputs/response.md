# Errores por servicio en los últimos 30 minutos — Datadog

Para obtener el conteo de errores agrupados por servicio, hay dos enfoques dependiendo de cómo estás instrumentado en Datadog:

---

## Opción 1: APM (traces) — `trace.web.request.errors`

```bash
NOW=$(date +%s)
FROM=$((NOW - 1800))

curl -s -X GET "https://api.datadoghq.com/api/v1/query" \
  -H "DD-API-KEY: ${DD_API_KEY}" \
  -H "DD-APPLICATION-KEY: ${DD_APP_KEY}" \
  -G \
  --data-urlencode "from=${FROM}" \
  --data-urlencode "to=${NOW}" \
  --data-urlencode "query=sum:trace.web.request.errors{*} by {service}.as_count()" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('Errors per service (last 30 min):')
print('=' * 50)
for series in data.get('series', []):
    service = series.get('scope', 'unknown')
    points = series.get('pointlist', [])
    total = sum(p[1] for p in points if p[1] is not None)
    print(f'  {service}: {int(total)} errors')
"
```

**Cuándo usarlo:** Si tienes APM/tracing habilitado. La métrica `trace.web.request.errors` cuenta requests con status 5xx o excepciones no manejadas por servicio.

---

## Opción 2: Logs — aggregate API

```bash
curl -s -X POST "https://api.datadoghq.com/api/v2/logs/analytics/aggregate" \
  -H "DD-API-KEY: ${DD_API_KEY}" \
  -H "DD-APPLICATION-KEY: ${DD_APP_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "query": "status:error",
      "from": "now-30m",
      "to": "now"
    },
    "group_by": [
      {
        "facet": "service",
        "sort": { "type": "measure", "order": "desc", "aggregation": "count" },
        "limit": 50
      }
    ],
    "compute": [
      { "aggregation": "count" }
    ]
  }' \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
print('Errors per service (last 30 min) - Logs:')
print('=' * 50)
for bucket in data.get('data', {}).get('buckets', []):
    service = bucket.get('by', {}).get('service', 'unknown')
    count = bucket.get('computes', {}).get('c0', 0)
    print(f'  {service}: {int(count)} errors')
"
```

**Cuándo usarlo:** Si tus servicios mandan logs a Datadog con `status:error`. Filtra por `status:error` y agrupa por el facet `service`.

---

## Resultado esperado

```
Errors per service (last 30 min):
==================================================
  service:payments-api: 143 errors
  service:auth-service: 87 errors
  service:user-service: 12 errors
  service:notification-worker: 3 errors
```

---

## Notas

- Si usas una query de métricas distinta (ej. `trace.servlet.request.errors` para Java/Spring), ajusta el nombre de la métrica.
- El flag `by {service}` en la query de métricas asume que tus traces/métricas tienen el tag `service`. Si usan otro tag (ej. `env`, `team`), ajústalo.
- Para logs, el facet `service` debe estar parseado/indexado en tu configuración de Datadog.
- Si quieres filtrar por entorno: agrega `env:production` a la query.

---

## Por qué no pude ejecutarlo ahora

Las variables `DD_API_KEY` y `DD_APP_KEY` no están disponibles en la sesión de shell actual del agente (el ambiente del proceso bash del agente no hereda las variables del entorno del usuario). Los comandos arriba funcionarán directamente en tu terminal donde las variables sí están seteadas.
