# Half-time Briefing

A multi-agent app that turns synthetic football events into an explained half-time briefing.
The same intelligence goes to two audiences:

- **Analyst mode**: three changes for the second half, each backed by evidence and a measurable target.
- **Fan mode**: a short story about your team and favourite player, in your language.

Built for the Microsoft x Premier League *Inside the Game* hackathon.

![Analyst mode](docs/analyst.png)

## How it maps to the hackathon brief

| Brief stage | What does it |
|---|---|
| Ingest | `halftime/generator.py` makes a seeded synthetic match (passes, shots, tackles, interceptions, pressures, fouls, sprints, possession changes). `/api/events` streams it, and the page can replay the half live. |
| Interpret | `halftime/metrics.py` computes possession, xG, expected threat (xT, Karun Singh's model, fitted on 40 simulated matches in `halftime/xt.py`), PPDA, high presses, pass difficulty, momentum, and the turning point of the half. |
| Explain | The tactics and explainer agents use these lenses: control vs chaos, pressure, game rhythm, chance quality. |
| Render | The overlay step outputs timed, machine-readable graphics cards (scorebug, stat bars, momentum, lower thirds). |
| Personalize | Analyst vs fan mode, team focus, favourite player, and language. |

## The agents

```
stats (code) -> tactics -> explainer -> coach | fan -> overlay (code)
```

- **Every number comes from code.** The model-backed agents only explain and decide, so they cannot invent a stat.
- **Model-backed agents run on Microsoft Agent Framework.** That's tactics, explainer, coach and fan. The tactics agent also gets the metric functions as tools.
- **Backend:** Microsoft Foundry when `FOUNDRY_PROJECT_ENDPOINT` and `FOUNDRY_MODEL` are set. Otherwise any OpenAI or Azure OpenAI endpoint (`OPENAI_API_KEY`, or `AZURE_OPENAI_ENDPOINT` with `AZURE_OPENAI_API_KEY`).
- **No model configured:** each agent falls back to a rule-based version with the same output shape, so the demo always runs. The same fallback catches a model reply that can't be parsed.
- **MCP:** `halftime/mcp_server.py` exposes the same tools over MCP, so GitHub Copilot agent mode or a Foundry agent can query the match directly.

## Run it

```bash
pip install -r requirements.txt
uvicorn app:app --reload          # http://localhost:8000
python -m pytest -q               # 10 tests
python -m halftime.mcp_server     # MCP server over stdio
```

Optional, to use Foundry (sign in with `az login` first):

```bash
export FOUNDRY_PROJECT_ENDPOINT=https://<your-project>.services.ai.azure.com/api/projects/<name>
export FOUNDRY_MODEL=<deployment-name>
```

## Status and limits

- Tested offline: rule-based agents, the API, the page at desktop and phone width, and the Agent Framework wiring (using a scripted stand-in model).
- The Foundry path has **not** yet been run against a live endpoint.
- Offline fan mode writes English only. Other languages need a model.
- The synthetic data has more turnovers than a real match, which makes PPDA run low. The demo match is seed 27: the home side leads 1-0, but the away side switches to a high press at 25' and takes over.
