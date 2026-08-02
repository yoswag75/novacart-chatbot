import asyncio
import json
import sys
import httpx
from httpx_sse import aconnect_sse
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.markdown import Markdown
from rich.live import Live

API_URL = "http://localhost:8000/query/stream"
API_TOKEN = "supersecrettoken" # Should ideally be from env

console = Console()

async def query_backend(question: str):
    headers = {
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {"question": question}
    
    try:
        async with httpx.AsyncClient(timeout=None) as client:
            # We will accumulate the answer text to render as Markdown
            full_answer = ""
            live = Live(Markdown(""), refresh_per_second=15, console=console)
            
            async with aconnect_sse(client, "POST", API_URL, headers=headers, json=payload) as event_source:
                async for sse in event_source.aiter_sse():
                    data = json.loads(sse.data)
                    
                    if data["type"] == "status":
                        # If live is running, stop it to print status, then restart
                        if live.is_started:
                            live.stop()
                        console.print(f"[dim]{data['message']}[/dim]")
                        
                    elif data["type"] == "plan":
                        if live.is_started:
                            live.stop()
                        plan_list = data.get("plan", [])
                        if plan_list:
                            console.print("\n[bold yellow]Search Plan:[/bold yellow]")
                            for i, step in enumerate(plan_list, 1):
                                console.print(f"  {i}. {step}")
                            console.print("\n")
                            
                    elif data["type"] == "token":
                        # Start live display if not started
                        if not live.is_started:
                            live.start()
                        full_answer += data["content"]
                        live.update(Markdown(full_answer))
                        
                    elif data["type"] == "complete":
                        if live.is_started:
                            live.stop()
                        
                        console.print("\n")
                        # Render Anomalies
                        if data.get("anomalies_detected"):
                            table = Table(title="Detected Anomalies", style="red")
                            table.add_column("Type", justify="left", style="cyan")
                            table.add_column("Description", justify="left", style="magenta")
                            for anomaly in data["anomalies_detected"]:
                                table.add_row(anomaly.get("type", "Unknown"), anomaly.get("description", ""))
                            console.print(table)
                            
                        # Render Missing Evidence
                        if data.get("missing_evidence"):
                            console.print(Panel(Text("Missing Evidence Flag Triggered - The agent could not find all required information.", style="bold red")))
                            
                        # Render Citations
                        if data.get("citations"):
                            table = Table(title="Citations", style="green")
                            table.add_column("Doc ID", justify="left", style="cyan")
                            table.add_column("Source Type", justify="left", style="magenta")
                            for cite in data["citations"]:
                                table.add_row(cite.get("doc_id", ""), cite.get("source_type", ""))
                            console.print(table)
                            
                    elif data["type"] == "error":
                        console.print(f"[bold red]Error: {data['message']}[/bold red]")
                        
    except httpx.ConnectError:
        console.print("[bold red]Could not connect to backend. Is the server running?[/bold red]")
    except Exception as e:
        console.print(f"[bold red]Unexpected error: {e}[/bold red]")

async def main():
    console.print(Panel.fit("[bold blue]NovaCart Global Agentic Reasoning CLI[/bold blue]\nType your question or 'exit' to quit."))
    session = PromptSession()
    
    while True:
        with patch_stdout():
            try:
                text = await session.prompt_async("Ask NovaCart > ")
            except (EOFError, KeyboardInterrupt):
                break

        if text.strip().lower() in ["exit", "quit"]:
            break

        if not text.strip():
            continue

        console.print("\n")
        await query_backend(text)
        console.print("\n")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
