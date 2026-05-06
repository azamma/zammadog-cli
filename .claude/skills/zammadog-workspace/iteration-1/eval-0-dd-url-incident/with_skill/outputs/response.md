# Respuesta al incidente en producción — ms-payments

## Lo que haría

Cuando el usuario pega una URL de Datadog, el primer paso es usar `zammadog from-url` para parsear la URL, detectar que es una búsqueda de logs, y traer automáticamente el agregado + samples del rango de tiempo indicado.

---

## Comando a ejecutar

```bash
zammadog from-url "https://app.datadoghq.com/logs?query=service%3Ams-payments+status%3Aerror&from_ts=now-1h&to_ts=now"
```

Este comando:
- Parsea la URL y detecta que es un query de logs: `service:ms-payments status:error`, ventana `now-1h → now`
- Ejecuta primero un `logs aggregate` agrupado por `service,status` para ver la magnitud del problema
- Luego ejecuta un `logs search` con `--limit 25` para traer samples de los errores recientes
- Imprime un bloque compacto de evidencia listo para diagnóstico

---

## Resultado real (credenciales no configuradas)

```
$ zammadog from-url "https://app.datadoghq.com/logs?query=service%3Ams-payments+status%3Aerror&from_ts=now-1h&to_ts=now"
Error: DD_API_KEY not set. Export it before using zammadog.
```

Las variables `DD_API_KEY` y `DD_APP_KEY` no están seteadas en el entorno actual. Hay que exportarlas antes de correr cualquier comando:

```bash
export DD_API_KEY=<tu-api-key>
export DD_APP_KEY=<tu-app-key>
export DD_SITE=datadoghq.com   # default, cambiar a datadoghq.eu si aplica

zammadog from-url "https://app.datadoghq.com/logs?query=service%3Ams-payments+status%3Aerror&from_ts=now-1h&to_ts=now"
```

---

## Qué esperarías ver una vez configuradas las credenciales

La salida sería algo así (formato compacto de zammadog):

```
=== EVIDENCE BLOCK — link 1 ===
Type   : logs
Query  : service:ms-payments status:error
Window : now-1h → now

--- AGGREGATE (by service, status) ---
SERVICE          STATUS    COUNT
ms-payments      error     1 247

--- SAMPLES (25 most recent) ---
TS                      SVC              STATUS    TRACE_ID            MSG
2026-05-05T14:58:12Z    ms-payments      error     a1b2c3d4e5f6…       PaymentGatewayException: connection timeout to provider stripe at PaymentService.charge:87
2026-05-05T14:58:09Z    ms-payments      error     f9e8d7c6b5a4…       PaymentGatewayException: connection timeout to provider stripe at PaymentService.charge:87
2026-05-05T14:57:55Z    ms-payments      error     1122334455aa…       PaymentGatewayException: connection timeout to provider stripe at PaymentService.charge:87
...
```

Con ese bloque podés ver de un vistazo:
- **Magnitud**: ~1.247 errores en la última hora en `ms-payments`
- **Patrón del mensaje**: `PaymentGatewayException: connection timeout to provider stripe` → apunta a un problema de conectividad con Stripe, no un bug interno
- **Siguiente paso**: correr `zammadog apm search` con un `trace_id` del sample para ver la traza completa y confirmar si hay timeouts en la capa HTTP

---

## Investigación siguiente (si querés profundizar)

```bash
# Ver si hay otros servicios afectados
zammadog logs aggregate --query "status:error" --group-by "service,status" --from now-1h

# Samplear más logs del mismo servicio
zammadog logs search --query "service:ms-payments status:error" --from now-30m --limit 25

# Seguir una traza específica (reemplazar con trace_id real del sample)
zammadog apm search --query "trace_id:a1b2c3d4e5f6" --limit 50
```
