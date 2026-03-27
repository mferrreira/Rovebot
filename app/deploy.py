import os
import subprocess
import sys
import json
from pathlib import Path

def run_cmd(cmd: str, silent=True) -> str:
    result = subprocess.run(cmd, shell=True, capture_output=silent, text=True)
    if result.returncode != 0 and silent:
        print(f"Error running: {cmd}\n{result.stderr}", file=sys.stderr)
        sys.exit(result.returncode)
    return result.stdout.strip() if silent else ""

def select_account() -> str:
    print("Fetching Google Cloud accounts...")
    output = run_cmd("gcloud auth list --format=json")
    accounts = json.loads(output)
    
    if not accounts:
        print("No gcloud accounts found. Please run 'gcloud auth login' first.")
        sys.exit(1)
        
    print("\n=== Select Google Cloud Account ===")
    for i, acc in enumerate(accounts):
        status = "[ACTIVE]" if acc.get("status") == "ACTIVE" else "        "
        print(f" {i+1}. {status} {acc['account']}")
        
    choice = input("\nSelect account (number) [1]: ").strip()
    idx = int(choice) - 1 if choice.isdigit() else 0
    if 0 <= idx < len(accounts):
        selected = accounts[idx]['account']
        run_cmd(f"gcloud config set account {selected}")
        return selected
    return accounts[0]['account']

def select_project() -> str:
    print("\nFetching Google Cloud projects...")
    output = run_cmd("gcloud projects list --format=json")
    projects = json.loads(output)
    
    print("\n=== Select Google Cloud Project ===")
    for i, p in enumerate(projects):
        print(f" {i+1}. {p['projectId']} ({p['name']})")
    print(f" {len(projects)+1}. Create a NEW project")
    
    choice = input("\nSelect project (number) [1]: ").strip()
    idx = int(choice) - 1 if choice.isdigit() else 0
    
    if idx == len(projects):
        new_project = input("Enter new project ID (e.g., my-awesome-project-123): ").strip()
        if not new_project: sys.exit("Operation cancelled.")
        print(f"Creating project {new_project}...")
        run_cmd(f"gcloud projects create {new_project} --quiet", silent=False)
        print("IMPORTANT: You MUST link a billing account to this new project before proceeding.")
        input("Press Enter once you have linked billing at https://console.cloud.google.com/billing ...")
        selected = new_project
    elif 0 <= idx < len(projects):
        selected = projects[idx]['projectId']
    else:
        selected = projects[0]['projectId']
        
    run_cmd(f"gcloud config set project {selected}")
    return selected

def main():
    print("Rovebot Interactive GCP Deployment")
    print("=" * 40)
    
    if not Path("env.yaml").exists():
        print("Error: env.yaml not found. Please run 'uv run rovebot setup' first.")
        sys.exit(1)
        
    account = select_account()
    print(f"-> Using account: {account}")
    
    project = select_project()
    print(f"-> Using project: {project}")
    
    region = "us-central1"
    
    print("\nEnabling required GCP APIs (this may take a minute)...")
    try:
        run_cmd(f"gcloud services enable run.googleapis.com cloudbuild.googleapis.com cloudscheduler.googleapis.com artifactregistry.googleapis.com storage.googleapis.com --project {project}")
    except SystemExit:
        print("\nFailed to enable APIs. Remember: the project MUST have an active billing account linked!")
        sys.exit(1)
        
    print("\nSetting up persistent Cloud Storage volume...")
    project_num = run_cmd(f"gcloud projects describe {project} --format='value(projectNumber)'")
    bucket_name = f"rovebot-data-{project_num}"
    
    existing_buckets = run_cmd(f"gcloud storage buckets list --project {project} --format='value(name)'")
    if bucket_name not in existing_buckets:
        print(f"Creating bucket gs://{bucket_name} ...")
        run_cmd(f"gcloud storage buckets create gs://{bucket_name} --project {project} --location {region} --quiet", silent=False)
        
    env_overrides = (
        "ROVEBOT_LEARNING_FILE: /app/data/learning.md\n"
        "ROVEBOT_DRAFT_STORE_FILE: /app/data/drafts_store.json\n"
        "ROVEBOT_HISTORY_ID_FILE: /app/data/last_history_id.txt\n"
    )
    # Append the mounted volume overrides directly to the env.yaml file
    with open("env.yaml", "a") as f:
        f.write("\n" + env_overrides)
        
    print("\nDeploying to Cloud Run (Service: rovebot)...")
    deploy_cmd = (
        f"gcloud run deploy rovebot "
        f"--source . --region {region} "
        f"--allow-unauthenticated "
        f"--execution-environment gen2 "
        f"--add-volume=name=gcs-volume,type=cloud-storage,bucket={bucket_name} "
        f"--add-volume-mount=volume=gcs-volume,mount-path=/app/data "
        f"--env-vars-file env.yaml "
        f"--port 8080 "
        f"--project {project} --quiet"
    )
    run_cmd(deploy_cmd, silent=False)
    
    print("\nFetching Cloud Run URL...")
    url = run_cmd(f"gcloud run services describe rovebot --platform managed --region {region} --format 'value(status.url)'")
    
    print("\nSetting up Cloud Scheduler cron ping...")
    # Find the current cron token from env.yaml or default to dev-cron-token
    cron_token = "dev-cron-token"
    if Path("env.yaml").exists():
        for line in Path("env.yaml").read_text().splitlines():
            if line.startswith("ROVEBOT_CRON_TOKEN:"):
                cron_token = line.split(":", 1)[1].strip().strip('"')
                break
                
    cron_uri = f"{url}/webhooks/cron/poll"
    
    # Check if job exists, update if so, else create
    jobs = run_cmd(f"gcloud scheduler jobs list --location={region} --format=json")
    job_exists = any("rovebot-polling" in j.get("name", "") for j in json.loads(jobs if jobs else "[]"))
    
    action = "update" if job_exists else "create"
    headers_flag = "--update-headers" if action == "update" else "--headers"
    
    cron_cmd = (
        f"gcloud scheduler jobs {action} http rovebot-polling "
        f"--schedule=\"*/10 * * * *\" "
        f"--uri=\"{cron_uri}\" "
        f"--http-method=POST "
        f"{headers_flag}=\"Authorization=Bearer {cron_token}\" "
        f"--location={region} "
        f"--project={project} --quiet"
    )
    run_cmd(cron_cmd, silent=False)
    
    print("=" * 40)
    print("Deployment Successful! 🎉")
    print(f"Cloud Run URL: {url}")
    print("Cron Job: rovebot-polling running every 10 minutes")
    
    print("\n=== FINAL SLACK SETUP ===")
    print("If you haven't already, go to your Slack App Dashboard -> 'Interactivity & Shortcuts'")
    print("Toggle Interactivity to ON, and paste this EXACT URL in the 'Request URL' box:")
    print(f"👉  {url}/webhooks/slack/actions  👈")
    print("=" * 40)

if __name__ == "__main__":
    main()
