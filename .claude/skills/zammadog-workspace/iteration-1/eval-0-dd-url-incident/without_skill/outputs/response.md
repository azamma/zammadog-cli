# Respuesta al incidente de producción

No puedo traerte el resumen del incidente directamente desde ese link de Datadog.

## Por qué no puedo acceder

El link apunta a `app.datadoghq.com`, que es la UI de Datadog. Para consultar logs programáticamente necesitaría usar la **Datadog Logs API** con credenciales válidas:

- `DD_API_KEY` — no está configurada en este entorno
- `DD_APP_KEY` — no está configurada en este entorno

Sin esas claves, cualquier llamada a la API devuelve 403. El link de la UI tampoco es accesible desde el servidor porque requiere sesión autenticada en el navegador.

## Lo que dice el link (análisis de la URL)

Aunque no puedo ejecutar la consulta, la URL contiene la query codificada:

```
query=service%3Ams-payments+status%3Aerror
→ service:ms-payments status:error
```

Rango de tiempo: `from_ts=now-1h` → última 1 hora.

**En palabras:** están buscando todos los logs de error del servicio `ms-payments` en la última hora.

## Qué necesito para ayudarte

Para darte un resumen real del incidente, necesito alguna de estas opciones:

1. **Las credenciales de Datadog** (`DD_API_KEY` + `DD_APP_KEY`) — con eso puedo llamar a la API y traerte los logs y métricas reales.
2. **Un screenshot o paste de los logs** — si alguien del equipo puede copiar el contenido de esa pantalla.
3. **El output de los logs** — si tienen acceso al servicio `ms-payments` directamente (kubectl logs, CloudWatch, etc.).

## Comando que correría si tuviera las credenciales

```bash
curl -X POST "https://api.datadoghq.com/api/v2/logs/events/search" \
  -H "DD-API-KEY: ${DD_API_KEY}" \
  -H "DD-APPLICATION-KEY: ${DD_APP_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "filter": {
      "query": "service:ms-payments status:error",
      "from": "now-1h",
      "to": "now"
    },
    "sort": "timestamp",
    "page": { "limit": 50 }
  }'
```

Avisame cómo quieren proceder.
