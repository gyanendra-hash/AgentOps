# ROADMAP 6.6: walks through every milestone's headline capability against a
# running `docker compose up` stack. Milestones 3-5's agent endpoints need
# OPENAI_API_KEY or ANTHROPIC_API_KEY set in .env before `docker compose up`
# -- pass -SkipLLM to skip those steps instead of failing on them.
param(
    [switch]$SkipLLM
)

$Gateway = "http://localhost:8080"
$Scheduler = "http://localhost:8002"
$AgentOps = "http://localhost:8004"

function Section($title) {
    Write-Host ""
    Write-Host "=== $title ==="
}

Section "Milestone 1: Rate Limiter + Gateway"
Write-Host "-> GET /api/ping through the Gateway (rate-limit checked):"
Invoke-WebRequest -Uri "$Gateway/api/ping" -Headers @{ "X-Client-Id" = "demo" } | Select-Object -ExpandProperty StatusCode

Section "Milestone 2: Scheduler + Worker Pool"
Write-Host "-> Submitting a 2-job DAG (b depends on a):"
$body = '{"jobs":[{"ref":"a","name":"extract","priority":5},{"ref":"b","name":"load","priority":1,"depends_on":["a"]}]}'
$response = Invoke-RestMethod -Method Post -Uri "$Scheduler/v1/jobs" -ContentType "application/json" -Body $body
$response | ConvertTo-Json -Depth 5
$jobA = $response.jobs[0].id
Write-Host "-> Job a's id: $jobA -- poll GET $Scheduler/v1/jobs/$jobA to watch it move through the state machine"
Write-Host "-> Queue depth (Milestone 5's Monitor Agent uses this too):"
Invoke-RestMethod -Uri "$Scheduler/v1/jobs/stats" | ConvertTo-Json

if (-not $SkipLLM) {
    Section "Milestone 3: RAG debugging"
    Invoke-RestMethod -Method Post -Uri "$AgentOps/v1/debug/ask" -ContentType "application/json" `
        -Body '{"question": "the dead letter queue is growing fast, what should I check?"}' | ConvertTo-Json -Depth 5

    Section "Milestone 4: Tool-calling (non-destructive)"
    Invoke-RestMethod -Method Post -Uri "$AgentOps/v1/agent/schedule" -ContentType "application/json" `
        -Body '{"question": "create a job called demo-job with priority 2"}' | ConvertTo-Json -Depth 5

    Section "Milestone 5: Unified entry point + Monitor Agent"
    Invoke-RestMethod -Method Post -Uri "$AgentOps/v1/agent/ask" -ContentType "application/json" `
        -Body '{"question": "how''s the queue looking right now?"}' | ConvertTo-Json -Depth 5
} else {
    Section "Milestones 3-5 skipped (-SkipLLM)"
}

Section "Milestone 5: Monitor Agent, no LLM needed"
Invoke-RestMethod -Uri "$AgentOps/v1/monitor/status" | ConvertTo-Json

Section "Milestone 6: per-node trace on the last debug/ask call"
Write-Host "(see the 'trace' field in the Milestone 3 response above -- latency_ms and usage per node)"
