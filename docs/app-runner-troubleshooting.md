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

---

## Resources

- [AWS App Runner Docs](https://docs.aws.amazon.com/apprunner/)
- [App Runner Troubleshooting](https://docs.aws.amazon.com/apprunner/latest/dg/troubleshoot.html)
- Service URL (when working): `https://cmits4shdg.us-east-1.awsapprunner.com`
