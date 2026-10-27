"""Start BERU's optional one-shot local voice interface."""
from modes.voice_assistant import voice_turn

if __name__ == "__main__":
    while True:
        command = input("Press Enter to speak, or type q to quit: ").strip().casefold()
        if command in {"q", "quit", "exit"}:
            break
        print(voice_turn())
