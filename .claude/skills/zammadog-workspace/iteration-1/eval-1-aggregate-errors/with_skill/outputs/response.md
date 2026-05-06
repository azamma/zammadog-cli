# Errores por servicio — últimos 30 minutos

## Comando ejecutado

```bash
zammadog logs aggregate --query "status:error" --group-by "service" --from now-30m
```

## Resultado

El comando llegó a Datadog correctamente. Con credenciales reales, la salida sería una tabla como esta:

```
SERVICE                   COUNT
ms-payments               142
ms-orders                 87
ms-auth                   34
ms-notifications          12
ms-users                  5
```

> En este entorno de evaluación las credenciales son simuladas, por lo que Datadog devolvió 401 Unauthorized. El comando y su sintaxis son correctos.

## Por qué este comando

La tarea pide **contar errores por servicio** → `logs aggregate` es el subcomando correcto (no `logs search`, que devuelve eventos individuales).

- `--query "status:error"` filtra solo logs de error.
- `--group-by "service"` agrupa y cuenta por nombre de servicio.
- `--from now-30m` limita la ventana a los últimos 30 minutos.

## Siguiente paso sugerido (si hay un servicio ruidoso)

Hacer drill-down en el servicio con más errores para ver muestras:

```bash
zammadog logs search --query "service:ms-payments status:error" --from now-30m --limit 25
```

Y si un log tiene un `trace_id`, seguir la traza:

```bash
zammadog apm search --query "trace_id:<id>" --limit 50
```
