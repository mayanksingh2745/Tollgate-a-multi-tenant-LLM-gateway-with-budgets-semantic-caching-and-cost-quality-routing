# Database Backup & Disaster Recovery Guide (Phase 15A)

## 1. Disaster Recovery Objectives

| Metric | Target SLA | Strategy |
| :--- | :--- | :--- |
| **Recovery Point Objective (RPO)** | **$\le 1$ Hour** | Automated daily logical dumps (`pg_dump`) supplemented by hourly database snapshots / WAL archives. |
| **Recovery Time Objective (RTO)** | **$\le 15$ Minutes** | Scripted single-command restoration via `./scripts/restore_postgres.sh`. |

---

## 2. Backup Schedule, Retention & Storage

### A. Frequency
* **Full Logical Backup**: Once daily at 02:00 UTC (during low-traffic window).
* **Pre-Deployment Backup**: Automatically created prior to running database migrations during `./scripts/deploy.sh`.

### B. Retention Policy
* **Daily Backups**: Retained for 7 days.
* **Weekly Backups**: Retained for 4 weeks.
* **Monthly Backups**: Retained for 12 months.

### C. Storage & Encryption
* **Format**: Compressed Gzip SQL archives (`.sql.gz`) with SHA-256 checksum manifests (`.sql.gz.sha256`).
* **Encryption**: Backups stored off-host must be encrypted at rest using AES-256 or GPG keys.
* **Git Safety**: Backup directories (`backups/`) and database dump files (`*.sql`, `*.sql.gz`) are strictly ignored in `.gitignore`.

### D. Automated Scheduling Mechanisms
Production backup execution is scheduled using one of the following automated runners:

1. **Linux Cron Job** (`/etc/cron.d/tollgate-backup`):
   ```cron
   # Run logical database backup daily at 02:00 UTC
   0 2 * * * root /opt/tollgate/scripts/backup_postgres.sh >> /var/log/tollgate/backup.log 2>&1
   ```

2. **Systemd Timer** (`/etc/systemd/system/tollgate-backup.timer`):
   ```ini
   [Unit]
   Description=Run Tollgate PostgreSQL Backup Daily
   
   [Timer]
   OnCalendar=*-*-* 02:00:00 UTC
   Persistent=true
   
   [Install]
   WantedBy=timers.target
   ```

3. **Kubernetes CronJob** (`deploy/k8s/backup-cronjob.yaml`):
   ```yaml
   apiVersion: batch/v1
   kind: CronJob
   metadata:
     name: tollgate-db-backup
   spec:
     schedule: "0 2 * * *"
     jobTemplate:
       spec:
         template:
           spec:
             containers:
             - name: postgres-backup
               image: postgres:16-alpine
               command: ["/bin/sh", "/scripts/backup_postgres.sh"]
             restartPolicy: OnFailure
   ```

---

## 3. Creating a Backup

Execute the automated backup script:
```bash
./scripts/backup_postgres.sh
```

### Script Execution Flow:
1. Detects database location (checks running `tollgate-postgres` Docker container or local `pg_dump`).
2. Extracts a consistent snapshot using `--clean --if-exists --no-owner --no-privileges`.
3. Streams output directly through `gzip -9` into `backups/tollgate_db_<timestamp>.sql.gz`.
4. Suppresses and masks credentials.
5. Verifies the generated file is non-empty and prints the final file size and path.

---

## 4. Restoring from a Backup

Restoring a database is an intentionally gated, destructive action.

```bash
# Syntax:
./scripts/restore_postgres.sh <path_to_backup_file.sql.gz>

# Example:
./scripts/restore_postgres.sh backups/tollgate_db_20260930_210000Z.sql.gz
```

### Safety Confirmation Gating:
The script requires the operator to confirm explicitly:
```text
======================================================================
 [DANGER] DESTRUCTIVE ACTION: RESTORING TOLLGATE DATABASE
 Target database: 'tollgate_db' at localhost:5432
 Source file:     'backups/tollgate_db_20260930_210000Z.sql.gz'
 WARNING: this will overwrite all existing tables and data in 'tollgate_db'.
======================================================================
To proceed, type exactly: RESTORE TOLLGATE
> RESTORE TOLLGATE
```

For non-interactive CI/CD drills, pass `--force` as the second argument:
```bash
./scripts/restore_postgres.sh backups/tollgate_db_20260930_210000Z.sql.gz --force
```

---

## 5. Verification & Restore Drill Workflow

To validate complete disaster recovery capabilities:

```text
1. Active Production Database
       │
       ▼
2. Create Backup: ./scripts/backup_postgres.sh
       │
       ▼
3. Restore onto clean/test DB: ./scripts/restore_postgres.sh <backup_file> --force
       │
       ▼
4. Verify Schema Migrations: python -m alembic upgrade head
       │
       ▼
5. Start Application: docker compose up -d gateway
       │
       ▼
6. Run Health Probe: curl -f http://localhost:8000/health/ready
       │
       ▼
7. Verification Success!
```
