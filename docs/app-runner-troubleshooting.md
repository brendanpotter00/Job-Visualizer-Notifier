# App Runner Deployment Troubleshooting Log

## Current Status: BLOCKED - Container fails silently on App Runner

**Service ARN:** `arn:aws:apprunner:us-east-1:500140837569:service/job-scraper-api/03d008fe7656409b84bb754ad636e5ea`

---

## Problem Summary

The container starts and works perfectly locally but produces **zero stdout/stderr** on App Runner before failing health checks.

---

## Investigation Timeline

### 2026-01-01 - Image Tag Mismatch (Partially Fixed)

**Finding:** App Runner was configured to use `:minimal` image tag (broken 101MB debug image) but GitHub Actions pushes to `:latest` tag (working 662MB image).

**Action:** Updated App Runner to use `:latest` tag via `aws apprunner update-service`

**Result:** Deployment still failed with same pattern - no application logs, health check failed.

---

### 2026-01-01 - Local Container Test (WORKS)

**Action:** Pulled `:latest` image from ECR and ran locally:
```bash
docker run --rm -p 8080:8080 \
  -e "ConnectionStrings__DefaultConnection=Host=localhost;Port=5432;Database=test;Username=test;Password=test" \
  -e "ASPNETCORE_ENVIRONMENT=Production" \
  500140837569.dkr.ecr.us-east-1.amazonaws.com/job-scraper-api:latest
```

**Result:** Container works perfectly:
```
info: Microsoft.Hosting.Lifetime[14]
      Now listening on: http://[::]:8080
info: Microsoft.Hosting.Lifetime[0]
      Application started. Press Ctrl+C to shut down.
```

**Health check works:** `curl http://localhost:8080/health` returns "OK"

**Conclusion:** The image is NOT corrupted. The issue is specific to App Runner environment.

---

### 2026-01-01 - VPC/Networking Investigation

**Checked:**
1. VPC Connector status: `ACTIVE` ✓
2. Security group outbound rules: Allows all (`0.0.0.0/0`) ✓
3. VPC Endpoints: Only S3 endpoint exists, no Secrets Manager endpoint

**Current network config:**
- Egress: VPC via private connector (`job-scraper-vpc-connector-private`)
- Private subnets route through NAT Gateway
- NAT Gateway IP: `54.89.118.189`

**Hypothesis:** Possible issue with Secrets Manager access through NAT Gateway, or timing issue with secret injection.

---

### 2026-01-01 - IAM/Secrets Verification

**Instance Role:** `AppRunnerInstanceRole` has correct `secretsmanager:GetSecretValue` permission for the secret ARN.

**Secret Format:** ADO.NET format (verified correct):
```
Host=job-scraper-db.csps6uqke28u.us-east-1.rds.amazonaws.com;Port=5432;Database=job-scraper-db;Username=jobscraper_admin;Password=***
```

---

## App Runner Log Analysis

**Events log shows:**
```
[AppRunner] Pulling image... Successfully pulled
[AppRunner] Performing health check on protocol `TCP` [Port: '8080']
[AppRunner] Health check failed on protocol `TCP` [Port: '8080']
```

**Deployment log shows:**
```
[AppRunner] Starting to deploy your application image
[AppRunner] Successfully pulled your application image from ECR
[AppRunner] Failed to deploy your application image
```

**Critical:** No instance log streams exist. The container never produces stdout/stderr.

---

## What We Know

| Aspect | Status |
|--------|--------|
| Image architecture | `linux/amd64` ✓ |
| Image works locally | Yes ✓ |
| ECR pull | Successful ✓ |
| IAM permissions | Correct ✓ |
| Secret format | Correct ✓ |
| VPC Connector | Active ✓ |
| Security group outbound | Allows all ✓ |

---

## Theories to Test

### Theory 1: Private VPC Connector Issue
The private VPC connector uses NAT Gateway. Maybe there's a timing/routing issue.
**Next step:** Switch to public VPC connector to eliminate NAT Gateway as variable.

### Theory 2: Secrets Manager Access
App Runner fetches secrets before starting container. If this fails, container may not start.
**Next step:** Try deploying without the secret (hardcode connection string as env var temporarily).

### Theory 3: Health Check Timing
Container might be slow to start on App Runner (cold start).
**Next step:** Increase health check interval and unhealthy threshold.

### Theory 4: Something in .NET Startup
The .NET app might be doing something at startup that fails silently on App Runner.
**Next step:** Add explicit console output at the very start of Program.cs before any configuration.

---

## GitHub Actions Workflow Issue

The workflow fails with:
```
An error occurred (InvalidRequestException) when calling the StartDeployment operation:
Can't start a deployment on the specified service, because it isn't in RUNNING state
```

**Root cause:** Service is in `CREATE_FAILED` state. `start-deployment` only works on `RUNNING` services.

**Fix needed:** The workflow should use `update-service` instead of `start-deployment` when the service is not in RUNNING state, or the underlying App Runner issue needs to be fixed first.

---

## Commands for Debugging

```bash
# Check service status
aws apprunner describe-service \
  --service-arn "arn:aws:apprunner:us-east-1:500140837569:service/job-scraper-api/03d008fe7656409b84bb754ad636e5ea" \
  --query 'Service.{Status:Status,URL:ServiceUrl}'

# Watch logs
aws logs tail "/aws/apprunner/job-scraper-api/03d008fe7656409b84bb754ad636e5ea/service" --follow

# List recent operations
aws apprunner list-operations \
  --service-arn "arn:aws:apprunner:us-east-1:500140837569:service/job-scraper-api/03d008fe7656409b84bb754ad636e5ea" \
  --max-results 5

# Check VPC connectors
aws apprunner list-vpc-connectors --query 'VpcConnectors[*].{Name:VpcConnectorName,Arn:VpcConnectorArn}'
```

---

## Troubleshooting Session Log (2026-01-01)

### Attempt 1: Switch to `:latest` image tag
**Time:** ~17:00 UTC
**Change:** Updated App Runner service to use `:latest` instead of `:minimal`
```bash
aws apprunner update-service --source-configuration '{"ImageRepository":{"ImageIdentifier":"...job-scraper-api:latest",...}}'
```
**Result:** FAILED - Same health check failure
**Logs:**
```
[AppRunner] Successfully pulled your application image from ECR.
[AppRunner] Performing health check on protocol `TCP` [Port: '8080'].
[AppRunner] Health check failed on protocol `TCP` [Port: '8080'].
```
**Finding:** No application logs produced. Container doesn't emit stdout/stderr before failing.

### Attempt 2: Switch to public VPC connector
**Time:** ~17:10 UTC
**Change:** Changed from private VPC connector (NAT Gateway routing) to public VPC connector (direct IGW)
```bash
aws apprunner update-service --network-configuration '{"EgressConfiguration":{"VpcConnectorArn":"...vpc-connector-public..."}}'
```
**Result:** FAILED - Same pattern, same logs
**Finding:** NAT Gateway is NOT the issue. Public subnets with direct Internet Gateway route also fail.

### Attempt 3: Remove Secrets Manager dependency
**Time:** ~17:15 UTC
**Change:** Replaced secret reference with hardcoded environment variable
```bash
aws apprunner update-service --source-configuration '{
  "RuntimeEnvironmentVariables": {"ConnectionStrings__DefaultConnection": "Host=...;Password=TestPassword123"},
  "RuntimeEnvironmentSecrets": {}
}'
```
**Result:** FAILED - Same pattern
**Finding:** Secrets Manager access is NOT the issue. Container fails even with plain environment variables.

### Local Container Test (Control Test)
**Time:** ~17:05 UTC
**Action:** Pulled `:latest` image from ECR and ran locally on Apple Silicon Mac
```bash
docker pull 500140837569.dkr.ecr.us-east-1.amazonaws.com/job-scraper-api:latest
docker run --rm -p 8080:8080 \
  -e "ConnectionStrings__DefaultConnection=Host=localhost;..." \
  500140837569.dkr.ecr.us-east-1.amazonaws.com/job-scraper-api:latest
```
**Result:** SUCCESS
```
info: Microsoft.Hosting.Lifetime[14]
      Now listening on: http://[::]:8080
info: Microsoft.Hosting.Lifetime[0]
      Application started. Press Ctrl+C to shut down.
```
**Health check:** `curl http://localhost:8080/health` returns "OK"
**Critical Finding:** The `:latest` image WORKS locally via Docker Desktop's Rosetta emulation. This proves the image content is correct.

### Attempt 4: Add shell debugging entrypoint
**Change:** Modified Dockerfile entrypoint to print "CONTAINER STARTING..." before running dotnet:
```dockerfile
ENTRYPOINT ["/bin/sh", "-c", "echo 'CONTAINER STARTING...' && exec dotnet JobsApi.dll"]
```
**Image:** `job-scraper-api:debug` pushed to ECR
**Result:** FAILED - No "CONTAINER STARTING..." appeared in logs! The shell itself isn't running.

**Critical Finding:** The container is failing before even `/bin/sh` can execute `echo`.
This suggests an issue with the container image format/compatibility on App Runner's infrastructure.

### Attempt 5: Debug image built locally with QEMU
**Realization:** The `:debug` image I pushed was built on Apple Silicon Mac with `--platform linux/amd64` which uses QEMU emulation during build. This likely corrupted the binaries just like the original issue.

**Evidence:** The image manifest shows an `unknown/unknown` platform entry, which is a sign of QEMU-built images.

**The `:latest` image built by GitHub Actions is the only properly built image.**

### Attempt 6: Re-deploy `:latest` with Secrets Manager
**Time:** ~17:45 UTC
**Action:** Reverted to original configuration (`:latest` image + Secrets Manager)
**Result:** FAILED - Same pattern
**Logs:**
```
[AppRunner] Successfully pulled your application image from ECR.
[AppRunner] Failed to deploy your application image.
```

**Note:** The `:latest` manifest looks normal (single platform, no `unknown/unknown`), unlike the QEMU-built `:debug` image. But it still fails.

### Current Theory: Service is in corrupted state
After multiple failed deployments with broken images, the App Runner service itself may be in a bad state.
**Recommended next step:** Delete and recreate the App Runner service from scratch.

### Attempt 7: Delete and recreate service
**Time:** ~18:00 UTC
**Actions:**
1. Deleted old service: `arn:aws:apprunner:us-east-1:500140837569:service/job-scraper-api/03d008fe7656409b84bb754ad636e5ea`
2. Created new service: `arn:aws:apprunner:us-east-1:500140837569:service/job-scraper-api/a8ada11694204c61b771e96b76b36aa5`
3. Changed health check from TCP to HTTP on `/health`
4. Added debug bash entrypoint to Dockerfile to get logs:
```dockerfile
ENTRYPOINT ["/bin/bash", "-c", "echo '=== CONTAINER STARTING ===' && echo \"DATE: $(date)\" && ... && exec dotnet JobsApi.dll"]
```
5. Updated workflow with new service ARN
6. Committed and pushed to trigger GitHub Actions build

**New Service URL:** `https://tmmm39kdu6.us-east-1.awsapprunner.com`
**New Service ARN:** `arn:aws:apprunner:us-east-1:500140837569:service/job-scraper-api/a8ada11694204c61b771e96b76b36aa5`

**Result:** New service also failed with same pattern (no logs). But used OLD image before debug logging was pushed.

### Attempt 8: Fix GitHub workflow to handle CREATE_FAILED
**Time:** ~18:30 UTC
**Problem:** `start-deployment` fails when service is not in RUNNING state
**Fix:** Updated workflow to:
1. Check service status first
2. Use `update-service` instead of `start-deployment` when service is in failed state
3. Increased timeout to 15 minutes
4. Removed `CREATE_FAILED` from immediate failure conditions

**Commits:**
- `96c362f` - debug: add logging to Dockerfile entrypoint
- `e50a8bd` - fix: handle CREATE_FAILED state in deploy workflow

**Next:** Trigger workflow again - it will now build NEW image with debug logging AND properly deploy to failed service

### Attempt 9: Debug logging deployed but had syntax error
**Time:** ~20:25 UTC
**Result:** FAILED - Container still produced no logs
**Investigation:** Pulled image locally and ran it - discovered bash syntax error:
```
/bin/bash: -c: line 1: unexpected EOF while looking for matching `"'
```
**Root cause:** Mismatched quotes in Dockerfile:
```dockerfile
echo \"=== Starting dotnet ===' # starts with \" but ends with '
```
**Fix:** Commit `a440883` - corrected to use consistent single quotes

### Attempt 10: Fixed quote syntax - deployed
**Time:** ~20:55 UTC
**Result:** FAILED - Still no application logs on App Runner

**Local test of SAME image:**
```
=== CONTAINER STARTING ===
DATE: Thu Jan  1 21:25:05 UTC 2026
HOSTNAME: 34c7ea255771
ASPNETCORE_URLS: http://+:8080
PORT: 8080
=== Starting dotnet ===
info: Microsoft.Hosting.Lifetime[14]
      Now listening on: http://[::]:8080
info: Microsoft.Hosting.Lifetime[0]
      Application started. Press Ctrl+C to shut down.
```

**Critical finding:** Image works PERFECTLY locally but produces ZERO output on App Runner.
The container fails before `/bin/bash` can even execute `echo`.

### Potential causes to investigate:
1. **App Runner has a different execution environment** that doesn't support this image format
2. **Something in the image metadata** that App Runner doesn't like
3. **Resource constraints** (memory, CPU) causing immediate OOM kill before any output
4. **Image layer issue** specific to how App Runner pulls/extracts layers

### Attempt 11: Remove VPC Connector + TCP Health Check
**Time:** 2026-01-01 ~22:00 UTC
**Hypothesis:** The VPC connector (even public one) may be causing issues. Switching to App Runner's DEFAULT egress (no VPC connector) and TCP health check (simpler than HTTP) might work.

**What's different from previous attempts:**
- Previous attempts used VPC connectors (both private and public)
- Previous attempts switched FROM TCP TO HTTP health check in Attempt 7
- This attempt uses NO VPC connector (DEFAULT egress) + returns to TCP health check

**Actions:**
1. Deploy minimal Alpine image (clean manifest, no attestations)
2. Update service with `EgressType: DEFAULT` (removes VPC connector)
3. Change health check back to TCP protocol

**Command:**
```bash
aws apprunner update-service \
  --service-arn "arn:aws:apprunner:us-east-1:500140837569:service/job-scraper-api/a8ada11694204c61b771e96b76b36aa5" \
  --network-configuration '{"EgressConfiguration": {"EgressType": "DEFAULT"}}' \
  --health-check-configuration '{"Protocol": "TCP", "Interval": 10, "Timeout": 5, "HealthyThreshold": 1, "UnhealthyThreshold": 5}'
```

**Result:** FAILED - Same pattern (no logs, health check failed)
```
[AppRunner] Successfully pulled your application image from ECR.
[AppRunner] Performing health check on protocol `TCP` [Port: '8080'].
[AppRunner] Health check failed on protocol `TCP` [Port: '8080'].
[AppRunner] Deployment failed.
```

**Finding:** VPC connector removal + TCP health check made no difference. Container still fails before producing any output.

### Attempt 12: Create Brand New App Runner Service
**Time:** 2026-01-01 ~22:30 UTC
**Hypothesis:** The existing service (even though it was recreated in Attempt 7) may have some internal state issue. Creating a completely fresh service with different configuration may help.

**Actions:**
1. Delete existing service completely
2. Create new service with:
   - Minimal Alpine image (clean manifest)
   - TCP health check
   - DEFAULT egress (no VPC connector)
   - No secrets
   - Simple configuration

**Result:** FAILED - Same pattern, no logs

### Attempt 13: Try official nginx image
**Time:** 2026-01-01 ~23:00 UTC
**Hypothesis:** The locally-built Alpine image may have some issue. Using the official nginx image (which is widely used with App Runner) should work.

**Actions:**
1. Pull official `nginx:alpine` for linux/amd64
2. Retag for ECR
3. Push to ECR (clean single-platform manifest)
4. Update App Runner to use nginx on port 80

**Result:** FAILED - Same pattern, no logs
```
[AppRunner] Successfully pulled your application image from ECR.
[AppRunner] Performing health check on protocol `TCP` [Port: '80'].
[AppRunner] Health check failed on protocol `TCP` [Port: '80'].
[AppRunner] Deployment failed.
```

---

## Final Diagnosis

**The official nginx:alpine image fails on App Runner** with zero application logs. This is a widely-used, production-grade image that works everywhere else.

### Conclusion
This is **NOT** a container image issue. The problem is with:
1. **AWS App Runner platform** - possible regional or account-level issue
2. **AWS account configuration** - some permission or quota issue
3. **ECR repository** - possible permissions issue despite successful pulls

### Evidence
| Test | Image | Works Locally | Works on App Runner |
|------|-------|---------------|---------------------|
| 1 | Main .NET + Python/Playwright | YES | NO |
| 2 | Minimal Alpine + busybox httpd | YES | NO |
| 3 | Official nginx:alpine | YES | NO |

All images: Successfully pulled, zero application logs, health check fails immediately.

### Recommended Next Steps
1. **Open AWS Support case** - This behavior is abnormal
2. **Try different AWS region** - Create service in us-west-2 or eu-west-1
3. **Try different AWS account** - Rule out account-level issues
4. **Consider alternative**: Deploy to **ECS Fargate** instead of App Runner

### Current Service
- **Service:** `job-scraper-api-v2`
- **ARN:** `arn:aws:apprunner:us-east-1:500140837569:service/job-scraper-api-v2/a6c5d379e77d43f0a1628eb598cb3d4f`
- **Status:** `CREATE_FAILED`

---

## 2026-01-02: Fresh Deployment Attempt (job-notifier-*)

### Context
Created entirely new AWS infrastructure with `job-notifier-*` naming convention to rule out any residual issues from previous `job-scraper-*` resources.

### New Infrastructure Created
| Resource | ID/ARN |
|----------|--------|
| VPC | `vpc-0eafdaf5d20092a32` |
| Public Subnets | `subnet-0b59188ff9eaa5aab`, `subnet-04873ad8a2cbebb99` |
| Private Subnets | `subnet-099f1cdc8fb8d7ffd`, `subnet-0681d44afaf3e0f13` |
| NAT Gateway | `nat-029e779ff1e66960c` |
| RDS PostgreSQL | `job-notifier-db.csps6uqke28u.us-east-1.rds.amazonaws.com` |
| ECR Repository | `job-notifier-api` |
| VPC Connector | `job-notifier-vpc-connector` |
| Secret | `arn:aws:secretsmanager:us-east-1:500140837569:secret:job-notifier-db-connection-VdnR40` |

### Docker Image Build
- Built using `docker buildx build --platform linux/amd64` on Apple Silicon Mac
- Pushed to ECR with `latest` tag
- Image manifest shows proper `linux/amd64` architecture
- Image works perfectly when run locally

### App Runner Service Creation
- **Service:** `job-notifier-api`
- **ARN:** `arn:aws:apprunner:us-east-1:500140837569:service/job-notifier-api/89cf3bbe6c5c4612904807b1b592dc4a`
- **URL:** `qgsmmm2p4x.us-east-1.awsapprunner.com`

### Result: FAILED - Same Pattern
```
[AppRunner] Starting to deploy your application image.
[AppRunner] Successfully pulled your application image from ECR.
[AppRunner] Performing health check on protocol `HTTP` [Path: '/health'], [Port: '8080'].
[AppRunner] Health check failed on protocol `HTTP`[Path: '/health'], [Port: '8080'].
[AppRunner] Failed to deploy your application image.
```

**Critical:** Zero application logs produced. Container fails before any stdout/stderr output.

### What This Proves
1. The issue is **NOT** related to specific AWS resources (VPC, subnets, security groups)
2. The issue is **NOT** related to resource naming or configuration
3. The issue persists across completely fresh infrastructure
4. The issue affects **all containers** in this AWS account/region, including official images like `nginx:alpine`

---

## Root Cause Analysis

### Definitive Conclusion
**AWS App Runner in us-east-1 for account 500140837569 is fundamentally broken.**

The container execution environment fails to run ANY container image, including:
- Custom .NET 8.0 + Python application
- Minimal Alpine Linux with busybox httpd
- Official `nginx:alpine` from Docker Hub

All containers:
1. Successfully pull from ECR
2. Produce zero stdout/stderr output
3. Fail health checks immediately
4. Show no application-level logs

This behavior indicates a platform-level issue that cannot be resolved through configuration changes.

### Possible Platform-Level Causes
1. **Account quota or limit** preventing container execution
2. **Regional App Runner infrastructure issue** specific to us-east-1
3. **Account-level configuration** blocking container starts
4. **ECR-to-App Runner permission issue** at the platform level (despite successful pulls)

---

## How to Open an AWS Support Case

### Step 1: Access AWS Support
1. Log into AWS Console: https://console.aws.amazon.com
2. Click "Support" in the top-right navigation
3. Click "Create case"

### Step 2: Case Configuration
- **Case type:** Technical
- **Service:** App Runner
- **Category:** Service health issues
- **Severity:** Normal (or higher if you have a support plan)
- **Subject:** App Runner containers fail to start with zero application logs

### Step 3: Use This Draft Message

```
Subject: App Runner containers fail to start with zero application logs - Account 500140837569

Hi AWS Support,

I'm experiencing a critical issue with AWS App Runner in us-east-1 where ALL container deployments fail without producing any application logs.

## Problem Summary
Every container deployed to App Runner fails health checks immediately. The containers produce zero stdout/stderr output before failing. This affects ALL images, including official Docker Hub images.

## Account Details
- Account ID: 500140837569
- Region: us-east-1
- Current failed service ARN: arn:aws:apprunner:us-east-1:500140837569:service/job-notifier-api/89cf3bbe6c5c4612904807b1b592dc4a

## What I've Tested
1. Custom .NET 8.0 application - FAILS (zero logs)
2. Minimal Alpine Linux with busybox httpd - FAILS (zero logs)
3. Official nginx:alpine image - FAILS (zero logs)

All images work perfectly when run locally with Docker.

## App Runner Logs Show
```
[AppRunner] Successfully pulled your application image from ECR.
[AppRunner] Performing health check on protocol `HTTP` [Path: '/health'], [Port: '8080'].
[AppRunner] Health check failed on protocol `HTTP` [Port: '8080'].
[AppRunner] Failed to deploy your application image.
```

No application log streams are created. The container never produces any output.

## What I've Ruled Out
- VPC configuration (tested with both VPC connector and DEFAULT egress)
- Secrets Manager access (tested with and without secrets)
- Health check configuration (tested TCP and HTTP on various ports)
- Image architecture (confirmed linux/amd64)
- Image corruption (all images work locally)
- Service state (created fresh services multiple times)
- Resource naming (tried different naming conventions)

## Expected Behavior
Containers should start and produce stdout/stderr output, even if they crash.

## Actual Behavior
Containers fail immediately with zero output, suggesting they cannot execute at all.

## Questions
1. Is there an account-level issue preventing container execution in App Runner?
2. Are there any quotas or limits that could cause this behavior?
3. Is there a known issue with App Runner in us-east-1?

Please investigate why containers cannot execute in my account. This appears to be a platform-level issue rather than a configuration problem.

Thank you,
[Your Name]
```

### Step 4: Attach Evidence
Consider attaching:
- Screenshot of CloudWatch Logs showing no application log streams
- The App Runner service configuration from the console

---

## Decision: Migrate to ECS Fargate

Given that App Runner is fundamentally broken for this account, the decision has been made to migrate to **ECS Fargate** which:
- Provides more debugging visibility
- Has a more mature execution environment
- Can reuse all existing infrastructure (VPC, subnets, RDS, ECR, secrets)

See: `docs/ecs-fargate-deployment-plan.md` for the migration plan.

---

## Resources

- [AWS App Runner Docs](https://docs.aws.amazon.com/apprunner/)
- [App Runner Troubleshooting](https://docs.aws.amazon.com/apprunner/latest/dg/troubleshoot.html)
- Service URL (when working): `https://cmits4shdg.us-east-1.awsapprunner.com`
