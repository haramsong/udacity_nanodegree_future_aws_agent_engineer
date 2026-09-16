#!/usr/bin/env bash
#
# Grant the AgentCore Runtime execution role access to the resources this agent
# actually uses.
#
# `agentcore configure` generates an execution role scoped to what the toolkit
# itself creates: its own Memory resource, the code interpreter, Bedrock models,
# ECR and logs. It knows nothing about the Knowledge Base, the Memory resource
# and the Gateway that our CloudFormation stack created, and it does not grant
# the browser tool at all. Without this policy the deployed agent fails RAG,
# cross-session memory, and browsing — while the same code works locally,
# because local runs use the developer's own credentials.
#
#   ./infra/grant-runtime-permissions.sh
#
set -euo pipefail

PROFILE="${AWS_PROFILE:-udacity}"
REGION="${AWS_REGION:-us-east-1}"
PROJECT="${PROJECT_NAME:-csai}"
CORE_STACK="${PROJECT}-core"
POLICY_NAME="CustomerSupportAgentResourceAccess"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"

aws() { command aws --profile "$PROFILE" --region "$REGION" "$@"; }
say() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"

# Execution role and gateway/KB/memory ids come from what is actually deployed.
ROLE_ARN="$(python3 -c "
import yaml,sys
cfg=yaml.safe_load(open('$ROOT/.bedrock_agentcore.yaml'))
name=cfg['default_agent']
print(cfg['agents'][name]['aws']['execution_role'])
")"
ROLE_NAME="${ROLE_ARN##*/}"

KB_ID="$(aws cloudformation describe-stacks --stack-name "$CORE_STACK" \
          --query "Stacks[0].Outputs[?OutputKey=='KnowledgeBaseId'].OutputValue" --output text)"
MEMORY_ID="$(aws cloudformation describe-stacks --stack-name "$CORE_STACK" \
          --query "Stacks[0].Outputs[?OutputKey=='MemoryId'].OutputValue" --output text)"

say "Role: $ROLE_NAME"
echo "Knowledge Base: $KB_ID"
echo "Memory:         $MEMORY_ID"

POLICY_FILE="$(mktemp)"
cat > "$POLICY_FILE" <<JSON
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "KnowledgeBaseRetrieve",
      "Effect": "Allow",
      "Action": ["bedrock:Retrieve", "bedrock:RetrieveAndGenerate"],
      "Resource": "arn:aws:bedrock:${REGION}:${ACCOUNT}:knowledge-base/${KB_ID}"
    },
    {
      "Sid": "CustomerSupportMemory",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:CreateEvent",
        "bedrock-agentcore:GetEvent",
        "bedrock-agentcore:GetMemory",
        "bedrock-agentcore:GetMemoryRecord",
        "bedrock-agentcore:ListActors",
        "bedrock-agentcore:ListEvents",
        "bedrock-agentcore:ListMemoryRecords",
        "bedrock-agentcore:ListSessions",
        "bedrock-agentcore:RetrieveMemoryRecords"
      ],
      "Resource": "arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT}:memory/${MEMORY_ID}"
    },
    {
      "Sid": "BrowserTool",
      "Effect": "Allow",
      "Action": [
        "bedrock-agentcore:StartBrowserSession",
        "bedrock-agentcore:StopBrowserSession",
        "bedrock-agentcore:GetBrowser",
        "bedrock-agentcore:GetBrowserSession",
        "bedrock-agentcore:ListBrowsers",
        "bedrock-agentcore:ListBrowserSessions",
        "bedrock-agentcore:ConnectBrowserAutomationStream",
        "bedrock-agentcore:ConnectBrowserLiveViewStream"
      ],
      "Resource": [
        "arn:aws:bedrock-agentcore:${REGION}:aws:browser/aws.browser.v1",
        "arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT}:browser/*",
        "arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT}:browser-session/*"
      ]
    },
    {
      "Sid": "SupportGateway",
      "Effect": "Allow",
      "Action": ["bedrock-agentcore:InvokeGateway"],
      "Resource": "arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT}:gateway/*"
    }
  ]
}
JSON

say "Attaching inline policy $POLICY_NAME"
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "file://$POLICY_FILE"
rm -f "$POLICY_FILE"

say "Done — IAM changes can take up to a minute to take effect"
