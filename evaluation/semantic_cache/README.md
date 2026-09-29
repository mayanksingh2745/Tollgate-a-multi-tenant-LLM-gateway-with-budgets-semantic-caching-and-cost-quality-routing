# Offline Semantic Cache Evaluation Harness

This directory contains the automated evaluation harness for Tollgate's **Phase 8 Semantic Response Cache**.

## Purpose

Vector similarity alone does not guarantee semantic equivalence. High lexical overlap can lead to catastrophic false hits (e.g., `"delete database"` vs. `"create database"`).

The evaluation harness measures empirical cache safety across varied thresholds:
- **Precision**: Fraction of accepted semantic matches that actually shared the same intent.
- **Recall**: Fraction of true semantic matches captured by the cache.
- **False Positive Rate (FPR)**: Rate of hazardous false matches.
- **False Negative Rate (FNR)**: Rate of missed valid cache opportunities.

## Running the Evaluation

Execute directly from repository root:

```bash
python -m evaluation.semantic_cache.runner
```

## Dataset Structure

The dataset (`datasets/evaluation_dataset.json`) contains:
1. **Positive Pairs**: Semantically equivalent intents with different phrasing/synonyms.
2. **Negative Pairs**: Completely different domain/technical intents.
3. **Dangerous Near-Matches**: High vocabulary overlap but opposing action verbs or critical noun divergence.
