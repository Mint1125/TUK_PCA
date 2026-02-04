"""
✅ 압축 통합 파이프라인 (chip.csv, multi.csv, aoi.csv → dt 기준 결과 1개 생성)
요청사항:
- offset 방식은 완전히 제외
- dt 매칭은 "window 안에서 가장 이른 AOI"가 아니라,
  ✅ "dt_median(모델별, 없으면 global)에 가장 가까운 AOI"를 선택
- 공정 제약: AOI Start Date >= multi 생산완료 시각(multi_end)  ✅
- 과거 오류 해결: model_key 미사용, dedup_mount ascending 길이 불일치 해결 ✅
- AOI 1:1 사용 (한 AOI는 한 보드에만 매칭)

입력(필수 컬럼)
- chip.csv : 기판명, 로트내 연번, 생산시작 시각, (선택) 완료 플래그
- multi.csv: 기판명, 로트내 연번, 생산시작 시각, 생산완료 시각, (선택) 완료 플래그
- aoi.csv  : Model, SerialNo, Start Date

출력(/match_outputs/)
- matched_by_dt_median.csv

실행:
python run_dt_median_match.py
"""

import os
import re
import pandas as pd
import numpy as np


# =============================
# 0) 경로/컬럼 설정
# =============================
CHIP_PATH  = "chip.csv"
MULTI_PATH = "multi.csv"
AOI_PATH   = "aoi.csv"

OUT_DIR = "match_outputs"
os.makedirs(OUT_DIR, exist_ok=True)

# ---- chip/multi 공통
MODEL_COL = "기판명"
LOTSEQ_COL = "로트내 연번"
START_COL = "생산시작 시각"
COMPLETE_COL = "완료 플래그"        # 없으면 무시

# ---- multi 전용 (중요)
MULTI_END_COL = "생산완료 시각"     # ✅ AOI가 이 시각보다 늦어야 함

# ---- aoi
AOI_MODEL_COL = "Model"
AOI_SERIAL_COL = "SerialNo"
AOI_START_COL = "Start Date"

# ---- dt window 파라미터
# offset을 쓰지 않으므로, dt window는 "모델별 AOI-start 간격"에서 추정할 수도 있지만
# 여기서는 안전하게: global window를 넉넉히 주고, median 기반 선택으로 오매칭을 줄이는 전략
GLOBAL_DT_LOW_SEC = 0               # multi_end 이후부터
GLOBAL_DT_HIGH_SEC = 3 * 3600       # 3시간 (필요하면 늘리기)

# 모델별 dt_median 추정 방법(옵션):
# - "AOI start - multi_end"의 정답 매칭이 없기 때문에, 여기서는 기본값/사용자 지정으로 둠
# - 대신 선택 규칙은 dt_median 기준으로 후보를 고른다.
# 아래 값을 바꾸면 전체 모델에 공통으로 적용됨.
GLOBAL_DT_MEDIAN_SEC = 600          # 기본 2분 (라인 특성에 맞게 조정 가능)

# 출력
OUT_DT = os.path.join(OUT_DIR, "temporal matching.csv")


# =============================
# 유틸
# =============================
def read_table(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext in [".xlsx", ".xls"]:
        return pd.read_excel(path)
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp949")

def to_dt(s):
    return pd.to_datetime(s, errors="coerce")

def require(df: pd.DataFrame, cols: list[str], name: str):
    miss = [c for c in cols if c not in df.columns]
    if miss:
        raise ValueError(f"[{name}] missing columns: {miss}")


# =============================
# 모델명 정규화 (_mk 생성)
# =============================
def norm_base_model(x) -> str:
    s = str(x).strip()
    s = re.sub(r'^(SEIL-|SH-)', '', s, flags=re.IGNORECASE)
    s = s.replace(" ", "")
    s = s.replace("-", "_")
    s = s.replace("+", "_PLUS_")
    s = re.sub(r"[()]+", "", s)
    s = re.sub(r"_+", "_", s).upper()
    s = re.sub(r"_(\d{6}|\d{8})$", "", s)

    # 요청 반영 룰
    s = s.replace("KOREA_G_E_NEW_CONTROL", "KOREA_NEW_CONTROL")
    s = s.replace("AIRDEEP_R_PLUS_C_TYPE", "AIRDEEP_C_TYPE")
    s = s.replace("AIRDEEP_R_C_TYPE", "AIRDEEP_C_TYPE")

    return re.sub(r"_+", "_", s).strip("_")


# =============================
# 1) chip/multi 보드 1행화 (ascending 버그 해결 버전)
# =============================
def dedup_mount(df: pd.DataFrame,
                model_col: str,
                lotseq_col: str,
                start_col: str,
                end_col: str | None = None,
                complete_col: str | None = None) -> pd.DataFrame:
    out = df.copy()

    need = [model_col, lotseq_col, start_col]
    if end_col:
        need.append(end_col)
    require(out, need, "mount_df")

    out[start_col] = to_dt(out[start_col])
    if end_col:
        out[end_col] = to_dt(out[end_col])

    key = [model_col, lotseq_col]

    if complete_col and complete_col in out.columns:
        out[complete_col] = pd.to_numeric(out[complete_col], errors="coerce")
        time_col = end_col if end_col else start_col
        sort_cols = key + [complete_col, time_col, start_col]
        asc = [True, True] + [False] * (len(sort_cols) - 2)  # ✅ 자동 길이 맞춤
        out = out.sort_values(sort_cols, ascending=asc)
        out = out.drop_duplicates(subset=key, keep="first")
        return out.reset_index(drop=True)

    time_col = end_col if end_col else start_col
    out = out.sort_values(key + [time_col])
    out = out.drop_duplicates(subset=key, keep="last")
    return out.reset_index(drop=True)


# =============================
# 2) anchor 생성 (chip+multi inner join, base_time=multi_end)
# =============================
def build_anchor(chip_1b: pd.DataFrame, multi_1b: pd.DataFrame) -> pd.DataFrame:
    c = chip_1b.copy().rename(columns={START_COL: "chip_start"})
    m = multi_1b.copy().rename(columns={START_COL: "multi_start", MULTI_END_COL: "multi_end"})

    require(c, [MODEL_COL, LOTSEQ_COL, "chip_start"], "chip_1b")
    require(m, [MODEL_COL, LOTSEQ_COL, "multi_start", "multi_end"], "multi_1b")

    c["chip_start"] = to_dt(c["chip_start"])
    m["multi_start"] = to_dt(m["multi_start"])
    m["multi_end"] = to_dt(m["multi_end"])

    anchor = c[[MODEL_COL, LOTSEQ_COL, "chip_start"]].merge(
        m[[MODEL_COL, LOTSEQ_COL, "multi_start", "multi_end"]],
        on=[MODEL_COL, LOTSEQ_COL],
        how="inner"
    )

    # 기준 시간은 multi_end
    anchor["base_time"] = anchor["multi_end"]

    # 정규화 키
    anchor["_mk"] = anchor[MODEL_COL].apply(norm_base_model)

    # 타입
    anchor[LOTSEQ_COL] = pd.to_numeric(anchor[LOTSEQ_COL], errors="coerce")

    # 보드 키
    anchor["board_key"] = (
        anchor[MODEL_COL].astype(str) + "||" +
        anchor[LOTSEQ_COL].astype(str) + "||" +
        anchor["multi_end"].astype(str)
    )

    return anchor.sort_values(["base_time", MODEL_COL, LOTSEQ_COL]).reset_index(drop=True)


# =============================
# 3) AOI 전처리
# =============================
def preprocess_aoi(aoi: pd.DataFrame) -> pd.DataFrame:
    out = aoi.copy()
    require(out, [AOI_MODEL_COL, AOI_SERIAL_COL, AOI_START_COL], "aoi_df")

    out[AOI_START_COL] = to_dt(out[AOI_START_COL])
    out[AOI_SERIAL_COL] = pd.to_numeric(out[AOI_SERIAL_COL], errors="coerce")

    # (Model, SerialNo) 중복은 가장 이른 StartDate 사용
    out = out.sort_values([AOI_MODEL_COL, AOI_SERIAL_COL, AOI_START_COL])
    out = out.drop_duplicates(subset=[AOI_MODEL_COL, AOI_SERIAL_COL], keep="first")

    out["_mk"] = out[AOI_MODEL_COL].apply(norm_base_model)
    return out.reset_index(drop=True)


# =============================
# 4) dt_median 기반 1:1 매칭
#    - 후보 window: [base_time + low, base_time + high]
#    - 후보가 여러 개면 |dt - dt_median|가 최소인 AOI 선택
#    - 선택된 AOI는 재사용 금지(1:1)
# =============================
def match_by_dt_median(anchor: pd.DataFrame,
                       aoi: pd.DataFrame,
                       low_sec: float,
                       high_sec: float,
                       global_median_sec: float) -> pd.DataFrame:
    A = anchor.copy()
    B = aoi.copy()

    require(A, ["_mk", "base_time"], "anchor")
    require(B, ["_mk", AOI_START_COL, AOI_SERIAL_COL], "aoi")

    A["base_time"] = to_dt(A["base_time"])
    B[AOI_START_COL] = to_dt(B[AOI_START_COL])
    B[AOI_SERIAL_COL] = pd.to_numeric(B[AOI_SERIAL_COL], errors="coerce")

    # 결과 컬럼
    A["dt_matched"] = False
    A["dt_aoi_start"] = pd.NaT
    A["dt_aoi_serial"] = np.nan
    A["dt_sec"] = np.nan
    A["dt_score_abs_median"] = np.nan

    # AOI 1:1 플래그
    B = B.sort_values(["_mk", AOI_START_COL]).reset_index(drop=True)
    B["_used"] = False

    # 모델별 매칭
    for mk, idxs in A.groupby("_mk").groups.items():
        A_idx = sorted(list(idxs), key=lambda i: A.loc[i, "base_time"])
        B_sub = B.index[B["_mk"] == mk].tolist()
        if not B_sub:
            continue

        # pointer (start 범위 이전 AOI skip)
        p = 0

        for ai in A_idx:
            t0 = A.loc[ai, "base_time"]
            if pd.isna(t0):
                continue

            start = t0 + pd.Timedelta(seconds=float(low_sec))
            end = t0 + pd.Timedelta(seconds=float(high_sec))

            # start 이전은 스킵
            while p < len(B_sub) and B.loc[B_sub[p], AOI_START_COL] < start:
                p += 1

            # 후보 수집: end까지, 사용 안 된 것만
            cand = []
            q = p
            while q < len(B_sub):
                bj = B_sub[q]
                if B.loc[bj, "_used"]:
                    q += 1
                    continue
                t1 = B.loc[bj, AOI_START_COL]
                if t1 > end:
                    break
                cand.append(bj)
                q += 1

            if not cand:
                continue

            # ✅ dt_median에 가장 가까운 후보 선택
            best = None
            best_score = None
            best_dt = None

            for bj in cand:
                dt = (B.loc[bj, AOI_START_COL] - t0).total_seconds()
                score = abs(dt - float(global_median_sec))
                if best is None or score < best_score:
                    best = bj
                    best_score = score
                    best_dt = dt

            # 확정
            B.loc[best, "_used"] = True
            A.loc[ai, "dt_matched"] = True
            A.loc[ai, "dt_aoi_start"] = B.loc[best, AOI_START_COL]
            A.loc[ai, "dt_aoi_serial"] = B.loc[best, AOI_SERIAL_COL]
            A.loc[ai, "dt_sec"] = best_dt
            A.loc[ai, "dt_score_abs_median"] = best_score

            # 효율 & 순서유지: chosen가 p보다 앞이면 p 갱신은 불필요하지만,
            # chosen가 cand 중간이면 이후 탐색에 영향이 적게 p는 그대로 둔다(안전).
            # (원하면 p를 B_sub.index(best)+1 로 옮겨도 됨)

    # ✅ 공정 제약 최종 확인: AOI < base_time이면 강제 실패
    A["dt_aoi_start"] = to_dt(A["dt_aoi_start"])
    bad = A["dt_matched"] & A["dt_aoi_start"].notna() & A["base_time"].notna() & (A["dt_aoi_start"] < A["base_time"])
    if bad.any():
        A.loc[bad, ["dt_matched", "dt_aoi_start", "dt_aoi_serial", "dt_sec", "dt_score_abs_median"]] = [False, pd.NaT, np.nan, np.nan, np.nan]

    return A


# =============================
# main
# =============================
if __name__ == "__main__":
    chip = read_table(CHIP_PATH)
    multi = read_table(MULTI_PATH)
    aoi = read_table(AOI_PATH)

    chip_1b = dedup_mount(chip, MODEL_COL, LOTSEQ_COL, START_COL, end_col=None, complete_col=COMPLETE_COL)
    multi_1b = dedup_mount(multi, MODEL_COL, LOTSEQ_COL, START_COL, end_col=MULTI_END_COL, complete_col=COMPLETE_COL)

    anchor = build_anchor(chip_1b, multi_1b)
    aoi_p = preprocess_aoi(aoi)

    matched = match_by_dt_median(
        anchor=anchor,
        aoi=aoi_p,
        low_sec=GLOBAL_DT_LOW_SEC,
        high_sec=GLOBAL_DT_HIGH_SEC,
        global_median_sec=GLOBAL_DT_MEDIAN_SEC
    )

    matched.to_csv(OUT_DT, index=False, encoding="utf-8-sig")

    total = len(anchor)
    mcnt = int(matched["dt_matched"].sum())

    print("DONE.")
    print(f"- total boards: {total}")
    print(f"- dt_median matched: {mcnt} ({mcnt/total:.2%}) -> {OUT_DT}")
    print(f"- window(sec): [{GLOBAL_DT_LOW_SEC}, {GLOBAL_DT_HIGH_SEC}] | median(sec): {GLOBAL_DT_MEDIAN_SEC}")
