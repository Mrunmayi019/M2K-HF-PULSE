"""Extracts R-J interval and I-J/J-K amplitude from subject 14's XJ-view BCG recording (Zhan et
al. 2025 Multi-Pathology BCG Dataset, figshare 10.6084/m9.figshare.28416896). Output feeds
scripts/bcg_real_patient_validation.py's RJ_INTERVAL_MS/IJ_AMPLITUDE/JK_AMPLITUDE constants -- see
docs/bcg_validation_note.md for the full method writeup and citations (Ashouri et al. 2016 for the
I-wave window, Feng et al. 2023 for the K-wave definition).

Requires the raw dataset on disk (not part of this repo -- set DATASET_DIR below to wherever it
was downloaded). Pure pandas/numpy, no Docker required.

PVC handling: subject 14 is tagged "PVCS+HF," but its XJ view specifically carries no `(PVCs)` tag
in the dataset's own ALL-sheet Data_file field (unlike its EJ/ZJ views) -- checked here anyway via
an R-R short-coupling-interval + compensatory-pause heuristic, confirming 0 PVCs in this clip's 20
beats.
"""
import pandas as pd
import numpy as np

DATASET_DIR = r"D:\5th sem notes\capstone\Dataset\Data\hdata14XJ"  # external raw dataset, not in this repo
FS = 100.0  # Hz, per the dataset's own signal.pdf plot and index/time ratio in the peak-annotation files
OUT_CSV = "data/bcg_validation/subject14/rj_ijk_features.csv"

XLSX_HR_BPM = 77  # Subject_Info.xlsx "HF" sheet, subject 014


def main():
    signal = pd.read_csv(f"{DATASET_DIR}\\signal.csv")
    bcg_peaks = pd.read_csv(f"{DATASET_DIR}\\hdata14XJ_BCG.csv")
    ecg_peaks = pd.read_csv(f"{DATASET_DIR}\\hdata14XJ_ECG.csv")

    print(f"signal.csv: {len(signal)} samples -> {len(signal)/FS:.2f}s at {FS}Hz")

    bcg_cols, ecg_cols = bcg_peaks.columns.tolist(), ecg_peaks.columns.tolist()
    j_t = bcg_peaks[bcg_cols[1]].to_numpy()
    r_t = ecg_peaks[ecg_cols[1]].to_numpy()
    print(f"n J-peaks (BCG): {len(j_t)}   n R-peaks (ECG): {len(r_t)}")

    # PVC detection: a PVC shows a short-coupling-interval + compensatory-pause R-R signature
    # (the R-R interval ENDING at the PVC beat is much shorter than the surrounding sinus R-R).
    rr = np.diff(r_t)
    median_rr = np.median(rr)
    short_thresh = 0.80 * median_rr
    pvc_beat_indices = {i + 1 for i in range(len(rr)) if rr[i] < short_thresh}
    print(f"median R-R = {median_rr:.3f}s -> reference sinus HR = {60/median_rr:.1f} bpm")
    print(f"Beats excluded as PVC: {len(pvc_beat_indices)} / {len(r_t)}")

    clean_r_indices = [i for i in range(len(r_t)) if i not in pvc_beat_indices]

    # R-J pairing: nearest BCG-J-peak time in a plausibility window after each R-peak.
    RJ_MIN, RJ_MAX = 0.05, 0.40
    clean_pairs = []
    for i in clean_r_indices:
        r_time = r_t[i]
        cands = j_t[(j_t - r_time >= RJ_MIN) & (j_t - r_time <= RJ_MAX)]
        if len(cands) >= 1:
            clean_pairs.append((r_time, cands[0]))

    print(f"Clean R-J pairs: {len(clean_pairs)} / {len(clean_r_indices)}")

    sinus_rr = np.diff(r_t[clean_r_indices])
    print(f"Sinus-only R-R -> HR={60/sinus_rr.mean():.1f} bpm (xlsx HR = {XLSX_HR_BPM} bpm)")

    # I/K localization on the denoised BCG channel: I = min in the 200ms window before J
    # (Ashouri et al. 2016); K = first local minimum after J (Feng et al. 2023).
    bcg_denoised = signal["Denoised_BCG_Signal"].to_numpy()
    n = len(bcg_denoised)
    I_WIN = K_WIN = int(0.20 * FS)

    rows = []
    for r_time, j_time in clean_pairs:
        j_i = int(round(j_time * FS))
        if j_i >= n:
            continue
        j_val = bcg_denoised[j_i]

        lo = max(0, j_i - I_WIN)
        pre = bcg_denoised[lo:j_i]
        i_i = lo + int(np.argmin(pre))
        i_val = bcg_denoised[i_i]

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
            "R_time_s": round(r_time, 2), "J_time_s": round(j_time, 2),
            "RJ_ms": round((j_time - r_time) * 1000, 1),
            "I_val": round(i_val, 4), "J_val": round(j_val, 4), "K_val": round(k_val, 4),
            "IJ_amplitude": round(j_val - i_val, 4), "JK_amplitude": round(j_val - k_val, 4),
        })

    feat = pd.DataFrame(rows)
    pd.set_option("display.width", 160)
    print(feat.to_string(index=False))
    print(f"\nR-J interval (n={len(feat)}): mean={feat.RJ_ms.mean():.1f} ms, sd={feat.RJ_ms.std():.1f} ms")
    print(f"IJ_amplitude: mean={feat.IJ_amplitude.mean():.4f}, sd={feat.IJ_amplitude.std():.4f}")
    print(f"JK_amplitude: mean={feat.JK_amplitude.mean():.4f}, sd={feat.JK_amplitude.std():.4f}")

    feat.to_csv(OUT_CSV, index=False)
    print(f"\nWrote {OUT_CSV}")


if __name__ == "__main__":
    main()
