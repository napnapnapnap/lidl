# Lidl Shopping Bot

A self-hosted Signal bot that fetches your Lidl digital receipts and sends weekly shopping suggestions to a Signal group. Runs on a GCP e2-micro VM (free tier) deployed via Terraform and GitHub Actions.

## What It Does

- **Weekly suggestions** — every Sunday, posts your top purchased items (last 30 days) to a Signal group
- **On-demand** — reply `/shopping` (or `/shopping --days 14`) in the group to get suggestions at any time
- **Auto-sync** — daily receipt sync keeps the data fresh from your Lidl account

## Architecture

```
Signal group
    │  /shopping command
    ▼
signal-cli-rest-api  ←──────────────────────────────┐
    │  polled every minute                           │
    ▼                                               │
n8n (workflow engine)                               │
    │  GET /top?days=N                              │ POST /v2/send
    ▼                                               │
lidl-api (FastAPI)  ←── scripts/lidl_receipts.py   │
    │  fetches from lidl.fr                         │
    ▼                                               │
/data/receipts/ ─────────────────────────────────────
```

All three containers run on a single GCE e2-micro instance with a 10 GB persistent data disk.

## Repository Layout

```
├── infra/                  Terraform — GCP VM, disk, firewall, OIDC
├── docker/
│   ├── docker-compose.yml  Production compose (n8n + signal-cli + lidl-api)
│   ├── lidl-api/           FastAPI wrapper around lidl_receipts.py
│   └── n8n/workflows/      4 n8n workflow JSON files
├── scripts/
│   └── lidl_receipts.py    Lidl receipt fetcher/parser (standalone CLI)
└── Makefile                SSH helpers (ssh-vm, ssh-tunnel, signal-link, setup-workflows)
```

## Prerequisites

- GCP project with billing enabled
- A Lidl account with purchase history enabled
- A Signal account for the bot phone number
- GitHub repository with Actions enabled

## Setup

### 1 — GCP infrastructure

```bash
cd infra
cp terraform.tfvars.example terraform.tfvars   # fill in project_id, region, ssh key
terraform init
terraform apply
```

This creates the VM, persistent disk, firewall rules, and a Workload Identity pool for GitHub Actions OIDC.

### 2 — GitHub secrets

| Secret | Value |
|---|---|
| `GCP_PROJECT_ID` | your GCP project ID |
| `GCP_WORKLOAD_IDENTITY_PROVIDER` | Workload Identity provider resource name |
| `GCP_SERVICE_ACCOUNT` | service account email |
| `VM_IP` | VM external IP from Terraform output |
| `SSH_PRIVATE_KEY` | private key matching the public key in `terraform.tfvars` |
| `LIDL_EMAIL` | Lidl account email |
| `LIDL_PASSWORD` | Lidl account password |
| `LIDL_COUNTRY` | country code, e.g. `FR`, `DE`, `GB` |
| `N8N_ENCRYPTION_KEY` | random 32-char string for n8n credential encryption |
| `SIGNAL_PHONE_NUMBER` | bot phone number in E.164 format, e.g. `+33612345678` |
| `SIGNAL_GROUP_ID` | Signal group ID (see step 5) |

### 3 — Deploy the app

Push to `main` or trigger the **Deploy App** workflow manually. It clones the repo on the VM, writes `docker/.env`, and runs `docker compose up -d`.

### 4 — Import n8n workflows

```bash
make setup-workflows VM_IP=<ip>
```

Then open the n8n UI to create your owner account:

```bash
make ssh-tunnel VM_IP=<ip>   # forwards :5678 to localhost
# open http://localhost:5678
```

### 5 — Link Signal

```bash
make signal-link VM_IP=<ip>
```

Scan the QR code in Signal → **Settings → Linked Devices → Link New Device**.

### 6 — Get the group ID and add the secret

```bash
ssh -i ~/.ssh/lidl_bot debian@<ip> \
  "curl -s http://localhost:8080/v1/groups/+<number>"
```

Copy the `id` field, add it as the `SIGNAL_GROUP_ID` secret in GitHub, then update the `.env` on the VM and restart:

```bash
ssh -i ~/.ssh/lidl_bot debian@<ip> \
  "echo 'SIGNAL_GROUP_ID=<id>' >> /opt/lidl/docker/.env && \
   cd /opt/lidl/docker && docker compose up -d"
```

### 7 — First receipt sync

```bash
ssh -i ~/.ssh/lidl_bot debian@<ip> \
  "curl -s -X POST http://localhost:8000/update"
```

Watch progress: `docker compose logs -f lidl-api`

## Signal Commands

| Command | Description |
|---|---|
| `/shopping` | Top items from the last 30 days |
| `/shopping --days 14` | Top items from the last N days |

The bot polls for messages every minute, so expect up to a 60-second response delay.

## Country Support

Set `LIDL_COUNTRY` to your ISO country code. Supported: `FR`, `DE`, `AT`, `BE`, `CH`, `ES`, `IT`, `LU`, `NL`, `PL`, `PT`, `CZ`, `SK`, `HU`, `RO`, `HR`, `SI`, `BG`, `RS`, `GB` (→ `lidl.co.uk`).

## Updating

Push changes to `main` — the Deploy App action runs automatically for changes under `docker/` or `scripts/`. Infrastructure changes require `terraform apply`.

## `lidl_receipts.py` CLI

The receipt fetcher also works standalone:

```bash
python3 scripts/lidl_receipts.py auth-check --login --auth-interactive
python3 scripts/lidl_receipts.py update --login --country FR
python3 scripts/lidl_receipts.py query --days 30 --include-articles
```

Run `python3 scripts/lidl_receipts.py --help` for all options.

## Disclaimer

Unofficial project. Not affiliated with or endorsed by Lidl.
