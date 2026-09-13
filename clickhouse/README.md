# clickhouse/ — owner: Jose Angel (Part 3)

See [docs/handoffs.md](../docs/handoffs.md) Section 3 for the full task.

Capa analítica: ClickHouse recibe, vía el mirror de PeerDB `postgres_to_clickhouse`
(Parte 2), todos los INSERT/UPDATE/DELETE que el generador hace en Postgres (Parte 1).

## Contenido

| Archivo | Qué es |
|---|---|
| `init/01_schema.sql` | Las 6 tablas destino (`ReplacingMergeTree(_peerdb_version)`). Se ejecuta solo al iniciar ClickHouse con el volumen vacío. |
| `verify.sh` | Verificación de UPDATE/DELETE: cambia filas en Postgres y muestra el estado final en ClickHouse con `FINAL`. |
| `verification/latest_run.txt` | Salida real de `verify.sh` (evidencia para el reporte). |

## Cómo corre

Todo es automático con `docker compose up --build`:

1. `clickhouse` arranca, crea la base `ecommerce` (`CLICKHOUSE_DB` del `.env`) y ejecuta `init/01_schema.sql`.
2. Su healthcheck solo pasa cuando existen las 6 tablas, así que `peerdb-init` (Parte 2) espera a que el esquema esté listo.
3. PeerDB encuentra las tablas ya creadas y las reutiliza (`CREATE TABLE IF NOT EXISTS`), hace la copia inicial y empieza a replicar cambios cada ~10 s.

Conectarse manualmente:

```bash
docker compose exec clickhouse sh -c 'clickhouse-client --password "$CLICKHOUSE_PASSWORD" -d ecommerce'
```

> Los scripts de `init/` solo corren cuando el volumen `clickhouse_data` está vacío. Si cambias
> el esquema, hay que recrear los volúmenes: `docker compose down -v && docker compose up --build`
> (esto borra los datos locales de Postgres, PeerDB y ClickHouse; el generador y PeerDB los vuelven a llenar).

> **Si ClickHouse se reinicia** con el pipeline corriendo, PeerDB registra errores de conexión
> ("failed to ping", "unexpected EOF") y espera 1 minuto antes de reanudar; si se acumulan varios
> errores seguidos, espera más (hasta 10 min). El mirror sigue activo, reanuda desde donde se quedó
> y no se pierden datos.

## Decisiones de esquema

### Tipos: exactamente lo que escribe PeerDB

Las columnas y tipos son los mismos que PeerDB (v0.37.7, con `PEERDB_NULLABLE=true`) genera
por su cuenta. Se comprobó dejando que PeerDB creara las tablas y comparando con `SHOW CREATE TABLE`.
Así PeerDB reutiliza nuestras tablas tal cual, sin conflictos de tipos.

| Postgres | ClickHouse |
|---|---|
| `SERIAL` / `INTEGER` | `Int32` |
| `NUMERIC(10,2)` | `Decimal(10, 2)` |
| `VARCHAR(n)` | `String` |
| `TIMESTAMPTZ` | `DateTime64(6)` |
| columna que acepta NULL (`payments.paid_at`, `customers.city`, `customers.country`) | `Nullable(...)` |

Además PeerDB llena tres columnas propias en cada tabla:

| Columna | Tipo | Uso |
|---|---|---|
| `_peerdb_version` | `UInt64` | Crece con cada cambio de la fila. Es la versión del `ReplacingMergeTree`. |
| `_peerdb_is_deleted` | `UInt8` | `1` si la fila fue borrada en Postgres (soft delete). |
| `_peerdb_synced_at` | `DateTime64(9)` | Cuándo llegó el cambio a ClickHouse. |

### Motor: `ReplacingMergeTree(_peerdb_version)` + `ORDER BY` la llave primaria

ClickHouse guarda los datos en partes inmutables; no modifica filas en sitio como Postgres. PeerDB
convierte cada UPDATE y cada DELETE en una **fila nueva** con la misma llave y un `_peerdb_version`
mayor. `ReplacingMergeTree` agrupa por el `ORDER BY` (la llave primaria de Postgres) y, al fusionar
partes, conserva solo la fila con la versión más alta.

Las fusiones ocurren en segundo plano y sin horario fijo, así que en un momento dado puede haber
varias versiones de la misma fila. `FINAL` hace esa deduplicación al momento de la consulta y
garantiza que solo se lee la última versión.

### Por qué `_peerdb_version` y no `updated_at`

`docs/handoffs.md` sugería `ReplacingMergeTree(updated_at)` "o la columna de versión que PeerDB
realmente llene". Se usa `_peerdb_version` porque `updated_at` no funciona:

- **DELETE:** las tablas usan `REPLICA IDENTITY DEFAULT`, así que en un DELETE Postgres solo envía
  la llave primaria. La fila de borrado llega con las demás columnas vacías (`updated_at = 1970-01-01`),
  perdería contra la versión anterior y la fila borrada "reviviría".
- **`categories`** no tiene `updated_at`.
- `_peerdb_synced_at` tampoco sirve: todas las filas de un mismo lote comparten el mismo valor.

### Sin `PARTITION BY`

El volumen es chico (cientos de miles de filas). Sin particiones, `FINAL` deduplica toda la tabla
de forma simple y no hay riesgo de versiones de la misma llave en particiones distintas.

### `Nullable` con `PEERDB_NULLABLE=true`

Sin ese ajuste, PeerDB escribe `1970-01-01` donde Postgres tiene `NULL` (por ejemplo, pagos sin
completar). Con él, `paid_at IS NULL` significa lo mismo en Postgres y en ClickHouse, así las
consultas pareadas de la Parte 4 no necesitan casos especiales.

## Patrón de consulta para Partes 4 y 5

**Regla:** toda tabla que se lea lleva `FINAL` y filtra `_peerdb_is_deleted = 0`.

```sql
-- una tabla
SELECT order_status, count() AS orders
FROM ecommerce.orders FINAL
WHERE _peerdb_is_deleted = 0
GROUP BY order_status;

-- con JOIN: FINAL y el filtro en cada tabla
SELECT c.category_name, sum(oi.quantity * oi.unit_price) AS revenue
FROM ecommerce.order_items AS oi FINAL
INNER JOIN ecommerce.products AS p FINAL ON p.product_id = oi.product_id
INNER JOIN ecommerce.categories AS c FINAL ON c.category_id = p.category_id
WHERE oi._peerdb_is_deleted = 0
  AND p._peerdb_is_deleted = 0
  AND c._peerdb_is_deleted = 0
GROUP BY c.category_name
ORDER BY revenue DESC;
```

- **Sin `FINAL`** se cuentan versiones viejas de filas actualizadas (conteos y sumas inflados).
- **Sin el filtro** se cuentan filas borradas, que además tienen sus columnas vacías (montos en `0`, textos `''`).
- Para el benchmark (Parte 4): `FINAL` tiene costo, porque deduplica al leer. Es parte de la comparación honesta con Postgres, no conviene quitarlo.

Nombres de tablas y columnas estables: los mismos de Postgres (`docs/requirements.md` §3) más las
tres columnas `_peerdb_*`.

## Verificación

Con el stack corriendo:

```bash
./clickhouse/verify.sh
```

El script cambia filas en Postgres con `psql`, espera a que el cambio llegue a ClickHouse y
guarda toda la salida en [`verification/latest_run.txt`](verification/latest_run.txt).
Para no chocar con el generador, usa columnas y filas que el generador no toca (`customers.email`,
un pago `refunded`, pedidos en estado final).

| Prueba | Resultado (corrida del 2026-09-13, stack levantado desde cero) |
|---|---|
| UPDATE en Postgres → `SELECT ... FINAL` | Nuevo valor visible en ClickHouse en ~2 s |
| DELETE en Postgres → soft delete | `_peerdb_is_deleted = 1` en ~11 s; con el filtro, la fila desaparece |
| UPDATEs hechos por el generador | 5 de 5 pedidos con el mismo `order_status` en Postgres y en ClickHouse `FINAL` |

### 1. UPDATE

Antes, en ClickHouse:

```
┌─customer_id─┬─email───────────────┬─city──────┬─────────────────updated_at─┬─_peerdb_version─┬─_peerdb_is_deleted─┐
│           1 │ vnewman@example.net │ Yorkmouth │ 2026-09-13 19:44:46.486086 │               0 │                  0 │
└─────────────┴─────────────────────┴───────────┴────────────────────────────┴─────────────────┴────────────────────┘
```

En Postgres:

```sql
UPDATE customers SET email = 'cdc-verify-1789328758@example.com', updated_at = now() WHERE customer_id = 1;
```

Después, **sin `FINAL`**: las dos versiones siguen guardadas hasta que ClickHouse fusione las partes.

```
┌─customer_id─┬─email─────────────────────────────┬─city──────┬─────────────────updated_at─┬─────_peerdb_version─┬─_peerdb_is_deleted─┐
│           1 │ vnewman@example.net               │ Yorkmouth │ 2026-09-13 19:44:46.486086 │                   0 │                  0 │
│           1 │ cdc-verify-1789328758@example.com │ Yorkmouth │ 2026-09-13 19:45:58.546321 │ 1789328758549198892 │                  0 │
└─────────────┴───────────────────────────────────┴───────────┴────────────────────────────┴─────────────────────┴────────────────────┘
```

Después, **con `FINAL`**: solo la última versión.

```
┌─customer_id─┬─email─────────────────────────────┬─city──────┬─────────────────updated_at─┬─────_peerdb_version─┬─_peerdb_is_deleted─┐
│           1 │ cdc-verify-1789328758@example.com │ Yorkmouth │ 2026-09-13 19:45:58.546321 │ 1789328758549198892 │                  0 │
└─────────────┴───────────────────────────────────┴───────────┴────────────────────────────┴─────────────────────┴────────────────────┘
```

Las filas que llegaron en la copia inicial tienen `_peerdb_version = 0`; cualquier cambio posterior
tiene una versión mayor y gana.

### 2. DELETE

```sql
DELETE FROM payments WHERE payment_id = 1;  -- pago 'refunded', amount 3147.54
```

`FINAL` devuelve la marca de borrado, con las columnas que no son llave vacías (Postgres solo envía la llave):

```
┌─payment_id─┬─order_id─┬─payment_status─┬─amount─┬─────────────────updated_at─┬─────_peerdb_version─┬─_peerdb_is_deleted─┐
│          1 │        0 │                │      0 │ 1970-01-01 00:00:00.000000 │ 1789328761271944950 │                  1 │
└────────────┴──────────┴────────────────┴────────┴────────────────────────────┴─────────────────────┴────────────────────┘
```

Y con el filtro `_peerdb_is_deleted = 0` la fila ya no aparece (`rows_visible = 0`).

### 3. UPDATEs del generador

Los últimos 5 pedidos que el generador movió a `delivered`/`cancelled` tienen exactamente el mismo
`order_status` y `updated_at` en Postgres y en `orders FINAL` (salida completa en `latest_run.txt`).
