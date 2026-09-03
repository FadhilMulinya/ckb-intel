#!/usr/bin/env python3
import csv, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ITEMS=[
('Dataset contract','Dataset V1','ckb_data/feature_engineering_v2/dataset_v1_snapshot/dataset_contract_v1.json','canonical'),
('Population manifest','Dataset V1','ckb_data/dataset_completion/population_manifest_v1.jsonl','canonical'),
('Feature V2 canonical','Feature V2','ckb_data/feature_engineering_v2/wallet_behaviour_features_v2.csv','canonical'),
('Feature V2 ML-safe','Feature V2','ckb_data/feature_engineering_v2/wallet_behaviour_features_v2_ml.csv','derived'),
('Feature V2 metadata','Feature V2','ckb_data/feature_engineering_v2/wallet_behaviour_features_v2_metadata.csv','derived'),
('Feature V2 evidence','Feature V2','ckb_data/feature_engineering_v2/wallet_behaviour_features_v2_evidence.jsonl','canonical'),
('Predictor audit','Validation','ckb_data/feature_validation/predictor_audit_v1.csv','derived'),
('Validation report','Validation','ckb_data/feature_validation/FEATURE_VALIDATION_ML_READINESS_REPORT.md','derived'),
('PCA contract','PCA','ckb_data/exploratory_ml_pca_v1/experiment_contract.json','derived'),
('PCA variance','PCA','ckb_data/exploratory_ml_pca_v1/pca_high_confidence_v1/explained_variance.csv','derived'),
('PCA loadings','PCA','ckb_data/exploratory_ml_pca_v1/pca_high_confidence_v1/loading_matrix.csv','derived'),
('PCA scores','PCA','ckb_data/exploratory_ml_pca_v1/pca_high_confidence_v1/pca_scores.csv','derived'),
('Phase 2 contract','Structure discovery','ckb_data/exploratory_ml_phase2_v1/experiment_contract.json','derived'),
('HDBSCAN registry','Structure discovery','ckb_data/exploratory_ml_phase2_v1/hdbscan_run_registry.csv','derived'),
('Stability report','Structure discovery','ckb_data/exploratory_ml_phase2_v1/cluster_stability_report.json','derived'),
('GMM selection','Structure discovery','ckb_data/exploratory_ml_phase2_v1/gmm_model_selection.csv','derived'),
('UMAP configuration','Structure discovery','ckb_data/exploratory_ml_phase2_v1/umap_visualization_config.json','derived'),
('Evidence review','Structure discovery','ckb_data/exploratory_ml_phase2_v1/evidence_review_records.csv','derived'),
('Final report','Submission','reports/final-research-report.md','derived')]
rows=[]
for name,phase,path,status in ITEMS:
 p=ROOT/path
 if not p.exists(): continue
 count=None
 if p.suffix=='.csv': count=sum(1 for _ in p.open())-1
 elif p.suffix=='.jsonl': count=sum(1 for _ in p.open())
 rows.append({'artifact':name,'phase':phase,'path':path,'description':name,'row_count':count,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'generated_by':'documented phase command or scripts/build_artifact_index.py','status':status})
out=ROOT/'artifacts';out.mkdir(exist_ok=True)
(out/'artifact-index.json').write_text(json.dumps(rows,indent=2)+'\n')
lines=['# Final artifact index','','| Artifact | Phase | Path | Rows | Status | SHA-256 |','|---|---|---|---:|---|---|']
for r in rows: lines.append(f"| {r['artifact']} | {r['phase']} | `{r['path']}` | {r['row_count'] or ''} | {r['status']} | `{r['sha256']}` |")
(out/'README.md').write_text('\n'.join(lines)+'\n')
print(f'indexed {len(rows)} artifacts')
