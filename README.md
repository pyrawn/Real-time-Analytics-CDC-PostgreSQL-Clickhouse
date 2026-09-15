# Real-Time Analytics with PostgreSQL CDC & ClickHouse

U1T01 — Trends in Data Science. CDC pipeline from PostgreSQL (OLTP) to ClickHouse
(OLAP) via PeerDB, fed by a continuous e-commerce data generator, benchmarked, with
an optional real-time dashboard.

Start here:
- [docs/instructions.pdf](docs/instructions.pdf) — original assignment
- [docs/requirements.md](docs/requirements.md) — schema, architecture, shared contract
- [docs/handoffs.md](docs/handoffs.md) — numbered instructions per team member

Team → part mapping: Julio (1: modeling & generator), Valeria (2: CDC/PeerDB),
Jose Angel (3: ClickHouse), Leonora (4: benchmarking), Lorena (5: dashboard).

## Cómo correrlo

Todo el stack corre en contenedores Linux, así que los pasos son los mismos en cualquier sistema;
solo cambian la terminal y un par de comandos.

### Requisitos

| | Linux / macOS | Windows |
|---|---|---|
| Docker | Docker Engine + plugin Compose v2 (o Docker Desktop / OrbStack en macOS) | Docker Desktop con el backend **WSL 2** |
| Git | `git` | [Git for Windows](https://git-scm.com/download/win) |
| Python (solo benchmark) | Python 3.10+ | Python 3.10+ |
| Terminal | cualquiera | PowerShell para arrancar; **Git Bash** o WSL para los scripts `.sh` |

### Linux / macOS

```bash
git clone https://github.com/pyrawn/Real-time-Analytics-CDC-PostgreSQL-Clickhouse.git
cd Real-time-Analytics-CDC-PostgreSQL-Clickhouse
cp .env.example .env
docker compose up --build -d
```

### Windows (PowerShell)

```powershell
git clone https://github.com/pyrawn/Real-time-Analytics-CDC-PostgreSQL-Clickhouse.git
cd Real-time-Analytics-CDC-PostgreSQL-Clickhouse
Copy-Item .env.example .env
docker compose up --build -d
```

Crea el `.env` copiando `.env.example` (como arriba), no como archivo nuevo desde el editor.

### Comprobar que funciona

```bash
docker compose ps                        # todos los servicios "running" / "healthy"
docker compose logs peerdb-init          # debe terminar con "CDC setup completed!"
docker compose logs --tail 5 generator   # total_ops debe ir creciendo
```

El arranque en frío tarda unos minutos (descarga de imágenes + copia inicial). UI de PeerDB en
<http://localhost:3000>.

Verificación de UPDATE/DELETE en ClickHouse (Parte 3):

```bash
./clickhouse/verify.sh          # Linux / macOS / Git Bash / WSL
```

En Windows ese script se corre desde **Git Bash** (o WSL), no desde PowerShell.

Benchmark (Parte 4), desde la raíz del repo:

```bash
python3 benchmark/run_benchmark.py   # Linux / macOS
py benchmark/run_benchmark.py        # Windows
```

### Detener

```bash
docker compose down        # conserva los datos
docker compose down -v     # borra los datos (necesario para volver a correr clickhouse/init)
```

### Puertos que usa

Si alguno ya está ocupado en tu máquina (por ejemplo un Postgres local en 5432), detén ese servicio
antes de `docker compose up`.

| Puerto | Servicio |
|---|---|
| 5432 | PostgreSQL |
| 8123, 9000 | ClickHouse (HTTP, nativo) |
| 3000 | PeerDB UI |
| 9900 | PeerDB server (SQL) |
| 9901 | Catálogo de PeerDB |
| 7233 | Temporal |
| 8112, 8113 | PeerDB flow API |
| 9001, 9002 | MinIO |

## Windows y los finales de línea (CRLF)

Git para Windows convierte por defecto los finales de línea a CRLF al descargar. Los scripts y
configs de este repo se ejecutan dentro de contenedores Linux, donde CRLF los rompe; el síntoma
típico es `peerdb-temporal-admin-tools` reiniciándose sin parar con
`exec /etc/temporal/entrypoint.sh: no such file or directory`.

El archivo [`.gitattributes`](.gitattributes) obliga a descargar todo con LF, así que un **clon
nuevo** funciona sin configurar nada.

**Si ya tenías el repo clonado antes de ese cambio**, Git no reescribe los archivos existentes.
Guarda tus cambios (commit o `git stash`) y ejecuta, en PowerShell o Git Bash:

```bash
git pull
git rm -r --cached .
git reset --hard
```

Para comprobarlo (debe salir vacío):

```bash
git ls-files --eol | grep crlf                              # Git Bash / Linux / macOS
git ls-files --eol | Select-String "w/crlf"                 # PowerShell
```

Después, `docker compose down` y `docker compose up --build -d` de nuevo.

Recomendaciones para quien usa Windows:
- Configura tu editor para guardar con LF (en VS Code: `"files.eol": "\n"`). Si un archivo
  aparece como modificado sin haberlo cambiado, casi siempre es por los finales de línea.
- Si usas WSL, clona el repo dentro del sistema de archivos de WSL (`~/...`), no en `/mnt/c/...`:
  es mucho más rápido con Docker.
