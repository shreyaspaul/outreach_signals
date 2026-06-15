# Cloud Deployment Specification: Cold Outreach Enrichment System

## Executive Summary

This specification outlines the cheapest, simplest, and most reliable approach to deploy the cold outreach enrichment system to the cloud with Slack integration. The recommended solution balances minimal cost (~$5-10/month), ease of use, and reliability for processing 100-500 companies in 30-60 minute batches.

**Recommended Architecture:** Railway.app or Render.com with background workers + Slack Bot (Bolt SDK)

---

## 1. Overview

### Business Requirements
1. **Cost Optimization**: Minimize monthly cloud spend
2. **Simplicity**: Easy to trigger and monitor
3. **Off-Machine**: Free up local development machine
4. **Slack Integration**: Trigger jobs via Slack commands + receive progress updates
5. **Reliability**: Handle long-running jobs (30-90 minutes) without interruption

### System Characteristics
- **Language**: Python 3.x
- **Dependencies**: Playwright (Chromium browser), pandas, requests, google-generativeai
- **Processing Time**: 5-30 seconds per website
- **Typical Workload**: 100-500 companies per batch
- **Runtime**: 30-90 minutes per batch
- **API Calls**: Google PageSpeed, Gemini Vision/Text, Jina AI, optionally SimilarWeb/Apify
- **File I/O**: Input CSV (~100 KB), output CSV (~500 KB), screenshots (~500 KB each), logs (~1 MB)
- **Project Size**: ~695 MB (including screenshots)

---

## 2. Cloud Platform Comparison

### Summary Table

| Platform | Can Run Playwright? | Max Runtime | Est. Monthly Cost | Ease of Setup | Verdict |
|----------|-------------------|-------------|------------------|---------------|---------|
| **Railway.app** | ✅ Yes (Docker) | Unlimited | ~$5-10 | ⭐⭐⭐⭐⭐ Excellent | ✅ **RECOMMENDED** |
| **Render.com** | ✅ Yes (Docker) | Unlimited | ~$7-14 | ⭐⭐⭐⭐⭐ Excellent | ✅ **RECOMMENDED** |
| **Fly.io** | ✅ Yes (Docker) | Unlimited | ~$3-5 | ⭐⭐⭐⭐ Good | ✅ Good Alternative |
| **Modal.com** | ✅ Yes | Unlimited | ~$0-30 free tier | ⭐⭐⭐⭐ Good | ✅ Good Alternative |
| **Hetzner Cloud** | ✅ Yes (VPS) | Unlimited | €3.49-6/month | ⭐⭐⭐ Medium | ✅ Cheapest VPS |
| **DigitalOcean** | ✅ Yes (Droplet) | Unlimited | $6-12/month | ⭐⭐⭐ Medium | ⚠️ More expensive |
| **AWS Lambda** | ⚠️ Complex | 15 min max | ~$1-5 | ⭐ Poor | ❌ Runtime too short |
| **AWS Fargate** | ✅ Yes | Unlimited | ~$15-30/month | ⭐⭐ Poor | ❌ Too expensive |
| **Google Cloud Run** | ✅ Yes | Up to 7 days | ~$5-15 | ⭐⭐⭐ Medium | ⚠️ Complex config |
| **AWS EC2 Spot** | ✅ Yes | Unlimited | ~$3-8/month | ⭐⭐ Poor | ⚠️ Can be interrupted |

### Detailed Evaluation

#### ✅ **Railway.app** (RECOMMENDED #1)

**Why It's Best:**
- **Pricing**: Hobby plan at $5/month + usage-based ($20/vCPU, $10/GB RAM)
- **Estimated Cost**: $5-10/month for 2-4 hours of monthly compute
- **Playwright Support**: Native Docker support with Microsoft's Playwright images
- **Deployment**: Git push to deploy, zero-config Docker deployment
- **Runtime**: Unlimited execution time for background workers
- **Ease**: Exceptionally simple - connect GitHub, Railway auto-deploys
- **Slack Integration**: Can expose webhooks for Slack triggers
- **File Storage**: Persistent volumes available ($0.25/GB/month)

**Pros:**
- Simple GitHub integration
- Excellent developer experience
- No complex configuration
- Built-in observability and logs
- Credit card required but very affordable

**Cons:**
- Paid service (no free tier)
- Less mature than AWS/GCP

**Sources:**
- [Railway vs Render comparison](https://northflank.com/blog/railway-vs-render)
- [Affordable Cloud in 2025](https://medium.com/@firat-gulec/affordable-cloud-in-2025-4082c00446e0)

---

#### ✅ **Render.com** (RECOMMENDED #2)

**Why It's Great:**
- **Pricing**: Background workers start at $7/month (512MB RAM, 0.5 CPU)
- **Estimated Cost**: $7-14/month depending on resource usage
- **Playwright Support**: Native Docker support
- **Deployment**: Git push to deploy, automatic deployments
- **Runtime**: Unlimited execution time
- **Ease**: Very simple - connect repo, configure env vars, deploy
- **Slack Integration**: Can expose webhooks
- **File Storage**: Persistent disks available

**Pros:**
- Excellent documentation
- Transparent pricing
- Prorated to the second (only pay when running)
- Built-in health checks and auto-restart
- More mature platform than Railway

**Cons:**
- Background workers not available on free plan
- Slightly more expensive than Railway

**Sources:**
- [Render Background Workers](https://render.com/docs/background-workers)
- [Render Pricing](https://render.com/pricing)

---

#### ⚠️ **Fly.io** (Good Alternative)

**Why Consider:**
- **Pricing**: Pay-as-you-go, ~$3-5/month for light usage
- **Estimated Cost**: ~$3-5/month (soft free tier for <$5 usage)
- **Playwright Support**: Docker containers supported
- **Runtime**: Unlimited

**Pros:**
- Cheapest option potentially
- Good global edge network
- Per-second billing

**Cons:**
- More complex setup than Railway/Render
- Background jobs require manual configuration
- Less intuitive developer experience
- $2/month fee for dedicated IPv4

**Sources:**
- [Fly.io pricing](https://fly.io/pricing/)
- [What Is Fly.io? Complete Guide](https://kuberns.com/blogs/post/what-is-flyio/)

---

#### ⚠️ **Modal.com** (Good Alternative - Python-Native)

**Why Consider:**
- **Pricing**: $30/month free compute credits
- **Estimated Cost**: $0-30/month (likely free for this workload)
- **Playwright Support**: Yes, with custom setup
- **Runtime**: Unlimited
- **Python-Native**: Built specifically for Python workloads

**Pros:**
- Free tier very generous
- Python-first design
- Fast cold starts (<1 second)
- Scale to zero (no idle costs)
- Perfect for AI/ML workloads

**Cons:**
- Less straightforward than Railway/Render for non-ML use cases
- Newer platform, less community support
- Requires Modal-specific code changes

**Sources:**
- [Modal Pricing](https://modal.com/pricing)
- [What is Modal AI?](https://www.eesel.ai/blog/modal-ai)

---

#### ⚠️ **Hetzner Cloud** (Cheapest VPS)

**Why Consider:**
- **Pricing**: €3.49/month (CX11: 1 vCPU, 2GB RAM) or €6/month (CPX11: 2 vCPU, 2GB RAM)
- **Estimated Cost**: €6-7/month (~$6-8 USD)
- **Always-On**: VM runs 24/7
- **Full Control**: Root access, install anything

**Pros:**
- Absolute cheapest for always-on compute
- Full Linux VPS with root access
- Excellent performance for price
- Based in Germany/Finland (GDPR-friendly)

**Cons:**
- Always-on means you pay even when idle
- More manual setup (SSH, systemd services, etc.)
- No auto-deployment from Git
- Need to manage security updates yourself
- Limited US data centers

**Sources:**
- [Hetzner vs DigitalOcean comparison](https://www.vpsbenchmarks.com/compare/docean_vs_hetzner)
- [Hetzner Cloud Review 2026](https://www.bitdoze.com/hetzner-cloud-review/)

---

#### ❌ **AWS Lambda** (Not Recommended)

**Why Not:**
- **Max Runtime**: 15 minutes - far too short for 30-90 minute jobs
- **Complexity**: Playwright setup very complex, requires custom layers
- **Cold Starts**: Can be slow for large containers

**Could Work For:**
- Triggering the job (webhook receiver)
- NOT for running the actual enrichment

**Sources:**
- [AWS Lambda quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
- [How to run Playwright in AWS Lambda](https://www.cloudtechsimplified.com/playwright-aws-lambda-python/)

---

#### ❌ **AWS Fargate** (Too Expensive)

**Why Not:**
- **Cost**: ~$15-30/month for minimal specs
- **Complexity**: Requires ECR, task definitions, VPC configuration
- **Overkill**: Enterprise-grade for a simple batch job

**Sources:**
- Not included in search results, but general AWS knowledge

---

#### ⚠️ **Google Cloud Run** (Medium Complexity)

**Why Consider:**
- **Pricing**: ~$5-15/month for sporadic usage
- **Runtime**: Up to 168 hours (7 days) for Cloud Run jobs
- **Playwright Support**: Yes, with Docker

**Pros:**
- Generous free tier
- Good for Python + Docker
- Scales to zero

**Cons:**
- More complex setup than Railway/Render
- Requires GCP account and billing setup
- Less intuitive for background jobs

**Sources:**
- [Cloud Run quotas](https://docs.cloud.google.com/run/quotas)
- [Running Playwright on Cloud Run](https://medium.com/@pawarvaibhav.vppv/running-playwright-tests-in-python-with-flask-on-cloud-run-380c428bebf0)

---

## 3. Recommended Architecture

### Primary Recommendation: Railway.app + Slack Bot

```
┌─────────────────────────────────────────────────────────────┐
│                         SLACK                               │
│  User: /enrich crunchbase.csv                               │
│  Bot: "Processing 250 companies... 0/250"                   │
└───────────────────┬─────────────────────────────────────────┘
                    │
                    │ Slack Events API (via Bolt SDK)
                    │
┌───────────────────▼─────────────────────────────────────────┐
│                  RAILWAY.APP                                │
│                                                             │
│  ┌─────────────────────────────────────────────────┐       │
│  │  Slack Bot Service (always-on)                  │       │
│  │  - Receives slash commands                      │       │
│  │  - Triggers enrichment jobs                     │       │
│  │  - Sends progress updates every 50 entries      │       │
│  │  - Python + Bolt SDK                            │       │
│  └──────────────────┬──────────────────────────────┘       │
│                     │                                       │
│                     │ Spawns subprocess/async task          │
│                     │                                       │
│  ┌──────────────────▼──────────────────────────────┐       │
│  │  Enrichment Worker (on-demand)                  │       │
│  │  - orchestrator.py                              │       │
│  │  - Playwright + Chromium (headless)             │       │
│  │  - Processes CSV row by row                     │       │
│  │  - Saves progress every 5 entries               │       │
│  │  - Reports to Slack every 50 entries            │       │
│  └──────────────────┬──────────────────────────────┘       │
│                     │                                       │
│  ┌──────────────────▼──────────────────────────────┐       │
│  │  Persistent Volume Storage                      │       │
│  │  - Input CSVs                                   │       │
│  │  - Output CSVs (data/)                          │       │
│  │  - Screenshots (screenshots/)                   │       │
│  │  - Logs (logs/)                                 │       │
│  └─────────────────────────────────────────────────┘       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
                    │
                    │ API Calls
                    │
┌───────────────────▼─────────────────────────────────────────┐
│  EXTERNAL APIs                                              │
│  - Google PageSpeed API                                     │
│  - Google Gemini API (Vision + Text)                        │
│  - Jina AI Reader API                                       │
│  - Apify/SimilarWeb (optional)                              │
└─────────────────────────────────────────────────────────────┘
```

### Architecture Components

#### 1. Slack Bot Service (Always-On)
- **Framework**: Python + Slack Bolt SDK
- **Purpose**: Receive Slack commands and trigger enrichment jobs
- **Resource**: Small container (256-512 MB RAM, 0.5 CPU)
- **Cost**: ~$5-7/month base cost (always-on)

**Key Features:**
- Listens for slash commands (e.g., `/enrich crunchbase.csv`)
- Validates input
- Spawns enrichment worker as subprocess or async task
- Sends Slack messages for progress updates
- Handles errors and timeouts

#### 2. Enrichment Worker (On-Demand)
- **Framework**: Existing Python scripts (orchestrator.py)
- **Purpose**: Process CSV and enrich company data
- **Resource**: Medium container (1-2 GB RAM, 1 CPU)
- **Cost**: ~$0-3/month additional (only runs when triggered, 2-4 hours/month)

**Key Features:**
- Runs orchestrator.py with input CSV
- Saves progress every 5 entries (existing feature)
- Reports to Slack every 50 entries (NEW)
- Handles resume on crash (existing feature)
- Stores output to persistent volume

#### 3. Persistent Storage
- **Purpose**: Store CSVs, screenshots, logs
- **Size**: ~5-10 GB
- **Cost**: ~$1-2.5/month on Railway ($0.25/GB/month)

#### 4. Slack Integration
- **Method**: Slack Bolt SDK (official Python framework)
- **Authentication**: Bot token + OAuth
- **Events**: Slash commands, message posting

---

## 4. Slack Integration Design

### Slack Bot Setup

**Option 1: Slack Bolt SDK (RECOMMENDED)**

The Bolt SDK is the official Slack framework for Python, handling token rotation, rate limiting, and providing a clean API.

**Advantages:**
- Official Slack framework
- Handles OAuth, token refresh automatically
- Built-in rate limit handling
- Easy slash command registration
- Interactive components support (buttons, modals)

**Disadvantages:**
- Slightly more complex than webhooks
- Requires always-on service to receive events

**Implementation:**

```python
# bot.py - Slack Bot Service
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import os
import subprocess
import threading

app = App(token=os.environ.get("SLACK_BOT_TOKEN"))

# Global state for tracking active jobs
active_jobs = {}

@app.command("/enrich")
def handle_enrich_command(ack, command, client):
    """Handle /enrich slash command"""
    ack()  # Acknowledge command immediately

    user_id = command['user_id']
    channel_id = command['channel_id']
    csv_file = command['text'].strip()  # e.g., "crunchbase.csv"

    # Validate input
    if not csv_file.endswith('.csv'):
        client.chat_postMessage(
            channel=channel_id,
            text=f"❌ Invalid file. Please specify a CSV file (e.g., `/enrich crunchbase.csv`)"
        )
        return

    # Check if CSV exists in storage
    csv_path = f"/app/data/{csv_file}"
    if not os.path.exists(csv_path):
        client.chat_postMessage(
            channel=channel_id,
            text=f"❌ File `{csv_file}` not found. Upload it to `/app/data/` first."
        )
        return

    # Check if job already running
    if csv_file in active_jobs:
        client.chat_postMessage(
            channel=channel_id,
            text=f"⚠️ Job for `{csv_file}` is already running. Wait for completion."
        )
        return

    # Send initial message
    response = client.chat_postMessage(
        channel=channel_id,
        text=f"🚀 Starting enrichment for `{csv_file}`...\n_Processing: 0/?_"
    )
    message_ts = response['ts']

    # Run enrichment in background thread
    job_thread = threading.Thread(
        target=run_enrichment_job,
        args=(csv_path, channel_id, message_ts, client, csv_file)
    )
    job_thread.daemon = True
    job_thread.start()

    active_jobs[csv_file] = {
        'thread': job_thread,
        'channel': channel_id,
        'message_ts': message_ts
    }


def run_enrichment_job(csv_path, channel_id, message_ts, client, csv_file):
    """Run orchestrator.py and update Slack progress"""
    try:
        # Start subprocess with orchestrator.py
        process = subprocess.Popen(
            [
                'python', '/app/scripts/orchestrator.py',
                csv_path,
                '--resume'  # Auto-resume if previous run exists
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1
        )

        total_entries = None
        current_entry = 0

        # Parse output for progress updates
        for line in process.stdout:
            # Look for pattern: "[X/Y]" in orchestrator output
            if '[' in line and '/' in line and ']' in line:
                try:
                    # Extract [X/Y]
                    progress_part = line[line.index('[')+1:line.index(']')]
                    current, total = progress_part.split('/')
                    current_entry = int(current)
                    total_entries = int(total)

                    # Update Slack every 50 entries or at completion
                    if current_entry % 50 == 0 or current_entry == total_entries:
                        percentage = (current_entry / total_entries) * 100
                        client.chat_update(
                            channel=channel_id,
                            ts=message_ts,
                            text=f"🔄 Enriching `{csv_file}`...\n"
                                 f"Progress: {current_entry}/{total_entries} ({percentage:.1f}%)\n"
                                 f"{'▓' * int(percentage/5)}{'░' * (20-int(percentage/5))}"
                        )
                except (ValueError, IndexError):
                    pass  # Skip malformed lines

        # Wait for completion
        returncode = process.wait()

        if returncode == 0:
            # Success
            output_file = f"enriched_{csv_file}"
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=f"✅ Enrichment complete!\n"
                     f"Processed: {total_entries} companies\n"
                     f"Output: `data/{output_file}`\n"
                     f"Download from persistent storage."
            )
        else:
            # Error
            stderr = process.stderr.read()
            client.chat_update(
                channel=channel_id,
                ts=message_ts,
                text=f"❌ Enrichment failed!\n"
                     f"Error: {stderr[:500]}"
            )

    except Exception as e:
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f"❌ Unexpected error: {str(e)}"
        )

    finally:
        # Remove from active jobs
        if csv_file in active_jobs:
            del active_jobs[csv_file]


@app.command("/status")
def handle_status_command(ack, command, client):
    """Check status of running jobs"""
    ack()

    channel_id = command['channel_id']

    if not active_jobs:
        client.chat_postMessage(
            channel=channel_id,
            text="ℹ️ No active enrichment jobs."
        )
    else:
        status_text = "📊 **Active Jobs:**\n"
        for csv_file, job_info in active_jobs.items():
            status_text += f"- `{csv_file}` (running)\n"

        client.chat_postMessage(
            channel=channel_id,
            text=status_text
        )


if __name__ == "__main__":
    # Use Socket Mode for easier deployment (no webhooks needed)
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
```

**Slack App Configuration:**
1. Create new Slack app at api.slack.com/apps
2. Enable Socket Mode (easier than webhooks, no public URL needed)
3. Add Bot Token Scopes: `chat:write`, `commands`
4. Create slash commands: `/enrich`, `/status`
5. Install app to workspace
6. Copy tokens to Railway environment variables

---

**Option 2: Incoming Webhooks (Simpler, One-Way Only)**

Webhooks are simpler but only support sending messages TO Slack, not receiving commands FROM Slack.

**Use Case:**
- If you trigger jobs manually (SSH, cron, external API)
- Just want progress notifications sent to Slack
- Don't need interactive commands

**Implementation:**

```python
# webhook_notifier.py
import requests

def send_slack_update(webhook_url, message):
    """Send update to Slack via webhook"""
    requests.post(webhook_url, json={'text': message})

# In orchestrator.py, add:
SLACK_WEBHOOK_URL = os.getenv('SLACK_WEBHOOK_URL')

# After processing every 50 entries:
if (idx + 1) % 50 == 0 and SLACK_WEBHOOK_URL:
    send_slack_update(
        SLACK_WEBHOOK_URL,
        f"🔄 Progress: {idx + 1}/{total} companies processed ({(idx+1)/total*100:.1f}%)"
    )
```

**Recommendation:** Use Bolt SDK (Option 1) for full bidirectional communication.

**Sources:**
- [Slack Bolt Python SDK](https://github.com/slackapi/bolt-python)
- [Building an app with Bolt](https://api.slack.com/start/building/bolt-python)
- [Slack Incoming Webhooks](https://johal.in/slack-incoming-webhooks-python-blocks-messages-2026/)

---

## 5. Implementation Specification

### Phase 1: Local Dockerization

Before deploying to Railway, we need to containerize the application.

**1.1 Create Dockerfile**

```dockerfile
# Dockerfile
FROM mcr.microsoft.com/playwright/python:v1.40.0-jammy

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Slack Bolt SDK
RUN pip install slack-bolt

# Copy application code
COPY scripts/ ./scripts/
COPY .env .env

# Create directories for data persistence
RUN mkdir -p /app/data /app/screenshots /app/logs

# Install Playwright browsers
RUN playwright install chromium

# Run Slack bot
CMD ["python", "scripts/bot.py"]
```

**1.2 Update requirements.txt**

```txt
pandas
requests
python-dotenv
apify-client
playwright
google-generativeai
cloudscraper
beautifulsoup4
slack-bolt
```

**1.3 Create .dockerignore**

```
.git
.env
__pycache__
*.pyc
data/*
screenshots/*
logs/*
venv/
.vscode/
```

**1.4 Test Locally**

```bash
# Build Docker image
docker build -t outreach-enrichment .

# Run locally with environment variables
docker run --rm \
  -e SLACK_BOT_TOKEN=xoxb-your-token \
  -e SLACK_APP_TOKEN=xapp-your-token \
  -e GEMINI_API_KEY=your-key \
  -e PAGESPEED_API_KEY=your-key \
  -e JINA_API_KEY=your-key \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/screenshots:/app/screenshots \
  -v $(pwd)/logs:/app/logs \
  outreach-enrichment
```

---

### Phase 2: Railway Deployment

**2.1 Create Railway Project**

1. Sign up at railway.app
2. Create new project
3. Connect GitHub repository
4. Railway auto-detects Dockerfile and deploys

**2.2 Configure Environment Variables**

In Railway dashboard, add:

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_APP_TOKEN=xapp-...
GEMINI_API_KEY=...
PAGESPEED_API_KEY=...
JINA_API_KEY=...
APIFY_TOKEN=... (optional)
```

**2.3 Add Persistent Volume**

1. In Railway dashboard, go to project settings
2. Add volume mount: `/app/data` → 5 GB
3. Add volume mount: `/app/screenshots` → 5 GB
4. Add volume mount: `/app/logs` → 1 GB

**2.4 Configure Resources**

- Memory: 2 GB (for Playwright + Chrome)
- CPU: 1 vCPU
- Auto-restart: Enabled

**2.5 Deploy**

```bash
# Push to GitHub - Railway auto-deploys
git add .
git commit -m "Add Railway deployment config"
git push origin main
```

---

### Phase 3: Slack App Setup

**3.1 Create Slack App**

1. Go to api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. Name: "Outreach Enrichment Bot"
4. Select workspace

**3.2 Enable Socket Mode**

1. Settings → Socket Mode → Enable
2. Generate App-Level Token with `connections:write` scope
3. Copy token → Save as `SLACK_APP_TOKEN` in Railway

**3.3 Add Bot Scopes**

1. OAuth & Permissions → Bot Token Scopes
2. Add scopes:
   - `chat:write` (post messages)
   - `commands` (slash commands)
   - `files:write` (optional, for uploading result CSVs)

**3.4 Create Slash Commands**

1. Slash Commands → Create New Command
2. Command: `/enrich`
   - Description: "Start CSV enrichment job"
   - Usage Hint: "crunchbase.csv"
3. Command: `/status`
   - Description: "Check enrichment job status"

**3.5 Install to Workspace**

1. OAuth & Permissions → Install to Workspace
2. Authorize
3. Copy Bot Token → Save as `SLACK_BOT_TOKEN` in Railway

**3.6 Test**

In Slack:
```
/enrich crunchbase.csv
```

Bot should respond:
```
🚀 Starting enrichment for crunchbase.csv...
Processing: 0/?
```

---

### Phase 4: Orchestrator Modifications

The current `orchestrator.py` already has progress tracking (saves every 5 entries, prints `[X/Y]` format). We just need to ensure the output is captured by the bot.

**Optional Enhancement: Add explicit Slack callback**

```python
# In orchestrator.py, add optional Slack notification callback

def run_enrichment(input_path, output_path=None, limit=None, delay=1.5,
                   skip_traffic=False, skip_grader=False, auto_resume=False,
                   slack_callback=None):  # NEW
    """
    Args:
        slack_callback: Optional function(current, total, message) for Slack updates
    """

    # ... existing code ...

    # Inside the processing loop:
    for idx, row in df.iterrows():
        # ... process entry ...

        # Report progress to Slack every 50 entries
        if slack_callback and (idx + 1) % 50 == 0:
            slack_callback(idx + 1, total, f"Processed {company} - {url}")
```

Then in `bot.py`, pass a callback:

```python
def slack_callback(current, total, message):
    percentage = (current / total) * 100
    client.chat_update(
        channel=channel_id,
        ts=message_ts,
        text=f"🔄 Enriching `{csv_file}`...\n"
             f"Progress: {current}/{total} ({percentage:.1f}%)\n"
             f"Latest: {message}"
    )

# Run with callback
from scripts.orchestrator import run_enrichment
run_enrichment(
    csv_path,
    auto_resume=True,
    slack_callback=slack_callback
)
```

---

## 6. Cost Breakdown

### Railway.app Costs (Recommended)

**Monthly Estimate: $8-12**

| Resource | Specification | Usage | Cost |
|----------|--------------|-------|------|
| Slack Bot Service | 512 MB RAM, 0.5 CPU | Always-on (720 hours/month) | ~$5 base |
| Enrichment Worker | 2 GB RAM, 1 CPU | 4 hours/month (8 runs @ 30 min) | ~$2-3 |
| Persistent Storage | 10 GB | Data + screenshots + logs | ~$2.50 |
| Outbound Bandwidth | ~1 GB/month | API calls, screenshots | ~$0.50 |
| **TOTAL** | | | **~$10-11/month** |

**Breakdown:**
- Base plan: $5/month (Hobby)
- Additional compute: ~$2-3 (4 hours @ $20/vCPU/month = 4/720 * $20 ≈ $1.11 per vCPU)
- Storage: 10 GB @ $0.25/GB = $2.50
- Bandwidth: Usually included

**Cost Scaling:**
- Process 2x more (8 hours/month): +$2 → ~$12-13/month
- Process 4x more (16 hours/month): +$4 → ~$14-15/month

---

### Render.com Costs (Alternative)

**Monthly Estimate: $9-14**

| Resource | Specification | Cost |
|----------|--------------|------|
| Background Worker | 512 MB RAM, 0.5 CPU | $7/month base |
| Additional compute | 4 hours @ 2 GB, 1 CPU | ~$2-3 prorated |
| Persistent Disk | 10 GB | ~$1/GB = $10 (more expensive) |
| **TOTAL** | | **~$19-20/month** |

**Note:** Render's disk pricing is higher ($1/GB vs Railway's $0.25/GB), making it ~$8 more expensive for storage-heavy workloads.

---

### Fly.io Costs (Budget Alternative)

**Monthly Estimate: $5-8**

| Resource | Specification | Cost |
|----------|--------------|------|
| Shared CPU | 1 vCPU, 256 MB RAM (bot) | ~$2-3/month |
| On-demand worker | 2 GB RAM during jobs | ~$2-3/month |
| Persistent volume | 10 GB | $0.15/GB = $1.50 |
| IPv4 address | Dedicated IP | $2/month |
| **TOTAL** | | **~$7-9/month** |

**Cheaper than Railway but:**
- More complex setup
- Less intuitive dashboard
- Manual background job configuration

---

### Hetzner Cloud Costs (Cheapest VPS)

**Monthly Estimate: €6-7 (~$6.50-7.50 USD)**

| Resource | Specification | Cost |
|----------|--------------|------|
| CPX11 VPS | 2 vCPU, 2 GB RAM, 40 GB SSD | €4.51/month |
| Backups | Optional | €1.13/month |
| **TOTAL** | | **€5.64-6.77/month** |

**Cheapest option but:**
- Always-on (pays even when idle)
- Manual setup (SSH, systemd, nginx, etc.)
- No auto-deploy from Git
- Need to manage OS updates, security
- Manual Slack integration setup

---

### Modal.com Costs (Python-Native Serverless)

**Monthly Estimate: $0-5**

| Resource | Usage | Cost |
|----------|-------|------|
| Compute | 4 hours/month @ 2 GB RAM, 1 CPU | ~$0-5 (free tier covers this) |
| Storage | 10 GB | Included in free tier |
| **TOTAL** | | **~$0-5/month (free tier)** |

**Potentially free but:**
- Requires code changes for Modal-specific patterns
- Less straightforward than Railway/Render
- Newer platform

---

## 7. Alternative Architectures

### Alternative 1: Separate Trigger + Worker

**Architecture:**
- **Trigger Service** (always-on): AWS Lambda or Railway micro-service
- **Worker Service** (on-demand): Railway background worker or Modal

**Pros:**
- Cheaper always-on trigger (Lambda free tier or tiny Railway service)
- Scale workers independently

**Cons:**
- More complex
- Need queue/messaging between services (Redis, AWS SQS)

**Cost:** ~$5-8/month (slightly cheaper)

---

### Alternative 2: Cron-Triggered with Manual CSV Upload

**Architecture:**
- Upload CSV to Railway volume via SFTP or Railway CLI
- Cron job checks for new CSVs every 15 minutes
- Processes automatically
- Sends Slack notification when complete

**Pros:**
- No Slack bot needed
- Simpler architecture

**Cons:**
- Less interactive
- No on-demand triggering
- Manual CSV upload

**Cost:** ~$7-9/month (no always-on bot)

---

### Alternative 3: Hybrid - Lambda Trigger + EC2 Spot Worker

**Architecture:**
- AWS Lambda: Receive Slack slash command via webhook
- Lambda starts EC2 Spot instance with enrichment script
- EC2 Spot processes CSV, sends Slack updates
- EC2 shuts down when complete

**Pros:**
- Very cheap compute (Spot instances ~70% cheaper)
- Only pay when processing

**Cons:**
- Complex AWS setup (IAM, Lambda, EC2, CloudWatch)
- Spot instances can be interrupted
- Slower startup (~2-3 minutes for EC2 boot)

**Cost:** ~$2-5/month (cheapest compute, but complex)

---

## 8. Recommended Implementation Steps

### Week 1: Containerization & Local Testing

**Day 1-2: Docker Setup**
- [ ] Create Dockerfile using Playwright base image
- [ ] Update requirements.txt with slack-bolt
- [ ] Create .dockerignore
- [ ] Build and test locally
- [ ] Verify Playwright works in container

**Day 3-4: Slack Bot Development**
- [ ] Create Slack app at api.slack.com
- [ ] Enable Socket Mode
- [ ] Add bot scopes and slash commands
- [ ] Create `scripts/bot.py` with `/enrich` and `/status` commands
- [ ] Test locally with Docker + Slack tokens

**Day 5: Integration Testing**
- [ ] Test end-to-end: Slack → Bot → Orchestrator → Slack
- [ ] Test progress updates every 50 entries
- [ ] Test error handling
- [ ] Test resume functionality

---

### Week 2: Cloud Deployment

**Day 1-2: Railway Setup**
- [ ] Create Railway account
- [ ] Create new project
- [ ] Connect GitHub repository
- [ ] Configure environment variables
- [ ] Add persistent volumes for data/screenshots/logs

**Day 3: Deploy & Test**
- [ ] Push code to GitHub (triggers Railway deploy)
- [ ] Monitor Railway logs for errors
- [ ] Test Slack bot in production
- [ ] Run test enrichment with `--limit 10`

**Day 4-5: Production Testing**
- [ ] Run full enrichment (100+ companies)
- [ ] Monitor memory/CPU usage
- [ ] Verify Slack updates every 50 entries
- [ ] Test resume after manual stop
- [ ] Verify output files saved to volume

---

### Week 3: Optimization & Documentation

**Day 1-2: Cost Optimization**
- [ ] Review Railway usage dashboard
- [ ] Adjust resource limits if needed
- [ ] Consider auto-sleep for bot service (if Railway supports)
- [ ] Optimize Docker image size

**Day 3-4: Monitoring & Alerts**
- [ ] Set up Railway deployment webhooks
- [ ] Add error notifications to Slack
- [ ] Add completion summary to Slack (total grade, counts, etc.)
- [ ] Optional: Add `/results` command to fetch latest CSV

**Day 5: Documentation**
- [ ] Document deployment process
- [ ] Create runbook for common issues
- [ ] Document cost monitoring
- [ ] Create user guide for Slack commands

---

## 9. Data Flow

### Triggering a Job

```
User in Slack
  │
  │ /enrich crunchbase.csv
  │
  ▼
Slack App (api.slack.com)
  │
  │ Event sent to Socket Mode
  │
  ▼
Railway: bot.py (Slack Bolt SDK)
  │
  │ Parse command, validate CSV exists
  │ Send initial Slack message "🚀 Starting..."
  │
  ▼
Spawn subprocess: orchestrator.py
  │
  │ Load CSV from /app/data/crunchbase.csv
  │ Check for existing enriched_*.csv (auto-resume)
  │
  ▼
Process each row:
  │
  ├─ [1/250] company.com
  │   ├─ Tech detection
  │   ├─ PageSpeed
  │   ├─ Traffic
  │   ├─ Screenshot + Gemini grading
  │   └─ Save progress every 5 entries
  │
  ├─ [50/250] → Update Slack "🔄 50/250 (20%)"
  ├─ [100/250] → Update Slack "🔄 100/250 (40%)"
  ├─ [150/250] → Update Slack "🔄 150/250 (60%)"
  ├─ [200/250] → Update Slack "🔄 200/250 (80%)"
  │
  ▼
[250/250] Complete
  │
  │ Save final CSV to /app/data/enriched_20260131_120000.csv
  │ Save screenshots to /app/screenshots/
  │ Save logs to /app/logs/
  │
  ▼
Update Slack "✅ Complete! 250 companies processed"
```

---

## 10. Edge Cases & Error Handling

### Edge Case 1: Job Crashes Mid-Processing

**Scenario:** Railway container restarts, process killed, network error

**Handling:**
- Orchestrator already saves progress every 5 entries
- Use `--resume` flag to auto-resume from last checkpoint
- Slack bot detects process exit code and sends error message

**Implementation:**
```python
# In bot.py
returncode = process.wait()

if returncode != 0:
    # Check for existing enriched_*.csv
    latest_csv = find_latest_enriched_csv()
    if latest_csv:
        progress = get_progress_from_csv(latest_csv)
        client.chat_update(
            channel=channel_id,
            ts=message_ts,
            text=f"⚠️ Job crashed at {progress['current']}/{progress['total']}\n"
                 f"Partial results saved to `{latest_csv}`\n"
                 f"Run `/enrich {csv_file}` to resume."
        )
```

---

### Edge Case 2: Long-Running Job (>2 hours)

**Scenario:** Processing 500 companies takes 3+ hours

**Handling:**
- Railway has no hard timeout for background workers
- Update Slack every 50 entries to show activity
- Consider rate limiting API calls if hitting quotas

**Implementation:**
- Already handled - no action needed
- Monitor Railway logs for API rate limit errors

---

### Edge Case 3: Playwright Hangs on a Website

**Scenario:** Website loads forever, Playwright timeout not set

**Handling:**
- Set timeout in Playwright: `page.goto(url, timeout=30000)` (30 sec)
- Orchestrator already handles per-site errors gracefully

**Implementation:**
```python
# In website_grader.py
async def capture_screenshot_and_content(url, screenshot_dir, semaphore):
    async with semaphore:
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, timeout=30000, wait_until='networkidle')
                # ... rest of capture
        except TimeoutError:
            return {'error': 'Page load timeout (30s)'}
```

---

### Edge Case 4: Slack Rate Limiting

**Scenario:** Sending too many Slack messages too quickly

**Handling:**
- Bolt SDK handles rate limiting automatically
- Reduce update frequency to every 50 entries (not every entry)

**Implementation:**
- Already handled by Bolt SDK
- Max 1 update per 50 entries = ~5-10 updates per job = well within limits

---

### Edge Case 5: Out of Disk Space

**Scenario:** Screenshots fill up 5 GB persistent volume

**Handling:**
- Monitor volume usage in Railway dashboard
- Add cleanup job to delete old screenshots after 30 days
- Increase volume size if needed ($0.25/GB)

**Implementation:**
```python
# Add to bot.py or separate cron job
def cleanup_old_screenshots():
    """Delete screenshots older than 30 days"""
    import time
    cutoff = time.time() - (30 * 24 * 60 * 60)  # 30 days

    for screenshot in Path('/app/screenshots').glob('*.png'):
        if screenshot.stat().st_mtime < cutoff:
            screenshot.unlink()
```

---

### Edge Case 6: API Key Expired or Invalid

**Scenario:** GEMINI_API_KEY becomes invalid mid-job

**Handling:**
- Orchestrator already handles API errors per-website
- Job continues, skips grading for failed sites
- Slack notification includes error count

**Implementation:**
- Already handled in orchestrator.py
- Add to final Slack message:
  ```python
  error_count = sum(1 for r in results if r.get('enrichment_errors'))
  client.chat_update(
      channel=channel_id,
      ts=message_ts,
      text=f"✅ Complete! {total} companies processed\n"
           f"⚠️ Errors: {error_count} sites"
  )
  ```

---

## 11. Monitoring & Observability

### Railway Built-In Monitoring

**Metrics Available:**
- CPU usage (%)
- Memory usage (MB)
- Network I/O
- Deployment logs
- Service uptime

**Alerts:**
- Railway sends email on deployment failure
- No built-in alerts for high memory/CPU

**Recommendation:**
- Monitor Railway dashboard weekly
- Check logs after each enrichment run

---

### Slack-Based Monitoring

**Self-Reporting:**
- Job start notification
- Progress updates every 50 entries
- Completion summary
- Error notifications

**Example Completion Summary:**
```
✅ Enrichment Complete!

📊 Summary:
- Processed: 250 companies
- Errors: 12 sites
- Avg Grade: B+
- WordPress: 85/250 (34%)
- Signal 2 (WP + poor speed + traffic): 23/250 (9%)

📁 Output:
- CSV: data/enriched_20260131_120000.csv
- Screenshots: 250 files
- Logs: logs/ai_requests_20260131_120000.log

⏱ Duration: 42 minutes
```

**Implementation:**
```python
# In bot.py, after enrichment completes
summary = generate_summary(results)
client.chat_postMessage(
    channel=channel_id,
    text=summary
)
```

---

### Optional: External Monitoring

**If needed for production:**
- **Sentry**: Error tracking ($0/month for 5K errors)
- **Datadog**: APM and logs ($0/month for 1 host, 5GB logs)
- **Better Uptime**: Service uptime monitoring (Free tier)

**Recommendation:** Start without external monitoring, add if needed.

---

## 12. Security Considerations

### Secrets Management

**Railway Environment Variables:**
- All API keys stored as Railway environment variables
- Encrypted at rest and in transit
- Never committed to Git

**Best Practices:**
- Rotate API keys quarterly
- Use separate keys for dev/prod if available
- Never log full API keys

---

### Slack Security

**Socket Mode vs Webhooks:**
- **Socket Mode** (recommended): No public URL, more secure
- **Webhooks**: Requires public endpoint, needs request signature verification

**Token Security:**
- Bot tokens (`xoxb-...`) give full access to workspace
- App tokens (`xapp-...`) for Socket Mode connection
- Store in Railway environment variables, never in code

---

### Docker Security

**Base Image:**
- Use official Microsoft Playwright image
- Regularly update to get security patches

**Run as Non-Root:**
```dockerfile
# Add to Dockerfile
RUN groupadd -r appuser && useradd -r -g appuser appuser
USER appuser
```

---

### Network Security

**Railway:**
- Services are private by default
- No public URL needed (Socket Mode)
- Outbound API calls only

**Firewall:**
- Not needed - Railway handles network isolation

---

## 13. Maintenance & Operations

### Routine Maintenance

**Weekly:**
- [ ] Check Railway usage dashboard
- [ ] Review error logs in Slack
- [ ] Monitor API quota usage (Gemini, PageSpeed)

**Monthly:**
- [ ] Review Railway bill
- [ ] Clean up old screenshots (>30 days)
- [ ] Update dependencies (pip, Playwright)

**Quarterly:**
- [ ] Rotate API keys
- [ ] Review and optimize resource allocation
- [ ] Update base Docker image

---

### Backup Strategy

**What to Backup:**
- Input CSVs (store in Git LFS or external storage)
- Output CSVs (download from Railway volume monthly)
- Configuration (.env values documented securely)

**What NOT to Backup:**
- Screenshots (regeneratable)
- Logs (ephemeral, can be purged)

**Implementation:**
```bash
# Download from Railway volume (via Railway CLI)
railway run -- tar -czf backup_$(date +%Y%m%d).tar.gz /app/data/*.csv

# Or add Slack command
@app.command("/backup")
def handle_backup_command(ack, command, client):
    # Create zip of data/*.csv
    # Upload to Slack as file attachment
    client.files_upload(channels=channel_id, file=zip_path)
```

---

### Troubleshooting Guide

**Issue: Slack bot not responding**
- Check Railway logs for errors
- Verify Socket Mode enabled
- Check `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN` set correctly

**Issue: "File not found" when running /enrich**
- CSV must be uploaded to Railway volume first
- Use Railway CLI: `railway run -- cp local.csv /app/data/`

**Issue: Playwright crashes with memory error**
- Increase Railway memory allocation to 2 GB
- Check if multiple jobs running simultaneously

**Issue: API rate limit errors**
- Increase delay between requests: `--delay 2.0`
- Check Gemini API quota in Google Cloud Console

**Issue: Job hangs indefinitely**
- Set Playwright timeout: `page.goto(url, timeout=30000)`
- Add overall job timeout (subprocess.run with timeout)

---

## 14. Future Enhancements

### Phase 4: CSV Upload via Slack

**Feature:** Upload CSV directly in Slack, no manual file transfer

**Implementation:**
```python
@app.event("file_shared")
def handle_file_shared(event, client):
    file_id = event['file_id']
    file_info = client.files_info(file=file_id)

    if file_info['file']['name'].endswith('.csv'):
        # Download file
        url = file_info['file']['url_private']
        response = requests.get(url, headers={'Authorization': f'Bearer {bot_token}'})

        # Save to volume
        with open(f"/app/data/{file_info['file']['name']}", 'wb') as f:
            f.write(response.content)

        client.chat_postMessage(
            channel=event['channel_id'],
            text=f"✅ Uploaded `{file_info['file']['name']}`\n"
                 f"Run `/enrich {file_info['file']['name']}` to process."
        )
```

---

### Phase 5: Download Results via Slack

**Feature:** Download enriched CSV directly from Slack

**Implementation:**
```python
@app.command("/download")
def handle_download_command(ack, command, client):
    ack()

    csv_file = command['text'].strip()
    csv_path = f"/app/data/{csv_file}"

    if os.path.exists(csv_path):
        client.files_upload(
            channels=command['channel_id'],
            file=csv_path,
            title=csv_file,
            initial_comment=f"📥 Here's your enriched CSV: `{csv_file}`"
        )
    else:
        client.chat_postMessage(
            channel=command['channel_id'],
            text=f"❌ File `{csv_file}` not found."
        )
```

---

### Phase 6: Scheduled Enrichment

**Feature:** Run enrichment on a schedule (e.g., every Monday at 9 AM)

**Implementation:**
```python
# Add to bot.py
import schedule
import threading

def scheduled_enrichment():
    """Run enrichment on crunchbase.csv every Monday at 9 AM"""
    schedule.every().monday.at("09:00").do(
        lambda: trigger_enrichment("crunchbase.csv", SLACK_CHANNEL_ID)
    )

    while True:
        schedule.run_pending()
        time.sleep(60)

# Start scheduler in background thread
scheduler_thread = threading.Thread(target=scheduled_enrichment, daemon=True)
scheduler_thread.start()
```

---

### Phase 7: Multi-User Support

**Feature:** Allow multiple team members to trigger jobs independently

**Implementation:**
- Track jobs per user: `active_jobs[user_id][csv_file]`
- Queue system: Process one job at a time, queue others
- Use Redis or Railway Postgres for job queue

---

### Phase 8: Real-Time Dashboard

**Feature:** Web dashboard showing live progress, stats, history

**Implementation:**
- Add Flask/FastAPI web server to Docker container
- Serve dashboard at Railway public URL
- WebSocket for live updates
- Show: active jobs, completion history, cost tracking

**Cost:** +$0 (same Railway service)

---

## 15. Conclusion

### Recommended Solution: Railway.app + Slack Bot

**Why This Works:**
1. **Cheap**: ~$10-12/month for typical usage
2. **Simple**: Git push to deploy, zero config
3. **Reliable**: No runtime limits, auto-restart, persistent storage
4. **Interactive**: Slack commands + progress updates
5. **Scalable**: Easy to increase resources if needed

### Getting Started

**Immediate Next Steps:**
1. Create Slack app (15 minutes)
2. Containerize application (2 hours)
3. Deploy to Railway (30 minutes)
4. Test end-to-end (1 hour)

**Total Setup Time:** ~4-5 hours

**Time to First Enrichment:** Same day

---

## 16. Cost Comparison Summary

| Platform | Monthly Cost | Setup Time | Maintenance | Recommendation |
|----------|-------------|------------|-------------|----------------|
| **Railway.app** | $10-12 | 4 hours | Low | ✅ **BEST CHOICE** |
| **Render.com** | $19-20 | 4 hours | Low | ✅ Good alternative |
| **Fly.io** | $7-9 | 6 hours | Medium | ⚠️ Cheaper but complex |
| **Modal.com** | $0-5 | 6 hours | Medium | ⚠️ Requires code changes |
| **Hetzner Cloud** | $6-8 | 8 hours | High | ⚠️ Cheapest VPS, manual |
| **AWS Lambda + Fargate** | $15-30 | 12 hours | High | ❌ Overengineered |

---

## 17. Sources

### Playwright & Docker Deployment
- [Playwright in AWS Lambda](https://www.cloudtechsimplified.com/playwright-aws-lambda-python/)
- [Running Playwright on Cloud Run](https://medium.com/@pawarvaibhav.vppv/running-playwright-tests-in-python-with-flask-on-cloud-run-380c428bebf0)
- [Playwright AWS Lambda - JupiterOne](https://github.com/JupiterOne/playwright-aws-lambda)
- [Running Playwright in AWS Lambda](https://www.steele.blue/playwright-on-lambda/)

### Cloud Platform Pricing
- [Railway vs Render comparison](https://northflank.com/blog/railway-vs-render)
- [Affordable Cloud in 2025](https://medium.com/@firat-gulec/affordable-cloud-in-2025-4082c00446e0)
- [Render Pricing](https://render.com/pricing)
- [Fly.io Pricing](https://fly.io/pricing/)
- [Modal Pricing](https://modal.com/pricing)
- [Hetzner vs DigitalOcean comparison](https://www.vpsbenchmarks.com/compare/docean_vs_hetzner)
- [AWS EC2 Spot Pricing](https://aws.amazon.com/ec2/spot/pricing/)
- [Google Cloud Run Quotas](https://docs.cloud.google.com/run/quotas)

### Slack Integration
- [Slack Bolt Python SDK](https://github.com/slackapi/bolt-python)
- [Building an app with Bolt](https://api.slack.com/start/building/bolt-python)
- [Slack Incoming Webhooks](https://johal.in/slack-incoming-webhooks-python-blocks-messages-2026/)
- [Slack Progress Bar](https://github.com/mlizzi/slack-progress-bar)
- [Run Python Scripts as Slack Commands](https://medium.com/@yogeshingale94/run-your-python-scripts-as-slack-commands-chatops-63bc334b74cd)

### AWS & Cloud Limits
- [AWS Lambda Quotas](https://docs.aws.amazon.com/lambda/latest/dg/gettingstarted-limits.html)
- [Lambda Container Images](https://docs.aws.amazon.com/prescriptive-guidance/latest/patterns/deploy-lambda-functions-with-container-images.html)
- [Overcoming Lambda 15min Timeout](https://medium.com/@igormardari_71620/how-i-overcome-the-lambda-15-mins-timeout-by-leveraging-the-ecs-fargate-95750618969d)

---

## Appendix A: Sample Railway Configuration

### railway.toml

```toml
[build]
builder = "DOCKERFILE"
dockerfilePath = "Dockerfile"

[deploy]
startCommand = "python scripts/bot.py"
restartPolicyType = "ON_FAILURE"
restartPolicyMaxRetries = 10

[service]
minReplicas = 1
maxReplicas = 1
```

---

## Appendix B: Sample Environment Variables

```bash
# Slack
SLACK_BOT_TOKEN=<your-slack-bot-token>
SLACK_APP_TOKEN=<your-slack-app-token>

# Google APIs
GEMINI_API_KEY=<your-gemini-api-key>
PAGESPEED_API_KEY=<your-pagespeed-api-key>

# Jina AI
JINA_API_KEY=<your-jina-api-key>

# Apify (optional)
APIFY_TOKEN=apify_api_abc123def456ghi789jkl012mno345pqr678stu901vwx234
```

---

## Appendix C: Slack Message Templates

### Progress Update
```json
{
  "blocks": [
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Enriching `crunchbase.csv`*\n🔄 Processing..."
      }
    },
    {
      "type": "section",
      "fields": [
        {
          "type": "mrkdwn",
          "text": "*Progress:*\n150/250 (60%)"
        },
        {
          "type": "mrkdwn",
          "text": "*Latest:*\nstripe.com"
        }
      ]
    },
    {
      "type": "context",
      "elements": [
        {
          "type": "mrkdwn",
          "text": "▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░"
        }
      ]
    }
  ]
}
```

### Completion Summary
```json
{
  "blocks": [
    {
      "type": "header",
      "text": {
        "type": "plain_text",
        "text": "✅ Enrichment Complete!"
      }
    },
    {
      "type": "section",
      "fields": [
        {
          "type": "mrkdwn",
          "text": "*Processed:*\n250 companies"
        },
        {
          "type": "mrkdwn",
          "text": "*Errors:*\n12 sites"
        },
        {
          "type": "mrkdwn",
          "text": "*Avg Grade:*\nB+"
        },
        {
          "type": "mrkdwn",
          "text": "*Duration:*\n42 minutes"
        }
      ]
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Signal 2 Targets (WP + poor speed + traffic):*\n23/250 (9%)"
      }
    },
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*Output:*\n• CSV: `data/enriched_20260131_120000.csv`\n• Screenshots: 250 files\n• Logs: `logs/ai_requests_20260131_120000.log`"
      }
    },
    {
      "type": "actions",
      "elements": [
        {
          "type": "button",
          "text": {
            "type": "plain_text",
            "text": "Download CSV"
          },
          "value": "enriched_20260131_120000.csv",
          "action_id": "download_csv"
        }
      ]
    }
  ]
}
```

---

**End of Specification**

This deployment plan provides a complete, production-ready solution for moving the cold outreach enrichment system to the cloud with Slack integration, optimized for cost, simplicity, and reliability.
