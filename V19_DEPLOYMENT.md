# V19.0.0 — Deployment

## Services
1. Render Interface: deploy the `Codes/` directory as the existing Streamlit service.
2. Render Gateway: use the same `Codes/` directory with the existing FastAPI start command.
3. Windows Local Agent: replace the old `local_agent/agent.py` and related files; run exactly one instance.

## Environment
Preserve existing working variables. At minimum the architecture expects:
- `OPENROUTER_API_KEY`
- `OPENROUTER_MODEL`
- `LOCAL_AGENT_TOKEN`
- `JARVIS_GATEWAY_URL` (on the Windows agent)
- existing Honcho variables if Honcho is used
- existing WhatsApp variables if WhatsApp is used
- existing Edge TTS variables if voice is used

Do not invent new variable names when an existing one already supplies the same setting.

## Version check
Interface, Gateway and Local Agent must report:
`19.0.0`
Build:
`19.0.0-command-os-complete`

## Local Agent
Close every old instance before starting the V19 agent. Verify the terminal reports V19.0.0.

## Security
Do not disable the Permission Manager or Kill Switch to make a test pass. Do not enable arbitrary shell execution. Delete operations remain confirmation/permission controlled.

## Rollback
Keep a copy of the V14.5.3 ZIP before deployment. If a deployment breaks production, redeploy the previous artifact rather than modifying production blindly.
