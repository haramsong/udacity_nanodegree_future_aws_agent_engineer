#!/usr/bin/env bash
#
# Customer Support AI Agent — infrastructure deployment.
#
#   ./infra/deploy.sh
#
# Creates everything the agent depends on, then writes GATEWAY_URL / KB_ID /
# MEMORY_ID / REGION back into main.py.
#
# It does NOT deploy the agent itself — that is done separately with:
#   uv run agentcore configure --entrypoint main.py --name <your-agent-name>
#   uv run agentcore deploy
#
set -euo pipefail

PROFILE="${AWS_PROFILE:-udacity}"
REGION="${AWS_REGION:-us-east-1}"
PROJECT="${PROJECT_NAME:-csai}"
BOOTSTRAP_STACK="${PROJECT}-bootstrap"
CORE_STACK="${PROJECT}-core"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
BUILD="$HERE/.build"

aws() { command aws --profile "$PROFILE" --region "$REGION" "$@"; }
say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

outp() {  # outp <stack> <OutputKey>
  aws cloudformation describe-stacks --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

# ── 0. Preflight ─────────────────────────────────────────────────────────────
say "Checking credentials"
aws sts get-caller-identity --output table
DEPLOYER_ARN="$(aws sts get-caller-identity --query Arn --output text)"
echo "Deployer principal: $DEPLOYER_ARN"

# ── 1. Bootstrap bucket ──────────────────────────────────────────────────────
say "Deploying $BOOTSTRAP_STACK"
aws cloudformation deploy \
  --stack-name "$BOOTSTRAP_STACK" \
  --template-file "$HERE/00-bootstrap.yaml" \
  --parameter-overrides "ProjectName=$PROJECT" \
  --no-fail-on-empty-changeset

BUCKET="$(outp "$BOOTSTRAP_STACK" ArtifactBucketName)"
echo "Artifact bucket: $BUCKET"

# ── 2. Package and upload artefacts ──────────────────────────────────────────
say "Packaging Lambda functions"
rm -rf "$BUILD" && mkdir -p "$BUILD"
# Built with python's zipfile so the script does not depend on the `zip` binary.
python3 - "$ROOT/lambda" "$BUILD" <<'PY'
import sys, zipfile, pathlib
src, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
for name in ("order_tracker", "refund_processor"):
    with zipfile.ZipFile(out / f"{name}.zip", "w", zipfile.ZIP_DEFLATED) as z:
        z.write(src / f"{name}.py", f"{name}.py")
    print(f"packaged {name}.zip")
PY

aws s3 cp "$BUILD/order_tracker.zip"    "s3://$BUCKET/lambda/order_tracker.zip"
aws s3 cp "$BUILD/refund_processor.zip" "s3://$BUCKET/lambda/refund_processor.zip"
aws s3 cp "$ROOT/product_catalog.txt"   "s3://$BUCKET/kb/product_catalog.txt"

# ── 3. Core stack ────────────────────────────────────────────────────────────
say "Deploying $CORE_STACK (OpenSearch collection takes a few minutes)"
aws cloudformation deploy \
  --stack-name "$CORE_STACK" \
  --template-file "$HERE/01-core.yaml" \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      "ProjectName=$PROJECT" \
      "ArtifactBucket=$BUCKET" \
      "DeployerPrincipalArn=$DEPLOYER_ARN" \
      "EmbeddingModelArn=arn:aws:bedrock:${REGION}::foundation-model/amazon.titan-embed-text-v2:0" \
  --no-fail-on-empty-changeset

GATEWAY_URL="$(outp "$CORE_STACK" GatewayUrl)"
KB_ID="$(outp "$CORE_STACK" KnowledgeBaseId)"
MEMORY_ID="$(outp "$CORE_STACK" MemoryId)"
DS_ID="$(outp "$CORE_STACK" DataSourceId)"

# ── 4. Sync the Knowledge Base (no CloudFormation equivalent) ────────────────
say "Starting Knowledge Base ingestion job"
JOB_ID="$(aws bedrock-agent start-ingestion-job \
            --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
            --query 'ingestionJob.ingestionJobId' --output text)"
echo "Ingestion job: $JOB_ID"

while :; do
  STATUS="$(aws bedrock-agent get-ingestion-job \
              --knowledge-base-id "$KB_ID" --data-source-id "$DS_ID" \
              --ingestion-job-id "$JOB_ID" \
              --query 'ingestionJob.status' --output text)"
  echo "  status: $STATUS"
  case "$STATUS" in
    COMPLETE)            break ;;
    FAILED|STOPPED)      echo "Ingestion job did not complete." >&2; exit 1 ;;
    *)                   sleep 10 ;;
  esac
done

# ── 5. Write the configuration values into main.py ───────────────────────────
say "Updating main.py configuration"
python3 - "$ROOT/main.py" "$GATEWAY_URL" "$KB_ID" "$REGION" "$MEMORY_ID" <<'PY'
import re, sys
path, gateway, kb, region, memory = sys.argv[1:6]
src = open(path).read()
for name, value in (("GATEWAY_URL", gateway), ("KB_ID", kb),
                    ("REGION", region), ("MEMORY_ID", memory)):
    # Replace only the quoted value, keeping the trailing "# TODO" comment.
    src = re.sub(rf'^({name}\s*=\s*)"[^"]*"', rf'\g<1>"{value}"', src, count=1, flags=re.M)
open(path, "w").write(src)
print("main.py updated")
PY

say "Done"
cat <<EOF
GATEWAY_URL = "$GATEWAY_URL"
KB_ID       = "$KB_ID"
REGION      = "$REGION"
MEMORY_ID   = "$MEMORY_ID"

Next steps (run from $ROOT):
  npx @modelcontextprotocol/inspector          # verify the Gateway tools
  uv run agentcore configure --entrypoint main.py --name <your-agent-name>
  uv run agentcore deploy
EOF
