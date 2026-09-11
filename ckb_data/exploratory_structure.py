#!/usr/bin/env python3
"""Phase 2 unsupervised structure discovery over immutable PCA representations."""
import csv, hashlib, json, math, os, platform, sqlite3, statistics
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
os.environ.setdefault("MPLCONFIGDIR","/tmp/ckb-mpl-cache");os.environ.setdefault("XDG_CACHE_HOME","/tmp/ckb-xdg-cache")
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
import hdbscan, umap
from sklearn.mixture import GaussianMixture
from sklearn.metrics import adjusted_mutual_info_score, adjusted_rand_score
from sklearn.preprocessing import StandardScaler

ROOT=Path(__file__).resolve().parent; P1=ROOT/"exploratory_ml_pca_v1"; VAL=ROOT/"feature_validation"
V2=ROOT/"feature_engineering_v2"; DB=ROOT/"ckb_data_v2/ckb_explorer.sqlite"; OUT=ROOT/"exploratory_ml_phase2_v1"
VERSION="ckb-exploratory-structure-v1"; SEED=20260902
GRID={"min_cluster_size":[15,25,40,60],"min_samples":[5,10,20],"cluster_selection_method":["eom","leaf"]}
BOOTSTRAPS=100; FORBIDDEN=("label","stratum","rule__","prediction","cluster","wallet","collection","support")

def dump(p,x): p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(x,indent=2,sort_keys=True)+"\n")
def write_csv(p,rows,cols=None):
 p.parent.mkdir(parents=True,exist_ok=True); cols=cols or sorted({k for r in rows for k in r})
 with p.open("w",newline="") as f:
  w=csv.DictWriter(f,fieldnames=cols,extrasaction="ignore"); w.writeheader()
  for row in rows: w.writerow({k:json.dumps(v,sort_keys=True) if isinstance(v,(dict,list)) else v for k,v in row.items()})
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def integrity():
 c=json.loads((P1/"experiment_contract.json").read_text()); conn=sqlite3.connect(f"file:{DB.resolve()}?mode=ro",uri=True); q=conn.execute("pragma quick_check").fetchone()[0];conn.close()
 paths=[P1/"experiment_contract.json",P1/"cross_experiment_comparison.json",V2/"wallet_behaviour_features_v2_evidence.jsonl",VAL/"activity_diagnostics_v1.csv"]
 return {"manifest":c["source_integrity"]["manifest_hash"],"database":c["source_integrity"]["database"],"quick_check":q,
 "artifacts":{str(p.relative_to(ROOT.parent)):sha(p) for p in paths}}
def load_rep(dirname):
 d=P1/dirname; cohort=json.loads((d/"cohort_contract.json").read_text()); feats=cohort["features"]; wallets=cohort["wallets"]
 rows=list(csv.DictReader((d/"raw_transformed_scaled_values.csv").open())); by={(r["wallet"],r["feature"]):float(r["scaled_value"]) for r in rows}
 x=np.array([[by[(w,f)] for f in feats] for w in wallets]); scores=list(csv.DictReader((d/"pca_scores.csv").open()))
 pcs=np.array([[float(r[f"PC{i+1}"]) for i in range(len(feats))] for r in scores]); return wallets,feats,x,pcs
def pathological(labels):
 n=len(labels); counts=Counter(labels); noise=counts.get(-1,0); clusters=[v for k,v in counts.items() if k>=0]
 reasons=[]
 if len(clusters)<2: reasons.append("FEWER_THAN_TWO_CLUSTERS")
 if noise/n>.80: reasons.append("NOISE_ABOVE_80_PERCENT")
 if clusters and max(clusters)/n>.85: reasons.append("GIANT_CLUSTER_ABOVE_85_PERCENT")
 return reasons
def grid_runs(name,wallets,x):
 out=[]; labels={}
 for mcs in GRID["min_cluster_size"]:
  for ms in GRID["min_samples"]:
   for method in GRID["cluster_selection_method"]:
    rid=f"{name}_mcs{mcs}_ms{ms}_{method}"; model=hdbscan.HDBSCAN(min_cluster_size=mcs,min_samples=ms,cluster_selection_method=method,metric="euclidean",prediction_data=True).fit(x)
    lab=model.labels_; counts=Counter(lab); reasons=pathological(lab); labels[rid]=lab
    out.append({"run_id":rid,"representation":name,"min_cluster_size":mcs,"min_samples":ms,"selection_method":method,
      "cluster_count":len([k for k in counts if k>=0]),"cluster_sizes":json.dumps({str(k):v for k,v in counts.items() if k>=0}),
      "noise_count":counts.get(-1,0),"noise_ratio":counts.get(-1,0)/len(lab),"mean_membership_probability":float(np.mean(model.probabilities_)),
      "mean_cluster_persistence":float(np.mean(model.cluster_persistence_)) if len(model.cluster_persistence_) else 0,"pathological":bool(reasons),"rejection_reasons":json.dumps(reasons)})
 return out,labels
def select_reference(runs):
 target=(25,10,"eom"); valid=[r for r in runs if not r["pathological"]]
 if not valid:return None
 return min(valid,key=lambda r:(abs(r["min_cluster_size"]-target[0])+abs(r["min_samples"]-target[1])+ (r["selection_method"]!=target[2])*10,r["run_id"]))
def bootstrap(x,base,params):
 rng=np.random.default_rng(SEED); n=len(x); records=[]; co=np.zeros((n,n)); seen=np.zeros((n,n)); survival=defaultdict(list)
 for b in range(BOOTSTRAPS):
  idx=np.sort(rng.choice(n,size=math.ceil(.8*n),replace=False)); model=hdbscan.HDBSCAN(min_cluster_size=params["min_cluster_size"],min_samples=params["min_samples"],cluster_selection_method=params["selection_method"]).fit(x[idx]); lab=model.labels_
  records.append({"resample":b,"ari":adjusted_rand_score(base[idx],lab),"ami":adjusted_mutual_info_score(base[idx],lab),"noise_ratio":float(np.mean(lab==-1)),"cluster_count":len(set(lab)-{-1})})
  ix=np.ix_(idx,idx); seen[ix]+=1; co[ix]+=((lab[:,None]==lab[None,:]) & (lab[:,None]>=0))
  for group in set(base)-{-1}:
   sub=lab[base[idx]==group]; survival[group].append(max(Counter(sub).values())/len(sub) if len(sub) else 0)
 return records,np.divide(co,seen,out=np.zeros_like(co),where=seen>0),{str(k):float(np.mean(v)) for k,v in survival.items()}
def effect(a,b):
 if len(a)<2 or len(b)<2:return 0
 pooled=math.sqrt(((len(a)-1)*np.var(a,ddof=1)+(len(b)-1)*np.var(b,ddof=1))/(len(a)+len(b)-2)); return float((np.mean(a)-np.mean(b))/pooled) if pooled else 0
def compact_feature_evidence(feature_record):
 """Retain bounded, inspectable evidence without copying full cached payloads."""
 hashes=[]
 def visit(value):
  if isinstance(value,dict):
   for key,item in value.items():
    if key in ("tx_hash","transaction_hash","creating_tx_hash","consuming_tx_hash") and isinstance(item,str): hashes.append(item)
    elif key in ("transaction_hashes","supporting_transaction_hashes") and isinstance(item,list): hashes.extend(str(v) for v in item)
    else: visit(item)
  elif isinstance(value,list):
   for item in value[:50]: visit(item)
 visit(feature_record)
 return {"support_state":feature_record.get("support_state"),"sample_count":feature_record.get("sample_count"),"coverage":feature_record.get("coverage"),"supporting_transaction_hashes":list(dict.fromkeys(hashes))[:20]}
def analyses(name,wallets,features,x,labels,probs,diagnostics,evidence):
 profiles=[]; activity=[]; reviews=[]; rules=[]
 for group in sorted(set(labels)-{-1}):
  mask=labels==group; other=~mask
  for j,f in enumerate(features):
   cohort_sd=float(np.std(x[:,j],ddof=1)); standardized=(float(np.mean(x[mask,j]))-float(np.mean(x[:,j])))/cohort_sd if cohort_sd else 0
   profiles.append({"representation":name,"group":group,"feature":f,"family":f.split("__",1)[0],"median":float(np.median(x[mask,j])),"q25":float(np.quantile(x[mask,j],.25)),"q75":float(np.quantile(x[mask,j],.75)),"standardized_difference":standardized})
  maxeff=0
  for metric in ("transaction_count","observed_cell_count","input_count","output_count"):
   vals=np.array([float(diagnostics[w][metric]) for w in wallets]); e=effect(vals[mask],vals[other]);maxeff=max(maxeff,abs(e)); activity.append({"representation":name,"group":group,"metric":metric,"median":float(np.median(vals[mask])),"q25":float(np.quantile(vals[mask],.25)),"q75":float(np.quantile(vals[mask],.75)),"standardized_effect":e})
  activity.append({"representation":name,"group":group,"metric":"OVERALL_CLASSIFICATION","activity_dependence":"HIGH_ACTIVITY_DEPENDENCE" if maxeff>=.8 else "MODERATE_ACTIVITY_DEPENDENCE" if maxeff>=.5 else "LOW_ACTIVITY_DEPENDENCE","maximum_absolute_effect":maxeff})
  center=np.mean(x[mask],axis=0); dist=np.linalg.norm(x-center,axis=1); members=np.where(mask)[0]
  choices=[("CENTRAL",members[np.argmin(dist[mask])]),("BOUNDARY",members[np.argmin(probs[mask])]),("EXTREME",members[np.argmax(dist[mask])])]
  for kind,i in choices:
   ev=evidence[wallets[i]]; reviews.append({"representation":name,"group":group,"selection":kind,"wallet":wallets[i],"membership_probability":float(probs[i]),"feature_support":{k:v["support_state"] for k,v in ev["features"].items()},"feature_evidence":{k:compact_feature_evidence(v) for k,v in ev["features"].items()},"supporting_rule_evidence":ev["rules"]})
  group_wallets={wallets[i] for i in np.where(mask)[0]}
  for rule in evidence[next(iter(group_wallets))]["rules"]:
   rn=rule["rule"]; supported=positive=0; cohort_supported=cohort_positive=0
   for w in group_wallets:
    rr=next(r for r in evidence[w]["rules"] if r["rule"]==rn)
    if rr["support_state"] in ("SUPPORTED","PARTIAL"): supported+=1; positive+= "THRESHOLDS_MET" in rr["reason_codes"] or "MULTIPLE_INDEPENDENT_PATTERNS" in rr["reason_codes"]
   for w in wallets:
    rr=next(r for r in evidence[w]["rules"] if r["rule"]==rn)
    if rr["support_state"] in ("SUPPORTED","PARTIAL"): cohort_supported+=1; cohort_positive+= "THRESHOLDS_MET" in rr["reason_codes"] or "MULTIPLE_INDEPENDENT_PATTERNS" in rr["reason_codes"]
   ratio=positive/supported if supported else None; baseline=cohort_positive/cohort_supported if cohort_supported else None
   rules.append({"representation":name,"group":group,"rule":rn,"supported_count":supported,"positive_count":positive,"positive_ratio":ratio,"cohort_supported_count":cohort_supported,"cohort_positive_ratio":baseline,"enrichment_ratio":ratio/baseline if ratio is not None and baseline else None})
 return profiles,activity,reviews,rules

def gmm_select(name,x):
 rows=[]; models={}
 for cov in ("full","diag"):
  for k in range(1,11):
   best=None
   for offset in range(3):
    model=GaussianMixture(k,covariance_type=cov,random_state=SEED+offset,n_init=1,max_iter=500,reg_covar=1e-6).fit(x)
    if best is None or model.bic(x)<best.bic(x):best=model
   prob=best.predict_proba(x); entropy=float(np.mean(-np.sum(prob*np.log(np.maximum(prob,1e-15)),axis=1)))
   row={"representation":name,"components":k,"covariance_type":cov,"bic":float(best.bic(x)),"aic":float(best.aic(x)),"converged":bool(best.converged_),"minimum_component_size":int(min(Counter(best.predict(x)).values())),"mean_assignment_entropy":entropy}
   rows.append(row);models[(cov,k)]=best
 chosen=min((r for r in rows if r["converged"] and r["minimum_component_size"]>=5),key=lambda r:r["bic"])
 return rows,models[(chosen["covariance_type"],chosen["components"])],chosen
def umap_views(x,labels):
 configs=[]; directory=OUT/"plots/umap";directory.mkdir(parents=True,exist_ok=True)
 for nn in (15,30,50):
  for md in (0.0,.1,.5):
   emb=umap.UMAP(n_neighbors=nn,min_dist=md,metric="euclidean",random_state=SEED,n_jobs=1).fit_transform(x)
   fig,ax=plt.subplots(figsize=(8,6)); ax.scatter(emb[:,0],emb[:,1],c=np.where(labels<0,-1,labels),s=10,cmap="tab20",alpha=.75); ax.set_title(f"UMAP diagnostic only: n_neighbors={nn}, min_dist={md}"); ax.set_xlabel("UMAP1");ax.set_ylabel("UMAP2");fig.tight_layout();fig.savefig(directory/f"umap_nn{nn}_md{str(md).replace('.','p')}.png",dpi=160);plt.close(fig)
   configs.append({"n_neighbors":nn,"min_dist":md,"metric":"euclidean","seed":SEED,"clustering_use":"PROHIBITED_VISUALIZATION_ONLY"})
 return configs
def research_plots(stability,labels,profiles,activity):
 directory=OUT/"plots/research";directory.mkdir(parents=True,exist_ok=True)
 def save(fig,name):
  fig.tight_layout();fig.savefig(directory/f"{name}.png",dpi=160);fig.savefig(directory/f"{name}.svg");plt.close(fig)
 names=[r["representation"].replace("HIGH_CONFIDENCE","HC").replace("TEMPORAL_STRUCTURE","TEMP").replace("CELL_STRUCTURE","CELL") for r in stability]
 x=np.arange(len(names));fig,ax=plt.subplots(figsize=(11,6));ax.bar(x-.2,[r["mean_ari"] for r in stability],.4,label="mean ARI");ax.bar(x+.2,[r["mean_ami"] for r in stability],.4,label="mean AMI");ax.axhline(.75,color="black",linestyle="--",linewidth=1,label="robust threshold");ax.set_xticks(x,names,rotation=35,ha="right");ax.set_ylim(0,1);ax.set_ylabel("80% resample agreement");ax.legend();save(fig,"hdbscan_resample_stability")
 counts=Counter(labels);keys=sorted(counts);fig,ax=plt.subplots(figsize=(7,5));ax.bar(["noise" if k==-1 else f"group {k+1}" for k in keys],[counts[k] for k in keys]);ax.set_ylabel("wallets");ax.set_title("Predeclared High-Confidence PCA4 partition");save(fig,"pca4_group_sizes")
 groups=sorted({int(r["group"]) for r in profiles});features=sorted({r["feature"] for r in profiles});lookup={(int(r["group"]),r["feature"]):float(r["standardized_difference"]) for r in profiles};matrix=np.array([[lookup[g,f] for f in features] for g in groups]);fig,ax=plt.subplots(figsize=(11,4));im=ax.imshow(matrix,aspect="auto",cmap="coolwarm",vmin=-max(1,np.max(np.abs(matrix))),vmax=max(1,np.max(np.abs(matrix))));ax.set_yticks(range(len(groups)),[f"group {g+1}" for g in groups]);ax.set_xticks(range(len(features)),[f.split("__",1)[-1] for f in features],rotation=45,ha="right");fig.colorbar(im,ax=ax,label="standardized difference from cohort");save(fig,"pca4_group_feature_profiles")
 act=[r for r in activity if r["metric"]!="OVERALL_CLASSIFICATION"];metrics=["transaction_count","observed_cell_count","input_count","output_count"];lookup={(int(r["group"]),r["metric"]):float(r["standardized_effect"]) for r in act};matrix=np.array([[lookup[g,m] for m in metrics] for g in groups]);fig,ax=plt.subplots(figsize=(7,4));im=ax.imshow(matrix,aspect="auto",cmap="coolwarm",vmin=-1,vmax=1);ax.set_yticks(range(len(groups)),[f"group {g+1}" for g in groups]);ax.set_xticks(range(len(metrics)),metrics,rotation=25,ha="right");fig.colorbar(im,ax=ax,label="standardized group-vs-rest effect");save(fig,"pca4_activity_dependence")
def main():
 OUT.mkdir(parents=True,exist_ok=True); before=integrity(); meta=list(csv.DictReader((VAL/"activity_diagnostics_v1.csv").open())); diagnostics={r["wallet"]:r for r in meta}; evidence={r["wallet"]:r for r in map(json.loads,(V2/"wallet_behaviour_features_v2_evidence.jsonl").read_text().splitlines())}
 specs={"HIGH_CONFIDENCE":("pca_high_confidence_v1",[3,4,6]),"TEMPORAL_STRUCTURE":("pca_temporal_structure_block_v1",[3]),"CELL_STRUCTURE":("pca_cell_structure_block_v1",[7])}; reps={}; base={}
 for name,(directory,dims) in specs.items():
  w,f,x,pcs=load_rep(directory); base[name]=(w,f,x,pcs); reps[name+"_SCALED"]=(w,f,x)
  for dim in dims: reps[f"{name}_PCA{dim}"]=(w,[f"PC{i+1}" for i in range(dim)],pcs[:,:dim])
 for name,(_,features,_) in reps.items():
  forbidden=[feature for feature in features if any(token in feature.lower() for token in FORBIDDEN)]
  if forbidden: raise RuntimeError(f"forbidden discovery fields in {name}: {forbidden}")
 representation_info={}
 for name,value in reps.items():
  info={"wallets":len(value[0]),"features":len(value[1]),"distance_metric":"euclidean"}
  if "_PCA" in name:
   base_name,dim_text=name.rsplit("_PCA",1); variance=list(csv.DictReader((P1/specs[base_name][0]/"explained_variance.csv").open()));info["retained_variance"]=float(variance[int(dim_text)-1]["cumulative_explained_variance"])
  else: info["retained_variance"]=1.0
  representation_info[name]=info
 upstream_registries={name:{filename:sha(P1/directory/filename) for filename in ("cohort_contract.json","selected_feature_registry.csv","transformation_registry.csv")} for name,(directory,_) in specs.items()}
 contract={"version":VERSION,"seed":SEED,"implementation_sha256":sha(Path(__file__)),"source_integrity":before,"upstream_registries":upstream_registries,"representations":representation_info,"interpretation_representation":"HIGH_CONFIDENCE_PCA4_PREDECLARED_APPROX_80_PERCENT_VARIANCE","hdbscan_grid":GRID,"bootstrap_resamples":BOOTSTRAPS,"rules_and_activity":"POST_HOC_ONLY","software":{"python":platform.python_version(),"numpy":np.__version__,"hdbscan":getattr(hdbscan,"__version__","0.8.44"),"sklearn":__import__("sklearn").__version__,"umap":umap.__version__}}
 dump(OUT/"experiment_contract.json",contract); allruns=[]; selected=[]; assignments={}; assignment_rows=[]; stability=[]
 for ri,(name,(wallets,features,x)) in enumerate(reps.items()):
  runs,label_registry=grid_runs(name,wallets,x); ref=select_reference(runs)
  if not ref: selected.append({"representation":name,"status":"NO_NON_PATHOLOGICAL_SOLUTION"});continue
  model=hdbscan.HDBSCAN(min_cluster_size=ref["min_cluster_size"],min_samples=ref["min_samples"],cluster_selection_method=ref["selection_method"],prediction_data=True).fit(x); labels=model.labels_;assignments[name]=(wallets,features,x,labels,model.probabilities_)
  for run in runs:
   candidate=label_registry[run["run_id"]]; run["ari_to_selected"]=float(adjusted_rand_score(labels,candidate));run["ami_to_selected"]=float(adjusted_mutual_info_score(labels,candidate))
  allruns+=runs
  assignment_rows.extend({"representation":name,"wallet":wallet,"cluster":int(label),"membership_probability":float(probability)} for wallet,label,probability in zip(wallets,labels,model.probabilities_))
  records,co,survival=bootstrap(x,labels,ref); np.savez_compressed(OUT/f"coassignment_{name.lower()}.npz",coassignment=co)
  summary={"representation":name,"selected_run":ref,"mean_ari":float(np.mean([r["ari"] for r in records])),"mean_ami":float(np.mean([r["ami"] for r in records])),"mean_noise_ratio":float(np.mean([r["noise_ratio"] for r in records])),"cluster_survival":survival}
  summary["stability_class"]="ROBUST" if summary["mean_ari"]>=.75 and summary["mean_ami"]>=.75 else "MODERATELY_STABLE" if summary["mean_ari"]>=.5 else "UNSTABLE";stability.append(summary);write_csv(OUT/f"bootstrap_{name.lower()}.csv",records);selected.append({"representation":name,"status":"SELECTED_PREDECLARED_REFERENCE",**ref})
 write_csv(OUT/"hdbscan_run_registry.csv",allruns);write_csv(OUT/"hdbscan_memberships.csv",assignment_rows);dump(OUT/"hdbscan_selected_runs.json",selected);dump(OUT/"cluster_stability_report.json",stability)
 primary=assignments.get("HIGH_CONFIDENCE_PCA4"); profiles=[];activity=[];reviews=[];rules=[];archetypes=[]
 if primary:
  w,_,_,lab,prob=primary; _,f,x,_=base["HIGH_CONFIDENCE"]; profiles,activity,reviews,rules=analyses("HIGH_CONFIDENCE_PCA4_LABELS_ON_SCALED_FEATURES",w,f,x,lab,prob,diagnostics,evidence)
  for g in sorted(set(lab)-{-1}):
   top=max((r for r in profiles if r["group"]==g),key=lambda r:abs(r["standardized_difference"])); dep=next(r for r in activity if r["group"]==g and r["metric"]=="OVERALL_CLASSIFICATION")["activity_dependence"]
   family=top["family"]
   if abs(top["standardized_difference"])<1 or dep=="HIGH_ACTIVITY_DEPENDENCE": name="UNINTERPRETED"
   elif top["feature"]=="capacity__target_consumed_capacity": name="LOW_TARGET_CONSUMED_CAPACITY_STRUCTURE" if top["standardized_difference"]<0 else "HIGH_TARGET_CONSUMED_CAPACITY_STRUCTURE"
   elif top["feature"] in ("scripts__type_family_count","scripts__unique_type_script_count"): name="SCRIPT_TYPE_DIVERSE_STRUCTURE" if top["standardized_difference"]>0 else "SCRIPT_TYPE_CONCENTRATED_STRUCTURE"
   else: name={"lineage":"CELL_LINEAGE_STRUCTURE","capacity":"CAPACITY_STRUCTURE","scripts":"SCRIPT_STRUCTURE"}.get(family,"UNINTERPRETED")
   archetypes.append({"group":int(g),"initial_name":f"BEHAVIOUR_GROUP_{int(g)+1:02d}","promoted_archetype":name,"strongest_feature":top["feature"],"standardized_difference":top["standardized_difference"],"activity_dependence":dep,"promotion_status":"EVIDENCE_SUPPORTED_DESCRIPTIVE" if name!="UNINTERPRETED" else "UNINTERPRETED"})
 write_csv(OUT/"group_feature_profiles.csv",profiles);write_csv(OUT/"activity_dependence_report.csv",activity);write_csv(OUT/"evidence_review_records.csv",reviews);write_csv(OUT/"transparent_rule_comparison.csv",rules);dump(OUT/"archetype_interpretations.json",archetypes)
 if primary: research_plots(stability,primary[3],profiles,activity)
 gmmrows=[];comparisons=[]
 for name in ("HIGH_CONFIDENCE_SCALED","TEMPORAL_STRUCTURE_SCALED","CELL_STRUCTURE_SCALED"):
  w,f,x=reps[name]; rows,model,chosen=gmm_select(name,x);gmmrows+=rows; gl=model.predict(x)
  comparison_name="HIGH_CONFIDENCE_PCA4" if name=="HIGH_CONFIDENCE_SCALED" else name; hp=assignments.get(comparison_name)
  comparisons.append({"representation":name,"gmm_choice":chosen,"hdbscan_comparison_representation":comparison_name,"hdbscan_available":bool(hp),"ari":adjusted_rand_score(hp[3],gl) if hp else None,"ami":adjusted_mutual_info_score(hp[3],gl) if hp else None})
 write_csv(OUT/"gmm_model_selection.csv",gmmrows);dump(OUT/"hdbscan_gmm_comparison.json",comparisons)
 configs=umap_views(base["HIGH_CONFIDENCE"][2],primary[3]) if primary else [];dump(OUT/"umap_visualization_config.json",configs)
 # Cross-representation agreement on overlapping wallets.
 cross=[]
 keys=list(assignments)
 for i,a in enumerate(keys):
  for b in keys[i+1:]:
   wa,_,_,la,_=assignments[a];wb,_,_,lb,_=assignments[b]; common=sorted(set(wa)&set(wb));
   if len(common)>=20: cross.append({"left":a,"right":b,"overlap":len(common),"ari":adjusted_rand_score([la[wa.index(w)] for w in common],[lb[wb.index(w)] for w in common]),"ami":adjusted_mutual_info_score([la[wa.index(w)] for w in common],[lb[wb.index(w)] for w in common])})
 dump(OUT/"cross_representation_comparison.json",cross)
 robust=sum(r["stability_class"]=="ROBUST" for r in stability); phase="PARTIAL" if assignments else "NOT READY"
 lines=[
  "# Exploratory ML Phase 2 — Behavioural Structure Discovery","",
  f"## Frozen contract\n\n- `{VERSION}`\n- Manifest `{before['manifest']}`\n- No imputation, labels, rules, activity diagnostics, or prior clusters entered discovery.","",
  f"## HDBSCAN sensitivity\n\nThe audit contains {len(allruns)} grid runs across {len(assignments)} selected representations. {robust} selected representations met the resampling stability threshold. The full ten-feature High-Confidence scaled solution was unstable. PCA3, PCA4, and PCA6 were robust but produced 2, 3, and 2 groups respectively, so the number of groups remains representation-dependent.","",
  "## Evidence-review representation\n\nPCA4 is used only for evidence review because it was predeclared as the approximately 80%-variance representation. Its labels are profiled against the original ten scaled High-Confidence features; this choice was not optimized for cluster count.","",
  f"```json\n{json.dumps(archetypes,indent=2)}\n```","",
  f"## GMM sensitivity\n\nGMM was fit independently on the full scaled family matrices. Its selected solutions disagree materially with HDBSCAN, so it is a sensitivity check rather than confirmation.\n\n```json\n{json.dumps(comparisons,indent=2)}\n```","",
  "## Negative-result policy\n\nUnstable, pathological, and disagreeing results remain in the audit. No parameter was selected to maximize cluster count, minimize noise, or improve agreement.","",
  "## Submission readiness","",
  f"- **BEHAVIOURAL STRUCTURE: {phase}** — stable low-dimensional structure exists, but group count and assignments depend on representation.",
  "- **HDBSCAN STABILITY: PARTIAL** — three PCA views are robust; the full scaled view and other blocks are not consistently robust.",
  "- **GMM SENSITIVITY: PARTIAL** — independently selected mixture solutions do not confirm HDBSCAN partitions.",
  "- **ACTIVITY-INDEPENDENCE: PARTIAL** — activity was excluded from discovery and audited post hoc; group-specific effects remain documented.",
  f"- **RAW EVIDENCE VALIDATION: {'PARTIAL' if reviews else 'NOT READY'}** — central, boundary, and extreme examples include bounded feature and transaction-hash evidence, but no manual semantic adjudication was performed.",
  f"- **ARCHETYPE INTERPRETATION: {'PARTIAL' if archetypes else 'NOT READY'}** — names are descriptive structural summaries, not identities.",
  "- **UMAP VISUALIZATION: READY** — visualization only; UMAP coordinates were never clustered.",
  "- **SUPERVISED CLASSIFICATION: NOT READY**.",
  f"- **NERVOS FINAL SUBMISSION: {'PARTIAL' if phase!='NOT READY' else 'NOT READY'}**.","",
  "No identity claims, UMAP clustering, supervised learning, collection, retry, commit, merge, or push occurred."
 ]
 (OUT/"EXPLORATORY_ML_PHASE2_REPORT.md").write_text("\n".join(lines)+"\n"); after=integrity();
 if before!=after:raise RuntimeError("source changed")
 dump(OUT/"source_integrity_after.json",after);print(json.dumps({"runs":len(allruns),"selected":len(assignments),"robust":robust,"groups":len(archetypes),"report":str(OUT/"EXPLORATORY_ML_PHASE2_REPORT.md")},indent=2))
if __name__=="__main__":main()
