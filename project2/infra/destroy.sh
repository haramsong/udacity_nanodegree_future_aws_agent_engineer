#!/usr/bin/env bash
#
# Tear down all project infrastructure.
#
# Run this when you are finished. The OpenSearch Serverless collection bills by
# the hour whether or not the agent is running, and the Gateway uses the NONE
# authorizer, so neither should be left up.
#
# Delete the AgentCore Runtime first:  uv run agentcore destroy
#
set -euo pipefail

PROFILE="${AWS_PROFILE:-udacity}"
REGION="${AWS_REGION:-us-east-1}"
PROJECT="${PROJECT_NAME:-csai}"

aws() { command aws --profile "$PROFILE" --region "$REGION" "$@"; }
say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

for STACK in "${PROJECT}-monitoring" "${PROJECT}-core"; do
  if aws cloudformation describe-stacks --stack-name "$STACK" >/dev/null 2>&1; then
    say "Deleting $STACK"
    aws cloudformation delete-stack --stack-name "$STACK"
    aws cloudformation wait stack-delete-complete --stack-name "$STACK"
  fi
done

BOOTSTRAP="${PROJECT}-bootstrap"
if aws cloudformation describe-stacks --stack-name "$BOOTSTRAP" >/dev/null 2>&1; then
  BUCKET="$(aws cloudformation describe-stacks --stack-name "$BOOTSTRAP" \
             --query "Stacks[0].Outputs[?OutputKey=='ArtifactBucketName'].OutputValue" --output text)"
  # The bucket is versioned, so every version and delete marker must go before
  # CloudFormation can remove it.
  say "Emptying s3://$BUCKET"
  aws s3api list-object-versions --bucket "$BUCKET" \
    --query '{Objects: [].{Key:Key,VersionId:VersionId}}' --output json \
    > /tmp/${PROJECT}-versions.json 2>/dev/null || echo '{"Objects":null}' > /tmp/${PROJECT}-versions.json
  if [ "$(python3 -c "import json;d=json.load(open('/tmp/${PROJECT}-versions.json'));print(len(d.get('Objects') or []))")" != "0" ]; then
    aws s3api delete-objects --bucket "$BUCKET" --delete "file:///tmp/${PROJECT}-versions.json" >/dev/null
  fi
  aws s3api list-object-versions --bucket "$BUCKET" \
    --query '{Objects: DeleteMarkers[].{Key:Key,VersionId:VersionId}}' --output json \
    > /tmp/${PROJECT}-markers.json 2>/dev/null || echo '{"Objects":null}' > /tmp/${PROJECT}-markers.json
  if [ "$(python3 -c "import json;d=json.load(open('/tmp/${PROJECT}-markers.json'));print(len(d.get('Objects') or []))")" != "0" ]; then
    aws s3api delete-objects --bucket "$BUCKET" --delete "file:///tmp/${PROJECT}-markers.json" >/dev/null
  fi

  say "Deleting $BOOTSTRAP"
  aws cloudformation delete-stack --stack-name "$BOOTSTRAP"
  aws cloudformation wait stack-delete-complete --stack-name "$BOOTSTRAP"
fi

say "All stacks removed"
