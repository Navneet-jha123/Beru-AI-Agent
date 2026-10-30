"""Train an optional local YOLO UI detector from a reviewed, labeled dataset.

This script never downloads initial weights or dataset files. It is deliberately
interactive because training consumes substantial local compute and disk.
"""
from __future__ import annotations

import argparse
import datetime
import os
from pathlib import Path

from config import BASE_DIR, WORKSPACE_DIR


def _inside_project(path: Path) -> bool:
    resolved = path.resolve(strict=True)
    return any(resolved == root or root in resolved.parents
               for root in (Path(BASE_DIR).resolve(), Path(WORKSPACE_DIR).resolve()))


def train(dataset_yaml: str, base_weights: str, epochs: int = 20, image_size: int = 640) -> str:
    dataset = Path(dataset_yaml).expanduser().resolve(strict=True)
    weights = Path(base_weights).expanduser().resolve(strict=True)
    if not _inside_project(dataset) or not dataset.is_file() or dataset.suffix.lower() not in {".yaml", ".yml"}:
        raise ValueError("Dataset YAML must be inside the project/workspace.")
    if not _inside_project(weights) or not weights.is_file() or weights.suffix.lower() != ".pt":
        raise ValueError("Initial model weights must be a local .pt file inside the project/workspace.")
    if not 1 <= int(epochs) <= 50 or not 320 <= int(image_size) <= 1024:
        raise ValueError("epochs must be 1..50 and image_size must be 320..1024.")

    import yaml
    config = yaml.safe_load(dataset.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("Dataset YAML must contain a mapping.")
    names = config.get("names", [])
    names = list(names.values()) if isinstance(names, dict) else names
    classes = {str(name).strip().casefold() for name in names}
    required = {"button", "input", "checkbox"}
    if not required.issubset(classes):
        raise ValueError("Dataset class names must include button, input, and checkbox.")
    data_root = Path(config.get("path") or dataset.parent)
    if not data_root.is_absolute():
        data_root = dataset.parent / data_root
    data_root = data_root.resolve(strict=True)
    if not _inside_project(data_root):
        raise ValueError("Dataset path must stay inside the project/workspace.")
    for split in ("train", "val"):
        split_value = config.get(split)
        if not isinstance(split_value, str):
            raise ValueError(f"Dataset YAML must define a local '{split}' directory.")
        split_path = Path(split_value)
        split_path = (data_root / split_path).resolve(strict=True) if not split_path.is_absolute() else split_path.resolve(strict=True)
        if not _inside_project(split_path) or not split_path.is_dir():
            raise ValueError(f"The '{split}' dataset must be an existing directory inside the project/workspace.")

    answer = input(f"Train locally for up to {epochs} epochs using {dataset.name}? Type TRAIN LOCAL MODEL to continue: ")
    if answer.strip() != "TRAIN LOCAL MODEL":
        return "Training cancelled."
    try:
        os.environ["YOLO_AUTOINSTALL"] = "false"
        from ultralytics import YOLO
    except ImportError as exc:
        raise RuntimeError("Install the optional ultralytics package before training.") from exc
    output = Path(WORKSPACE_DIR) / "beru_yolo_runs"
    model = YOLO(str(weights), task="detect")
    run_name = "ui_controls_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    result = model.train(data=str(dataset), epochs=int(epochs), imgsz=int(image_size),
                         project=str(output), name=run_name, exist_ok=False,
                         plots=False, save=True, verbose=False)
    save_dir = getattr(getattr(model, "trainer", None), "save_dir", output / run_name)
    best = Path(save_dir) / "weights" / "best.pt"
    return f"Training finished. Review local weights at: {best} . Set BERU_YOLO_MODEL to this path after reviewing the model."


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="Local YOLO dataset YAML inside the project/workspace")
    parser.add_argument("--weights", required=True, help="Existing local YOLOv8 .pt weights")
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--image-size", type=int, default=640)
    args = parser.parse_args()
    print(train(args.dataset, args.weights, args.epochs, args.image_size))


if __name__ == "__main__":
    main()
