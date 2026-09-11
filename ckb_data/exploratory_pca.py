from __future__ import annotations

import csv
import hashlib
import itertools
import json
import math
import platform
import sqlite3
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
VALIDATION = ROOT / "feature_validation"
V2 = ROOT / "feature_engineering_v2"
DB = ROOT / "ckb_data_v2" / "ckb_explorer.sqlite"
OUT = ROOT / "exploratory_ml_pca_v1"

EXPERIMENT_VERSION = "ckb-exploratory-ml-pca-v1"
SEED = 20260902
RESAMPLES = 500
RESAMPLE_FRACTION = .80
MIN_WALLETS = 100
MIN_RATIO = 5.0
ACTIVITY_LOW = .50
ACTIVITY_HIGH = .80
FAMILY_DOMINANCE = .60
DEGENERATE_GAP = .10
SOURCE_FILES = [
    V2 / "wallet_behaviour_features_v2.csv",
    V2 / "wallet_behaviour_features_v2_ml.csv",
    V2 / "wallet_behaviour_features_v2_metadata.csv",
    V2 / "wallet_behaviour_features_v2_evidence.jsonl",
    V2 / "feature_definitions_v2.json",
    VALIDATION / "high_confidence.csv",
    VALIDATION / "low_redundancy_core.csv",
    VALIDATION / "candidate_matrix_metadata_v1.csv",
    VALIDATION / "predictor_registry_v1.csv",
    VALIDATION / "activity_diagnostics_v1.csv",
    VALIDATION / "candidate_feature_sets_v1.json",
]


def dump(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict], columns: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = columns or sorted({key for row in rows for key in row})
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_integrity() -> dict:
    contract = json.loads((V2 / "dataset_v1_snapshot/dataset_contract_v1.json").read_text())
    if DB.stat().st_size != contract["source_database"]["bytes"] or sha256(DB) != contract["source_database"]["sha256"]:
        raise RuntimeError("frozen database digest changed")
    conn = sqlite3.connect(f"file:{DB.resolve()}?mode=ro", uri=True)
    quick = conn.execute("PRAGMA quick_check").fetchone()[0]; conn.close()
    if quick != "ok":
        raise RuntimeError("SQLite integrity failed")
    return {"manifest_hash": contract["manifest_hash"], "database": contract["source_database"],
            "sqlite_quick_check": quick,
            "artifacts": {str(path.relative_to(ROOT.parent)): {"bytes": path.stat().st_size,
                                                                  "sha256": sha256(path)}
                          for path in SOURCE_FILES}}


def read_matrix(name: str) -> tuple[list[str], list[list[float | None]]]:
    with (VALIDATION / name).open() as handle:
        reader = csv.DictReader(handle); features = list(reader.fieldnames or [])
        rows = [[float(row[feature]) if row[feature] != "" else None for feature in features]
                for row in reader]
    return features, rows


def complete_cases(rows: list[list[float | None]]) -> list[int]:
    return [index for index, row in enumerate(rows) if all(value is not None for value in row)]


def signed_log1p(values: np.ndarray) -> np.ndarray:
    return np.sign(values) * np.log1p(np.abs(values))


def transform_column(values: np.ndarray, feature: str) -> tuple[np.ndarray, dict]:
    if feature.endswith(("_ratio", "_repetition")) or (np.any(values < 0) and
            feature != "capacity__target_net_capacity_delta"):
        transformed = values.copy(); initial = "IDENTITY"
        center = float(np.mean(transformed)); scale = float(np.std(transformed, ddof=0))
        scaler = "STANDARD_SCALER"
        if scale == 0:
            scale = 1.0
    else:
        if feature == "capacity__target_net_capacity_delta":
            transformed = signed_log1p(values); initial = "SIGNED_LOG1P"
        else:
            transformed = np.log1p(values); initial = "LOG1P"
        center = float(np.median(transformed))
        q25, q75 = np.quantile(transformed, [.25, .75])
        scale = float(q75 - q25); scaler = "ROBUST_SCALER_MEDIAN_IQR"
        if scale == 0:
            center = float(np.mean(transformed)); scale = float(np.std(transformed, ddof=0))
            scaler = "STANDARD_SCALER_ZERO_IQR_FALLBACK"
            if scale == 0:
                scale = 1.0
    scaled = (transformed - center) / scale
    return scaled, {"feature": feature, "initial_transform": initial, "scaler": scaler,
                    "center": center, "scale": scale, "raw_min": float(np.min(values)),
                    "raw_max": float(np.max(values)), "transformed_min": float(np.min(transformed)),
                    "transformed_max": float(np.max(transformed))}


def transform_matrix(raw: np.ndarray, features: list[str]) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    scaled, transformed, registry = np.empty_like(raw), np.empty_like(raw), []
    for index, feature in enumerate(features):
        scaled[:, index], record = transform_column(raw[:, index], feature)
        if record["initial_transform"] == "IDENTITY":
            transformed[:, index] = raw[:, index]
        elif record["initial_transform"] == "SIGNED_LOG1P":
            transformed[:, index] = signed_log1p(raw[:, index])
        else:
            transformed[:, index] = np.log1p(raw[:, index])
        registry.append(record)
    return transformed, scaled, registry


def fit_pca(scaled: np.ndarray) -> dict:
    means = scaled.mean(axis=0)
    centered = scaled - means
    covariance = np.cov(centered, rowvar=False, ddof=1)
    eigenvalues, vectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues)[::-1]
    eigenvalues = np.maximum(eigenvalues[order], 0.0)
    components = vectors[:, order].T
    scores = centered @ components.T
    total = eigenvalues.sum()
    ratios = eigenvalues / total if total else np.zeros_like(eigenvalues)
    return {"means": means, "eigenvalues": eigenvalues, "components": components,
            "scores": scores, "explained_variance_ratio": ratios,
            "cumulative_variance": np.cumsum(ratios)}


def average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort"); ranks = np.empty(len(values), dtype=float)
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[order[end]] == values[order[start]]:
            end += 1
        ranks[order[start:end]] = (start + 1 + end) / 2
        start = end
    return ranks


def correlation(left: np.ndarray, right: np.ndarray) -> tuple[float | None, float | None]:
    if len(left) < 3 or np.std(left) == 0 or np.std(right) == 0:
        return None, None
    return float(np.corrcoef(left, right)[0, 1]), float(np.corrcoef(average_ranks(left), average_ranks(right))[0, 1])


def feasible(n: int, p: int) -> tuple[bool, str]:
    accepted = n >= MIN_WALLETS and n / p >= MIN_RATIO
    return accepted, ("ACCEPTED" if accepted else
                      f"REJECTED: requires n>={MIN_WALLETS} and n/p>={MIN_RATIO}; observed n={n}, p={p}, n/p={n/p:.3f}")


def align_first_five(reference: np.ndarray, candidate: np.ndarray) -> tuple[np.ndarray, list[int], list[float]]:
    k = min(5, reference.shape[0], candidate.shape[0])
    similarities = np.abs(reference[:k] @ candidate[:k].T)
    permutation = max(itertools.permutations(range(k)),
                      key=lambda perm: sum(similarities[index, perm[index]] for index in range(k)))
    aligned = candidate.copy(); cosines = []
    for index, selected in enumerate(permutation):
        vector = candidate[selected].copy()
        signed = float(reference[index] @ vector)
        if signed < 0: vector *= -1
        aligned[index] = vector; cosines.append(abs(signed))
    return aligned, list(permutation), cosines


def bootstrap_stability(scaled: np.ndarray, reference: dict, seed: int) -> dict:
    rng = np.random.default_rng(seed); n = len(scaled); sample_size = math.ceil(n * RESAMPLE_FRACTION)
    k = min(5, scaled.shape[1]); cosine_values = [[] for _ in range(k)]
    order_retention = [0] * k; subspace = []
    relative_gaps = []
    eigen = reference["eigenvalues"]
    for index in range(k - 1):
        relative_gaps.append(abs(eigen[index] - eigen[index + 1]) / max(eigen[index], 1e-12))
    degenerate_groups = [(index, index + 1) for index, gap in enumerate(relative_gaps) if gap <= DEGENERATE_GAP]
    for _ in range(RESAMPLES):
        indices = rng.choice(n, size=sample_size, replace=True)
        fitted = fit_pca(scaled[indices])
        aligned, permutation, cosines = align_first_five(reference["components"], fitted["components"])
        for index, value in enumerate(cosines):
            cosine_values[index].append(value)
            order_retention[index] += permutation[index] == index
        for left, right in degenerate_groups:
            singular = np.linalg.svd(reference["components"][[left, right]] @
                                     aligned[[left, right]].T, compute_uv=False)
            subspace.append({"group": f"PC{left+1}-PC{right+1}",
                             "minimum_canonical_correlation": float(np.min(singular))})
    components = []
    for index, values in enumerate(cosine_values):
        components.append({"component": f"PC{index+1}", "resamples": RESAMPLES,
                           "median_absolute_loading_cosine": float(np.median(values)),
                           "p05_absolute_loading_cosine": float(np.quantile(values, .05)),
                           "p95_absolute_loading_cosine": float(np.quantile(values, .95)),
                           "unpermuted_order_retention_ratio": order_retention[index] / RESAMPLES,
                           "stability": "STABLE" if np.median(values) >= .90 else
                                        "MODERATE" if np.median(values) >= .75 else "UNSTABLE"})
    groups = []
    for name in sorted({row["group"] for row in subspace}):
        values = [row["minimum_canonical_correlation"] for row in subspace if row["group"] == name]
        groups.append({"component_group": name, "relative_eigenvalue_gap_threshold": DEGENERATE_GAP,
                       "median_minimum_canonical_correlation": float(np.median(values)),
                       "p05_minimum_canonical_correlation": float(np.quantile(values, .05))})
    return {"method": "80_PERCENT_BOOTSTRAP_WITH_REPLACEMENT", "seed": seed,
            "sample_size": sample_size, "resamples": RESAMPLES,
            "component_stability": components, "near_degenerate_eigenspaces": groups}


def variance_table(pca: dict) -> tuple[list[dict], dict]:
    rows = [{"component": f"PC{index+1}", "eigenvalue": float(value),
             "explained_variance_ratio": float(pca["explained_variance_ratio"][index]),
             "cumulative_explained_variance": float(pca["cumulative_variance"][index])}
            for index, value in enumerate(pca["eigenvalues"])]
    thresholds = {}
    for threshold in (.50, .70, .80, .90, .95):
        thresholds[str(threshold)] = int(np.searchsorted(pca["cumulative_variance"], threshold) + 1)
    return rows, thresholds


def loading_tables(pca: dict, features: list[str], registry: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    rows, families = [], []
    for component_index, vector in enumerate(pca["components"]):
        absolute_sum = np.abs(vector).sum()
        family_values = defaultdict(float)
        for feature_index, coefficient in enumerate(vector):
            feature = features[feature_index]; family = registry[feature]["family"]
            correlation_loading = coefficient * math.sqrt(pca["eigenvalues"][component_index])
            row = {"component": f"PC{component_index+1}", "feature": feature, "family": family,
                   "coefficient": float(coefficient), "absolute_coefficient": float(abs(coefficient)),
                   "correlation_loading": float(correlation_loading),
                   "squared_contribution": float(coefficient ** 2),
                   "absolute_loading_share": float(abs(coefficient) / absolute_sum)}
            rows.append(row); family_values[family] += row["absolute_loading_share"]
        dominant = max(family_values, key=family_values.get)
        for family, contribution in sorted(family_values.items()):
            families.append({"component": f"PC{component_index+1}", "family": family,
                             "absolute_loading_contribution": contribution,
                             "dominant_family": dominant,
                             "single_family_dominance": family_values[dominant] >= FAMILY_DOMINANCE})
    return rows, families


def score_diagnostics(scores: np.ndarray, wallets: list[str], evidence_path: str) -> tuple[list[dict], list[dict]]:
    summaries, extremes = [], []
    for index in range(min(5, scores.shape[1])):
        values = scores[:, index]
        summaries.append({"component": f"PC{index+1}", "mean": float(np.mean(values)),
                          "median": float(np.median(values)), "std": float(np.std(values)),
                          "p01": float(np.quantile(values, .01)), "p05": float(np.quantile(values, .05)),
                          "p25": float(np.quantile(values, .25)), "p75": float(np.quantile(values, .75)),
                          "p95": float(np.quantile(values, .95)), "p99": float(np.quantile(values, .99)),
                          "min": float(np.min(values)), "max": float(np.max(values))})
        order = np.argsort(values)
        for side, selected in (("LOWER", order[:5]), ("UPPER", order[-5:][::-1])):
            for rank, row_index in enumerate(selected, 1):
                extremes.append({"component": f"PC{index+1}", "tail": side, "rank": rank,
                                 "wallet": wallets[row_index], "score": float(values[row_index]),
                                 "evidence_artifact": evidence_path})
    return summaries, extremes


def activity_audit(scores: np.ndarray, wallets: list[str], diagnostics: dict[str, dict]) -> list[dict]:
    output = []
    for component in range(min(5, scores.shape[1])):
        for metric in ("transaction_count", "observed_cell_count", "input_count", "output_count"):
            right = np.array([float(diagnostics[wallet][metric]) for wallet in wallets])
            p, s = correlation(scores[:, component], right)
            maximum = max(abs(p or 0), abs(s or 0))
            output.append({"component": f"PC{component+1}", "diagnostic": metric,
                           "pearson": p, "spearman": s, "absolute_maximum": maximum,
                           "association": "HIGH_ACTIVITY_ASSOCIATION" if maximum >= ACTIVITY_HIGH else
                                          "MODERATE_ACTIVITY_ASSOCIATION" if maximum >= ACTIVITY_LOW else
                                          "LOW_ACTIVITY_ASSOCIATION"})
    return output


class Plot:
    def __init__(self, title: str, width: int = 1000, height: int = 700):
        self.width, self.height = width, height
        self.image = Image.new("RGB", (width, height), "white")
        self.draw = ImageDraw.Draw(self.image); self.svg = []
        self.text(30, 20, title, "#111827")

    def line(self, points, color="#2563eb", width=2):
        self.draw.line(points, fill=color, width=width)
        self.svg.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="{color}" stroke-width="{width}"/>')

    def circle(self, x, y, radius=2, color="#2563eb"):
        self.draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=color)
        self.svg.append(f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{color}"/>')

    def rect(self, box, color):
        self.draw.rectangle(box, fill=color)
        x1,y1,x2,y2=box; self.svg.append(f'<rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="{color}"/>')

    def text(self, x, y, value, color="#111827"):
        self.draw.text((x, y), str(value), fill=color, font=ImageFont.load_default())
        safe = str(value).replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
        self.svg.append(f'<text x="{x}" y="{y+10}" font-size="12" fill="{color}">{safe}</text>')

    def save(self, base: Path):
        base.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(base.with_suffix(".png"))
        base.with_suffix(".svg").write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}">' +
            "".join(self.svg) + "</svg>\n")


def scale_points(x: np.ndarray, y: np.ndarray, width=1000, height=700):
    margin = 70; xmin,xmax=float(x.min()),float(x.max()); ymin,ymax=float(y.min()),float(y.max())
    dx=max(xmax-xmin,1e-12); dy=max(ymax-ymin,1e-12)
    return [(margin+(float(a)-xmin)/dx*(width-2*margin), height-margin-(float(b)-ymin)/dy*(height-2*margin))
            for a,b in zip(x,y)]


def generate_plots(directory: Path, pca: dict, features: list[str], loadings: list[dict], families: list[dict]):
    ratios=pca["explained_variance_ratio"]; cumulative=pca["cumulative_variance"]
    for name, values, title in (("scree",ratios,"Explained variance by component"),
                               ("cumulative_variance",cumulative,"Cumulative explained variance")):
        plot=Plot(title); x=np.arange(1,len(values)+1); points=scale_points(x,np.array(values))
        plot.line([(70,630),(930,630)],"#9ca3af",1); plot.line([(70,70),(70,630)],"#9ca3af",1)
        plot.line(points); [plot.circle(a,b,4) for a,b in points]
        plot.text(440,660,"Principal component"); plot.text(5,340,"Variance ratio")
        plot.save(directory/name)
    for left,right in ((0,1),(0,2),(1,2)):
        plot=Plot(f"Uncolored PCA scores: PC{left+1} vs PC{right+1}")
        plot.line([(70,630),(930,630)],"#9ca3af",1); plot.line([(70,70),(70,630)],"#9ca3af",1)
        for x,y in scale_points(pca["scores"][:,left],pca["scores"][:,right]): plot.circle(x,y,2,"#374151")
        plot.text(470,660,f"PC{left+1} score"); plot.text(5,340,f"PC{right+1} score")
        plot.save(directory/f"pc{left+1}_vs_pc{right+1}")
    first=min(5,len(features)); matrix=np.array([[row["coefficient"] for row in loadings if row["component"]==f"PC{pc+1}"]
                                                for pc in range(first)])
    plot=Plot("PCA coefficient heatmap",1200,max(500,100+len(features)*18)); cell_w=140; cell_h=18
    for row in range(len(features)):
        plot.text(10,70+row*cell_h,features[row][:65])
        for pc in range(first):
            value=matrix[pc,row]; intensity=int(min(255,abs(value)*500))
            color=f"#{255-intensity:02x}{255-intensity:02x}{255 if value>=0 else 255-intensity:02x}"
            plot.rect((600+pc*cell_w,70+row*cell_h,600+(pc+1)*cell_w-2,70+(row+1)*cell_h-2),color)
    for pc in range(first): plot.text(650+pc*cell_w,48,f"PC{pc+1}")
    plot.save(directory/"loading_heatmap")
    plot=Plot("Absolute loading contribution by feature family")
    palette={"capacity":"#2563eb","lineage":"#16a34a","scripts":"#ea580c","temporal":"#7c3aed",
             "templates":"#0891b2","topology":"#dc2626","lifecycle":"#ca8a04","periodicity":"#4b5563"}
    grouped=defaultdict(dict)
    for row in families: grouped[row["component"]][row["family"]]=row["absolute_loading_contribution"]
    for index,(component,values) in enumerate(sorted(grouped.items())[:5]):
        x1=100+index*170; bottom=620
        for family,value in sorted(values.items()):
            height=value*500; plot.rect((x1,bottom-height,x1+100,bottom),palette.get(family,"#9ca3af")); bottom-=height
        plot.text(x1,640,component)
    for index,(family,color) in enumerate(sorted(palette.items())):
        plot.rect((620,40+index*18,635,55+index*18),color); plot.text(642,40+index*18,family)
    plot.save(directory/"family_contribution")


def run_experiment(name: str, features: list[str], rows: list[list[float | None]], row_indices: list[int],
                   wallets_all: list[str], registry: dict[str, dict], diagnostics: dict[str, dict], seed: int) -> dict:
    directory=OUT/name.lower(); directory.mkdir(parents=True,exist_ok=True)
    wallets=[wallets_all[index] for index in row_indices]
    raw=np.array([[rows[index][column] for column in range(len(features))] for index in row_indices],dtype=float)
    transformed,scaled,transformation_registry=transform_matrix(raw,features)
    pca=fit_pca(scaled); variance,thresholds=variance_table(pca)
    loadings,family_contributions=loading_tables(pca,features,registry)
    score_summary,extremes=score_diagnostics(pca["scores"],wallets,
        str(V2/"wallet_behaviour_features_v2_evidence.jsonl"))
    activity=activity_audit(pca["scores"],wallets,diagnostics)
    stability=bootstrap_stability(scaled,pca,seed)
    component_rows=[]
    for index in range(len(features)):
        component=f"PC{index+1}"; component_loadings=[row for row in loadings if row["component"]==component]
        positive=sorted(component_loadings,key=lambda row:-row["coefficient"])[:3]
        negative=sorted(component_loadings,key=lambda row:row["coefficient"])[:3]
        component_rows.append({"component":component,"eigenvalue":float(pca["eigenvalues"][index]),
            "explained_variance_ratio":float(pca["explained_variance_ratio"][index]),
            "cumulative_explained_variance":float(pca["cumulative_variance"][index]),
            "strongest_positive_loadings":json.dumps([{r["feature"]:r["coefficient"]} for r in positive]),
            "strongest_negative_loadings":json.dumps([{r["feature"]:r["coefficient"]} for r in negative]),
            "families_represented":json.dumps(sorted({row["family"] for row in component_loadings}))})
    selected=[]
    for feature in features:
        selected.append({key:registry[feature].get(key) for key in
                         ("predictor","family","definition","support_requirement","unit","missing_semantics",
                          "recommended_transform","transformation_reason","audit_classification")})
        selected[-1]["reason_retained"]="Validated candidate-set membership; complete-case availability; no prohibited metadata or rule output."
    raw_rows=[]
    for row_index,wallet in enumerate(wallets):
        for column,feature in enumerate(features):
            raw_rows.append({"wallet":wallet,"feature":feature,"raw_value":float(raw[row_index,column]),
                             "transformed_value":float(transformed[row_index,column]),
                             "scaled_value":float(scaled[row_index,column])})
    score_rows=[{"wallet":wallet,**{f"PC{i+1}":float(pca["scores"][row_index,i])
                                     for i in range(pca["scores"].shape[1])}}
                for row_index,wallet in enumerate(wallets)]
    write_csv(directory/"selected_feature_registry.csv",selected)
    write_csv(directory/"transformation_registry.csv",transformation_registry)
    write_csv(directory/"raw_transformed_scaled_values.csv",raw_rows)
    write_csv(directory/"explained_variance.csv",variance)
    write_csv(directory/"pca_component_table.csv",component_rows)
    write_csv(directory/"loading_matrix.csv",loadings)
    write_csv(directory/"pca_scores.csv",score_rows)
    write_csv(directory/"activity_correlations.csv",activity)
    write_csv(directory/"family_contributions.csv",family_contributions)
    write_csv(directory/"score_diagnostics.csv",score_summary)
    write_csv(directory/"extreme_wallets.csv",extremes)
    dump(directory/"bootstrap_stability.json",stability)
    dump(directory/"variance_thresholds.json",thresholds)
    dump(directory/"cohort_contract.json",{"experiment":name,"wallet_count":len(wallets),
         "feature_count":len(features),"wallets_per_feature":len(wallets)/len(features),
         "wallets":wallets,"features":features,"missing_policy":"COMPLETE_CASE_NO_IMPUTATION"})
    generate_plots(directory/"plots",pca,features,loadings,family_contributions)
    max_activity=max((row["absolute_maximum"] for row in activity),default=0)
    first_five=stability["component_stability"]
    family_pc={component:max((row for row in family_contributions if row["component"]==component),
                            key=lambda row:row["absolute_loading_contribution"])
               for component in [f"PC{i+1}" for i in range(min(5,len(features)))]}
    top_loadings={row["component"]:{"positive":json.loads(row["strongest_positive_loadings"]),
                                    "negative":json.loads(row["strongest_negative_loadings"])}
                  for row in component_rows[:5]}
    strongest_activity={component:max((row for row in activity if row["component"]==component),
                                      key=lambda row:row["absolute_maximum"])
                        for component in [f"PC{i+1}" for i in range(min(5,len(features)))]}
    return {"name":name,"status":"EXECUTED","n_wallets":len(wallets),"n_features":len(features),
            "wallets_per_feature":len(wallets)/len(features),"features":features,
            "variance_thresholds":thresholds,"pc1_variance":variance[0]["explained_variance_ratio"],
            "pc1_pc2_variance":variance[min(1,len(variance)-1)]["cumulative_explained_variance"],
            "first_3_variance":variance[min(2,len(variance)-1)]["cumulative_explained_variance"],
            "first_5_variance":variance[min(4,len(variance)-1)]["cumulative_explained_variance"],
            "maximum_pc1_pc5_activity_association":max_activity,
            "high_activity_component_relationships":sum(row["association"]=="HIGH_ACTIVITY_ASSOCIATION" for row in activity),
            "median_pc1_pc5_loading_stability":statistics.median(row["median_absolute_loading_cosine"] for row in first_five),
            "top_loadings_pc1_pc5":top_loadings,"strongest_activity_pc1_pc5":strongest_activity,
            "dominant_families_pc1_pc5":{key:{"family":value["family"],
                "contribution":value["absolute_loading_contribution"],
                "single_family_dominance":value["single_family_dominance"]} for key,value in family_pc.items()},
            "output_directory":str(directory)}


def report(contract: dict, decisions: list[dict], results: list[dict]) -> Path:
    by={row["name"]:row for row in results}; primary=by["PCA_HIGH_CONFIDENCE_V1"]
    high_activity=primary["high_activity_component_relationships"]>0
    primary_status="READY" if primary["median_pc1_pc5_loading_stability"]>=.75 else "PARTIAL"
    activity_status="PARTIAL" if high_activity else "READY"
    next_control=("Run a separate activity-control sensitivity experiment using removal or ratio normalization; do not residualize the frozen representation in place."
                  if high_activity else "Retain the representation for the next sensitivity stage while continuing post-hoc activity audits.")
    lines=["# Exploratory ML Phase 1 — PCA and Feature-Space Diagnostics","",
           "## A. Frozen-source verification","",f"- Manifest: `{contract['source_integrity']['manifest_hash']}`",
           f"- Database: `{contract['source_integrity']['database']['sha256']}`","- SQLite: `ok`","- Source artifacts unchanged before/after execution.","",
           "## B. ML experiment contract","",f"- Experiment: `{EXPERIMENT_VERSION}`",f"- Seed: `{SEED}`",
           "- Missing-data policy: complete cases only; no imputation.","- PCA: centered covariance eigendecomposition using NumPy.","",
           "## C. High-Confidence cohort","",f"Confirmed: **{primary['n_wallets']} wallets × {primary['n_features']} features**.","",
           "## D. Transformations","","Bounded ratios use StandardScaler. Non-negative magnitudes use log1p then median/IQR scaling. Signed net capacity uses signed-log1p. Zero-IQR columns fall back to mean/std scaling; every decision is recorded.","",
           "## E. PCA variance results","",f"- PC1: {primary['pc1_variance']:.4f}",f"- PC1+PC2: {primary['pc1_pc2_variance']:.4f}",
           f"- First 3: {primary['first_3_variance']:.4f}",f"- First 5: {primary['first_5_variance']:.4f}",f"- PCs needed: `{primary['variance_thresholds']}`","",
           "## F. Component loadings","","Components retain neutral PC names. Strongest signed loadings:","","```json",
           json.dumps(primary["top_loadings_pc1_pc5"],indent=2,sort_keys=True),"```","",
           "## G. Activity-volume correlations","",f"Maximum PC1–PC5 activity correlation: **{primary['maximum_pc1_pc5_activity_association']:.4f}**.",
           f"High-association diagnostic relationships: **{primary['high_activity_component_relationships']}**.","","```json",
           json.dumps(primary["strongest_activity_pc1_pc5"],indent=2,sort_keys=True),"```","",
           "## H. Feature-family contribution","","```json",json.dumps(primary["dominant_families_pc1_pc5"],indent=2,sort_keys=True),"```","",
           "Absent temporal/topology/template/lifecycle families are a limitation of High-Confidence support, not evidence that those behaviours are unimportant.","",
           "## I. PCA score and extreme-wallet review","","PC1–PC5 distributions and five upper/lower extremes are exported with wallet identifiers and evidence-artifact references. No outlier was deleted.","",
           "## J. Bootstrap stability","",f"Median PC1–PC5 loading cosine: **{primary['median_pc1_pc5_loading_stability']:.4f}** across {RESAMPLES} deterministic resamples.","",
           "## K. Low-Redundancy Core feasibility","","```json",json.dumps(decisions,indent=2,sort_keys=True),"```","",
           "## L. Family-block PCA results","","```json",json.dumps([row for row in results if row['name']!='PCA_HIGH_CONFIDENCE_V1'],indent=2,sort_keys=True),"```","",
           "## M. Cross-experiment comparison","","Valid experiments are compared by variance concentration, family contribution, activity association, and component stability. Different feature spaces are not expected to yield identical components.","",
           "## N. Recommended primary feature representation","","Keep **High-Confidence** as the clean complete-case reference representation. Use the accepted Temporal and Cell blocks as complementary behavioural-coverage sensitivity experiments; do not replace the reference with the 28×59 Low-Redundancy matrix.","",
           "## O. Recommended next ML experiment","",next_control,"Review PCA geometry and activity axes before defining any UMAP or clustering experiment.","",
           "## P. Readiness","",f"- **PCA HIGH-CONFIDENCE: {primary_status}** — complete-case reference executed and stability measured.",
           "- **PCA LOW-REDUNDANCY: NOT READY** — 28×59 fails the locked feasibility gate.",
           f"- **ACTIVITY-VOLUME CONTROL: {activity_status}** — diagnostics complete; separate control experiment required only if high association is present.",
           f"- **COMPONENT STABILITY: {'READY' if primary['median_pc1_pc5_loading_stability']>=.75 else 'PARTIAL'}** — deterministic resampling completed.",
           "- **PRIMARY FEATURE REPRESENTATION: READY** — High-Confidence remains the reference, with family blocks as sensitivity views.",
           f"- **UMAP: {'PARTIAL' if primary_status=='READY' and not high_activity else 'NOT READY'}** — not executed; requires locked follow-up preprocessing.",
           "- **HDBSCAN: NOT READY** — PCA geometry must inform a separate clustering contract.",
           "- **GMM: NOT READY** — covariance/geometry suitability must be evaluated separately.",
           "- **SUPERVISED CLASSIFICATION: NOT READY** — no defensible labels exist.","",
           "No UMAP, clustering, classification, collection, retry, identity interpretation, commit, merge, or push was performed."]
    path=OUT/"EXPLORATORY_ML_PCA_PHASE1_REPORT.md"; path.write_text("\n".join(lines)+"\n"); return path


def main() -> None:
    OUT.mkdir(parents=True,exist_ok=True)
    integrity_before=source_integrity()
    metadata=list(csv.DictReader((VALIDATION/"candidate_matrix_metadata_v1.csv").open()))
    wallets=[row["wallet"] for row in metadata]
    registry={row["predictor"]:row for row in csv.DictReader((VALIDATION/"predictor_registry_v1.csv").open())}
    diagnostics={row["wallet"]:row for row in csv.DictReader((VALIDATION/"activity_diagnostics_v1.csv").open())}
    high_features,high_rows=read_matrix("high_confidence.csv")
    forbidden=("wallet","label","stratum","lifetime","collection","support","coverage","rule__","prediction","cluster","classifier")
    invalid=[feature for feature in high_features if any(token in feature.lower() for token in forbidden)]
    if invalid: raise RuntimeError(f"forbidden High-Confidence fields: {invalid}")
    high_cases=complete_cases(high_rows)
    if len(high_features)!=10 or len(high_cases)!=513:
        raise RuntimeError(f"High-Confidence contract discrepancy: {len(high_cases)}x{len(high_features)}")
    low_features,low_rows=read_matrix("low_redundancy_core.csv")
    block_families={
        "PCA_TEMPORAL_STRUCTURE_BLOCK_V1":{"temporal","periodicity","templates","topology"},
        "PCA_CELL_STRUCTURE_BLOCK_V1":{"lifecycle","lineage","capacity"},
        "PCA_SCRIPT_TRANSACTION_STRUCTURE_BLOCK_V1":{"scripts","templates","topology","capacity"},
    }
    definitions=[("PCA_LOW_REDUNDANCY_COMPLETE_CASE_V1",low_features,list(range(len(low_features))),complete_cases(low_rows))]
    for name,families in block_families.items():
        columns=[index for index,feature in enumerate(low_features) if feature.split("__",1)[0] in families]
        subset=[[row[index] for index in columns] for row in low_rows]
        definitions.append((name,[low_features[index] for index in columns],columns,complete_cases(subset)))
    decisions=[]
    for name,features,_,cases in definitions:
        accepted,reason=feasible(len(cases),len(features))
        decisions.append({"experiment":name,"n_wallets":len(cases),"n_features":len(features),
                          "wallets_per_feature":len(cases)/len(features),"accepted":accepted,"decision":reason,
                          "feature_family_composition":dict(Counter(feature.split("__",1)[0] for feature in features))})
    expected={"PCA_LOW_REDUNDANCY_COMPLETE_CASE_V1":(28,59),"PCA_TEMPORAL_STRUCTURE_BLOCK_V1":(249,34),
              "PCA_CELL_STRUCTURE_BLOCK_V1":(172,18),"PCA_SCRIPT_TRANSACTION_STRUCTURE_BLOCK_V1":(46,36)}
    for decision in decisions:
        if (decision["n_wallets"],decision["n_features"])!=expected[decision["experiment"]]:
            raise RuntimeError(f"verified experiment size changed: {decision}")
    contract={"experiment_version":EXPERIMENT_VERSION,"random_seed":SEED,"resamples":RESAMPLES,
              "resample_fraction":RESAMPLE_FRACTION,"population_version":"ckb-wallet-population-local-v1",
              "observation_contract":"wallet-observation-30d-v1","feature_set":"HIGH_CONFIDENCE",
              "wallet_cohort":"PCA_COHORT_HIGH_CONFIDENCE_V1","missing_data_policy":"COMPLETE_CASE_NO_IMPUTATION",
              "transformation_policy":"PER_FEATURE_EXPLICIT_WITH_SIGNED_LOG_OVERRIDE_AND_ZERO_IQR_FALLBACK",
              "scaling_policy":"STANDARD_FOR_BOUNDED; ROBUST_AFTER_LOG_FOR_MAGNITUDES",
              "diagnostic_metadata":["transaction_count","observed_cell_count","input_count","output_count"],
              "diagnostic_metadata_role":"POST_HOC_ONLY_EXCLUDED_FROM_PCA",
              "feasibility_gate":{"minimum_wallets":MIN_WALLETS,"minimum_wallets_per_feature":MIN_RATIO},
              "activity_thresholds":{"moderate":ACTIVITY_LOW,"high":ACTIVITY_HIGH},
              "family_dominance_threshold":FAMILY_DOMINANCE,"source_integrity":integrity_before,
              "implementation":{"python":platform.python_version(),"numpy":np.__version__,
                                "pillow":Image.__version__ if hasattr(Image,"__version__") else "unknown",
                                "algorithm":"numpy.linalg.eigh symmetric covariance PCA"}}
    dump(OUT/"experiment_contract.json",contract)
    dump(OUT/"experiment_feasibility_decisions.json",decisions)
    results=[run_experiment("PCA_HIGH_CONFIDENCE_V1",high_features,high_rows,high_cases,wallets,registry,diagnostics,SEED)]
    for offset,(name,features,columns,cases) in enumerate(definitions[1:],1):
        decision=next(row for row in decisions if row["experiment"]==name)
        if not decision["accepted"]: continue
        subset=[[row[index] for index in columns] for row in low_rows]
        results.append(run_experiment(name,features,subset,cases,wallets,registry,diagnostics,SEED+offset))
    dump(OUT/"cross_experiment_comparison.json",results)
    report_path=report(contract,decisions,results)
    integrity_after=source_integrity()
    if integrity_before!=integrity_after: raise RuntimeError("frozen source artifacts changed")
    dump(OUT/"source_integrity_after.json",integrity_after)
    print(json.dumps({"experiment":EXPERIMENT_VERSION,"primary_cohort":len(high_cases),"primary_features":len(high_features),
                      "executed_experiments":[row["name"] for row in results],"decisions":decisions,
                      "report":str(report_path)},indent=2))


if __name__=="__main__":
    main()
