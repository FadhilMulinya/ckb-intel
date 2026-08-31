# Wallet Segment Classifier -- Training Report

Model: **random_forest**

## What this model is (and isn't)

This classifier reproduces the GMM clustering decision boundary from CLUSTERING_REPORT.md so new wallets can be labeled quickly without re-fitting GMM against the whole population every time. Its "accuracy" measures agreement with GMM's own (heuristically-named) cluster assignments, not ground-truth correctness of the archetype labels themselves -- GMM was never validated against known bot/human/miner wallets, so neither is this.

Dormant wallets are handled by the same hard rule as the original pipeline (`n_tx_in_window <= 0` -> `Dormant / No Activity`) and never touch the ML model -- there's no behavioral signal in a wallet with zero transactions to learn from.

## Training population

- 123 Dormant wallet(s) excluded (rule-based)
- 764 wallet(s) used for training/evaluation

                        n_wallets
segment                          
Bot-like / Consistent         359
Human-like / Daytime          339
Miner / Heavy Activity         66

## Cross-validation (5-fold, balanced accuracy)

0.917 +/- 0.021 across folds: [0.914, 0.904, 0.914, 0.957, 0.895]

## Test-set classification report
```
                        precision    recall  f1-score   support

 Bot-like / Consistent       0.96      0.97      0.97        72
  Human-like / Daytime       0.97      0.97      0.97        68
Miner / Heavy Activity       1.00      0.92      0.96        13

              accuracy                           0.97       153
             macro avg       0.98      0.96      0.97       153
          weighted avg       0.97      0.97      0.97       153
```

## Files

- `wallet_classifier.joblib` -- the trained model bundle (model + label encoder + feature list + Dormant rule). Load with `joblib.load()`.
- `confusion_matrix.png`
- `feature_importances.png`

## Using this model on new wallets

```bash
python3 train_wallet_classifier.py --predict-file new_wallets.csv --model-dir ./wallet_classifier --out-file predictions.csv
```