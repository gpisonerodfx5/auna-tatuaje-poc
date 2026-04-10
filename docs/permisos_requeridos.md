# Permisos IAM requeridos para PoC Tatuaje Auna v2.1

**Usuario:** gpisonero@dfx5.com
**Cuenta:** 369037400928 (pe-auna-consolidado-bi-no-prd)
**Region:** us-east-1
**Scope:** Todos los recursos con prefijo `auna-tatuaje-poc-*`
**Tag:** `Project: PoC Tatuaje`

---

## Politica IAM recomendada (JSON)

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "IAMRolesPoC",
            "Effect": "Allow",
            "Action": [
                "iam:CreateRole",
                "iam:GetRole",
                "iam:UpdateRole",
                "iam:DeleteRole",
                "iam:PutRolePolicy",
                "iam:GetRolePolicy",
                "iam:DeleteRolePolicy",
                "iam:ListRolePolicies",
                "iam:TagRole",
                "iam:PassRole",
                "iam:AttachRolePolicy",
                "iam:DetachRolePolicy",
                "iam:ListAttachedRolePolicies"
            ],
            "Resource": [
                "arn:aws:iam::369037400928:role/auna-tatuaje-poc-*"
            ]
        },
        {
            "Sid": "LambdaPoC",
            "Effect": "Allow",
            "Action": [
                "lambda:CreateFunction",
                "lambda:UpdateFunctionCode",
                "lambda:UpdateFunctionConfiguration",
                "lambda:GetFunction",
                "lambda:GetFunctionConfiguration",
                "lambda:ListFunctions",
                "lambda:DeleteFunction",
                "lambda:TagResource",
                "lambda:UntagResource",
                "lambda:ListTags",
                "lambda:AddPermission",
                "lambda:RemovePermission",
                "lambda:GetPolicy",
                "lambda:InvokeFunction",
                "lambda:CreateEventSourceMapping",
                "lambda:DeleteEventSourceMapping",
                "lambda:ListEventSourceMappings",
                "lambda:UpdateEventSourceMapping"
            ],
            "Resource": [
                "arn:aws:lambda:us-east-1:369037400928:function:auna-tatuaje-poc-*",
                "arn:aws:lambda:us-east-1:369037400928:event-source-mapping:*"
            ]
        },
        {
            "Sid": "LambdaListAll",
            "Effect": "Allow",
            "Action": [
                "lambda:ListFunctions",
                "lambda:ListEventSourceMappings"
            ],
            "Resource": "*"
        },
        {
            "Sid": "SQSPoC",
            "Effect": "Allow",
            "Action": [
                "sqs:CreateQueue",
                "sqs:DeleteQueue",
                "sqs:GetQueueUrl",
                "sqs:GetQueueAttributes",
                "sqs:SetQueueAttributes",
                "sqs:SendMessage",
                "sqs:ReceiveMessage",
                "sqs:DeleteMessage",
                "sqs:PurgeQueue",
                "sqs:TagQueue",
                "sqs:UntagQueue",
                "sqs:ListQueueTags"
            ],
            "Resource": "arn:aws:sqs:us-east-1:369037400928:auna-tatuaje-poc-*"
        },
        {
            "Sid": "SQSList",
            "Effect": "Allow",
            "Action": "sqs:ListQueues",
            "Resource": "*"
        },
        {
            "Sid": "DynamoDBPoC",
            "Effect": "Allow",
            "Action": [
                "dynamodb:CreateTable",
                "dynamodb:DeleteTable",
                "dynamodb:DescribeTable",
                "dynamodb:UpdateTable",
                "dynamodb:PutItem",
                "dynamodb:GetItem",
                "dynamodb:UpdateItem",
                "dynamodb:DeleteItem",
                "dynamodb:Query",
                "dynamodb:Scan",
                "dynamodb:TagResource",
                "dynamodb:UntagResource",
                "dynamodb:ListTagsOfResource",
                "dynamodb:UpdateTimeToLive",
                "dynamodb:DescribeTimeToLive"
            ],
            "Resource": "arn:aws:dynamodb:us-east-1:369037400928:table/auna-tatuaje-poc-*"
        },
        {
            "Sid": "StepFunctionsPoC",
            "Effect": "Allow",
            "Action": [
                "states:CreateStateMachine",
                "states:UpdateStateMachine",
                "states:DeleteStateMachine",
                "states:DescribeStateMachine",
                "states:ListStateMachines",
                "states:StartExecution",
                "states:StopExecution",
                "states:DescribeExecution",
                "states:ListExecutions",
                "states:GetExecutionHistory",
                "states:TagResource",
                "states:UntagResource",
                "states:ListTagsForResource"
            ],
            "Resource": [
                "arn:aws:states:us-east-1:369037400928:stateMachine:auna-tatuaje-poc-*",
                "arn:aws:states:us-east-1:369037400928:execution:auna-tatuaje-poc-*:*"
            ]
        },
        {
            "Sid": "StepFunctionsList",
            "Effect": "Allow",
            "Action": "states:ListStateMachines",
            "Resource": "*"
        },
        {
            "Sid": "SecretsManagerPoC",
            "Effect": "Allow",
            "Action": [
                "secretsmanager:CreateSecret",
                "secretsmanager:UpdateSecret",
                "secretsmanager:DeleteSecret",
                "secretsmanager:DescribeSecret",
                "secretsmanager:GetSecretValue",
                "secretsmanager:PutSecretValue",
                "secretsmanager:TagResource",
                "secretsmanager:UntagResource"
            ],
            "Resource": "arn:aws:secretsmanager:us-east-1:369037400928:secret:auna/*"
        },
        {
            "Sid": "S3PoC",
            "Effect": "Allow",
            "Action": [
                "s3:CreateBucket",
                "s3:DeleteBucket",
                "s3:ListBucket",
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:PutBucketPublicAccessBlock",
                "s3:PutBucketLifecycleConfiguration",
                "s3:GetBucketLifecycleConfiguration",
                "s3:PutBucketNotificationConfiguration",
                "s3:GetBucketNotificationConfiguration",
                "s3:PutBucketTagging",
                "s3:GetBucketTagging",
                "s3:GetBucketVersioning",
                "s3:GetBucketLocation"
            ],
            "Resource": [
                "arn:aws:s3:::auna-tatuaje-poc-*",
                "arn:aws:s3:::auna-tatuaje-poc-*/*"
            ]
        },
        {
            "Sid": "CloudWatchMetrics",
            "Effect": "Allow",
            "Action": [
                "cloudwatch:PutMetricData",
                "cloudwatch:GetMetricData",
                "cloudwatch:GetMetricStatistics",
                "cloudwatch:ListMetrics",
                "cloudwatch:PutMetricAlarm",
                "cloudwatch:DescribeAlarms",
                "cloudwatch:DeleteAlarms",
                "cloudwatch:PutDashboard",
                "cloudwatch:GetDashboard",
                "cloudwatch:ListDashboards",
                "cloudwatch:DeleteDashboards"
            ],
            "Resource": "*"
        },
        {
            "Sid": "CloudWatchLogs",
            "Effect": "Allow",
            "Action": [
                "logs:CreateLogGroup",
                "logs:DeleteLogGroup",
                "logs:CreateLogStream",
                "logs:PutLogEvents",
                "logs:GetLogEvents",
                "logs:FilterLogEvents",
                "logs:DescribeLogGroups",
                "logs:DescribeLogStreams",
                "logs:PutRetentionPolicy",
                "logs:DeleteRetentionPolicy",
                "logs:TagLogGroup"
            ],
            "Resource": [
                "arn:aws:logs:us-east-1:369037400928:log-group:/aws/lambda/auna-tatuaje-poc-*",
                "arn:aws:logs:us-east-1:369037400928:log-group:/aws/lambda/auna-tatuaje-poc-*:log-stream:*",
                "arn:aws:logs:us-east-1:369037400928:log-group:/aws/states/auna-tatuaje-poc-*",
                "arn:aws:logs:us-east-1:369037400928:log-group:/aws/states/auna-tatuaje-poc-*:log-stream:*"
            ]
        },
        {
            "Sid": "CloudWatchLogsList",
            "Effect": "Allow",
            "Action": "logs:DescribeLogGroups",
            "Resource": "*"
        },
        {
            "Sid": "ConnectPoC",
            "Effect": "Allow",
            "Action": [
                "connect:CreateInstance",
                "connect:DescribeInstance",
                "connect:ListInstances",
                "connect:DeleteInstance",
                "connect:CreateContactFlow",
                "connect:UpdateContactFlowContent",
                "connect:UpdateContactFlowMetadata",
                "connect:DescribeContactFlow",
                "connect:ListContactFlows",
                "connect:DeleteContactFlow",
                "connect:CreateContactFlowModule",
                "connect:UpdateContactFlowModuleContent",
                "connect:UpdateContactFlowModuleMetadata",
                "connect:StartOutboundVoiceContact",
                "connect:GetContactAttributes",
                "connect:UpdateContactAttributes",
                "connect:AssociateBot",
                "connect:DisassociateBot",
                "connect:AssociateLexBot",
                "connect:DisassociateLexBot",
                "connect:AssociateLambdaFunction",
                "connect:DisassociateLambdaFunction",
                "connect:ListLambdaFunctions",
                "connect:ClaimPhoneNumber",
                "connect:ListPhoneNumbers",
                "connect:ListPhoneNumbersV2",
                "connect:ReleasePhoneNumber",
                "connect:SearchAvailablePhoneNumbers",
                "connect:CreateUser",
                "connect:DescribeUser",
                "connect:ListUsers",
                "connect:GetMetricData",
                "connect:GetMetricDataV2",
                "connect:GetCurrentMetricData",
                "connect:ListQueues",
                "connect:DescribeQueue",
                "connect:ListRoutingProfiles",
                "connect:DescribeRoutingProfile",
                "connect:TagResource",
                "connect:UntagResource"
            ],
            "Resource": "*"
        },
        {
            "Sid": "BedrockPoC",
            "Effect": "Allow",
            "Action": [
                "bedrock:CreateAgent",
                "bedrock:UpdateAgent",
                "bedrock:GetAgent",
                "bedrock:ListAgents",
                "bedrock:DeleteAgent",
                "bedrock:PrepareAgent",
                "bedrock:CreateAgentAlias",
                "bedrock:UpdateAgentAlias",
                "bedrock:GetAgentAlias",
                "bedrock:ListAgentAliases",
                "bedrock:DeleteAgentAlias",
                "bedrock:CreateAgentActionGroup",
                "bedrock:UpdateAgentActionGroup",
                "bedrock:GetAgentActionGroup",
                "bedrock:ListAgentActionGroups",
                "bedrock:DeleteAgentActionGroup",
                "bedrock:InvokeAgent",
                "bedrock:InvokeModel",
                "bedrock:InvokeModelWithResponseStream",
                "bedrock:ListFoundationModels",
                "bedrock:GetFoundationModel",
                "bedrock:CreateKnowledgeBase",
                "bedrock:UpdateKnowledgeBase",
                "bedrock:GetKnowledgeBase",
                "bedrock:ListKnowledgeBases",
                "bedrock:DeleteKnowledgeBase",
                "bedrock:AssociateAgentKnowledgeBase",
                "bedrock:DisassociateAgentKnowledgeBase",
                "bedrock:TagResource",
                "bedrock:UntagResource",
                "bedrock:ListTagsForResource"
            ],
            "Resource": "*"
        },
        {
            "Sid": "STSIdentity",
            "Effect": "Allow",
            "Action": "sts:GetCallerIdentity",
            "Resource": "*"
        },
        {
            "Sid": "TaggingDiscovery",
            "Effect": "Allow",
            "Action": [
                "tag:GetResources",
                "tag:TagResources",
                "tag:UntagResources"
            ],
            "Resource": "*"
        },
        {
            "Sid": "EventBridgePoC",
            "Effect": "Allow",
            "Action": [
                "events:PutRule",
                "events:PutTargets",
                "events:RemoveTargets",
                "events:DeleteRule",
                "events:DescribeRule",
                "events:ListRules"
            ],
            "Resource": "arn:aws:events:us-east-1:369037400928:rule/auna-tatuaje-poc-*"
        }
    ]
}
```

---

## Resumen por servicio

| Servicio | Para que |
|----------|---------|
| **IAM** | Crear roles de ejecucion para Lambda y Step Functions |
| **Lambda** | Crear y desplegar las 5 funciones Lambda |
| **SQS** | Cola de mensajes para procesamiento de afiliados |
| **DynamoDB** | Tablas de interacciones y blacklist |
| **Step Functions** | Orquestador principal del flujo de llamadas |
| **Secrets Manager** | Credenciales de API Multisede |
| **S3** | Bucket de input para CSVs de afiliados |
| **CloudWatch** | Metricas de negocio y alarmas |
| **CloudWatch Logs** | Logs de Lambda y Step Functions |
| **Connect** | Instancia de telefonia, contact flows, llamadas outbound |
| **Bedrock** | Agente Nova Sonic 2 para conversacion por voz |
| **EventBridge** | Programacion de ejecuciones (futuro) |
| **STS** | Verificacion de identidad |
| **Tagging** | Etiquetado de recursos como "PoC Tatuaje" |

## Notas

- Todos los recursos usan el prefijo `auna-tatuaje-poc-*` para facilitar el scoping
- Todos los recursos se etiquetan con `Project: PoC Tatuaje`
- La politica esta limitada a la region `us-east-1`
- Los permisos de Connect y Bedrock usan `Resource: *` porque sus ARNs se generan dinamicamente
- Se puede crear como politica gestionada: `AunaTatuajePocDeveloper`
