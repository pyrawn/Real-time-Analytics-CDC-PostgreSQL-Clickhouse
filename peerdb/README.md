# peerdb/ — owner: Valeria (Part 2)

See [docs/handoffs.md](../docs/handoffs.md) Section 2 for the full task.

This folder configures the **CDC pipeline using PeerDB**, mirroring changes from PostgreSQL to ClickHouse in real-time.

## What was deployed

- **PeerDB Stack:** Se han integrado los servicios de PeerDB directamente en el `docker-compose.yml` raíz. Para evitar conflictos, todos tienen el prefijo `peerdb-` (ej. `peerdb-catalog`, `peerdb-temporal`, `peerdb-server`, `peerdb-ui`, `peerdb-minio`, etc.).
- **PeerDB Init:** Se creó un contenedor de inicialización automática (`peerdb-init`) que ejecuta el script `setup_mirror.sh`. Este script espera a que la API/Server de PeerDB esté disponible y luego utiliza la interfaz SQL compatible de PeerDB (puerto 9900) para configurar los *Peers* de origen y destino, así como el *Mirror*.
- **Mirror CDC:** El nombre del mirror creado es `postgres_to_clickhouse`. Se configuró para consumir de la publicación `peerdb_pub` (generada en la Parte 1) y escribir a ClickHouse.

## How to check mirror status

Existen dos formas principales de comprobar el estado del mirror y el flujo CDC:

1. **Vía Interfaz Gráfica (UI):**
   - Accede a `http://localhost:3000` en tu navegador para abrir la interfaz de PeerDB.
   - En la sección **Mirrors**, podrás ver `postgres_to_clickhouse` y revisar sus métricas y estado en tiempo real.

2. **Vía SQL (CLI de PeerDB Server):**
   - El servidor de PeerDB expone un endpoint compatible con Postgres en el puerto `9900` (password `peerdb`).
   - Puedes conectarte con:
     ```bash
     docker compose exec -e PGPASSWORD=peerdb peerdb-server psql -h localhost -p 9900 -U postgres
     ```
   - Y ejecutar comandos de estado, por ejemplo:
     ```sql
     SELECT name, status FROM flows;
     SELECT name, type FROM peers;
     ```

## Mirror configuration

`setup_mirror.sh` crea el mirror con:

- `do_initial_copy = true`: copia también las filas que ya existían en Postgres antes de crear el mirror (el generador siembra `categories`, `products` y `customers` antes, y `categories` nunca recibe UPDATEs).
- `sync_interval = 10`: los cambios llegan a ClickHouse en segundos.
- `PEERDB_NULLABLE=true` (en `x-flow-worker-env` del compose): las columnas que aceptan NULL en Postgres (`payments.paid_at`, `customers.city`, `customers.country`) se crean como `Nullable(...)` en ClickHouse, en vez de guardar valores vacíos como `1970-01-01`. Solo aplica a mirrors creados después de activarlo.
- Los statements usan `IF NOT EXISTS` y el script reintenta si PeerDB aún no está listo, así que volver a correr `docker compose up` es seguro.

## Delete-propagation finding (IMPORTANTE para Parte 3)

Se investigó el comportamiento de PeerDB respecto a la eliminación de filas (*DELETEs*). PeerDB **NO** hace un borrado físico (hard-delete) directo en ClickHouse. En su lugar, emplea **soft-deletes**.

- PeerDB agrega automáticamente tres columnas a las tablas destino de ClickHouse: `_peerdb_is_deleted` (`UInt8`, 0/1), `_peerdb_version` (`UInt64`) y `_peerdb_synced_at` (`DateTime64(9)`).
- Cuando una fila es eliminada en PostgreSQL, PeerDB propaga esa acción insertando una nueva versión de la fila en ClickHouse con `_peerdb_is_deleted = 1` y un `_peerdb_version` mayor.
- Como las tablas usan `REPLICA IDENTITY DEFAULT`, en un DELETE Postgres solo envía la llave primaria: en esa fila las demás columnas llegan vacías (`0`, `''`, `1970-01-01`, o `NULL` en las columnas `Nullable`). Por eso la versión de las tablas debe ser `_peerdb_version` y no `updated_at`.
- **Para la Parte 3:** Las consultas analíticas en ClickHouse y el DDL deben contemplar esto. Si deseas ver únicamente las filas activas, tus consultas deberán filtrar las filas borradas. Ejemplo:
  ```sql
  SELECT * FROM ecommerce.orders FINAL WHERE _peerdb_is_deleted = 0;
  ```
