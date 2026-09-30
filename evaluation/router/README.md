# Tollgate Learned Model Router — Training & Evaluation Suite

This directory contains the dataset, training pipeline, evaluation framework, and batch inference tools for Tollgate's **Learned Model Router** (Phase 9).

## Architecture

The router uses an interpretable, latency-sensitive machine learning pipeline (`StandardScaler` + `LogisticRegression`) trained on prompt structural and lexical signals. It determines whether incoming requests can be safely satisfied by a fast, cost-efficient model (`mock-fast`, `gpt-4o-mini`) or require a stronger reasoning model (`mock-model`, `gpt-4o`, `claude-3-5-sonnet`).

## Directory Structure

- `datasets/router_benchmark.json`: Ground-truth benchmark dataset (300 queries spanning simple queries, multi-step math, SQL, code generation, and long-context dialogues).
- `generate.py`: Deterministic benchmark dataset generation script (`seed=42`).
- `train.py`: Model training pipeline (70/15/15 train/val/test split, conservative threshold selection, artifact export).
- `evaluate.py`: Benchmark evaluation runner (threshold sweep from 0.10 to 0.90, baseline comparisons, cost-quality tradeoff).
- `predict.py`: CLI inference utility for single-prompt or batch routing prediction.
- `metrics.py`: Metrics calculations (Accuracy, Precision, Recall, F1, FPR, FNR, Brier score, Cost savings %, Quality degradation %).
- `evaluation_report.json`: Exported comprehensive evaluation report.

## Quickstart

### 1. Generate Dataset
```bash
python evaluation/router/generate.py
```

### 2. Train Model and Export Artifacts
```bash
python evaluation/router/train.py
```
This saves the trained model to `artifacts/router/model.joblib` and metadata to `artifacts/router/metadata.json`.

### 3. Run Benchmark Evaluation
```bash
python evaluation/router/evaluate.py
```

### 4. Interactive Prediction
```bash
python evaluation/router/predict.py --prompt "Explain the difference between inner and outer joins in SQL"
```
