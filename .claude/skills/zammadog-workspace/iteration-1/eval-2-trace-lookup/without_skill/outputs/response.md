# Trace Lookup: abc123def456789 en ms-orders

Para ver todos los spans de ese trace en Datadog APM, usaría la **Datadog API REST** directamente con `curl`, ya que tengo `DD_API_KEY` y `DD_APP_KEY` disponibles.

## Enfoque: Datadog APM Traces API

Datadog expone el endpoint `/api/v1/query` para métricas y `/api/v2/spans/events` para búsqueda de spans. Para buscar por trace ID específico, el endpoint más directo es:

```
GET https://api.datadoghq.com/api/v2/spans/events?filter[query]=trace_id:abc123def456789&filter[from]=<timestamp_hace_25min>&filter[to]=<timestamp_ahora>
```

### Pasos concretos:

1. **Calcular el rango de tiempo** (hace ~25 min para cubrir los 20 minutos mencionados):
   ```bash
   NOW=$(date +%s)
   FROM=$((NOW - 1800))  # 30 min atrás para tener margen
   ```

2. **Llamar a la API de spans**:
   ```bash
   curl -X GET "https://api.datadoghq.com/api/v2/spans/events" \
     -H "DD-API-KEY: ${DD_API_KEY}" \
     -H "DD-APPLICATION-KEY: ${DD_APP_KEY}" \
     -G \
     --data-urlencode "filter[query]=trace_id:abc123def456789 service:ms-orders" \
     --data-urlencode "filter[from]=$(date -u -d @$FROM +%Y-%m-%dT%H:%M:%SZ)" \
     --data-urlencode "filter[to]=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
     --data-urlencode "page[limit]=100"
   ```

3. **Alternativamente, abrir directamente en la UI de Datadog**:
   ```
   https://app.datadoghq.com/apm/trace/abc123def456789
   ```
   Esto muestra la flame graph completa con todos los spans.

## Limitaciones del enfoque sin herramienta especializada

- Hay que calcular manualmente los timestamps en formato ISO 8601.
- La respuesta JSON de la API es cruda — hay que parsear con `jq` para ver los spans de forma legible.
- Si el trace ID usa formato hexadecimal largo, Datadog podría requerir convertirlo a decimal para algunos endpoints.
- La paginación es manual si hay muchos spans.

## Comando completo con jq para output legible:

```bash
curl -s -X GET "https://api.datadoghq.com/api/v2/spans/events" \
  -H "DD-API-KEY: ${DD_API_KEY}" \
  -H "DD-APPLICATION-KEY: ${DD_APP_KEY}" \
  -G \
  --data-urlencode "filter[query]=trace_id:abc123def456789" \
  --data-urlencode "filter[from]=$(date -u -d '30 minutes ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --data-urlencode "filter[to]=$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --data-urlencode "page[limit]=100" \
  | jq '.data[] | {span_id: .id, service: .attributes.service, resource: .attributes.resource, duration_ms: (.attributes.duration / 1000000), status: .attributes.status}'
```

## Resultado esperado

Una lista de objetos con los spans del trace, ordenados por inicio, mostrando:
- `span_id`
- `service` (debería ser `ms-orders` y cualquier servicio downstream que haya llamado)
- `resource` (nombre del endpoint/operación)
- `duration_ms`
- `status` (ok / error)
