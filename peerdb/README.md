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
   - El servidor de PeerDB expone un endpoint compatible con Postgres en el puerto `9900`.
   - Puedes conectarte con:
     ```bash
     docker compose exec peerdb-server psql -h localhost -p 9900 -U postgres
     ```
   - Y ejecutar comandos de estado, por ejemplo:
     ```sql
     SELECT * FROM mirrors;
     SELECT * FROM peers;
     ```

## Delete-propagation finding (IMPORTANTE para Parte 3)

Se investigó el comportamiento de PeerDB respecto a la eliminación de filas (*DELETEs*). PeerDB **NO** hace un borrado físico (hard-delete) directo en ClickHouse. En su lugar, emplea **soft-deletes**.

- PeerDB inyecta automáticamente una columna llamada `_peerdb_is_deleted` (o `_PEERDB_IS_DELETED`, de tipo booleano / UInt8) en las tablas destino de ClickHouse.
- Cuando una fila es eliminada en PostgreSQL, PeerDB propaga esa acción insertando (o fusionando) una nueva versión de la fila en ClickHouse con `_peerdb_is_deleted = true`.
- **Para Jose Angel (Parte 3):** Las consultas analíticas en ClickHouse y el DDL deben contemplar esto. Si deseas ver únicamente las filas activas, tus consultas deberán filtrar las filas borradas. Ejemplo:
  ```sql
  SELECT * FROM ecommerce.orders FINAL WHERE NOT _peerdb_is_deleted;
  ```
