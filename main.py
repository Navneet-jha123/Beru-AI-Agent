"""
main.py - Sovereign CLI Command Interface for BERU AI AGENT.
Interactive REPL with Rich banners, live execution spinner, and mode switching.
"""
# -*- coding: utf-8 -*-
import sys
import io

_enc = getattr(sys.stdout, "encoding", None) or ""
if _enc.lower() != "utf-8":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")
    except Exception:
        pass

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="pydantic")

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

# Force UTF-8 output on Windows — fixes Rich Panel border mojibake
import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from agent import run_agent
from proactive_daemon import generate_system_health_briefing

console = Console()
BANNER = """[bold cyan]
    ██████╗ ███████╗██████╗ ██╗   ██╗
    ██╔══██╗██╔════╝██╔══██╗██║   ██║
    ██████╔╝█████╗  ██████╔╝██║   ██║
    ██╔══██╗██╔══╝  ██╔══██╗██║   ██║
    ██████╔╝███████╗██║  ██║╚██████╔╝
    ╚═════╝ ╚══════╝╚═╝  ╚═╝ ╚═════╝
[/bold cyan]
[bold white]The Autonomous AI Agent | Command Center[/bold white]
[dim cyan]Version 2.0 | Neural Gateway Active[/dim cyan]
"""

def main():
    console.print(BANNER)
    current_mode = "General"
    history = []  # recent {"role","content"} turns, so follow-ups like "yes" keep their context
    console.print(f"[bold green]System Online.[/bold green] Current Mode: [bold yellow]{current_mode}[/bold yellow]")
    console.print("[dim]Commands: /mode <General|Developer|Tester|Hacker>, /health, /clear, /quit[/dim]\n")

    while True:
        try:
            user_input = Prompt.ask(f"[bold cyan]BERU ({current_mode})[/bold cyan]").strip()
            if not user_input:
                continue

            # Command Handlers
            if user_input.lower() in ("/quit", "/exit", "exit", "quit"):
                console.print("[bold red]Shutting down BERU AI AGENT. Goodbye![/bold red]")
                break
            elif user_input.lower().startswith("/mode"):
                parts = user_input.split()
                if len(parts) > 1 and parts[1].capitalize() in ("General", "Developer", "Tester", "Hacker"):
                    current_mode = parts[1].capitalize()
                    console.print(f"🔄 Mode switched to: [bold yellow]{current_mode}[/bold yellow]\n")
                else:
                    console.print("Valid modes: General, Developer, Tester, Hacker\n")
                continue
            elif user_input.lower() == "/health":
                briefing = generate_system_health_briefing()
                console.print(Panel(Markdown(briefing), title="🩺 System Health Telemetry", border_style="cyan"))
                continue
            elif user_input.lower() == "/clear":
                history.clear()
                console.clear()
                console.print(BANNER)
                continue

            # Run Agent
            with console.status(f"[bold cyan]BERU is operating in {current_mode} mode...[/bold cyan]", spinner="dots"):
                def on_thought(t):
                    console.print(f"[dim italic]🧠 {t}[/dim italic]")

                def on_tool(name, args):
                    console.print(f"[bold magenta]⚡ Executing:[/bold magenta] [cyan]{name}[/cyan]({args})")

                def on_result(name, res):
                    preview = (res[:120] + "...") if len(res) > 120 else res
                    console.print(f"[dim green]↳ {preview}[/dim green]")

                response = run_agent(
                    user_input,
                    mode=current_mode,
                    history=list(history),
                    on_thought=on_thought,
                    on_tool_call=on_tool,
                    on_tool_result=on_result,
                )

            console.print(Panel(Markdown(response), title=f"🤖 BERU Output ({current_mode})", border_style="green"))
            console.print()

            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": response})
            del history[:-8]  # keep the last 4 exchanges (agent.py also keeps at most 8 messages)

        except KeyboardInterrupt:
            console.print("\n[bold red]Interrupted. Type /quit to exit.[/bold red]")
        except Exception as e:
            console.print(f"[bold red]Error: {e}[/bold red]\n")


if __name__ == "__main__":
    main()
