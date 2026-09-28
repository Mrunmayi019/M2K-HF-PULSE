"""Extracts R-J interval and I-J/J-K amplitude from subject 102's XJ-view BCG recording (Zhan et
al. 2025 Multi-Pathology BCG Dataset, figshare 10.6084/m9.figshare.28416896). Output feeds
scripts/bcg_subject102_validation.py's RJ_INTERVAL_MS/IJ_AMPLITUDE/JK_AMPLITUDE constants -- see
docs/bcg_validation_note.md for the full method writeup, citations, and the R-J-pairing artifact
this subject's recording specifically has (3 missing + 4 spurious/edge BCG peak detections out of
17 true cardiac cycles, excluded rather than force-matched).

Requires the raw dataset on disk (not part of this repo -- set DATASET_DIR below to wherever it
was downloaded). Pure pandas/numpy, no Docker required.

Ground-truth note: this subject's own R-R-derived HR (computed here) showed an unexplained 2.15x
mismatch against Subject_Info.xlsx's HR (115 bpm) -- confirmed real (via the dataset's own
signal.pdf plot), not a bug in this extraction. See docs/bcg_validation_note.md for the full
investigation; downstream comparisons use the xlsx HR, not this script's R-R-derived value.
"""
import pandas as pd
import numpy as np

DATASET_DIR = r"D:\5th sem notes\capstone\Dataset\Data\hdata102XJ"  # external raw dataset, not in this repo
FS = 100.0  # Hz, per the dataset's own signal.pdf plot and index/time ratio in the peak-annotation files
OUT_CSV = "data/bcg_validation/subject102/rj_ijk_features.csv"

XLSX_HR_BPM = 115  # Subject_Info.xlsx "HF" sheet, subject 102 -- NOT this clip's own R-R-derived HR

# Plausibility window for a genuine same-cycle R->J pairing, based on the tight empirical cluster
# (160-190ms) seen in an unfiltered first pass -- wide enough to be conservative, tight enough to
# exclude the double-RR-length pairing artifacts this subject's BCG peaks specifically have.
RJ_MIN, RJ_MAX = 0.05, 0.30


def main():
    signal = pd.read_csv(f"{DATASET_DIR}\\signal.csv")
    bcg_peaks = pd.read_csv(f"{DATASET_DIR}\\hdata102XJ_BCG.csv")
    ecg_peaks = pd.read_csv(f"{DATASET_DIR}\\hdata102XJ_ECG.csv")

    j_t = bcg_peaks["BCG_Peark_Times"].to_numpy()
    j_idx_all = bcg_peaks["BCG_Peark_Point"].to_numpy()
    r_t = ecg_peaks["ECG_Peark_Times"].to_numpy()

    clean_pairs, unmatched_r = [], []
    for r_time in r_t:
        cands = j_t[(j_t - r_time >= RJ_MIN) & (j_t - r_time <= RJ_MAX)]
        if len(cands) >= 1:
            clean_pairs.append((r_time, cands[0], cands[0] - r_time))
        else:
            unmatched_r.append(r_time)

    matched_j_times = {p[1] for p in clean_pairs}
    extra_j = sorted(set(j_t.tolist()) - matched_j_times)

    print(f"Clean R-J pairs: {len(clean_pairs)} / {len(r_t)} R-peaks")
    print(f"Unmatched (missing-J) R-peaks: {[round(x, 2) for x in unmatched_r]}")
    print(f"Extra/unpaired BCG peaks (spurious or edge): {[round(x, 2) for x in extra_j]}")

    rj_vals = np.array([p[2] for p in clean_pairs])
    print(f"R-J interval (n={len(rj_vals)}): mean={rj_vals.mean()*1000:.1f} ms, "
          f"sd={rj_vals.std()*1000:.1f} ms")

    rr = np.diff(r_t)
    print(f"R-R from all {len(r_t)} ECG R-peaks -> HR={60/rr.mean():.1f} bpm (this clip) "
          f"vs Subject_Info.xlsx HR={XLSX_HR_BPM} bpm -- see module docstring, use xlsx downstream")

    bcg_denoised = signal["Denoised_BCG_Signal"].to_numpy()
    n = len(bcg_denoised)
    clean_j_idx = [int(j_idx_all[np.where(j_t == jt)[0][0]]) for _, jt, _ in clean_pairs]
    I_WIN = K_WIN = int(0.20 * FS)

    rows = []
    for (r_time, j_time, rj), j_i in zip(clean_pairs, clean_j_idx):
        j_val = bcg_denoised[j_i]

        lo = max(0, j_i - I_WIN)
        pre = bcg_denoised[lo:j_i]
        i_val = bcg_denoised[lo + int(np.argmin(pre))]

        hi = min(n, j_i + K_WIN + 1)
        post = bcg_denoised[j_i + 1:hi]
        k_rel = next(
            (t for t in range(1, len(post) - 1) if post[t] < post[t - 1] and post[t] <= post[t + 1]),
            None,
        )
        if k_rel is None:
            k_rel = int(np.argmin(post))
        k_val = bcg_denoised[j_i + 1 + k_rel]

        rows.append({
            "R_time_s": round(r_time, 2), "J_time_s": round(j_time, 2), "RJ_ms": round(rj * 1000, 1),
            "I_val": round(i_val, 4), "J_val": round(j_val, 4), "K_val": round(k_val, 4),
            "IJ_amplitude": round(j_val - i_val, 4), "JK_amplitude": round(j_val - k_val, 4),
        })

    feat = pd.DataFrame(rows)
    pd.set_option("display.width", 160)
    print(feat.to_string(index=False))
    print(f"\nIJ_amplitude (n={len(feat)}): mean={feat.IJ_amplitude.mean():.4f}, sd={feat.IJ_amplitude.std():.4f}")
    print(f"JK_amplitude (n={len(feat)}): mean={feat.JK_amplitude.mean():.4f}, sd={feat.JK_amplitude.std():.4f}")

    feat.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV}")


if __name__ == "__main__":
    main()
